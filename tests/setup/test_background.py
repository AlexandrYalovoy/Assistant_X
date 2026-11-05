# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The installation in the background for an agent (install --background, setup/status.py): the one short line of
the status, the stages and the share done, the end of the worker written whatever it is, a worker that died started
again a few times and then reported, the meaning of the exit codes, the base install that needs the user's choice;
and a real trial run in the background from the start to its end."""

import json, os, subprocess, sys, time

import pytest

from assistant_x.setup import install, status as S


@pytest.fixture
def pc(tmp_path, monkeypatch):
    monkeypatch.setenv("AX_MACHINE_DIR", str(tmp_path / "pc"))
    return tmp_path / "pc"


def test_the_stages_and_the_end_of_a_worker(pc, monkeypatch):
    monkeypatch.setattr(S.Worker, "_beat", lambda self: None)
    w = S.Worker(["--yes", "--worker"])
    assert os.environ["AX_PROGRESS"] == S.path(S.PROGRESS)
    w.stage("packages")
    out = S.short(S.read())
    assert out["state"] == "running" and out["stage"] == "packages" and out["percent"] == 4 and out["poll_s"] == 300
    assert len(json.dumps(out)) < 400  # one short line
    w.finish(True, {"problems": ["x" * 500], "next": ["connect --check"], "command": "ax.exe"})
    out = S.short(S.read())
    assert out["state"] == "done" and out["ok"] and out["poll_s"] == 0 and out["percent"] == 100
    assert len(out["problems"][0]) == 200 and out["command"] == "ax.exe"
    w._atexit()  # ended already: the end stays as written
    assert S.read()["state"] == "done"


def test_a_worker_that_ends_without_its_summary_says_so(pc, monkeypatch):
    monkeypatch.setattr(S.Worker, "_beat", lambda self: None)
    w = S.Worker(["--worker"])
    w._atexit()
    d = S.read()
    assert d["state"] == "failed" and d["error"]["code"] == "exception" and d["error"]["fix"]


def test_a_new_installation_starts_its_stages_anew(pc, monkeypatch):
    monkeypatch.setattr(S.Worker, "_beat", lambda self: None)
    S.write({"state": "done", "stage": "doctor", "argv": ["--worker"], "restarts": 2})
    S.Worker(["--worker"])
    d = S.read()
    assert d["stage"] == "start" and d["restarts"] == 0 and d["state"] == "running"


def test_the_share_of_the_base_install(pc):
    S.write({"state": "running", "stage": "base", "stage_started": time.time() - 600})
    with open(S.path(S.PROGRESS), "w", encoding="utf-8") as f:
        json.dump({"stage": "base install: extract", "done": 50, "total": 100}, f)
    pc_, share = S.percent(S.read(), json.load(open(S.path(S.PROGRESS), encoding="utf-8")))
    assert share == pytest.approx(0.02 + 0.45 / 2) and pc_ == 40 + int(57 * share)
    assert S.eta_min(S.read(), share) == round(600 / share * (1 - share) / 60)
    assert S.base_share({"stage": "embed", "done": 1, "total": 1}) == pytest.approx(0.97)
    assert S.base_share({"stage": "base install: vectors"}) == 0.75


def test_a_dead_worker_is_started_again_then_reported(pc, monkeypatch):
    started = []
    monkeypatch.setattr(S, "spawn", lambda python, argv, cwd: started.append(argv) or (4242, "wmi"))
    monkeypatch.setattr(S, "alive", lambda pid, started=None: False)
    S.write({"state": "running", "stage": "base", "pid": 1, "argv": ["--base", "x", "--worker"], "heartbeat": 1})
    for n in range(1, S.MAX_RESTARTS + 1):
        out = S.short(S.read())
        assert out["state"] == "running" and out["restarts"] == n and "started again" in out["last_event"]
    assert started == [["--base", "x", "--worker"]] * S.MAX_RESTARTS
    out = S.short(S.read())
    assert out["state"] == "failed" and out["error"]["code"] == "died" and out["poll_s"] == 0
    assert S.short(S.read(), resume=False)["state"] == "failed"


def test_why_a_worker_is_gone(monkeypatch):
    monkeypatch.setattr(S, "boot_time", lambda: 2000.0)
    assert "restarted" in S.why_dead({"heartbeat": 1000.0})
    assert "from outside" in S.why_dead({"heartbeat": 3000.0})
    assert "closed" in S.why_exit(-1073741510) and "closed" in S.why_exit(0xC000013A)
    assert "memory" in S.why_exit(0xC0000017) and S.why_exit(7) == "ended with code 7"


def test_alive_knows_this_process_and_not_a_new_one_of_its_pid():
    assert S.alive(os.getpid())
    assert not S.alive(os.getpid(), started=time.time() + 3600)
    assert not S.alive(0)


def test_nothing_started_yet(pc):
    out = S.short(S.read())
    assert out["state"] == "none" and out["poll_s"] == 0


def test_a_package_whose_codes_collide_stops_for_the_choice_of_the_user(tmp_path, monkeypatch):
    def run(cmd, dry, **kw):
        if "inspect" in cmd:
            out = cmd[cmd.index("--json") + 1]
            with open(out, "w", encoding="utf-8") as f:
                json.dump({"ok": True, "codes": {"mapping": {"N-00001": "N-00009"}, "renumbered": ""}}, f)
        return 0

    before = os.environ["AX_WORKSPACE"]
    install.use_workspace(tmp_path / "ws")
    try:
        monkeypatch.setattr(install, "run", run)
        with pytest.raises(install.Stop) as e:
            install.install_base("py", str(tmp_path / "x.axbase"), None, dry=False)
        assert e.value.code == "base_choice"
        assert install.install_base("py", str(tmp_path / "x.axbase"), "package", dry=False) == []
        monkeypatch.setattr(install, "run", lambda cmd, dry, **kw: 0 if "inspect" in cmd else 3221225786)
        with pytest.raises(install.Stop) as e:
            install.install_base("py", str(tmp_path / "x.axbase"), "package", dry=False)
        assert e.value.code == "base_failed" and "closed" in str(e.value)
    finally:
        monkeypatch.undo()
        install.use_workspace(before)


def test_a_trial_run_in_the_background_from_start_to_end(tmp_path):
    """install --background --dry-run: one JSON line at once, a worker that outlives the starter, its stages up to
    the end in status.json, its output in the log."""
    from assistant_x.setup import install as I

    env = dict(os.environ, AX_MACHINE_DIR=str(tmp_path / "pc"), AX_WORKSPACE=str(tmp_path / "ws"), PYTHONUTF8="1")
    cmd = [sys.executable, "-m", "assistant_x.setup.install", "--background", "--dry-run", "--yes", "--no-register"]
    t0 = time.time()
    p = subprocess.run(cmd + ["--venv", str(tmp_path / "venv")], cwd=I.CODE, env=env, capture_output=True, text=True)
    assert p.returncode == 0 and time.time() - t0 < 30
    first = json.loads(p.stdout.strip().splitlines()[-1])
    assert first["started"] and first["pid"] and "status.py" in first["status"] and first["poll_s"] >= 300
    poll = [sys.executable, os.path.join(I.CODE, "assistant_x", "setup", "status.py"), "--json"]
    deadline = time.time() + 180
    while True:
        out = json.loads(subprocess.run(poll, env=env, capture_output=True, text=True).stdout)
        if out["state"] != "running" or time.time() > deadline:
            break
        time.sleep(2)
    assert out["state"] == "done" and out["ok"] and out["stage"] == "doctor", out
    log = open(out["log"], encoding="utf-8").read()
    assert "Installation of Assistant X (trial run" in log and "11. Check" in log
