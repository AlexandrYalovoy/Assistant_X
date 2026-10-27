# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The transfer into the library as a background job and a base that is up to date (audit 7, M-045, M-046):
intake_apply(confirm=True) answers at once and intake_status shows the stage of the job; a second call while it runs
says so; intake_reindex does nothing on a base that is up to date unless forced, and reindex_last.json tells when the
base was last recalculated."""

import json, os, sqlite3, subprocess, sys, time

import psutil

from assistant_x.search import reindex
from assistant_x.server import intake_tools


def _jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_tools, "JOBS", str(tmp_path / "_claude"))
    os.makedirs(tmp_path / "_claude", exist_ok=True)
    return tmp_path / "_claude"


def _write_job(d, pid, ident="j1"):
    job = {"id": ident, "pid": pid, "created": psutil.Process(pid).create_time(), "cmd": [], "started": time.time() - 120}
    (d / "apply.json").write_text(json.dumps(job), encoding="utf-8")
    return job


def test_the_states_of_the_transfer_job(tmp_path, monkeypatch):
    d = _jobs(tmp_path, monkeypatch)
    _write_job(d, os.getpid())  # a live process stands for the job
    assert intake_tools.state("apply")[0] == "running"
    assert intake_tools.apply(confirm=False).startswith("The transfer is already running (started 2 min ago)")
    assert intake_tools.reindex().startswith("The transfer into the library is running")
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    job = _write_job(d, p.pid)
    p.wait()
    assert intake_tools.state("apply", job)[0] == "stopped"  # gone without an exit code
    (d / "apply.exit.json").write_text(json.dumps({"job": "j1", "code": 0}), encoding="utf-8")
    assert intake_tools.state("apply", job) == ("finished", 0)
    (d / "apply.exit.json").write_text(json.dumps({"job": "j1", "code": 2}), encoding="utf-8")
    assert intake_tools.state("apply", job) == ("failed", 2)
    assert any("apply" in x for x in intake_tools.interrupted())


def test_the_transfer_starts_in_the_background(tmp_path, monkeypatch):
    d = _jobs(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setattr(intake_tools, "_start", lambda kind, cmd, **env: seen.append((kind, cmd, env)) or (True, ""))
    monkeypatch.setattr(intake_tools, "_last_work", lambda: str(tmp_path))
    (tmp_path / "meta.jsonl").write_text(
        "\n".join(json.dumps(x) for x in ({"tid": "T0001", "sec": "N"}, {"tid": "T0002", "part": "T0001"})),
        encoding="utf-8",
    )
    out = intake_tools.start_apply(personal=True)
    assert out == (
        "The transfer started in the background: 1 documents; intake_status shows the stage; the base is "
        "recalculated after it."
    )
    kind, cmd, env = seen[0]
    assert kind == "apply" and cmd[1:] == ["-m", "assistant_x.intake.apply_job", "--personal"]
    assert env["AX_PROGRESS"] == str(d / "apply.progress.json")
    monkeypatch.setenv(reindex.PROGRESS, env["AX_PROGRESS"])
    reindex.write_progress("apply")
    assert intake_tools.reindex_words({}, env["AX_PROGRESS"]) == "Step: moving the files into the library (apply)."


def _base(tmp_path, missing=0):
    db = tmp_path / "db" / "search.sqlite"
    db.parent.mkdir()
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE chunks(id INTEGER PRIMARY KEY, vec_row INTEGER)")
    con.executemany("INSERT INTO chunks(vec_row) VALUES(?)", [(i,) for i in range(10)] + [(None,)] * missing)
    con.commit()
    con.close()
    texts, cards = tmp_path / "texts", tmp_path / "cards"
    texts.mkdir()
    cards.mkdir()
    old = time.time() - 3600
    for p in (texts / "N-00001.md", cards / "N-00001.json"):
        p.write_text("=== page 1 ===\n\nx\n", encoding="utf-8")
        os.utime(p, (old, old))
    return {"db": str(db), "texts_dir": str(texts), "cards_dir": str(cards)}


def test_an_up_to_date_base_is_not_recalculated(tmp_path, monkeypatch):
    _jobs(tmp_path, monkeypatch)
    cfg = _base(tmp_path)
    from assistant_x.core import common

    monkeypatch.setattr(common, "load_config", lambda path=None: cfg)
    started = []
    monkeypatch.setattr(intake_tools, "_start", lambda kind, cmd, **env: started.append(kind) or (True, ""))
    monkeypatch.setattr(intake_tools, "embed_estimate", lambda cpu=False: "")
    reindex.write_last(cfg, time.time() - 900, 80.0, 9050, "cuda")  # 9 050 vectors were missing, none is now
    out = intake_tools.reindex()
    assert out.startswith("The base is up to date: last recalculation ") and "10 fragments, 113.1/s on cuda" in out
    assert started == []
    assert intake_tools.reindex(force=True).startswith("The base recalculation started") and started == ["reindex"]
    new = tmp_path / "texts" / "N-00002.md"
    new.write_text("=== page 1 ===\n\ny\n", encoding="utf-8")  # a text newer than the base
    assert intake_tools.reindex().startswith("The base recalculation started") and started == ["reindex", "reindex"]
    assert reindex.counts(cfg["db"]) == (10, 0)
