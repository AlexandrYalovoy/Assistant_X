# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The known failures, one table (core/problems.py) for every place that reports one: doctor --json, connect --check
--json, library_guide and the troubleshooting section of the docs. Every item has a stable code, a message and the
exact command (or step) that fixes it, so an agent (Codex, Claude Code, DeepSeek Harness) can repair the setup by
itself."""

import json, os, subprocess, sys

import pytest

from assistant_x.cli import main
from assistant_x.core import problems


def test_every_known_failure_has_a_code_a_message_and_a_fix():
    assert len(problems.PROBLEMS) >= 12
    for code, (message, fix) in problems.PROBLEMS.items():
        assert code == code.lower() and " " not in code and message.endswith(".") and fix
    item = problems.item("app-not-connected", app="codex")
    assert item == {
        "code": "app-not-connected",
        "message": problems.PROBLEMS["app-not-connected"][0],
        "fix": "assistant-x connect codex",
    }
    with pytest.raises(KeyError):
        problems.item("no-such-code")


def test_the_troubleshooting_table_lists_every_code():
    table = problems.markdown()
    assert all(f"`{code}`" in table for code in problems.PROBLEMS) and table.startswith("| Code |")


def doctor_json(capsys, *argv):
    rc = main.main(["doctor", "--json", *argv])
    return rc, json.loads(capsys.readouterr().out)


def test_doctor_json_names_a_missing_workspace(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AX_WORKSPACE", str(tmp_path / "none"))
    rc, out = doctor_json(capsys)
    assert rc == 1 and not out["ok"] and [p["code"] for p in out["problems"]] == ["workspace-missing"]
    assert out["problems"][0]["fix"] == f'assistant-x init "{tmp_path / "none"}"'


def test_doctor_json_of_a_library_without_model_or_vectors(mini, monkeypatch, capsys):
    monkeypatch.setenv("AX_WORKSPACE", mini["root"])
    rc, out = doctor_json(capsys)
    codes = {p["code"] for p in out["problems"] + out["remarks"]}
    assert "model-missing" in codes and codes <= set(problems.PROBLEMS) and out["workspace"] == str(mini["root"])
    assert rc == (1 if out["problems"] else 0) and out["ok"] == (not out["problems"])
    assert all(set(p) == {"code", "message", "fix"} for p in out["problems"] + out["remarks"])


def test_doctor_json_names_a_low_video_memory(mini, monkeypatch, capsys):
    from assistant_x.core import gpu_guard

    monkeypatch.setenv("AX_WORKSPACE", mini["root"])
    monkeypatch.setattr(
        gpu_guard, "_smi", lambda *q: ["16303, 15800"] if "--query-gpu=memory.total,memory.used" in q else None
    )
    _, out = doctor_json(capsys)
    low = [p for p in out["remarks"] if p["code"] == "gpu-memory-low"]
    assert low and 'device = "cpu"' in low[0]["fix"]


def test_doctor_json_is_one_json_document_on_stdout(mini):
    env = dict(os.environ, AX_WORKSPACE=str(mini["root"]), PYTHONUTF8="1")
    r = subprocess.run([sys.executable, "-m", "assistant_x", "doctor", "--json"], capture_output=True, text=True, env=env)
    assert json.loads(r.stdout)["workspace"] == str(mini["root"])


def test_library_guide_names_the_setup_problems_first(monkeypatch):
    """library_guide puts the doctor items of this PC (code, message, fix) before the guide; a failing check never
    takes the guide away."""
    from assistant_x.core import problems as PB
    from assistant_x.server import mcp_server

    monkeypatch.setattr(main, "diagnose", lambda w: ([], [PB.item("model-missing")]))
    text = mcp_server.library_guide()
    assert text.startswith("## The setup of this PC") and "model-missing" in text and "assistant-x download-models" in text
    monkeypatch.setattr(main, "diagnose", lambda w: ([], []))
    assert not mcp_server.library_guide().startswith("## The setup")

    def broken(w):
        raise OSError("disk")

    monkeypatch.setattr(main, "diagnose", broken)
    assert mcp_server.library_guide()  # the guide anyway


def test_an_app_with_its_own_server_is_named_with_the_fix(mini, monkeypatch, capsys):
    """An entry made before 0.5 starts a server inside the app (assistant_x.server.mcp_server): it holds the models
    and the video card apart from the shared service (M-082). doctor --json names it with the command that moves it
    to the bridge; connect --check names it on that app too."""
    from assistant_x.clients import connect

    monkeypatch.setenv("AX_WORKSPACE", mini["root"])
    rows = [
        {"app": "claude_desktop", "connected": True, "through_service": False},
        {"app": "lmstudio", "connected": True, "through_service": True},
        {"app": "codex", "connected": False, "through_service": False},
    ]
    monkeypatch.setattr(connect, "listing", lambda: rows)
    _, out = doctor_json(capsys)
    own = [p for p in out["remarks"] if p["code"] == "app-in-process"]
    assert len(own) == 1 and own[0]["fix"] == "assistant-x connect claude_desktop, then restart the app"
