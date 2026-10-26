# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one way the package starts a program: subprocess with no console window on Windows.

A process without a console of its own (the MCP server started by Claude Desktop, a detached background job) that
starts a console program without CREATE_NO_WINDOW gives it a fresh, visible console: a black window pops up on the
user's desktop. The venv python.exe is such a program even when it starts python itself (a redirector: it starts the
base interpreter as a child). So every start goes through here:

- run / call / popen: subprocess with CREATE_NO_WINDOW added on Windows whenever the child could otherwise get a
  window of its own: always when this process has no console, and when the child's output is captured. A child that
  writes into the user's terminal (setup, pip) shares the console of this process: no window either way.
- popen(detach=True): a job that outlives this process — a hidden console every descendant inherits, a process group of
  its own, out of the job object of the client where the job object allows it (never DETACHED_PROCESS: its children
  would open windows).
- python(): the interpreter for a child python, the base one of a venv (one process less, no redirector) with the
  variable that keeps it in the venv.

tests/test_proc_guard.py fails on a direct use of subprocess outside this module, intake/limits.py and
intake/balance.py (which set the flags themselves)."""

import os, subprocess, sys

DEVNULL, PIPE, STDOUT = subprocess.DEVNULL, subprocess.PIPE, subprocess.STDOUT
TimeoutExpired, SubprocessError = subprocess.TimeoutExpired, subprocess.SubprocessError
CalledProcessError, CompletedProcess, Popen = subprocess.CalledProcessError, subprocess.CompletedProcess, subprocess.Popen

_nt = os.name == "nt"
NO_WINDOW = 0x08000000 if _nt else 0  # CREATE_NO_WINDOW
NEW_GROUP = 0x00000200 if _nt else 0  # CREATE_NEW_PROCESS_GROUP
BREAKAWAY = 0x01000000 if _nt else 0  # CREATE_BREAKAWAY_FROM_JOB
DETACHED_PROCESS = 0x00000008 if _nt else 0
BELOW_NORMAL = 0x00004000 if _nt else 0  # BELOW_NORMAL_PRIORITY_CLASS
VENV_LAUNCHER = "__PYVENV_LAUNCHER__"  # the venv python.exe a base interpreter is started for (Windows, macOS)


def has_console():
    """True when this process has a console (a terminal, or the hidden console of its parent)."""
    if not _nt:
        return True
    import ctypes

    ids = (ctypes.c_uint32 * 4)()  # a hidden console (CREATE_NO_WINDOW) has no window but is attached: listed too
    try:
        return ctypes.windll.kernel32.GetConsoleProcessList(ids, 4) > 0
    except (AttributeError, OSError):
        return False


def _captured(kw):
    if kw.get("capture_output"):
        return True
    return kw.get("stdout") is not None and kw.get("stderr") is not None


def flags(kw, hidden=None):
    """The creationflags for kw (its own flags kept): NO_WINDOW added when the child could get a window. hidden=True
    or False forces the choice."""
    cf = kw.get("creationflags", 0) or 0
    if not _nt:
        return cf
    if hidden is None:
        hidden = _captured(kw) or not has_console()
    if hidden and not cf & DETACHED_PROCESS:
        cf |= NO_WINDOW
    return cf


def _kw(kw, hidden):
    if _nt:
        kw["creationflags"] = flags(kw, hidden)
    return kw


def run(cmd, *, hidden=None, **kw):
    """subprocess.run with no window (see the module)."""
    return subprocess.run(cmd, **_kw(kw, hidden))


def call(cmd, *, hidden=None, **kw):
    """subprocess.call with no window (see the module)."""
    return subprocess.call(cmd, **_kw(kw, hidden))


def popen(cmd, *, hidden=None, detach=False, **kw):
    """subprocess.Popen with no window. detach=True: the child outlives this process (see the module); the process
    gets .broke_away — False when the job object of the client refused the breakaway (the child ends with the job)."""
    if not detach:
        return subprocess.Popen(cmd, **_kw(kw, hidden))
    if not _nt:
        p = subprocess.Popen(cmd, start_new_session=True, **kw)
        p.broke_away = True
        return p
    base = (kw.pop("creationflags", 0) or 0) & ~DETACHED_PROCESS | NO_WINDOW | NEW_GROUP
    try:
        p = subprocess.Popen(cmd, creationflags=base | BREAKAWAY, **kw)
        p.broke_away = True
    except PermissionError:  # the job object of the client forbids a breakaway: the job ends if the client ends it
        p = subprocess.Popen(cmd, creationflags=base, **kw)
        p.broke_away = False
    return p


def python():
    """The interpreter for a child python: the base one of a venv on Windows (the venv python.exe is a redirector that
    starts it as one more process), else sys.executable. Start it with python_env(env) so it stays in the venv."""
    base = getattr(sys, "_base_executable", None)
    if _nt and base and sys.prefix != sys.base_prefix and os.path.isfile(base):
        return base
    return sys.executable


def python_env(env=None):
    """env (os.environ when None) for a child started with python(): the venv it belongs to, when it is the base one."""
    env = dict(os.environ if env is None else env)
    if python() != sys.executable:
        env[VENV_LAUNCHER] = sys.executable
    return env
