# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every program the package starts goes through core/proc (no console window on Windows, M-008 of audit 6): a direct
use of subprocess (or os.system / os.popen) anywhere else fails here, like the Cyrillic-in-code guard."""

import ast, os, subprocess, sys
from pathlib import Path

import pytest

from assistant_x.core import proc

PACKAGE = Path(__file__).resolve().parent.parent / "assistant_x"

# module (relative to assistant_x/) -> why it may use subprocess itself
ALLOWED = {
    "core/proc.py": "the wrapper itself",
    "intake/limits.py": "starts the tools in a job object with its own CREATE_NO_WINDOW and priority flags",
    "intake/balance.py": "reads the processor topology (wmic/powershell) with CREATE_NO_WINDOW of its own",
}


def _offences(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name == "subprocess" for a in node.names):
            yield node.lineno, "import subprocess"
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            yield node.lineno, "from subprocess import"
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and node.attr in ("system", "popen", "spawnl", "spawnv", "spawnve", "spawnlp", "spawnvp")
        ):
            yield node.lineno, f"os.{node.attr}"


def test_no_direct_subprocess():
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE).as_posix()
        if rel in ALLOWED:
            continue
        found += [f"{rel}:{line}: {what}" for line, what in _offences(path)]
    assert not found, "start programs through assistant_x.core.proc:\n" + "\n".join(found)


def test_allowed_modules_exist():
    assert all((PACKAGE / rel).is_file() for rel in ALLOWED)


def test_flags_add_no_window_when_captured():
    if os.name != "nt":
        assert proc.flags({"capture_output": True}) == 0
        return
    assert proc.flags({"capture_output": True}) & proc.NO_WINDOW
    assert proc.flags({"stdout": proc.DEVNULL, "stderr": proc.DEVNULL}) & proc.NO_WINDOW
    assert proc.flags({}, hidden=True) & proc.NO_WINDOW
    assert not proc.flags({}, hidden=False) & proc.NO_WINDOW
    assert proc.flags({"creationflags": proc.BELOW_NORMAL}, hidden=True) == proc.BELOW_NORMAL | proc.NO_WINDOW
    # DETACHED_PROCESS and CREATE_NO_WINDOW exclude each other: the caller's choice is kept
    assert proc.flags({"creationflags": proc.DETACHED_PROCESS}, hidden=True) == proc.DETACHED_PROCESS


def test_run_and_call():
    r = proc.run([sys.executable, "-c", "print(42)"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout.strip() == "42"
    assert proc.call([sys.executable, "-c", "import sys; sys.exit(3)"], stdout=proc.DEVNULL, stderr=proc.DEVNULL) == 3


def test_python_stays_in_the_venv(tmp_path):
    """The base interpreter of a venv started with python_env() sees the venv, as the venv python.exe does."""
    code = "import sys; print(sys.prefix)"
    r = proc.run(
        [proc.python(), "-c", code], capture_output=True, text=True, env=proc.python_env(), cwd=tmp_path, timeout=60
    )
    assert r.returncode == 0
    assert os.path.normcase(r.stdout.strip()) == os.path.normcase(sys.prefix)


@pytest.mark.skipif(os.name != "nt", reason="consoles are of Windows")
def test_detached_child_gets_no_window(tmp_path):
    """A detached start (the background intake of the MCP server) runs in a hidden console: the child and its own
    child (the venv redirector case) have a console without a window."""
    out = tmp_path / "out.txt"
    probe = (
        "import ctypes, sys, subprocess\n"
        "k = ctypes.windll.kernel32\n"
        "ids = (ctypes.c_uint32 * 8)()\n"
        "me = (k.GetConsoleProcessList(ids, 8) > 0, bool(k.GetConsoleWindow()))\n"
        "kid = subprocess.run([sys.executable, '-c', 'import ctypes; k = ctypes.windll.kernel32; "
        "ids = (ctypes.c_uint32 * 8)(); print(k.GetConsoleProcessList(ids, 8) > 0, bool(k.GetConsoleWindow()))'],"
        " capture_output=True, text=True, creationflags=0).stdout.split()\n"
        f"open({str(out)!r}, 'w').write(repr((me, kid)))\n"
    )
    p = proc.popen([sys.executable, "-c", probe], detach=True, stdin=proc.DEVNULL, stdout=proc.DEVNULL, stderr=proc.DEVNULL)
    assert p.wait(timeout=60) == 0
    me, kid = eval(out.read_text())  # noqa: S307 — our own probe
    assert me == (True, False)  # attached to a console, and the console has no window
    assert kid == ["True", "False"]  # the grandchild inherits the hidden console, no window either


def test_subprocess_names_reexported():
    assert proc.TimeoutExpired is subprocess.TimeoutExpired and proc.DEVNULL == subprocess.DEVNULL
