# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""DirectML backend (onnx_models.py): when it is chosen, that the search and embed.py load the ONNX models then, and
that gpu_guard takes a card with its own memory instead of asking about the processor. No model is run here."""

import pytest

from assistant_x.core import gpu_guard
from assistant_x.search import onnx_models

RX = [(0, "AMD Radeon RX 7600", onnx_models.AMD, 8.0), (1, "AMD Radeon(TM) Graphics", onnx_models.AMD, 0.5)]


class _Ort:
    def __init__(self, providers):
        self.providers = providers

    def get_available_providers(self):
        return self.providers


@pytest.fixture
def dml_ready(monkeypatch, tmp_path):
    """DirectML installed, the ONNX models in place, no CUDA, an AMD card with 8 GB."""
    import sys

    monkeypatch.setitem(sys.modules, "onnxruntime", _Ort(["DmlExecutionProvider", "CPUExecutionProvider"]))
    (tmp_path / "bge-m3").mkdir()
    (tmp_path / "bge-m3" / "model.onnx").write_bytes(b"")
    monkeypatch.setattr(onnx_models, "ONNX_DIR", str(tmp_path))
    monkeypatch.setattr(onnx_models, "adapters", lambda: RX)
    torch = pytest.importorskip("torch")  # CI installs no torch (the dense extra): these tests skip there

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)


def test_pick_adapter_skips_integrated_and_nvidia(monkeypatch):
    monkeypatch.setattr(onnx_models, "adapters", lambda: [(0, "NVIDIA GeForce RTX 5080", onnx_models.NVIDIA, 15.6)] + RX[1:])
    assert onnx_models.pick_adapter() is None  # NVIDIA goes through CUDA, the integrated one is no faster than the CPU
    monkeypatch.setattr(onnx_models, "adapters", lambda: RX)
    assert onnx_models.pick_adapter() == (0, "AMD Radeon RX 7600", 8.0)
    assert onnx_models.pick_adapter(1) == (1, "AMD Radeon(TM) Graphics", 0.5)


def test_dml_device_by_backend(dml_ready, monkeypatch):
    assert onnx_models.dml_device({"backend": "auto"}) == "dml:0"
    assert onnx_models.dml_device({"backend": "torch"}) is None
    assert onnx_models.dml_device({"backend": "onnx-dml", "dml_device": 1}) == "dml:1"
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert onnx_models.dml_device({"backend": "auto"}) is None  # CUDA first
    assert onnx_models.dml_device({"backend": "onnx-dml"}) == "dml:0"


def test_no_directml_package_means_torch(monkeypatch, tmp_path):
    import sys

    monkeypatch.setitem(sys.modules, "onnxruntime", _Ort(["CPUExecutionProvider"]))
    monkeypatch.setattr(onnx_models, "adapters", lambda: RX)
    assert onnx_models.dml_device({"backend": "onnx-dml"}) is None


def test_search_loads_onnx_on_directml(dml_ready, lib, monkeypatch):
    made = []

    class Enc:
        def __init__(self, model, device):
            made.append(device)
            self.device = __import__("types").SimpleNamespace(type="dml")

    monkeypatch.setattr(onnx_models, "OnnxEncoder", Enc)
    monkeypatch.setattr(lib, "_dml", False)
    monkeypatch.setitem(lib.cfg, "embed_model", onnx_models.onnx_dir())  # any existing folder: Enc does not read it
    assert isinstance(lib._load_embedder(None), Enc) and made == ["dml:0"]
    assert lib.may_rerank() is False  # the mini library has no reranker folder
    import sys, types

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(
            SentenceTransformer=lambda model, device: types.SimpleNamespace(
                torch=True, device=types.SimpleNamespace(type=device)
            )
        ),
    )
    enc = lib._load_embedder("cpu")  # the second server: torch on the processor, not DirectML
    assert enc.torch and enc.device.type == "cpu" and enc.max_seq_length == 1024 and enc.variant == "fp32"


def test_gpu_guard_takes_a_card_with_own_memory(dml_ready, monkeypatch):
    monkeypatch.setattr(gpu_guard, "card", lambda: None)
    monkeypatch.setattr(gpu_guard, "journal", lambda text: None)
    assert gpu_guard.check({"gpu_min_free_gb": 5}, "embed", units=100, say=lambda *_: None) == "dml:0"
    monkeypatch.setattr(onnx_models, "adapters", lambda: [(0, "AMD Radeon RX 6400", onnx_models.AMD, 3.0)])
    with pytest.raises(SystemExit):  # too little memory: the usual question about the processor (nobody to answer)
        gpu_guard.check({"gpu_min_free_gb": 5}, "embed", units=100, say=lambda *_: None)
