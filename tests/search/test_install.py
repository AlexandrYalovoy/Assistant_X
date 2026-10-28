# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scenarios of install.py and debug_report.py on a copy of the mini library in a folder with a space and Cyrillic
letters, as a user has it: trial run, a window without keyboard, Ctrl+C, telling Claude Desktop from
Claude Code. Nothing is installed: the trial run only prints, the refusal stops before the environment."""

import os, shutil, subprocess, sys

import pytest

from assistant_x.core import config
from assistant_x.setup import install


@pytest.fixture
def kit(mini, tmp_path):
    """Copy of the mini library as a workspace in a folder with a space and Cyrillic."""
    root = tmp_path / "Мои документы" / "Assistant X"  # a space and Cyrillic, as in a Russian user profile
    shutil.copytree(mini["root"], root, ignore=shutil.ignore_patterns(".assistant_x"))
    return root


def run(kit, *args, pipe=False):
    """pipe: input from a pipe (no console at all) instead of NUL."""
    return subprocess.run(
        [sys.executable, "-m", "assistant_x.setup.install", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env=dict(os.environ, PYTHONUTF8="1", AX_WORKSPACE=str(kit)),
        **({"input": ""} if pipe else {"stdin": subprocess.DEVNULL}),
    )


def test_dry_run_in_a_folder_with_space_and_cyrillic(kit):
    p = run(kit, "--dry-run", "--no-register")
    out = p.stdout
    assert p.returncode == 0, out + p.stderr
    assert "Installation of Assistant X" in out and f"Folder: {kit}" in out and "trial run" in out
    assert "search base: present" in out and "texts of the documents: present" in out
    assert "embedding model: MISSING" in out  # the mini library has no model
    assert "AGPL-3.0 license (file LICENSE)" in out
    assert not (kit / ".venv").exists()


@pytest.mark.parametrize("exc", [EOFError, KeyboardInterrupt])
def test_interrupted_answer_stops_cleanly(monkeypatch, exc):
    def broken(prompt):
        raise exc

    monkeypatch.setattr("builtins.input", broken)
    with pytest.raises(install.Stop):
        install.ask("Question? ")


def test_desktop_told_from_claude_code():
    store = r"C:\Program Files\WindowsApps\Claude_3.6556.2.0_x64__pzs8sxrjxfjjc\app\Claude.exe"
    classic = r"C:\Users\u\AppData\Local\AnthropicClaude\app-1.0.0\claude.exe"
    code_in_desktop = r"C:\Users\u\AppData\Roaming\Claude\claude-code\2.1.308\c17a819afb40\claude.exe"
    code_cli = r"C:\Users\u\.local\bin\claude.exe"
    assert install.is_desktop([code_cli, store]) and install.is_desktop([classic])
    assert not install.is_desktop([code_cli, code_in_desktop, ""])


def report(kit):
    p = subprocess.run(
        [sys.executable, "-m", "assistant_x.setup.debug_report", "--quick", "--no-open"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env=dict(os.environ, PYTHONUTF8="1", AX_NO_OPEN="1", AX_WORKSPACE=str(kit)),
    )
    assert p.returncode == 0, p.stdout + p.stderr
    path = next(l.split(":", 1)[1].strip() for l in p.stdout.splitlines() if l.startswith("Done:"))
    assert os.path.dirname(path).startswith(str(kit / ".assistant_x" / "debug"))
    return open(path, encoding="utf-8").read()


def test_debug_report_quick_on_the_copy(kit):
    """The report a user sends: written even without the model and the originals, with the findings on top."""
    text = report(kit)
    for part in ("## What stands out", "## Computer", "## Self-test", "## Failure journal"):
        assert part in text
    import platform
    from assistant_x.core import debuglog

    assert platform.node() not in text and debuglog.pc_id() in text  # passed on: the PC by a hash of its name only


@pytest.mark.parametrize("rerank", ["auto", True])
def test_missing_reranker_is_a_finding_only_when_switched_on(kit, rerank):
    """The release has no reranker model: with "auto" that is normal, only rerank: true needs it."""
    config.save({"rerank": rerank, "rerank_model": "models/bge-reranker-v2-m3"}, "search", kit / "assistant_x.toml")
    findings = report(kit).split("## What stands out", 1)[1].split("\n## ", 1)[0]
    assert ("No path rerank_model" in findings) == (rerank is True)


# ---------- the video card and the intake ----------


@pytest.mark.parametrize(
    "nv, cpu, wheel, want",
    [
        (None, False, True, "cpu"),
        ({"name": "RTX 4060", "driver": "566.36", "vram_gb": 8}, False, True, "cpu"),  # driver older than 570
        ({"name": "RTX 4060", "driver": "576.02", "vram_gb": 8}, False, False, "cpu"),  # no wheel on the media
        ({"name": "RTX 4060", "driver": "576.02", "vram_gb": 8}, True, True, "cpu"),  # --cpu
        ({"name": "RTX 4060", "driver": "576.02", "vram_gb": 8}, False, True, "cuda"),
    ],
)
def test_choose_device(monkeypatch, tmp_path, capsys, nv, cpu, wheel, want):
    from assistant_x.search import onnx_models

    monkeypatch.setattr(onnx_models, "adapters", lambda: [])  # no card for DirectML here
    monkeypatch.setattr(install, "nvidia", lambda: nv)
    monkeypatch.setattr(install, "video_cards", lambda: ["Intel(R) Graphics"] + ([nv["name"]] if nv else []))
    monkeypatch.setattr(install.P, "WHEELS_GPU", str(tmp_path))
    if wheel:
        (tmp_path / "torch-2.11.0+cu128-cp311-cp311-win_amd64.whl").write_bytes(b"")
    assert install.choose_device(cpu, offline=True) == want
    out = capsys.readouterr().out
    assert "Intel(R) Graphics" in out and ("chosen: video card" in out) == (want == "cuda")


def test_gpu_torch_goes_first_offline(monkeypatch):
    calls = []
    monkeypatch.setattr(install, "run", lambda cmd, dry, **kw: calls.append(cmd) or 0)
    assert install.install_packages("py", offline=True, dry=True, device="cuda") == "cuda"
    assert install.GPU_TORCH in calls[0] and install.WHEELS_GPU in calls[0] and "-r" in calls[1]
    calls.clear()
    install.install_packages("py", offline=True, dry=True, device="cpu")
    assert len(calls) == 3 and install.GPU_TORCH not in calls[0] and calls[1][-2:] == ["setuptools", "wheel"]
    assert calls[2][-2:] == ["-e", install.CODE] and "--no-build-isolation" in calls[2]  # offline: the media's build tools


def test_check_intake_on_a_project_copy(kit, monkeypatch):
    """A workspace copy: the programs are found and tried, inbox is created."""
    monkeypatch.setenv("AX_WORKSPACE", str(kit))
    monkeypatch.setattr(install.P, "INBOX", str(kit / "inbox"))
    monkeypatch.setattr(install.P, "ROOT", str(kit))
    problems = install.check_intake(sys.executable, dry=False)
    assert (kit / "inbox").is_dir()
    if os.path.isdir(os.environ["AX_PROGRAMS"]):  # an offline media: the portable programs work from the folder
        assert problems == [], problems


@pytest.mark.parametrize(
    "found, onnx, want",
    [
        ([(0, "AMD Radeon RX 7600", 0x1002, 8.0), (1, "AMD Radeon(TM) Graphics", 0x1002, 0.5)], True, "dml"),
        ([(0, "Intel(R) Graphics", 0x8086, 0.1)], True, "cpu"),  # integrated: no faster than the CPU
        ([(0, "AMD Radeon RX 7600", 0x1002, 8.0)], False, "cpu"),  # no ONNX models or DirectML on the media
        ([], True, "cpu"),
    ],
)
def test_directml_for_cards_with_own_memory(monkeypatch, tmp_path, capsys, found, onnx, want):
    from assistant_x.search import onnx_models

    monkeypatch.setattr(onnx_models, "adapters", lambda: found)
    monkeypatch.setattr(install, "nvidia", lambda: None)
    monkeypatch.setattr(install, "video_cards", lambda: [n for _, n, _, _ in found])
    monkeypatch.setattr(install.P, "WHEELS_DML", str(tmp_path))
    monkeypatch.setattr(install.P, "MODELS", str(tmp_path / "models"))
    if onnx:
        (tmp_path / "onnxruntime_directml-1.24.4-cp311-cp311-win_amd64.whl").write_bytes(b"")
        (tmp_path / "models" / "onnx" / "bge-m3").mkdir(parents=True)
        (tmp_path / "models" / "onnx" / "bge-m3" / "model.onnx").write_bytes(b"")
    assert install.choose_device(False, offline=True) == want
    assert ("DirectML" in capsys.readouterr().out) == (want == "dml" or (bool(found) and found[0][3] >= 2))


def test_install_makes_the_chosen_workspace(tmp_path, monkeypatch):
    """--workspace and --profile: the installation makes that workspace with that profile and its skill."""
    monkeypatch.setattr(install, "PROFILE", "oil-gas-ru")
    before = os.environ["AX_WORKSPACE"]
    monkeypatch.setenv("AX_WORKSPACE", before)  # given back after the test
    install.use_workspace(tmp_path / "My library")
    try:
        assert install.check_workspace(dry=False) == []
        cfg = (tmp_path / "My library" / "assistant_x.toml").read_text(encoding="utf-8")
        assert 'profile = "oil-gas-ru"' in cfg and install.ROOT == str(tmp_path / "My library")
        from assistant_x.setup import skill

        assert skill.main([]) == 0 and "process engineer" in (tmp_path / "My library" / "skill" / "SKILL.md").read_text(
            encoding="utf-8"
        )
    finally:
        install.use_workspace(before)


def test_install_json_for_an_agent(tmp_path, capsys, monkeypatch):
    """--json: the messages on stderr, one JSON summary on stdout, the downloads named before anything is installed."""
    import json

    from assistant_x.setup import install

    monkeypatch.setattr(
        sys,
        "argv",
        ["install", "--dry-run", "--json", "--yes", "--no-register", "--cpu", "--workspace", str(tmp_path / "ws")],
    )
    monkeypatch.setattr(install, "self_check", lambda py, dry: [])
    from assistant_x.clients import connect

    monkeypatch.setattr(connect, "listing", lambda: [])  # not the apps of this PC
    before = os.environ.get("AX_WORKSPACE")
    try:
        assert install.main() == 0
    finally:
        install.JSON = False
        install.use_workspace(before)
    out = capsys.readouterr().out.strip().splitlines()
    s = json.loads(out[-1])
    assert len(out) == 1 and s["ok"] and s["dry_run"] and s["device"] == "cpu" and s["workspace"].endswith("ws")
    assert s["command"].endswith(("assistant-x.exe", "assistant-x")) and "connect --check" in " ".join(s["next"])
    assert "packages" in s["downloads"] and s["lmstudio_link"].startswith("lmstudio://")
