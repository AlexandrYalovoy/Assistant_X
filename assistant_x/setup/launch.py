# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The start of a background installation (install --background, setup/status.spawn): python -m
assistant_x.setup.launch LAUNCH.json [arguments of the installation].

LAUNCH.json gives the environment the installation needs ({"env": {...}, "log": path}): a process the WMI service
starts (core/proc.start_outside: an agent whose job forbids a breakaway) has the environment of the user, not that of
the agent. The output of this process and of every child goes into the log (its standard handles moved there), then
the installation runs as python -m assistant_x.setup.install would. Standard library only."""

import json, os, runpy, sys


def redirect(log):
    """stdout and stderr of this process (and of the children that inherit them) into the file log, appended."""
    os.makedirs(os.path.dirname(log), exist_ok=True)
    f = open(log, "ab", buffering=0)
    os.dup2(f.fileno(), 1)
    os.dup2(f.fileno(), 2)
    if os.name == "nt":
        import ctypes, msvcrt

        k = ctypes.windll.kernel32
        k.SetStdHandle(-11, msvcrt.get_osfhandle(1))  # STD_OUTPUT_HANDLE
        k.SetStdHandle(-12, msvcrt.get_osfhandle(2))  # STD_ERROR_HANDLE
    sys.stdout = open(1, "w", encoding="utf-8", errors="replace", closefd=False, buffering=1)
    sys.stderr = open(2, "w", encoding="utf-8", errors="replace", closefd=False, buffering=1)


def main(argv):
    with open(argv[0], encoding="utf-8") as f:
        spec = json.load(f)
    os.environ.update({k: str(v) for k, v in (spec.get("env") or {}).items()})
    if spec.get("log"):
        redirect(spec["log"])
    if spec.get("cwd"):
        os.chdir(spec["cwd"])
    sys.argv = ["assistant_x.setup.install", *argv[1:]]
    runpy.run_module("assistant_x.setup.install", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main(sys.argv[1:])
