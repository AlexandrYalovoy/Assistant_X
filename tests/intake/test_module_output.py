# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The intake modules run by themselves (python -m, as apply_job runs them) with the output in a legacy code page:
a character such as an arrow is replaced instead of stopping the command halfway (an apply stopped on a log line)."""

import io
import sys

import pytest


def cp1251_out(monkeypatch):
    """Set in the test itself: the capture of pytest puts its own stdout back after the fixtures."""
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1251")
    monkeypatch.setattr(sys, "stdout", out)
    return out


def test_pipeline_output_survives_an_arrow(monkeypatch):
    from assistant_x.intake import pipeline

    out = cp1251_out(monkeypatch)
    with pytest.raises(SystemExit):
        pipeline.main(["--help"])
    print("a → b")
    out.flush()


def test_apply_job_output_survives_an_arrow(monkeypatch):
    from assistant_x.core import proc
    from assistant_x.intake import apply_job

    monkeypatch.setattr(apply_job, "write_progress", lambda *a, **k: None)
    monkeypatch.setattr(proc, "call", lambda *a, **k: 1)
    out = cp1251_out(monkeypatch)
    assert apply_job.main([]) == 1
    print("a → b")
    out.flush()
