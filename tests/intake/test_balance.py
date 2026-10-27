# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Share of the PC a heavy task takes (balance.py) and one heavy task at a time (core/lock.py)."""

import os, subprocess, sys, textwrap

import pytest

from assistant_x.intake import balance
from assistant_x.core import lock as machine_lock


PC24 = {
    "logical": 24,
    "physical": 24,
    "ecores": list(range(2, 10)) + list(range(14, 22)),
    "ram_gb": 32,
    "avail_gb": 20,
    "gpu": None,
}
PC4 = {"logical": 4, "physical": 2, "ecores": None, "ram_gb": 8, "avail_gb": 5, "gpu": None}


def test_budget_from_the_pc():
    o = balance.options({})
    b = balance.budget(PC24, o, cap=8, worker_mb=3072)  # a worker is one core; the cap of the settings: 8
    assert b == {"workers": 8, "threads": 1, "free": 8, "active": 8}
    assert balance.budget(PC24, o, cap=0)["workers"] == 15  # memory: (20 - 4.8) GB / 1 GB = 15 (22 CPUs past the reserve)
    small = balance.budget(PC4, o, cap=8)  # 5 GB free past the reserve of 4: one worker
    assert small == {"workers": 1, "threads": 1, "free": 1, "active": 1}
    weak = balance.budget(PC24, balance.options({"profile": "weak"}), cap=8)
    assert weak == {"workers": 2, "threads": 1, "free": 2, "active": 2}
    with pytest.raises(ValueError):
        balance.options({"profile": "turbo"})
    few = balance.budget(PC24, o, cap=8, worker_mb=3072, tasks=3)  # 3 documents: a worker each, the cores shared
    assert few["workers"] == 3 and few["threads"] == balance.THREADS_MAX
    assert balance.budget(PC24, o, cap=8, worker_mb=3072, tasks=20)["threads"] == 1  # more tasks than workers
    assert balance.budget(PC24, balance.options({"threads": 2}), cap=8, tasks=3)["threads"] == 2  # set by hand


def sample(cpu=30, ours=20, disk=10, avail=12, idle=0, temp=None, throttled=False):
    return {"cpu": cpu, "ours": ours, "disk": disk, "avail_gb": avail, "idle_s": idle, "temp": temp, "throttled": throttled}


def test_regulator_user_away_and_back():
    b = {"workers": 8, "threads": 2, "free": 8, "active": 4}
    r = balance.Regulator(b, balance.options({}), PC24)
    assert r.n == 4
    n, state, why = r.step(sample(idle=10), 0)
    assert (n, state) == (4, balance.ACTIVE)
    t, seen = 0, []
    for _ in range(60):  # the user is away: one more worker every 45 s while the CPU is below the corridor
        t += 5
        n, state, _ = r.step(sample(cpu=40, idle=600 + t), t)
        seen.append(n)
    assert state == balance.FREE and seen[-1] == 8 and all(b - a in (0, 1) for a, b in zip(seen, seen[1:]))
    n, state, why = r.step(sample(cpu=40, idle=1), t + 5)  # back at the keyboard: at once to the "at the computer" budget
    assert (n, state) == (4, balance.ACTIVE) and any("budget" in w for w in why)


def test_regulator_corridor_and_other_load():
    b = {"workers": 8, "threads": 2, "free": 8, "active": 8}
    r = balance.Regulator(b, balance.options({"profile": "night"}), PC24)
    assert r.n == 8
    n, _, why = r.step(sample(cpu=88, ours=80), 100)  # above 75 + 8 %: one worker less
    assert n == 7 and any("CPU 88 %" in w for w in why)
    n, _, _ = r.step(sample(cpu=88, ours=80), 104)  # not again within 8 s
    assert n == 7
    r2 = balance.Regulator(b, balance.options({}), PC24)
    _, state, _ = r2.step(sample(cpu=70, ours=10, idle=3600), 0)  # nobody types, but 60 % of the CPU is someone else's
    assert state == balance.ACTIVE


def test_regulator_memory_emergency_and_return():
    b = {"workers": 8, "threads": 2, "free": 8, "active": 8}
    r = balance.Regulator(b, balance.options({"profile": "night"}), PC24)
    n, _, why = r.step(sample(avail=0.8), 0)
    assert n == 0 and any("all paused" in w for w in why)
    n, _, _ = r.step(sample(avail=8), 5)
    assert n == 1  # memory came back: one worker, then up slowly
    ns = [r.step(sample(cpu=20, avail=8), 5 + 5 * k)[0] for k in range(1, 30)]
    assert ns[-1] > 1 and all(b - a in (0, 1) for a, b in zip(ns, ns[1:]))


