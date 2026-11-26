# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run with AX_TEST_CUDA_MODELS pointing to the two installed BAAI model folders."""

import os
from pathlib import Path

import pytest


@pytest.mark.slow
def test_cuda_embedding_and_reranking(monkeypatch):
    folder = os.environ.get("AX_TEST_CUDA_MODELS")
    if not folder:
        pytest.skip("set AX_TEST_CUDA_MODELS to qualify a CUDA release")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    import numpy as np
    import torch

    from assistant_x.search import models
    from assistant_x.setup import install

    assert torch.__version__ == install.GPU_TORCH.split("==")[1]
    assert models.resolve_device(None) == "cuda"
    cfg = {
        key: str(Path(folder) / name) for key, name in (("embed_model", "bge-m3"), ("rerank_model", "bge-reranker-v2-m3"))
    }
    query = "What is the inspection interval for the separator?"
    texts = ["Inspect the separator every twelve months.", "The office kitchen serves breakfast at eight."]
    enc = models.load_embedder(cfg)
    assert enc.device.type == "cuda" and enc.variant == "fp16"
    vectors = enc.encode([query, *texts], normalize_embeddings=True).astype("float32")
    assert vectors.shape == (3, 1024) and np.isfinite(vectors).all()
    assert np.dot(vectors[0], vectors[1]) > np.dot(vectors[0], vectors[2])
    del enc
    torch.cuda.empty_cache()

    ranker = models.load_reranker(cfg)
    assert ranker.model.device.type == "cuda"
    scores = ranker.predict([(query, text) for text in texts])
    assert np.isfinite(scores).all() and scores[0] > scores[1]
