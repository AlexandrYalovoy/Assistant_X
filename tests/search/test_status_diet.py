# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A short intake_status (audit 7, M-042, M-033, M-028, M-005, M-006, M-047): at most 3 000 characters by default, a
background job that ended before the batch started left out, the summary and the quality only with full=True; the
harmless warnings of the model libraries out of the job tails; PYTHONUTF8 in the Claude Desktop entry."""

import json, os, time

import psutil

from assistant_x.server import intake_tools


def _data(errors=0, started=None):
    return {
        "done": 3,
        "total": 3 + errors,
        "running": [],
        "queued": [],
        "errors": [
            {"tid": f"T{i:04d}", "status": "error", "rel": f"folder/file {i}.pdf", "why": "x" * 120} for i in range(errors)
        ],
        "eta_seconds": None,
        "started": started,
    }


def _setup(tmp_path, monkeypatch, data):
    monkeypatch.setattr(intake_tools, "JOBS", str(tmp_path / "_claude"))
    os.makedirs(tmp_path / "_claude", exist_ok=True)
    work = tmp_path / "2026-10-27"
    work.mkdir()
    (work / "summary.md").write_text("# Intake summary\n" + "line\n" * 2000, encoding="utf-8")
    monkeypatch.setattr(intake_tools, "_last_work", lambda: str(work))
    monkeypatch.setattr(intake_tools, "_intake", lambda *a, **k: (0, json.dumps(data) if "status" in a else "0\n"))
    monkeypatch.setattr(intake_tools, "vector_note", lambda: "")
    return tmp_path / "_claude"


def _finished_job(d, kind, started, ended):
    p = psutil.Process(os.getpid())
    job = {"id": "j", "pid": 999999, "created": p.create_time(), "cmd": [], "started": started}
    (d / f"{kind}.json").write_text(json.dumps(job), encoding="utf-8")
    (d / f"{kind}.exit.json").write_text(json.dumps({"job": "j", "code": 0}), encoding="utf-8")
    os.utime(d / f"{kind}.exit.json", (ended, ended))


def test_the_status_is_short(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, _data(errors=40))
    out = intake_tools.status()
    assert len(out) <= intake_tools.SHORT and "intake_status(full=True)" in out and "## summary.md" not in out
    assert out.startswith("Batch: 3 of 43 files done")
    full = intake_tools.status(full=True)
    assert "## summary.md" in full and len(full) > intake_tools.SHORT


def test_a_job_before_the_batch_is_left_out(tmp_path, monkeypatch):
    now = time.time()
    d = _setup(tmp_path, monkeypatch, _data(started=now - 3600))
    _finished_job(d, "reindex", now - 9 * 3600, now - 8 * 3600)  # before the batch started
    _finished_job(d, "apply", now - 1800, now - 900)
    out = intake_tools.status()
    assert "Base recalculation" not in out
    assert "Transfer to the library: finished 15 min ago in 15 min." in out


def test_harmless_warnings_out_of_the_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_tools, "JOBS", str(tmp_path))
    (tmp_path / "reindex.log").write_text(
        "W1027 10:01:02.123 12345 redirects.py:29] NOTE: Redirects are currently not supported in Windows or MacOs.\n"
        "embed: 900 of 900 fragments\n"
        "C:/x/site-packages/torch/nn/functional.py:5000: UserWarning: something\n",
        encoding="utf-8",
    )
    assert intake_tools._tail("reindex") == "embed: 900 of 900 fragments"


def test_the_desktop_entry_has_pythonutf8(tmp_path, monkeypatch):
    from assistant_x.clients import claude_desktop
    from assistant_x.setup import install

    conf = tmp_path / "claude_desktop_config.json"
    conf.write_text(json.dumps({"mcpServers": {install.SERVER: {"command": "old", "env": {"MINE": "1"}}}}), encoding="utf-8")
    monkeypatch.setattr(claude_desktop, "dirs", lambda: ([str(tmp_path)], True))
    install.register_desktop("python.exe", False)
    env = json.loads(conf.read_text(encoding="utf-8"))["mcpServers"][install.SERVER]["env"]
    assert env["PYTHONUTF8"] == "1" and env["MINE"] == "1" and env["HF_HUB_OFFLINE"] == "1"
