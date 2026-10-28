# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""The folder of the PC on Windows is %USERPROFILE%\.assistant_x: Claude Desktop from the Microsoft Store runs its
children with %LOCALAPPDATA% redirected into its package (a folder its children made first is theirs alone), so the
older %LOCALAPPDATA%\AssistantX split one PC into two (the live test of 0.5: two services, one without models). An
older folder is taken over once: the small files of state copied, the big folders (venv, models, app, programs, src)
linked, the private copy of the Store app too; doctor names what is left behind."""

import json, os, sys

import pytest

from assistant_x.core import workspace

windows = pytest.mark.skipif(os.name != "nt", reason="the folder of the PC moved on Windows only")


@pytest.fixture
def pc(tmp_path, monkeypatch):
    """A user profile and a %LOCALAPPDATA% of their own, no AX_MACHINE_DIR."""
    monkeypatch.delenv("AX_MACHINE_DIR", raising=False)
    home, local = tmp_path / "Users" / "u", tmp_path / "Users" / "u" / "AppData" / "Local"
    local.mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return home, local


def older(folder, models=True):
    folder.mkdir(parents=True)
    (folder / "connections.json").write_text('{"lmstudio": {}}', encoding="utf-8")
    (folder / "speed.json").write_text("{}", encoding="utf-8")
    (folder / "mcp_http_token.txt").write_text("old", encoding="utf-8")  # made again: never copied
    if models:
        (folder / "models" / "bge-m3").mkdir(parents=True)
        (folder / "models" / "bge-m3" / "config.json").write_text("{}", encoding="utf-8")
    (folder / "venv" / "Scripts").mkdir(parents=True)
    return folder


@windows
def test_the_folder_of_the_pc_is_in_the_profile(pc, monkeypatch):
    home, _ = pc
    assert workspace.machine_dir() == home / ".assistant_x"
    monkeypatch.setenv("AX_MACHINE_DIR", str(home / "elsewhere"))
    assert workspace.machine_dir() == home / "elsewhere" and workspace.legacy_machine_dirs() == []


@windows
def test_an_older_folder_is_taken_over_once(pc):
    home, local = pc
    old = older(local / "AssistantX")
    store = older(local / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Local" / "AssistantX", models=False)
    (store / "model_fingerprints.json").write_text("{}", encoding="utf-8")
    assert workspace.legacy_machine_dirs() == [old, store]
    done = workspace.migrate_machine_dir()
    new = home / ".assistant_x"
    assert json.loads((new / "connections.json").read_text(encoding="utf-8")) == {"lmstudio": {}}
    assert (new / "model_fingerprints.json").exists() and not (new / "mcp_http_token.txt").exists()
    assert (new / "models" / "bge-m3" / "config.json").exists() and os.path.realpath(new / "models") == os.path.realpath(
        old / "models"
    )
    assert os.path.realpath(new / "venv") == os.path.realpath(old / "venv")  # the first older folder wins
    assert any("models" in d for d in done) and json.loads((new / "migrated.json").read_text(encoding="utf-8"))["from"]
    assert workspace.migrate_machine_dir() == []  # once
    assert old.exists() and (old / "models" / "bge-m3").exists()  # nothing of the older folder is moved or deleted


@windows
def test_a_store_copy_alone_is_taken_over(pc):
    home, local = pc
    store = older(local / "Packages" / "Claude_x" / "LocalCache" / "Local" / "AssistantX")
    workspace.migrate_machine_dir()
    assert os.path.realpath(home / ".assistant_x" / "models") == os.path.realpath(store / "models")


@windows
def test_doctor_names_the_older_folders(pc):
    _, local = pc
    old = older(local / "AssistantX")
    lines = workspace.split_note()
    assert lines and str(old) in lines[0]
    workspace.migrate_machine_dir()
    assert "taken over" in workspace.split_note()[0]


def test_nothing_to_take_over_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setenv("AX_MACHINE_DIR", str(tmp_path / "m"))
    assert workspace.migrate_machine_dir() == [] and workspace.split_note() == []
    if sys.platform != "win32":
        monkeypatch.delenv("AX_MACHINE_DIR")
        assert workspace.legacy_machine_dirs() == []
