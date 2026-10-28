# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every check in one command, as scripts/check.ps1, for a shell where PowerShell scripts may not run (an agent's,
Linux): ruff, ruff format --check, then the tests at a low priority.

    python scripts/check.py [--fast] [--log FOLDER] [pytest options...]

--fast: without the slow tests; --log FOLDER: a full record of the run there (every test with -rA -v, the 30
slowest, junit xml, the output in pytest.out.log). Any other argument goes to pytest. The exit code is 0 only when
everything passed."""

import os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pytest_args(fast=False, log="", extra=()):
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", os.path.join(ROOT, "tests")]
    if fast:
        args += ["-m", "not slow"]
    if log:
        args += ["-rA", "-v", "--durations=30", "--junitxml=" + os.path.join(log, "junit.xml")]
    return args + list(extra)


def low_priority(pid):
    try:
        import psutil

        p = psutil.Process(pid)
        p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)
    except Exception:  # noqa: BLE001 — no psutil, or not allowed: the tests run at the normal priority
        pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    fast = "--fast" in argv
    argv = [a for a in argv if a != "--fast"]
    log = ""
    if "--log" in argv:
        i = argv.index("--log")
        log = argv[i + 1]
        del argv[i : i + 2]
    env = dict(os.environ, PYTHONUTF8="1", AX_NO_OPEN="1", PYTHONDONTWRITEBYTECODE="1")
    print("ruff...", flush=True)
    for cmd in (["check", ROOT], ["format", "--check", ROOT]):
        if subprocess.run([sys.executable, "-m", "ruff", *cmd], env=env).returncode:
            print("check: ruff found errors" if cmd[0] == "check" else "check: files not formatted: python -m ruff format .")
            return 1
    print("tests...", flush=True)
    out = None
    if log:
        os.makedirs(log, exist_ok=True)
        out = open(os.path.join(log, "pytest.out.log"), "w", encoding="utf-8")
        print(f"the record of the run: {log}", flush=True)
    p = subprocess.Popen(
        pytest_args(fast, log, argv), cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT if out else None
    )
    low_priority(p.pid)
    rc = p.wait()
    if out:
        out.close()
        with open(os.path.join(log, "pytest.out.log"), encoding="utf-8", errors="replace") as f:
            print((f.read().strip().splitlines() or [""])[-1])
    print("check: everything passed" if rc == 0 else "check: the tests failed")
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
