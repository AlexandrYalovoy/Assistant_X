# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Intake commands of the server (intake_tools.py) on a temporary workspace of tests/intake: what is waiting, the
background jobs, meta lines, the plan before the move, and the question before a CPU run."""

import json, os, sys, time

import pytest

from assistant_x.server import intake_tools


@pytest.fixture
def proj(tmp_path, monkeypatch):
    """The test project of intake (text.pdf, a scan, an archive, a letter) and the commands pointed at it."""
    from tests.intake.intake_fixtures import make_project

    path = make_project(tmp_path / "Проект")  # a Cyrillic folder, as in a Russian user profile
    root = tmp_path / "Проект"
    monkeypatch.setenv("AX_CONFIG", str(path))
    monkeypatch.setattr(intake_tools.P, "ROOT", str(root))
    monkeypatch.setattr(intake_tools.P, "INBOX", str(root / "inbox"))
    monkeypatch.setattr(intake_tools.P, "WORK", str(root / "intake" / "work"))
    monkeypatch.setattr(intake_tools, "JOBS", str(root / "intake" / "work" / "_claude"))
    return root


def test_inbox_list(proj):
    out = intake_tools.inbox_list()
    assert "Files 4" in out and ".pdf 2" in out and ".zip 1" in out and "Сканы\\" in out and "_duplicates" not in out


def test_empty_inbox_says_where_to_put(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_tools.P, "INBOX", str(tmp_path / "inbox"))
    monkeypatch.setattr(intake_tools, "JOBS", str(tmp_path / "jobs"))
    out = intake_tools.inbox_list()
    assert "Empty: ask the user to put documents into this folder" in out and str(tmp_path / "inbox") in out


def _kill_tree(pid):
    import psutil

    try:
        p = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    for c in p.children(recursive=True) + [p]:
        try:
            c.kill()
        except psutil.NoSuchProcess:
            pass


def _wait_for(cond, seconds=20):
    t0 = time.time()
    while not cond() and time.time() - t0 < seconds:
        time.sleep(0.1)
    return cond()


def test_background_job_is_tracked(proj, monkeypatch):
    """A job is running, then finished (code 0), failed (its code) or stopped before the end (killed: no code)."""
    monkeypatch.setattr(intake_tools, "QUICK", 1)
    ok, text = intake_tools._start(
        "run", [sys.executable, "-c", "import time; print('running', flush=True); time.sleep(30)"]
    )
    try:
        assert ok and text == "" and intake_tools.state("run") == ("running", None)
    finally:
        _kill_tree(intake_tools._job("run")["pid"])
    assert _wait_for(lambda: intake_tools.state("run")[0] != "running")
    assert intake_tools.state("run") == ("stopped", None)
    assert "stopped before the end" in intake_tools.state_text("run")
    assert any("Background job run" in x and "intake_run(resume=True)" in x for x in intake_tools.interrupted())
    ok, text = intake_tools._start("q", [sys.executable, "-c", "import sys; print('the lock is busy'); sys.exit(3)"])
    assert not ok and "code 3" in text and "the lock is busy" in text
    assert intake_tools.state("q") == ("failed", 3) and "exit code 3" in intake_tools.state_text("q")
    ok, text = intake_tools._start("f", [sys.executable, "-c", "print('done')"])
    assert not ok and intake_tools.state("f") == ("finished", 0)
    assert not any("job f" in x for x in intake_tools.interrupted())


SERVER = """import os, sys, time
from assistant_x.server import intake_tools as T
T.JOBS, T.QUICK = sys.argv[1], 0.5
T.P.ROOT = os.path.dirname(sys.argv[1])  # never the workspace of the user
while not os.path.exists(sys.argv[2]):
    time.sleep(0.05)