def test_regulator_heat_and_sustained_cpu():
    b = {"workers": 8, "threads": 2, "free": 8, "active": 8}
    r = balance.Regulator(b, balance.options({"profile": "night"}), PC24)
    n, _, why = r.step(sample(cpu=70, temp=91), 0)
    assert n == 7 and any("heat" in w for w in why)
    for t in range(4, 60, 4):  # hot: down one by one, never up
        n, _, _ = r.step(sample(cpu=50, temp=88), t)
    assert n <= 2
    m, _, why = r.step(sample(cpu=40, temp=80), 64)  # below 85 but above 75: still no additions
    assert m <= n
    m2, _, why = r.step(sample(cpu=40, temp=70), 70)
    assert "cooled down" in why
    r = balance.Regulator(b, balance.options({"profile": "night"}), PC24)
    for t in (0, 4):
        n, _, _ = r.step(sample(cpu=97, ours=90), t)
    assert n == 7  # corridor step only: the emergency waits 15 s
    n, _, why = r.step(sample(cpu=97, ours=90), 16)
    assert n == 3 and any("half" in w for w in why)
    n, _, _ = r.step(sample(cpu=60, throttled=True), 30)  # the clock fell under load: counts as heat
    assert r.hot and n == 2


def test_cpus_and_mask():
    n = os.cpu_count()
    assert balance.cpus("all") is None and balance.mask("all") == 0 and balance.cpus("auto") is None
    assert balance.cpus([1, 0, 1]) == [0, 1] and balance.mask("0,1") == 3
    e = balance.cpus("ecores")
    assert e is None or max(e) < n
    with pytest.raises(ValueError):
        balance.cpus([n + 5])
    with pytest.raises(ValueError):
        balance.priority_class("turbo")


def test_env_round_trip():
    env = balance.env("idle", "0,1")
    assert env["OMP_NUM_THREADS"] == env["MKL_NUM_THREADS"] == env["OPENBLAS_NUM_THREADS"] == "1"
    assert balance.from_env(env) == (balance.PRIORITIES["idle"], 3)
    assert balance.from_env({}) == (0, 0)


@pytest.mark.skipif(os.name != "nt", reason="Windows priority classes and job objects")
def test_tool_gets_priority_and_cpus(tmp_path):
    from assistant_x.intake import limits as intake_limits

    out = tmp_path / "out.txt"
    code = f"import psutil; p = psutil.Process(); open(r'{out}', 'w').write(f'{{p.nice()}} {{p.cpu_affinity()}}')"
    env = dict(os.environ, **balance.env("below_normal", "0,1"))
    rc, why = intake_limits.run([sys.executable, "-c", code], timeout=60, env=env)
    assert (rc, why) == (0, None)
    nice, cpus = out.read_text().split(" ", 1)
    assert int(nice) == balance.PRIORITIES["below_normal"] and cpus == "[0, 1]"


@pytest.mark.skipif(os.name != "nt", reason="Windows job objects")
def test_job_counts_cpu_of_its_tree():
    """The regulator tells our load from the rest by the CPU time of the workers' jobs."""
    from assistant_x.intake import limits as intake_limits

    j = intake_limits.Job(0, per_process=True)
    # until it has used 1 s of CPU, however busy the PC is (a loop by the wall clock got less under load)
    p = subprocess.Popen([sys.executable, "-c", "import time\nwhile time.process_time() < 1: pass"])
    assert j.assign(int(p._handle))
    p.wait()
    assert j.cpu_seconds() > 0.5
    j.close()


HOLD = textwrap.dedent("""
    import sys, time
    from assistant_x.core import lock as machine_lock
    with machine_lock.heavy_task("test holds"):
        print("held", flush=True)
        sys.stdin.readline()
""")


def test_lock_busy_then_free(heavy_lock):
    assert machine_lock.holder() is None
    p = subprocess.Popen(
        [sys.executable, "-c", HOLD], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=dict(os.environ)
    )
    try:
        assert p.stdout.readline().strip() == "held"
        h = machine_lock.holder()
        assert h["task"] == "test holds" and h["pid"]  # a venv python is a launcher: the holder is its child
        said = []
        with pytest.raises(machine_lock.Busy) as e:
            with machine_lock.heavy_task("second", say=said.append):
                pass
        assert e.value.code == machine_lock.BUSY and "test holds" in said[0]
        assert machine_lock.main(["second", "--", sys.executable, "-c", "pass"]) == machine_lock.BUSY
    finally:
        p.communicate("\n", timeout=30)
    assert machine_lock.holder() is None
    with machine_lock.heavy_task("after"):
        assert machine_lock.holder()["task"] == "after"
    log = (heavy_lock.parent / "heavy.log").read_text(encoding="utf-8")
    assert "took\ttest holds" in log and "busy\tsecond" in log and "released\tafter" in log


def test_child_of_holder_passes(heavy_lock):
    child = "from assistant_x.core import lock as machine_lock\nwith machine_lock.heavy_task('nested'): print('inside')"
    with machine_lock.heavy_task("parent"):
        r = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True, env=dict(os.environ))
    assert r.returncode == 0 and "inside" in r.stdout
    assert machine_lock.main(["outside", "--", sys.executable, "-c", "pass"]) == 0


def test_a_missing_program_under_the_lock_is_one_line(heavy_lock, capsys):
    """lock -- CMD with a program that is not there: one line and the code of a shell, no traceback; the lock freed."""
    assert machine_lock.main(["--", "no-such-program-of-assistant-x"]) == 127
    err = capsys.readouterr().err
    assert err.startswith("cannot start no-such-program-of-assistant-x") and "Traceback" not in err
    assert machine_lock.holder() is None and machine_lock.main(["--"]) == 2
