# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search models in ONNX: running on any video card through DirectML (AMD, Intel, built-in ones too) without CUDA.
The backend "onnx-dml" (assistant_x.toml: backend) replaces torch: OnnxEncoder repeats SentenceTransformer.encode,
OnnxCrossEncoder repeats CrossEncoder.predict, so search.py and embed.py use them the same way. The vectors are the
same as torch gives (CLS, normalized): the base is shared, no recalculation needed (check: --check, cosine ≥ 0.999).

    python onnx_models.py --export            export bge-m3 and bge-reranker-v2-m3 to models/onnx (build PC: torch, onnx)
    python onnx_models.py --int8              bge-m3 with int8 weights for the processor (models/onnx/bge-m3/
                                              model.int8.onnx), checked at once as by --check
    python onnx_models.py --check             the int8 vectors against the float32 ONNX and torch ones
    python onnx_models.py --adapters          DirectML video adapters (number = device_id)
models/onnx/<model>/model.onnx (+ model.onnx.data), the tokenizer comes from the folder of the original model.

int8 on the processor (search/models.py loads it there when it exists, [search] cpu_int8 = true): the weights of the
MatMuls quantized dynamically to int8 (onnxruntime, QInt8, a scale per channel), about 1.7x faster than float32 on a
processor. It must give the vectors of the same model, since a base keeps one model forever and mixes the vectors of
every PC that extends it: --check embeds 200 fragments of the base (or the sample sentences of the language packs,
model_check_sentences, without a base) and refuses the file — deletes it, exit code 1 — when the mean cosine to the
float32 vectors is below 0.99 or one of them below 0.97."""

import argparse, ctypes, os, sys, time

from assistant_x.core import workspace

MODELS = ONNX_DIR = None  # the models of the workspace in use (models_dir, onnx_dir), unless set


def models_dir():
    return MODELS or str(workspace.current().models)


def onnx_dir():
    return ONNX_DIR or os.path.join(models_dir(), "onnx")


OPSET = 17


# ---------- video adapters (DXGI): what DirectML can run on ----------


def adapters():
    """[(device_id, name, vendor id, dedicated VRAM GB)]; [] off Windows. DirectML numbers device_id by GPU preference
    «high performance» (the discrete card first), not by the plain DXGI order: measured 24.10.2026 — id 0 loaded the
    RTX 5080 (69 %) while DXGI lists the Intel graphics first. IDXGIFactory6::EnumAdapterByGpuPreference gives that
    order; without it (old Windows) the plain order."""
    if os.name != "nt":
        return []

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", ctypes.c_uint32), ("HighPart", ctypes.c_int32)]

    class DESC1(ctypes.Structure):
        _fields_ = [
            ("Description", ctypes.c_wchar * 128),
            ("VendorId", ctypes.c_uint),
            ("DeviceId", ctypes.c_uint),
            ("SubSysId", ctypes.c_uint),
            ("Revision", ctypes.c_uint),
            ("DedicatedVideoMemory", ctypes.c_size_t),
            ("DedicatedSystemMemory", ctypes.c_size_t),
            ("SharedSystemMemory", ctypes.c_size_t),
            ("AdapterLuid", LUID),
            ("Flags", ctypes.c_uint),
        ]

    class GUID(ctypes.Structure):
        _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]

    iid = GUID(
        0x770AAE78, 0xF26F, 0x4DBA, (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87)
    )  # IDXGIFactory1
    factory = ctypes.c_void_p()
    try:
        if ctypes.windll.dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory)) != 0:
            return []
    except OSError:
        return []

    def method(obj, index, *types):
        vtbl = ctypes.cast(ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *types)(vtbl[index])

    iid6 = GUID(
        0xC1B6694F, 0xFF09, 0x44A9, (ctypes.c_ubyte * 8)(0xB0, 0x3C, 0x77, 0x90, 0x0A, 0x0A, 0x1D, 0x17)
    )  # IDXGIFactory6
    iid_a1 = GUID(
        0x29038F61, 0x3839, 0x4626, (ctypes.c_ubyte * 8)(0x91, 0xFD, 0x08, 0x68, 0x79, 0x01, 0x1A, 0x05)
    )  # IDXGIAdapter1
    f6 = ctypes.c_void_p()
    method(factory, 0, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(factory, ctypes.byref(iid6), ctypes.byref(f6))

    def enum(i, adapter):
        if f6.value:  # EnumAdapterByGpuPreference(index, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE, IDXGIAdapter1)
            return method(f6, 29, ctypes.c_uint, ctypes.c_int, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(
                f6, i, 2, ctypes.byref(iid_a1), ctypes.byref(adapter)
            )
        return method(factory, 12, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(factory, i, ctypes.byref(adapter))

    out, i = [], 0
    while True:
        adapter = ctypes.c_void_p()
        if enum(i, adapter) != 0:
            break  # DXGI_ERROR_NOT_FOUND: no more adapters
        d = DESC1()
        method(adapter, 10, ctypes.POINTER(DESC1))(adapter, ctypes.byref(d))  # IDXGIAdapter1::GetDesc1
        method(adapter, 2)(adapter)  # Release
        if not d.Flags & 2:  # DXGI_ADAPTER_FLAG_SOFTWARE (Microsoft Basic Render Driver)
            out.append((i, d.Description, d.VendorId, d.DedicatedVideoMemory / 2**30))
        i += 1
    if f6.value:
        method(f6, 2)(f6)
    method(factory, 2)(factory)
    return out


NVIDIA, AMD, INTEL = 0x10DE, 0x1002, 0x8086


MIN_DML_GB = 2  # dedicated video memory of a card worth DirectML: integrated graphics (Intel in Core Ultra 9 275HX:
# 0.1 GB of its own) encoded 100 fragments in 121 s against 93 s of the CPU (24.10.2026), so it stays on the CPU


def pick_adapter(prefer=None):
    """(device_id, name, VRAM GB) for DirectML: the given index, else the non-NVIDIA card with the most dedicated
    memory, at least MIN_DML_GB (NVIDIA goes through CUDA, integrated graphics is no faster than the CPU); None."""
    found = adapters()
    if prefer is not None:
        return next(((i, n, m) for i, n, v, m in found if i == int(prefer)), None)
    other = [(m, i, n) for i, n, v, m in found if v != NVIDIA and m >= MIN_DML_GB]
    if not other:
        return None
    m, i, n = max(other)
    return i, n, m


def dml_device(cfg):
    """ "dml:N" when DirectML should run the models, else None (torch: CUDA or the CPU). assistant_x.toml «backend»:
    "torch" — never; "onnx-dml" — whenever DirectML, the ONNX models and an adapter are there (dml_device picks one,
    integrated graphics too); "auto" (default) — only without CUDA and on a discrete non-NVIDIA card (pick_adapter)."""
    backend = cfg.get("backend") or "auto"
    if backend == "torch":
        return None
    if backend == "auto":
        try:
            import torch

            if torch.cuda.is_available():
                return None
        except ImportError:
            pass
    try:
        import onnxruntime

        if "DmlExecutionProvider" not in onnxruntime.get_available_providers():
            return None
    except ImportError:
        return None
    if not os.path.exists(os.path.join(onnx_dir(), "bge-m3", "model.onnx")):
        return None
    if backend == "onnx-dml" and cfg.get("dml_device") is None:
        found = adapters()
        a = pick_adapter() or (found[0][:2] + (found[0][3],) if found else None)
    else:
        a = pick_adapter(cfg.get("dml_device"))
    return f"dml:{a[0]}" if a else None


# ---------- runtime ----------


def _session(path, device):
    """onnxruntime session: device "dml:N" — DirectML on adapter N (and the CPU for what it lacks), "cpu" — the CPU."""
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.log_severity_level = 3
    if str(device).startswith("dml"):
        so.enable_mem_pattern = False  # required by DirectML
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        dev = int(str(device).split(":", 1)[1]) if ":" in str(device) else 0
        providers = [("DmlExecutionProvider", {"device_id": dev}), "CPUExecutionProvider"]
    else:
        providers = ["CPUExecutionProvider"]
        so.intra_op_num_threads = max(1, (os.cpu_count() or 2) // 2)  # half of the CPUs: the PC stays usable
    return ort.InferenceSession(path, so, providers=providers)


def model_file(name, file="model.onnx"):
    """models/onnx/<name>/model.onnx (its weights in model.onnx.data beside it), or another file of that folder."""
    p = os.path.join(onnx_dir(), name, file)
    if os.path.exists(p):
        return p
    raise FileNotFoundError(f"no ONNX model (models\\onnx\\{name}\\{file})")


class _Device:
    def __init__(self, kind):
        self.type = kind


class OnnxEncoder:
    """bge-m3 in ONNX with the interface search.py and embed.py use of SentenceTransformer. file: model.onnx (float32)
    or model.int8.onnx (int8 weights, for the processor); .variant says which."""

    def __init__(self, model_dir, device="dml:0", max_seq_length=8192, file="model.onnx", path=None):
        from transformers import AutoTokenizer

        name = os.path.basename(os.path.normpath(model_dir))
        self.tok = AutoTokenizer.from_pretrained(model_dir)
        self.sess = _session(path or model_file(name, file), device)
        self.max_seq_length = max_seq_length
        self.device = _Device("dml" if str(device).startswith("dml") else "cpu")
        self.variant = "int8" if "int8" in os.path.basename(path or file) else "fp32"
        dim = self.sess.get_outputs()[0].shape[-1]  # [batch, 1024]: the export names only the batch axis
        self.dim = dim if isinstance(dim, int) else None

    def get_sentence_embedding_dimension(self):
        if self.dim is None:  # a model exported with a symbolic last axis: ask it once
            self.dim = int(self.encode(["dimension"], normalize_embeddings=False).shape[1])
        return self.dim

    get_embedding_dimension = get_sentence_embedding_dimension

    def half(self):  # the weights are what the export made them; vectors are stored as float16 anyway
        return self

    def encode(self, texts, batch_size=32, normalize_embeddings=True, convert_to_numpy=True, **_):
        import numpy as np

        out = []
        order = sorted(range(len(texts)), key=lambda i: -len(texts[i]))  # similar lengths in a batch: less padding
        for k in range(0, len(order), batch_size):
            part = [texts[i] for i in order[k : k + batch_size]]
            t = self.tok(part, padding=True, truncation=True, max_length=self.max_seq_length, return_tensors="np")
            v = self.sess.run(
                None, {"input_ids": t["input_ids"].astype(np.int64), "attention_mask": t["attention_mask"].astype(np.int64)}
            )[0].astype(np.float32)
            out.append(v)
        if not out:
            return np.empty((0, self.dim or 0), dtype=np.float32)
        vecs = np.empty((len(texts), out[0].shape[1]), dtype=np.float32)
        vecs[order] = np.concatenate(out)
        if normalize_embeddings:
            vecs /= np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-12)
        return vecs


class OnnxCrossEncoder:
    """bge-reranker-v2-m3 in ONNX with the interface of CrossEncoder.predict (the logit: only the order matters)."""

    def __init__(self, model_dir, device="dml:0", max_length=1024):
        from transformers import AutoTokenizer

        name = os.path.basename(os.path.normpath(model_dir))
        self.tok = AutoTokenizer.from_pretrained(model_dir)
        self.sess = _session(model_file(name), device)
        self.max_length = max_length

    def predict(self, pairs, batch_size=16, **_):
        import numpy as np

        out = []
        for k in range(0, len(pairs), batch_size):
            q, d = zip(*pairs[k : k + batch_size])
            t = self.tok(list(q), list(d), padding=True, truncation=True, max_length=self.max_length, return_tensors="np")
            out.append(
                self.sess.run(
                    None,
                    {"input_ids": t["input_ids"].astype(np.int64), "attention_mask": t["attention_mask"].astype(np.int64)},
                )[0].reshape(-1)
            )
        return np.concatenate(out) if out else np.zeros(0, dtype=np.float32)


# ---------- export (build PC) ----------


def export():
    import torch
    from transformers import AutoModel, AutoModelForSequenceClassification

    torch.set_num_threads(max(1, (os.cpu_count() or 2) // 2))

    class Emb(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, input_ids, attention_mask):
            h = self.m(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state[:, 0]
            return torch.nn.functional.normalize(h.float(), dim=-1)

    class Rer(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, input_ids, attention_mask):
            return self.m(input_ids=input_ids, attention_mask=attention_mask).logits[:, 0].float()

    for name, load, wrap, out in (
        ("bge-m3", AutoModel, Emb, "embedding"),
        ("bge-reranker-v2-m3", AutoModelForSequenceClassification, Rer, "score"),
    ):
        src = os.path.join(models_dir(), name)
        dst = os.path.join(onnx_dir(), name)
        os.makedirs(dst, exist_ok=True)
        path = os.path.join(dst, "model.onnx")
        t0 = time.time()
        m = load.from_pretrained(src).eval()  # float32: an fp16 export from the CPU mixes types (LayerNorm)
        ids = torch.ones((2, 16), dtype=torch.long)
        mask = torch.ones((2, 16), dtype=torch.long)
        # the exporter writes the weights (>2 GB: a file per tensor) through a path it cannot open when it has Cyrillic
        # letters: into a temporary folder first, then one model.onnx + model.onnx.data in models/onnx
        import onnx, shutil, tempfile

        tmp = tempfile.mkdtemp(prefix="ax_onnx_")
        try:
            with torch.no_grad():
                torch.onnx.export(
                    wrap(m),
                    (ids, mask),
                    os.path.join(tmp, "model.onnx"),
                    dynamo=False,
                    opset_version=OPSET,
                    input_names=["input_ids", "attention_mask"],
                    output_names=[out],
                    dynamic_axes={
                        "input_ids": {0: "batch", 1: "seq"},
                        "attention_mask": {0: "batch", 1: "seq"},
                        out: {0: "batch"},
                    },
                )
            model = onnx.load(os.path.join(tmp, "model.onnx"))
            onnx.save(
                model,
                path,
                save_as_external_data=True,
                all_tensors_to_one_file=True,
                location=os.path.basename(path) + ".data",
                size_threshold=1024,
            )
            del model
        finally:
            shutil.rmtree(tmp, ignore_errors=True)  # the temporary folder made above
        size = sum(os.path.getsize(os.path.join(dst, f)) for f in os.listdir(dst))
        print(f"{name}: {path} ({size / 2**30:.2f} GB, {time.time() - t0:.0f} s)", flush=True)
        del m


# ---------- int8 for the processor ----------

MIN_MEAN_COS, MIN_COS = 0.99, 0.97  # --check: the int8 vectors against the float32 ones, else the file is refused
CHECK_FRAGMENTS = 200


def quantize(src, dst, per_channel=True, exclude=()):
    """model.onnx -> model.int8.onnx: the weights of every MatMul as int8 (onnxruntime dynamic quantization, a scale
    per output channel: one scale per tensor gave a mean cosine of 0.980 on bge-m3, below MIN_MEAN_COS), the
    activations stay float; exclude: names of nodes kept in float32. The word embeddings (a Gather) stay float32, so the file is ~1.3 GB.
    Nothing is written beside src: given a path, onnxruntime writes its shape inference as <src>-inferred.onnx there
    (the folder of the models, maybe a read-only link, maybe a Cyrillic path its C++ cannot open); given the loaded
    model it uses a temporary folder. Peak memory about three times the float32 model (~7 GB for bge-m3)."""
    import onnx
    from onnxruntime.quantization import QuantType, quantize_dynamic

    quantize_dynamic(
        onnx.load(src),
        dst,
        weight_type=QuantType.QInt8,
        per_channel=per_channel,
        reduce_range=False,
        op_types_to_quantize=["MatMul"],
        nodes_to_exclude=list(exclude),
    )


def sample_texts(cfg=None, n=CHECK_FRAGMENTS):
    """What --check embeds: n fragments of the base of the workspace as the models read them (common.model_text), or,
    without a base, the sample sentences of the language packs (model_check_sentences, in every language)."""
    from assistant_x.core import lang
    from assistant_x.core.common import PAGES_JOIN_SQL, SEARCH_TEXT_SQL, connect, has_column, load_config, model_text

    try:
        cfg = cfg or load_config()
        con = connect(cfg["db"], readonly=True)
        text, join = ("c.text", "") if has_column(con, "chunks", "text") else (SEARCH_TEXT_SQL, PAGES_JOIN_SQL)
        rows = con.execute(
            f"SELECT {text} AS text, c.heading, d.title FROM chunks c JOIN docs d ON d.code=c.code {join} "
            "ORDER BY random() LIMIT ?",
            (n,),
        ).fetchall()
        con.close()
        if rows:
            return [model_text(r["title"], r["heading"], r["text"]) for r in rows]
    except Exception:  # noqa: BLE001 — no workspace, no base: the sentences of the packs
        pass
    return [s for code in lang.available() for s in lang.get(code, "model_check_sentences", [])]


def cosines(a, b):
    import numpy as np

    return np.sum(a * b, axis=1) / np.maximum(np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1), 1e-12)


def check(model_dir, int8, fp32, texts, torch_model=None, say=print):
    """Embed texts with the int8 file, the float32 ONNX and torch (float32, the processor); (passed, report). Passed:
    the int8 vectors are within MIN_MEAN_COS on average and MIN_COS each of both others. The time per text of the
    int8 model goes into the measured speeds of the processor (gpu_guard.record_speed)."""
    from assistant_x.core import gpu_guard

    t0 = time.perf_counter()
    q = OnnxEncoder(model_dir, device="cpu", path=int8).encode(texts, batch_size=16)
    per_text = (time.perf_counter() - t0) / max(len(texts), 1)
    ref = {"onnx float32": OnnxEncoder(model_dir, device="cpu", path=fp32).encode(texts, batch_size=16)}
    if torch_model is None:
        from sentence_transformers import SentenceTransformer

        torch_model = SentenceTransformer(model_dir, device="cpu")
    ref["torch float32"] = torch_model.encode(texts, batch_size=16, normalize_embeddings=True, convert_to_numpy=True)
    ok, lines = True, [f"{len(texts)} texts, int8 {per_text:.2f} s per text on the processor"]
    for what, v in ref.items():
        c = cosines(q, v)
        good = float(c.mean()) >= MIN_MEAN_COS and float(c.min()) >= MIN_COS
        ok = ok and good
        lines.append(
            f"int8 against {what}: mean cosine {c.mean():.4f}, min {c.min():.4f} "
            f"({'ok' if good else f'below {MIN_MEAN_COS} / {MIN_COS}'})"
        )
    if ok and len(texts) >= 50:
        gpu_guard.record_speed("fragments", "cpu", per_text)
    for line in lines:
        say(line)
    return ok, lines


def int8_main(do_quantize):
    """--int8: quantize bge-m3 and check it; --check: check the file there is. A file that fails is deleted (exit 1):
    the search would mix vectors that are not the same as the base's."""
    name = "bge-m3"
    fp32, int8 = os.path.join(onnx_dir(), name, "model.onnx"), os.path.join(onnx_dir(), name, "model.int8.onnx")
    if not os.path.exists(fp32):
        print(f"No float32 ONNX model {fp32}: python -m assistant_x.search.onnx_models --export first.")
        return 1
    if do_quantize:
        t0 = time.time()
        quantize(fp32, int8)
        print(f"{name}: {int8} ({os.path.getsize(int8) / 2**30:.2f} GB, {time.time() - t0:.0f} s)", flush=True)
    elif not os.path.exists(int8):
        print(f"No int8 model {int8}: python -m assistant_x.search.onnx_models --int8")
        return 1
    ok, _ = check(os.path.join(models_dir(), name), int8, fp32, sample_texts())
    if not ok:
        os.remove(int8)
        print(f"Refused: {int8} deleted, the processor uses the float32 model.")
        return 1
    print("The int8 model gives the same vectors: the processor uses it ([search] cpu_int8 = true).")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--int8", action="store_true", help="bge-m3 with int8 weights for the processor, then --check")
    ap.add_argument("--check", action="store_true", help="the int8 vectors against the float32 ones (deleted below)")
    ap.add_argument("--adapters", action="store_true")
    a = ap.parse_args()
    if a.adapters:
        for i, n, v, m in adapters():
            print(f"{i}: {n} (vendor {v:04X}, {m:.1f} GB of its own memory)")
        return 0
    if a.export:
        export()
    if a.int8 or a.check:
        return int8_main(a.int8)
    if a.export:
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
