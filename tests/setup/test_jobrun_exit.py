# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The wrapper of the background jobs of the server (server/jobrun.py) tells every end: the exit code with its
meaning, and for a job gone without one, from its last heartbeat, whether the PC restarted (a colleague's base
indexing died with no cause written)."""

import json, os, sys

import pytest

from assistant_x.server import jobrun
from assistant_x.setup import status as S


def test_an_exit_code_is_written_with_its_meaning(tmp_path):
    log, done = str(tmp_path / "job.log"), str(tmp_path / "job.exit.json")
    code = 3221225477 if os.name == "nt" else 3  # an access violation on Windows
    cmd = ["cmd", "/c", "exit", "-1073741819"] if os.name == "nt" else [sys.executable, "-c", "import sys; sys.exit(3)"]
    assert jobrun.main([log, done, "--", *cmd]) == code
    data = json.load(open(done, encoding="utf-8"))
    assert data["code"] == code and data["why"] == S.why_exit(code)
    assert "exit code" in open(log, encoding="utf-8").read()
    beat = jobrun.read_beat(done)
    assert beat["pid"] == os.getpid() and beat["beat"]


def test_a_job_gone_without_its_code_is_told_from_its_heartbeat(tmp_path, monkeypatch):
    done = str(tmp_path / "job.exit.json")
    with open(jobrun.beat_path(done), "w", encoding="utf-8") as f:
        json.dump({"pid": 1, "job": "j1", "beat": 1000.0, "events": ["10:00 no heartbeat for 40 min: the PC slept"]}, f)
    monkeypatch.setattr(S, "boot_time", lambda: 2000.0)
    why = jobrun.gone_why(done, "j1")
    assert "restarted" in why and "slept" in why
    monkeypatch.setattr(S, "boot_time", lambda: 500.0)
    assert "from outside" in jobrun.gone_why(done, "j1")
    assert jobrun.gone_why(done, "another job") == ""


@pytest.mark.parametrize("code,word", [(0xC000013A, "closed"), (0xC0000017, "memory"), (1, "error")])
def test_the_meaning_of_the_codes(code, word):
    assert word in S.why_exit(code)