job = "import sys, time; time.sleep(3); open(sys.argv[1], 'w').write('done')"
print(T._start("long", [sys.executable, "-c", job, sys.argv[3]])[0], flush=True)
time.sleep(120)
"""


def _server_in_a_job(tmp_path, breakaway):
    """A stand-in for the server, put into a job object that kills its processes when it is closed (as the MCP
    client of Python does); it starts a background job of 3 s and is killed with its job object a moment later."""
    win32job = pytest.importorskip("win32job")
    import subprocess, win32api, win32con

    jobs, go, marker = tmp_path / "jobs", tmp_path / "go", tmp_path / "marker.txt"
    # the interpreter itself, not the launcher of the environment: the process put into the job object is the server
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in sys.path if p))
    py = getattr(sys, "_base_executable", sys.executable)
    server = subprocess.Popen(
        [py, "-c", SERVER, str(jobs), str(go), str(marker)], stdout=subprocess.PIPE, text=True, env=env
    )
    job = win32job.CreateJobObject(None, "")
    info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | (
        win32job.JOB_OBJECT_LIMIT_BREAKAWAY_OK if breakaway else 0
    )
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
    handle = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, server.pid)
    win32job.AssignProcessToJobObject(job, handle)
    go.write_text("go")
    try:
        assert server.stdout.readline().strip() == "True"  # started, the server goes on
    finally:
        win32job.TerminateJobObject(job, 1)  # the client closes the server and its job object
        win32api.CloseHandle(handle)
        job.Close()
        server.wait(10)
    return jobs, marker


@pytest.mark.skipif(sys.platform != "win32", reason="job objects are of Windows")
def test_a_job_outlives_the_server(tmp_path, monkeypatch):
    """The server is closed with its job object mid-way: the background job goes on and ends with its code."""
    jobs, marker = _server_in_a_job(tmp_path, breakaway=True)
    monkeypatch.setattr(intake_tools, "JOBS", str(jobs))
    assert intake_tools._job("long")["detached"] is True
    assert _wait_for(lambda: intake_tools.state("long")[0] == "finished")
    assert marker.read_text() == "done"


@pytest.mark.skipif(sys.platform != "win32", reason="job objects are of Windows")
def test_a_job_killed_with_the_server_is_reported_stopped(tmp_path, monkeypatch):
    """A job object without breakaway takes the background job too: the status says stopped, never finished."""
    jobs, marker = _server_in_a_job(tmp_path, breakaway=False)
    monkeypatch.setattr(intake_tools, "JOBS", str(jobs))
    assert intake_tools._job("long")["detached"] is False
    assert _wait_for(lambda: intake_tools.state("long")[0] != "running")
    assert intake_tools.state("long") == ("stopped", None) and not marker.exists()


def test_a_job_left_in_the_job_of_claude_says_so(monkeypatch):
    """A job that did not leave the job object of the client (nested job objects) is running, and closing Claude
    stops it: the status says so; a detached one is just running."""
    monkeypatch.setattr(intake_tools, "_alive", lambda job: True)
    assert "closing Claude stops it" in intake_tools.state_text("run", {"detached": False, "started": 0})
    assert intake_tools.state_text("run", {"detached": True, "started": 0}) == "running"
    if sys.platform == "win32":
        assert not intake_tools.in_my_job(4)  # the System process is in no job of ours


@pytest.mark.skipif(sys.platform == "win32", reason="the session of POSIX")
def test_a_job_outlives_the_server_posix(tmp_path, monkeypatch):
    """Elsewhere the job runs in a session of its own: killing the server's process group leaves it running."""
    import signal, subprocess

    jobs, go, marker = tmp_path / "jobs", tmp_path / "go", tmp_path / "marker.txt"
    go.write_text("go")
    server = subprocess.Popen(
        [sys.executable, "-c", SERVER, str(jobs), str(go), str(marker)],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    assert server.stdout.readline().strip() == "True"
    os.killpg(server.pid, signal.SIGKILL)
    server.wait(10)
    monkeypatch.setattr(intake_tools, "JOBS", str(jobs))
    assert _wait_for(lambda: intake_tools.state("long")[0] == "finished")
    assert marker.read_text() == "done"


def test_save_meta_and_plan_before_move(proj):
    work = proj / "intake" / "work" / "2026-10-25"
    from assistant_x.intake import pipeline as intake
    from assistant_x.intake import config as intake_cfg
    from assistant_x.intake.state import State

    cfg = intake_cfg.load()
    work.mkdir(parents=True)
    state = State(work / "state.sqlite")
    intake.register(cfg, state)
    t = state.by_rel("text.pdf")["tid"]
    (work / "md").mkdir()
    (work / "md" / f"{t}.md").write_text("=== page 1 ===\n\nКнига о сепараторах.\n", encoding="utf-8")
    state.update(t, status="done", pages=1, ocr_pages=0)
    state.con.close()
    assert "not JSON" in intake_tools.save_meta(["{no"])
    from tests.intake.intake_fixtures import doc_line

    out = intake_tools.save_meta([doc_line(t, "L", "Книга", "Book", year=2020)])
    assert "Lines written: 1" in out
    assert json.loads((work / "meta.jsonl").read_text(encoding="utf-8"))["sec"] == "L"
    plan = intake_tools.apply(confirm=False)
    assert (
        "this is only the plan" in plan
        and 'token="' in plan
        and "L-00001" in plan + (work / "codes.json").read_text(encoding="utf-8")
    )
    assert (proj / "inbox" / "text.pdf").exists()  # nothing moved
    assert "Not confirmed" in intake_tools.apply(confirm=True)  # no token: nothing moves
    assert "Not confirmed" in intake_tools.apply(confirm=True, token="deadbeef")
    import re

    token = re.search(r'token="(\w+)"', plan)[1]
    with open(work / "meta.jsonl", "a", encoding="utf-8") as f:  # the batch changed after the plan the user saw
        f.write(json.dumps(doc_line(t, "N", "Книга", "Book", year=2021), ensure_ascii=False) + "\n")
    assert "the batch (meta.jsonl) changed after the plan" in intake_tools.apply(confirm=True, token=token)
    assert (proj / "inbox" / "text.pdf").exists()


def test_save_meta_and_build_check_alike(proj):
    """intake_save_meta (check-meta) and the build of intake_apply check meta.jsonl by the same rules of the profile:
    a contents title without its Russian text is an error for both, with the same words."""
    from assistant_x.intake import pipeline as intake
    from assistant_x.intake import config as intake_cfg
    from assistant_x.intake.state import State
    from tests.intake.intake_fixtures import doc_line

    work = proj / "intake" / "work" / "2026-10-25"
    work.mkdir(parents=True)
    state = State(work / "state.sqlite")
    intake.register(intake_cfg.load(), state)
    t = state.by_rel("text.pdf")["tid"]
    (work / "md").mkdir()
    (work / "md" / f"{t}.md").write_text("=== page 1 ===\n\nКнига о сепараторах.\n", encoding="utf-8")
    state.update(t, status="done", pages=1, ocr_pages=0)
    state.con.close()
    line = doc_line(t, "L", "Книга", "Book", year=2020, toc=[{"title": {"en": "Separators"}, "page": 1}])
    saved = intake_tools.save_meta([line])
    want = f"{t}: doc/toc/0/title: no text in ru"
    assert want in saved and "errors 0" not in saved
    built = intake_tools.apply(confirm=False)
    assert built.startswith("The build failed") and want in built


def test_reindex_asks_before_the_processor(monkeypatch):
    msg = (
        "Ended at once (code 3):\nembed: no video card, everything will be computed on the processor: 120 fragments, "
        "estimate about 48 s. To compute on the processor add --cpu."
    )
    monkeypatch.setattr(intake_tools, "_job", lambda kind: None)
    monkeypatch.setattr(intake_tools, "_start", lambda kind, cmd, **env: (False, msg))
    out = intake_tools.reindex(cpu=False)
    assert "The user has to decide" in out and "intake_reindex(cpu=True)" in out and "48 s" in out
    seen = []
    monkeypatch.setattr(intake_tools, "_start", lambda kind, cmd, **env: seen.append(cmd) or (True, ""))
    assert "on the processor" in intake_tools.reindex(cpu=True) and seen[0][-1] == "--cpu"


def test_the_drafts_explain_the_shelves(proj):
    """intake_card tells Claude the shelves of the profile, the genres, the card languages and the topics in use."""
    text = intake_tools.classification()
    assert "N Standards / Стандарты:" in text and "Types: standard, guideline." in text and "J Journals and papers" in text
    assert "maps in these languages: en, ru" in text and "pipelines" in text  # the topic of the card of the library
