# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one place that loads the models of the meaning search, for embed.py and the search (retrieval.Library) alike.

    load_embedder(cfg, device)   bge-m3: "dml:N" — ONNX through DirectML (onnx_models.py); "cuda" — torch in float16;
                                 "cpu" — the int8 ONNX (models/onnx/bge-m3/model.int8.onnx, onnx_models.py --export
                                 --int8) when it is there and [search] cpu_int8 = true, else torch;
                                 None — CUDA when torch sees a card, else the processor. max_seq_length from [search].
    load_reranker(cfg, device)   bge-reranker-v2-m3: "dml:N" — ONNX, else torch (CrossEncoder giving the logit).
    model_name(path)             "bge-m3" of a folder or of a HuggingFace name: what a base remembers of its model.
    model_mismatch(cfg, con)     why the vectors of a base do not fit the model of this workspace, or None.

One base, one model, forever: the vectors of a base are compared with the vectors of the questions, so a base is
embedded by one model only (meta embed_model), whoever builds or extends it. The speed-ups keep the vectors: float16
on a video card, DirectML, int8 on a processor all give vectors of the same model (cosine >= 0.99 to the float32
ones, onnx_models.py --check), which is why embed_variant is only informational and never refused."""

import os, re

INT8 = "model.int8.onnx"


def model_name(path):
    """The name of a model: the last part of its folder or of its HuggingFace name ("BAAI/bge-m3" -> "bge-m3")."""
    return re.split(r"[\\/]", os.path.normpath(str(path or "")).rstrip("\\/"))[-1]


def resolve_device(device):
    """The device to load on: the one given, else "cuda" when torch sees a card, else "cpu"."""
    if device:
        return str(device)
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def int8_path(model):
    """models/onnx/<name of the model>/model.int8.onnx."""
    from assistant_x.search import onnx_models

    return os.path.join(onnx_models.onnx_dir(), model_name(model), INT8)


def load_embedder(cfg, device=None):
    """The embedding model of cfg on device, with the interface of SentenceTransformer (encode, max_seq_length,
    device.type, the dimension); .variant tells "fp16", "fp32" or "int8"."""
    model = cfg.get("embed_model") or "BAAI/bge-m3"
    device = resolve_device(device)
    if device.startswith("dml"):  # AMD or Intel card: the same vectors from ONNX through DirectML
        from assistant_x.search import onnx_models

        enc = onnx_models.OnnxEncoder(model, device=device)
    elif device == "cpu" and cfg.get("cpu_int8", False) and os.path.exists(int8_path(model)):
        from assistant_x.search import onnx_models  # ~1.7x faster on a processor, accepted only by --check

        enc = onnx_models.OnnxEncoder(model, device="cpu", file=INT8)
    else:
        from sentence_transformers import SentenceTransformer

        enc = SentenceTransformer(model, device=device)
    enc.max_seq_length = int(cfg.get("max_seq_length", 1024))  # the same for the fragments and the questions
    if enc.device.type == "cuda":
        enc.half()  # float16 on the GPU: about twice as fast, vectors are stored as float16 anyway
    if not hasattr(enc, "variant"):
        enc.variant = "fp16" if enc.device.type == "cuda" else "fp32"
    return enc


def load_reranker(cfg, device=None):
    """The reranker of cfg on device, with the interface of CrossEncoder.predict giving the logit (retrieval.rerank
    takes its sigmoid)."""
    model = cfg.get("rerank_model") or "BAAI/bge-reranker-v2-m3"
    device = resolve_device(device)
    if device.startswith("dml"):
        from assistant_x.search import onnx_models

        return onnx_models.OnnxCrossEncoder(model, device=device)
    import torch
    from sentence_transformers import CrossEncoder

    # the default activation of CrossEncoder for one label is a sigmoid: the logit instead, as ONNX gives it
    enc = CrossEncoder(model, device=device, max_length=1024, activation_fn=torch.nn.Identity())
    net = getattr(enc, "model", None)
    if net is not None and getattr(getattr(net, "device", None), "type", "") == "cuda":
        # float16 on the card: the same ranks on 40 control questions, a third of the time, much less video memory
        net.half()
    return enc


def model_mismatch(cfg, con):
    """A message when the base has vectors of another model than the one this workspace is set to, else None (the
    names are compared: model_name of a folder or of a HuggingFace name)."""
    from assistant_x.core.common import meta

    had = meta(con, "embed_model")
    want = model_name(cfg.get("embed_model") or "BAAI/bge-m3")
    if not had or model_name(had) == want:
        return None
    if not con.execute("SELECT 1 FROM chunks WHERE vec_row IS NOT NULL LIMIT 1").fetchone():
        return None  # no vectors yet: the base takes the model of the workspace
    return (
        f"The base was embedded with {model_name(had)}, this workspace is set to {want}; one base, one model. "
        f'Set embed_model = "{model_name(had)}" in assistant_x.toml, or build the base anew '
        f"(assistant-x build --full, then assistant-x embed)."
    )
