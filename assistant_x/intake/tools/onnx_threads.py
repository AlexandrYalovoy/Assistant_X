# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Threads of the ONNX models of pymupdf.layout and pymupdf4llm. A session made without options takes every core and
spins waiting for work, so a few conversions at once spend the CPU on that waiting: in debug/intake_timing 8 processes
converted the same 8 pages in 43 s each, against 2.7 s with one thread per session.

  limit(n)  before the first conversion of the process: at most n threads per session, one between operators, no busy
            waiting, whatever the session asked for (pymupdf4llm makes its own); the first call wins.
            n=None takes AX_ONNX_THREADS (default 1); 0 leaves onnxruntime as it is."""

import os

_done = False


def limit(n=None):
    global _done
    if _done:
        return
    _done = True
    n = int(os.environ.get("AX_ONNX_THREADS", 1)) if n is None else int(n)
    if n <= 0:
        return
    try:
        import onnxruntime as ort
    except ImportError:  # pymupdf4llm without the layout models: nothing to limit
        return
    base = ort.InferenceSession

    class Session(base):
        def __init__(self, path, sess_options=None, *a, **kw):
            so = sess_options or ort.SessionOptions()
            if not so.intra_op_num_threads or so.intra_op_num_threads > n:  # fewer threads asked by a session stay
                so.intra_op_num_threads = n
            so.inter_op_num_threads = 1
            so.add_session_config_entry("session.intra_op.allow_spinning", "0")
            so.add_session_config_entry("session.inter_op.allow_spinning", "0")
            super().__init__(path, so, *a, **kw)

    ort.InferenceSession = Session
