# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic stand-ins for the models of the meaning search, so that the dense path, the fusion and the reranking
run in the tests without bge-m3, without torch and without a video card.

  FakeEmbedder   SentenceTransformer: a text is the normalized hashed bag of its word stems (common.tokens, stop
                 words dropped) in FAKE_DIM dimensions, the same for a question and a fragment. Two texts with shared
                 stems are close, others nearly orthogonal: a crude but stable "meaning" that words in another order,
                 or a few words of a long fragment, still find.
  FakeReranker   CrossEncoder: predict(pairs) gives a logit from the share of the stems of the question that the
                 fragment has (6 * share - 3: all stems ~ +3, none -3).
  fake_models()  sentence_transformers replaced by the two, the machine lock and the video card check skipped:
                 embed.main runs as on a PC with the models.
  embed(config)  embed.main on a built base with the fakes: vectors.f16 of dimension FAKE_DIM.
  fake_library(cfg)  a Library with the fakes loaded and the meaning search ready.

The numbers these give (tests/search/quality.py) measure the plumbing: the fusion, the weights, the pool, the
filters. What bge-m3 itself does on a real library comes from assistant-x eval --from-cards there."""

import contextlib, os, sys, types, zlib

import numpy as np

from assistant_x.core.common import tokens

FAKE_DIM = 64


def stems(text):
    return [t for t in tokens(text or "", drop_stop=True) if t]


def bag(text, dim=FAKE_DIM):
    """The hashed bag of stems of a text: a stem adds +1 or -1 (by another bit of its hash) to one dimension."""
    v = np.zeros(dim, dtype=np.float32)
    for s in stems(text):
        h = zlib.crc32(s.encode("utf-8"))
        v[h % dim] += 1.0 if (h >> 16) & 1 else -1.0
    return v


class FakeEmbedder:
    """The interface of SentenceTransformer that embed.py and retrieval.py use."""

    def __init__(self, name=None, device=None, **_):
        self.name = name
        self.device = types.SimpleNamespace(type="cpu")
        self.max_seq_length = 512
        self.encoded = 0  # texts encoded so far: what a test may count

    def get_sentence_embedding_dimension(self):
        return FAKE_DIM

    get_embedding_dimension = get_sentence_embedding_dimension

    def half(self):
        return self

    def encode(self, texts, batch_size=32, normalize_embeddings=True, convert_to_numpy=True, **_):
        self.encoded += len(texts)
        v = np.stack([bag(t) for t in texts]) if len(texts) else np.zeros((0, FAKE_DIM), np.float32)
        if normalize_embeddings:
            v /= np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)
        return v


class FakeReranker:
    """The interface of CrossEncoder.predict: a logit per (question, fragment) pair."""

    def __init__(self, name=None, device=None, max_length=None, **_):
        self.name, self.max_length = name, max_length
        self.pairs = 0

    def predict(self, pairs, batch_size=16, **_):
        self.pairs += len(pairs)
        out = []
        for q, d in pairs:
            want, have = set(stems(q)), set(stems(d))
            out.append(6.0 * len(want & have) / len(want) - 3.0 if want else -3.0)
        return np.array(out, dtype=np.float32)


@contextlib.contextmanager
def fake_models():
    """sentence_transformers replaced by the fakes; no machine lock, no video card check (always the processor)."""
    from assistant_x.core import gpu_guard

    saved = sys.modules.get("sentence_transformers"), gpu_guard.hold_machine, gpu_guard.check
    sys.modules["sentence_transformers"] = types.SimpleNamespace(SentenceTransformer=FakeEmbedder, CrossEncoder=FakeReranker)
    gpu_guard.hold_machine = lambda *a, **k: None
    gpu_guard.check = lambda *a, **k: "cpu"
    try:
        yield
    finally:
        if saved[0] is None:
            sys.modules.pop("sentence_transformers", None)
        else:
            sys.modules["sentence_transformers"] = saved[0]
        gpu_guard.hold_machine, gpu_guard.check = saved[1:]


def embed(config, *args):
    """embed.main on the base of config with the fake model (its folder is made: embed.py asks for it)."""
    from assistant_x.core.common import load_config
    from assistant_x.search import embed as embed_mod

    model = load_config(config).get("embed_model") or ""
    if os.path.isabs(model):
        os.makedirs(model, exist_ok=True)
    argv = sys.argv
    sys.argv = ["embed.py", "--config", config, *args]
    try:
        with fake_models():
            embed_mod.main()
    finally:
        sys.argv = argv


def fake_library(cfg):
    """A Library on cfg with the fake models in place of the real ones and the meaning search ready."""
    from assistant_x.search.retrieval import Library

    lib = Library(cfg)
    lib._embedder, lib._reranker = FakeEmbedder(), FakeReranker()
    lib.dense_ready.set()
    return lib
