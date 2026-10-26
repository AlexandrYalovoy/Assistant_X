# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The model factory (search/models.py): which model is loaded on which device, int8 on the processor; the int8
quantization and its check (onnx_models.py), with stand-ins: no real model is run here (the real check needs the
models: python -m assistant_x.search.onnx_models --int8); the base that remembers its model; the measured speeds
(core/gpu_guard.py) and the estimate of the reindex."""

import os, sys, types

import numpy as np
import pytest

from assistant_x.core import common, gpu_guard
from assistant_x.search import models, onnx_models
from tests.search.fake_embedder import FakeEmbedder, FakeReranker, fake_models


class _Onnx:
    """A stand-in for OnnxEncoder / OnnxCrossEncoder: records how it was made."""

    made = []

    def __init__(self, model, device="dml:0", file="model.onnx", **kw):
        _Onnx.made.append((os.path.basename(model), device, file))
        self.device = types.SimpleNamespace(type="dml" if device.startswith("dml") else "cpu")
        self.variant = "int8" if "int8" in file else "fp32"


@pytest.fixture
def onnx_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(onnx_models, "ONNX_DIR", str(tmp_path / "onnx"))
    monkeypatch.setattr(onnx_models, "OnnxEncoder", _Onnx)
    monkeypatch.setattr(onnx_models, "OnnxCrossEncoder", _Onnx)
    _Onnx.made = []
    return tmp_path / "onnx"


def test_model_name():
    assert models.model_name("BAAI/bge-m3") == "bge-m3" and models.model_name("bge-m3") == "bge-m3"
    assert models.model_name(os.path.join("C:" + os.sep, "x", "models", "bge-m3") + os.sep) == "bge-m3"


def test_the_embedder_by_device(onnx_dir, monkeypatch):
    cfg = {"embed_model": "/m/bge-m3", "max_seq_length": 512}
    with fake_models():
        enc = models.load_embedder(cfg, "cpu")  # no int8 file: torch on the processor
        assert isinstance(enc, FakeEmbedder) and enc.max_seq_length == 512 and enc.variant == "fp32"
        (onnx_dir / "bge-m3").mkdir(parents=True)
        (onnx_dir / "bge-m3" / models.INT8).write_bytes(b"")
        assert isinstance(models.load_embedder(cfg, "cpu"), FakeEmbedder)  # int8 there, but off by default
        enc = models.load_embedder(dict(cfg, cpu_int8=True), "cpu")  # asked for: ONNX int8 on the processor
        assert _Onnx.made == [("bge-m3", "cpu", models.INT8)] and enc.variant == "int8" and enc.max_seq_length == 512
        enc = models.load_embedder(cfg, "dml:1")
        assert _Onnx.made[-1] == ("bge-m3", "dml:1", "model.onnx") and enc.variant == "fp32"
    halved = []

    class OnCuda(FakeEmbedder):
        def __init__(self, name=None, device=None, **kw):
            super().__init__(name, device)
            self.device = types.SimpleNamespace(type=device)

        def half(self):
            halved.append(1)
            return self

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=OnCuda))
    enc = models.load_embedder(cfg, "cuda")  # torch on the card: float16
    assert halved == [1] and enc.variant == "fp16" and enc.max_seq_length == 512


def test_the_reranker_by_device(onnx_dir):
    pytest.importorskip("torch")  # load_reranker imports torch for the CPU path; CI installs no torch
    with fake_models():
        assert isinstance(models.load_reranker({"rerank_model": "/m/bge-reranker-v2-m3"}, "cpu"), FakeReranker)
        models.load_reranker({"rerank_model": "/m/bge-reranker-v2-m3"}, "dml:0")
        assert _Onnx.made == [("bge-reranker-v2-m3", "dml:0", "model.onnx")]


def test_the_torch_reranker_gives_logits(monkeypatch):
    torch = pytest.importorskip("torch")
    seen = {}
    monkeypatch.setitem(
        sys.modules, "sentence_transformers", types.SimpleNamespace(CrossEncoder=lambda model, **kw: seen.update(kw))
    )
    models.load_reranker({"rerank_model": "x"}, "cpu")
    assert isinstance(seen["activation_fn"], torch.nn.Identity) and seen["max_length"] == 1024


def test_onnx_encoder_reads_its_dimension(monkeypatch, tmp_path):
    """The dimension comes from the output of the session, not from a constant; the vectors are normalized."""

    class Sess:
        def get_outputs(self):
            return [types.SimpleNamespace(shape=["batch", 8])]

        def run(self, _, feed):
            return [np.ones((feed["input_ids"].shape[0], 8), np.float32)]

    class Tok:
        def __call__(self, texts, **kw):
            return {"input_ids": np.ones((len(texts), 3)), "attention_mask": np.ones((len(texts), 3))}

    transformers = pytest.importorskip("transformers")
    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", lambda path: Tok())
    monkeypatch.setattr(onnx_models, "_session", lambda path, device: Sess())
    enc = onnx_models.OnnxEncoder(str(tmp_path / "bge-m3"), device="cpu", path=str(tmp_path / "model.int8.onnx"))
    assert enc.get_sentence_embedding_dimension() == 8 and enc.variant == "int8" and enc.device.type == "cpu"
    v = enc.encode(["a", "bb", "ccc"])
    assert v.shape == (3, 8) and np.allclose(np.linalg.norm(v, axis=1), 1)
    assert enc.encode([]).shape == (0, 8)


def _vectors(noise):
    """A stand-in OnnxEncoder whose int8 file gives the float32 vectors plus noise."""
    base = np.random.default_rng(0).standard_normal((60, 16)).astype(np.float32)
    base /= np.linalg.norm(base, axis=1, keepdims=True)

    class Enc:
        def __init__(self, model_dir, device="cpu", path=None, **kw):
            self.int8 = "int8" in os.path.basename(path or "")

        def encode(self, texts, **kw):
            if not self.int8:
                return base[: len(texts)]
            return base[: len(texts)] + noise * np.random.default_rng(1).standard_normal((len(texts), 16))

    return Enc, types.SimpleNamespace(encode=lambda texts, **kw: base[: len(texts)])


def test_check_of_the_int8_model(monkeypatch, tmp_path):
    monkeypatch.setenv("AX_SPEED_FILE", str(tmp_path / "speed.json"))
    texts = [f"text {i}" for i in range(60)]
    enc, torch_model = _vectors(0.01)
    monkeypatch.setattr(onnx_models, "OnnxEncoder", enc)
    ok, lines = onnx_models.check("bge-m3", "model.int8.onnx", "model.onnx", texts, torch_model, say=lambda *_: None)
    assert ok and "int8 against torch float32: mean cosine" in lines[-1]
    assert gpu_guard.measured("fragments", "cpu")  # 60 texts: the speed of the processor is remembered
    enc, torch_model = _vectors(0.5)
    monkeypatch.setattr(onnx_models, "OnnxEncoder", enc)
    ok, lines = onnx_models.check("bge-m3", "model.int8.onnx", "model.onnx", texts, torch_model, say=lambda *_: None)
    assert not ok and "below 0.99 / 0.97" in lines[1]


def test_a_refused_int8_file_is_deleted(onnx_dir, monkeypatch, capsys):
    (onnx_dir / "bge-m3").mkdir(parents=True)
    (onnx_dir / "bge-m3" / "model.onnx").write_bytes(b"")
    monkeypatch.setattr(onnx_models, "quantize", lambda src, dst: open(dst, "wb").close())
    monkeypatch.setattr(onnx_models, "sample_texts", lambda: ["a"])
    monkeypatch.setattr(onnx_models, "check", lambda *a, **k: (False, []))
    assert onnx_models.int8_main(True) == 1 and not (onnx_dir / "bge-m3" / models.INT8).exists()
    assert "Refused" in capsys.readouterr().out
    monkeypatch.setattr(onnx_models, "check", lambda *a, **k: (True, []))
    assert onnx_models.int8_main(True) == 0 and (onnx_dir / "bge-m3" / models.INT8).exists()
    assert onnx_models.int8_main(False) == 0  # --check of the file there is


def test_sample_texts_of_the_base_or_of_the_packs(dense):
    texts = onnx_models.sample_texts(dense.cfg, n=5)
    assert len(texts) == 5 and all(
        t.splitlines()[0] in {r[0] for r in dense.con.execute("SELECT title FROM docs")} for t in texts
    )
    packs = onnx_models.sample_texts({"db": "/no/base.sqlite"})
    assert len(packs) >= 20 and any("quality management" in t for t in packs) and any(not t.isascii() for t in packs)


# ---------- one base, one model ----------


@pytest.fixture
def own(tmp_path):
    from tests.search.conftest import dense_library

    return dense_library(str(tmp_path / "Библиотека"))


def set_model(lib, name):
    path = os.path.join(lib.cfg["workspace"], "assistant_x.toml")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text.replace('embed_model = "models/bge-m3"', f'embed_model = "models/{name}"'))
    return path


def test_the_base_remembers_its_model(own):
    assert common.meta(own.con, "embed_model") == "bge-m3" and common.meta(own.con, "embed_variant") == "fp32"
    assert own.search("насос", stats=(st := {})) and "dense_error" not in st
    config = set_model(own, "e5-large")
    with open(os.path.join(own.cfg["texts_dir"], "N-00002.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("=== page 1 ===\n\nНовый абзац о сепараторе.\n\n")  # a fragment to embed
    from tests.search.conftest import build
    from tests.search.fake_embedder import embed

    build(config)
    with pytest.raises(SystemExit, match="embedded with bge-m3, this workspace is set to e5-large; one base, one model"):
        embed(config)
    from tests.search.fake_embedder import fake_library

    other = fake_library(common.load_config(config))
    st = {}
    assert other.search("насос", stats=st)  # by words
    assert "one base, one model" in st["dense_error"] and "dense_top" not in st


def test_an_older_base_kept_the_path_of_its_model(own):
    con = common.connect(own.cfg["db"])
    con.execute("INSERT OR REPLACE INTO meta VALUES('embed_model', ?)", (os.path.join(own.cfg["models_dir"], "bge-m3"),))
    con.commit()
    assert models.model_mismatch(own.cfg, con) is None
    assert "one base" in models.model_mismatch(dict(own.cfg, embed_model="x/e5-large"), con)
    con.execute("UPDATE chunks SET vec_row = NULL")  # no vectors yet: any model may start the base
    assert models.model_mismatch(dict(own.cfg, embed_model="x/e5-large"), con) is None
    con.rollback()


# ---------- the measured speeds ----------


def test_speeds_are_measured_and_used(monkeypatch, tmp_path):
    monkeypatch.setenv("AX_SPEED_FILE", str(tmp_path / "speed.json"))
    assert gpu_guard.measured("fragments", "cpu") is None
    gpu_guard.record_speed("fragments", "cpu", 0.1, n=10)  # too few to say anything
    assert gpu_guard.measured("fragments", "cpu") is None
    s = gpu_guard.measure_speed(FakeEmbedder(), [f"t {i}" for i in range(60)])
    assert gpu_guard.measured("fragments", "cpu") == pytest.approx(s, abs=1e-5)
    gpu_guard.record_speed("fragments", "cuda:0", 0.01, n=500)
    assert gpu_guard.measured("fragments", "cuda") == 0.01
    assert gpu_guard.estimate(600, "fragments", "cuda", cpu_s=0.4) == pytest.approx(6.0)
    assert gpu_guard.estimate(10, "fragments", "dml", cpu_s=0.4) is None  # a card never measured: no guess
    gpu_guard.record_speed("fragments", "cpu", 0.25, n=100)
    said = []
    monkeypatch.setattr(gpu_guard, "low_priority", lambda: None)
    monkeypatch.setattr(gpu_guard, "journal", lambda text: None)
    assert gpu_guard.check({}, "embed", units=480, cpu_s=0.4, cpu=True, say=said.append) == "cpu"
    assert "about 2 min" in said[0]  # 480 x 0.25 s measured, not 480 x 0.4 s


def _torch(cuda):
    return types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: cuda))


def test_a_card_torch_cannot_use_is_no_card(monkeypatch):
    """nvidia-smi reports a card, the torch installed is the CPU build: not "cuda" (it would crash in the model), the
    question about the processor instead, with the hint how to get the CUDA build; torch with CUDA, or no torch at all,
    keep the card."""
    monkeypatch.setattr(gpu_guard, "_smi", lambda *q: ["NVIDIA GeForce RTX 5080, 15000, 16303"])
    monkeypatch.setattr(gpu_guard, "_dml", lambda cfg: None)
    monkeypatch.setattr(gpu_guard, "journal", lambda text: None)
    monkeypatch.setattr(gpu_guard, "ask", lambda text: None)  # nobody at the console
    monkeypatch.setitem(sys.modules, "torch", _torch(False))
    said = []
    with pytest.raises(SystemExit) as e:
        gpu_guard.check({}, "embed", units=70, say=said.append)
    assert e.value.code == gpu_guard.BUSY and gpu_guard.NO_CUDA in said[0] and "no video card" in said[1]
    monkeypatch.setattr(gpu_guard, "ask", lambda text: True)
    monkeypatch.setattr(gpu_guard, "low_priority", lambda: None)
    assert gpu_guard.check({}, "embed", units=70, say=said.append) == "cpu"  # "y" at the question
    monkeypatch.setitem(sys.modules, "torch", _torch(True))
    assert gpu_guard.check({}, "embed", units=70, say=said.append) == "cuda"
    monkeypatch.setitem(sys.modules, "torch", None)  # no torch: import fails, the card is kept as before
    assert gpu_guard.check({}, "embed", units=70, say=said.append) == "cuda"


def test_reindex_tells_the_time_of_the_embeddings(own, monkeypatch, tmp_path):
    from assistant_x.server import intake_tools

    monkeypatch.setenv("AX_SPEED_FILE", str(tmp_path / "speed.json"))
    monkeypatch.setenv("AX_SEARCH_CONFIG", os.path.join(own.cfg["workspace"], "assistant_x.toml"))
    monkeypatch.setattr(intake_tools, "_job", lambda kind: None)
    monkeypatch.setattr(intake_tools, "_start", lambda kind, cmd, **env: (True, ""))
    assert intake_tools.pending_fragments(own.cfg) == 0  # every fragment has its vector, no newer text
    assert "Embeddings" not in intake_tools.reindex()
    later = os.path.getmtime(own.cfg["db"]) + 10
    for name in ("N-00001.md", "J-00001.md"):
        os.utime(os.path.join(own.cfg["texts_dir"], name), (later, later))
    assert intake_tools.pending_fragments(own.cfg) == 6  # their pages, a fragment each
    assert "Embeddings" not in intake_tools.reindex()  # no video card measured here: no guess
    gpu_guard.record_speed("fragments", "cuda", 30.0, n=100)
    out = intake_tools.reindex()
    assert "Embeddings: about 3 min (6 fragments, on the video card, the speed measured on this PC)." in out
    assert "Embeddings: about 5 s (6 fragments, on the processor, not measured on this PC yet)." in intake_tools.reindex(
        cpu=True
    )
