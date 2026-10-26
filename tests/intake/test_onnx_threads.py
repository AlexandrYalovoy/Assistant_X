# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""intake/tools/onnx_threads.py: every ONNX session of the process gets at most n threads, one between operators and
no busy waiting; a session that asks for fewer keeps them; the first call wins; 0 leaves onnxruntime alone."""

import sys, types

import pytest

from assistant_x.intake.tools import onnx_threads


class Options:
    def __init__(self):
        self.intra_op_num_threads, self.inter_op_num_threads, self.entries = 0, 0, {}

    def add_session_config_entry(self, k, v):
        self.entries[k] = v


class Session:
    def __init__(self, path, sess_options=None, *a, **kw):
        self.path, self.options = path, sess_options


@pytest.fixture
def ort(monkeypatch):
    fake = types.SimpleNamespace(InferenceSession=Session, SessionOptions=Options)
    monkeypatch.setitem(sys.modules, "onnxruntime", fake)
    monkeypatch.setattr(onnx_threads, "_done", False)
    return fake


def test_the_sessions_are_limited(ort, monkeypatch):
    monkeypatch.setenv("AX_ONNX_THREADS", "2")
    onnx_threads.limit()
    s = ort.InferenceSession("model.onnx")
    assert s.options.intra_op_num_threads == 2 and s.options.inter_op_num_threads == 1
    assert s.options.entries == {"session.intra_op.allow_spinning": "0", "session.inter_op.allow_spinning": "0"}
    few = Options()
    few.intra_op_num_threads = 1
    assert ort.InferenceSession("m", few).options.intra_op_num_threads == 1  # fewer asked: kept
    many = Options()
    many.intra_op_num_threads = 16
    assert ort.InferenceSession("m", many).options.intra_op_num_threads == 2
    cls = ort.InferenceSession
    onnx_threads.limit(8)  # the first call wins
    assert ort.InferenceSession is cls


def test_zero_leaves_onnxruntime_alone(ort):
    onnx_threads.limit(0)
    assert ort.InferenceSession is Session


def test_without_onnxruntime(monkeypatch):
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    monkeypatch.setattr(onnx_threads, "_done", False)
    onnx_threads.limit(1)  # nothing to limit, no error
