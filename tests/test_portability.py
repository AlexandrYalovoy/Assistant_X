# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Portability and the last boundaries: the limits of a process on POSIX (resource, nice, affinity; a note where the
system lacks one), the intake modules importable as on Linux, the setup naming the packages of apt, dnf or brew, no
workspace read at the import of any module, the codes of two batches built one after the other, the library
vocabulary rebuilt by every apply."""

import os, subprocess, sys, types

from assistant_x.intake import limits
from assistant_x.setup import setup_intake

CODE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_posix_limits_of_a_process(monkeypatch):
    calls = []
    fake = types.SimpleNamespace(RLIMIT_AS=9, prlimit=lambda pid, what, lim: calls.append(("mem", pid, what, lim)))
    monkeypatch.setitem(sys.modules, "resource", fake)
    monkeypatch.setattr(os, "PRIO_PROCESS", 0, raising=False)
    monkeypatch.setattr(os, "getpriority", lambda which, pid: 0, raising=False)
    monkeypatch.setattr(os, "setpriority", lambda which, pid, n: calls.append(("nice", pid, n)), raising=False)
    monkeypatch.setattr(os, "sched_setaffinity", lambda pid, cpus: calls.append(("cpus", pid, cpus)), raising=False)
    done = limits.posix_limits(42, 1024, 0x40, 0b1100)
    assert done == ["memory", "priority", "cpus"]
    assert calls == [("mem", 42, 9, (1024, 1024)), ("nice", 42, 19), ("cpus", 42, [2, 3])]


def test_posix_limits_note_what_the_system_lacks(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "resource", types.SimpleNamespace(RLIMIT_AS=9))  # no prlimit (macOS)
    monkeypatch.delattr(os, "sched_setaffinity", raising=False)
    monkeypatch.setattr(limits, "_noted", set())
    assert limits.posix_limits(42, 1024, 0, 1) == []
    err = capsys.readouterr().err
    assert "no memory cap for another process" in err and "no CPU affinity" in err


def test_intake_modules_import_as_on_linux():
    """os.name "posix" from the start: the Windows parts stay out (no ctypes.WinDLL), a Job keeps no handle."""
    code = (
        "import os, pathlib, subprocess, ctypes, psutil, shutil, json, tempfile, threading, multiprocessing, multiprocessing.connection, concurrent.futures, queue, assistant_x.core.config; os.name = 'posix'\n"
        "from assistant_x.intake import limits, balance, pool\n"
        "assert not hasattr(limits, '_k32') and balance._nt is False\n"
        "j = limits.Job(100, priority=0x4000); assert j.handle is None and j.assign(1) is False\n"
        "assert balance.creation_flags(0x4000) == 0 and balance.idle_seconds() == 0.0\n"
        "print('ok')"
    )
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=CODE, timeout=120)
    assert p.returncode == 0 and "ok" in p.stdout, p.stderr[-2000:]


def test_setup_names_the_packages_of_the_system():
    which = {"apt-get": "/usr/bin/apt-get"}.get
    hint = setup_intake.install_hint(["soffice", "tesseract", "ddjvu"], ["rus"], which=which)
    assert hint == "sudo apt-get install libreoffice tesseract-ocr djvulibre-bin tesseract-ocr-rus"
    brew = setup_intake.install_hint(["soffice", "sevenzip"], [], which={"brew": "/opt/homebrew/bin/brew"}.get)
    assert brew == "brew install p7zip\nbrew install --cask libreoffice"
    assert setup_intake.install_hint(["soffice"], [], which=lambda m: None) == ""


def test_no_workspace_read_at_import():
    mods = [
        "assistant_x.core.debuglog",
        "assistant_x.search.eval",
        "assistant_x.search.onnx_models",
        "assistant_x.server.intake_tools",
        "assistant_x.setup.install",
        "assistant_x.setup.prepare_media",
        "assistant_x.intake.tools.ocr_score",
        "assistant_x.intake.tools.dupcheck",
        "assistant_x.intake.manifest",
    ]
    code = (
        "import importlib\nfrom assistant_x.core import workspace\n"
        "def boom():\n    raise RuntimeError('workspace.current() at import')\n"
        "workspace.current = boom\n" + "".join(f"importlib.import_module({m!r})\n" for m in mods) + "print('ok')"
    )
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=CODE, timeout=120)
    assert p.returncode == 0 and "ok" in p.stdout, p.stderr[-2000:]


def test_lazy_paths_follow_the_workspace(tmp_path, monkeypatch):
    from assistant_x.core import debuglog, workspace
    from assistant_x.search import onnx_models
    from assistant_x.server import intake_tools
    from assistant_x.setup import install

    monkeypatch.setenv("AX_WORKSPACE", str(tmp_path))
    w = workspace.Workspace(tmp_path)
    for k in ("LOG_DIR", "ERRORS", "CALLS"):
        monkeypatch.setattr(debuglog, k, None)  # another test may have pointed them at its own folder
    monkeypatch.setattr(onnx_models, "ONNX_DIR", None)
    monkeypatch.setattr(intake_tools, "JOBS", None)
    monkeypatch.setattr(intake_tools, "P", intake_tools._Paths())  # a fixture that pointed P elsewhere left its value
    assert debuglog.calls_path() == os.path.join(str(w.debug), "calls.log") and onnx_models.onnx_dir().startswith(
        str(w.models)
    )
    assert intake_tools.jobs_dir().startswith(str(w.work))
    old = install.P.ROOT
    install.use_workspace(tmp_path / "other")
    try:
        assert install.ROOT == str(tmp_path / "other") and install.P.WHEELS.endswith("wheels")
    finally:
        install.use_workspace(old)


def test_code_lock_is_exclusive(tmp_path):
    from assistant_x.intake import build as intake_build

    f = intake_build.code_lock(tmp_path)
    try:
        code = (
            "import sys; sys.path.insert(0, %r)\nfrom assistant_x.intake import build\n"
            "print('free' if build.code_lock(%r, wait=1) else 'busy')" % (CODE, str(tmp_path))
        )
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=CODE, timeout=120)
        assert p.stdout.strip().endswith("busy"), p.stderr[-1000:]
    finally:
        f.close()
