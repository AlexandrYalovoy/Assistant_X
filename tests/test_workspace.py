# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The workspace, the settings and the locks of the core: where the data goes, one TOML file for the search and the
intake, the environment names, the folder lock and the exclusive lock."""

import os, subprocess, sys
from pathlib import Path

import pytest

from assistant_x.core import config, env, lock, workspace
from assistant_x.core.common import load_config
from assistant_x.intake import config as intake_cfg

CODE = Path(__file__).resolve().parents[1]


def test_data_folders_of_a_workspace(tmp_path):
    w = workspace.Workspace(tmp_path)
    assert w.db == tmp_path / ".assistant_x" / "db" and w.models == workspace.machine_dir() / "models"
    assert w.work == tmp_path / ".assistant_x" / "work" and w.reports == tmp_path / "reports"
    assert w.texts == tmp_path / "index" / "texts" and not w.exists()
    assert workspace.Workspace(tmp_path, {"db": "base"}).db == tmp_path / "base"


def test_workspace_is_found(tmp_path, monkeypatch):
    (tmp_path / "ws" / "sub").mkdir(parents=True)
    (tmp_path / "ws" / workspace.CONFIG).write_text("", encoding="utf-8")
    monkeypatch.delenv("AX_WORKSPACE")
    assert workspace.find(tmp_path / "ws" / "sub") == (tmp_path / "ws").resolve()  # upward from the current folder
    assert workspace.find(tmp_path) == workspace.default_root()
    monkeypatch.setenv("AX_CONFIG", str(tmp_path / "other" / workspace.CONFIG))
    assert workspace.find(tmp_path / "ws") == (tmp_path / "other").resolve()
    monkeypatch.setenv("AX_WORKSPACE", str(tmp_path / "given"))
    assert workspace.find(tmp_path / "ws") == (tmp_path / "given").resolve()


def test_one_settings_file_for_search_and_intake(tmp_path):
    path = tmp_path / workspace.CONFIG
    path.write_text(
        'profile = "oil-gas-ru"\n[paths]\nlibrary = "docs"\n[search]\nrerank = false\n[intake]\nworkers = 3\n',
        encoding="utf-8",
    )
    config.save({"tesseract": "C:/t/tesseract.exe", "heavy_mb": 50}, "intake", path)
    assert "tesseract" not in path.read_text(encoding="utf-8")  # a program path is of this PC only
    assert "tesseract" in (tmp_path / workspace.LOCAL_CONFIG).read_text(encoding="utf-8")
    s = load_config(str(path))
    assert s["rerank"] is False and s["index_dir"] == str(tmp_path / ".assistant_x" / "db")
    assert s["synonyms"].endswith(os.path.join("profiles", "oil-gas-ru", "synonyms.txt"))
    assert s["embed_model"] == str(workspace.machine_dir() / "models" / "bge-m3")
    c = intake_cfg.load(path)
    assert (
        c.workers == 3
        and c.heavy_mb == 50
        and c.library == tmp_path / "docs"
        and c.work == tmp_path / ".assistant_x" / "work"
    )


def test_settings_written_back_as_toml(tmp_path):
    import tomllib

    data = {
        "profile": "x",
        "search": {"rerank": "auto", "gpu_min_free_gb": 5, "device": None},
        "intake": {"timeouts": {"soffice": 900}, "affinity": [2, 3], "personal": True, "name": 'a "b" \\ c'},
    }
    back = tomllib.loads(config.dumps(data))
    assert back == {
        "profile": "x",
        "search": {"rerank": "auto", "gpu_min_free_gb": 5},
        "intake": {"timeouts": {"soffice": 900}, "affinity": [2, 3], "personal": True, "name": 'a "b" \\ c'},
    }


def test_environment_names(monkeypatch):
    monkeypatch.delenv("AX_WORKERS", raising=False)
    assert env.get("WORKERS") is None
    monkeypatch.setenv("AX_WORKERS", "6")
    assert env.get("WORKERS") == "6" and not env.flag("NO_SUCH_FLAG")


def test_folder_lock_and_exclusive_lock(tmp_path):
    with lock.hold(tmp_path, "run"):
        with pytest.raises(lock.FolderBusy, match="An intake is running already: run"):
            lock.acquire(tmp_path, "apply")
    assert not (tmp_path / lock.NAME).exists()
    f = lock.exclusive(tmp_path / "models.lock")
    assert f is not None
    other = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from assistant_x.core import lock; sys.exit(0 if lock.exclusive(sys.argv[1]) is None else 1)",
            str(tmp_path / "models.lock"),
        ]
    )
    assert other.returncode == 0  # another process does not get it
    f.close()


def test_init_and_doctor(tmp_path, monkeypatch, capsys):
    """init makes a whole empty workspace, a second init changes nothing; doctor tells empty from broken."""
    from assistant_x.cli import main

    ws = tmp_path / "Мой проект"
    assert main.main(["init", str(ws), "--personal"]) == 0
    assert (ws / workspace.CONFIG).is_file() and (ws / "inbox").is_dir() and (ws / ".assistant_x" / "db").is_dir()
    assert (ws / "index" / "cards" / "_README.md").is_file() and (ws / "inbox" / "_README.md").is_file()
    assert all((ws / "inbox" / d).is_dir() for d in ("_duplicates", "_to_delete", "_rejected"))
    assert "Documents: 0." in (ws / "index" / "CATALOG.md").read_text(encoding="utf-8")
    assert "## Open" in (ws / "index" / "sources_to_update.md").read_text(encoding="utf-8")
    assert "personal = true" in (ws / workspace.CONFIG).read_text(encoding="utf-8")
    first = capsys.readouterr().out  # the one choice left to the user is named, not made (audit 6)
    assert "auto_apply = true under [intake]" in first and "auto_apply" not in (ws / workspace.CONFIG).read_text(
        encoding="utf-8"
    ).replace("# auto_apply", "")
    (ws / "index" / "CATALOG.md").write_text("# my own catalog\n", encoding="utf-8")
    assert main.main(["init", str(ws)]) == 0  # repeated: nothing overwritten
    again = capsys.readouterr().out
    assert "nothing was missing" in again and "auto_apply" not in again
    assert (ws / "index" / "CATALOG.md").read_text(encoding="utf-8") == "# my own catalog\n"
    (ws / "index" / "CATALOG.md").unlink()
    assert main.main(["init", str(ws)]) == 0 and (ws / "index" / "CATALOG.md").exists()  # completed
    monkeypatch.setenv("AX_WORKSPACE", str(ws))
    assert main.main(["doctor"]) == 0  # empty and in order
    out = capsys.readouterr().out
    assert "empty and in order" in out and "synonyms         none in this profile" in out and "MISSING (-)" not in out
    from tests.intake.intake_fixtures import old_card
    from assistant_x.core import card as C

    C.dump(old_card(), ws / "index" / "cards" / "N-00001.json")
    assert main.main(["doctor"]) == 1  # a card of a document but no base: broken
    assert "no search base" in capsys.readouterr().out
    monkeypatch.setenv("AX_WORKSPACE", str(tmp_path / "none"))
    assert main.main(["doctor"]) == 1 and "not made yet" in capsys.readouterr().out
    assert main.main(["no-such-command"]) == 2


def test_help_of_every_command_does_nothing(tmp_path):
    """`assistant-x <command> --help` prints the help of the command (its usage names the command, not a module file)
    and writes nothing: no workspace (the default
    one in Documents either), no PC folder, no log, no server, no lock. init also refuses an unknown option."""
    from assistant_x.cli import main

    lines = [["init"], ["doctor"]] + [[c] for c in main.COMMANDS]
    lines += [["intake", c] for c in ("run", "status", "check-meta", "build", "apply")]
    lines += [["base", c] for c in ("export", "inspect", "install", "update", "remove")]
    script = (
        "import contextlib, io, json, sys\n"
        "from assistant_x.cli import main\n"
        "out = []\n"
        "for line in json.loads(sys.argv[1]):\n"
        "    buf = io.StringIO()\n"
        "    with contextlib.redirect_stdout(buf):\n"
        "        rc = main.main(line + ['--help'])\n"
        "    out.append([line, rc, buf.getvalue()])\n"
        "print(json.dumps(out))\n"
    )
    home, cwd = tmp_path / "home", tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    environ = dict(os.environ, PYTHONPATH=str(CODE), AX_WORKSPACE=str(tmp_path / "ws"), AX_NO_OPEN="1")
    environ.update(AX_MACHINE_DIR=str(tmp_path / "pc"), USERPROFILE=str(home), HOME=str(home))
    environ.update(AX_HEAVY_LOCK_FILE=str(tmp_path / "pc" / "heavy.lock"), PYTHONDONTWRITEBYTECODE="1")
    import json

    r = subprocess.run(
        [sys.executable, "-c", script, json.dumps(lines)], cwd=cwd, env=environ, capture_output=True, text=True, timeout=300
    )
    assert r.returncode == 0, r.stderr[-2000:]
    for line, rc, text in json.loads(r.stdout.strip().splitlines()[-1]):
        usage = text.lstrip().split("\n")[0]
        assert rc == 0 and "assistant-x " + " ".join(line) in usage and ".py" not in usage, (line, rc, usage)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["cwd", "home"]  # no ws, no pc folder
    assert not list(home.rglob("*")) and not list(cwd.rglob("*"))
    assert main.main(["init", str(tmp_path / "w"), "--profiel", "general"]) == 2 and not (tmp_path / "w").exists()


def test_index_files_of_an_empty_index(tmp_path):
    """The views of an empty index are made from no cards; a file there already is never overwritten by ensure()."""
    from assistant_x.core import index_files

    (tmp_path / "CATALOG.md").write_text("# my own\n", encoding="utf-8")
    made = index_files.ensure(tmp_path, "2026-10-25")
    assert (tmp_path / "CATALOG.md").read_text(encoding="utf-8") == "# my own\n"
    upd = (tmp_path / "sources_to_update.md").read_text(encoding="utf-8")
    assert "Open items: 0." in upd and "## Open" in upd and "## Closed" in upd and tmp_path / "sources_to_update.md" in made
    assert (tmp_path / "cards" / "_README.md").is_file() and index_files.ensure(tmp_path) == []


def test_server_answers_an_empty_library(tmp_path, monkeypatch):
    """No base: the library commands say what to do instead of failing."""
    from assistant_x.cli import main
    from assistant_x.server import mcp_server

    ws = tmp_path / "ws"
    main.main(["init", str(ws)])
    monkeypatch.setattr(mcp_server, "_lib", None)
    monkeypatch.setattr(mcp_server, "load_config", lambda: load_config(str(ws / workspace.CONFIG)))
    out = mcp_server.search_library("separator")
    assert out.startswith("The library is empty") and "intake_run()" in out
    assert mcp_server.list_documents().startswith("The library is empty")


def test_no_code_writes_into_the_code_folder():
    """The tests ran: nothing of a workspace was left in the code folder."""
    for name in ("inbox", "library", "index", ".assistant_x", "reports", "debug", workspace.CONFIG):
        assert not (CODE / name).exists(), name
    assert not list((CODE / "assistant_x").rglob("*.lock")) and not list((CODE / "assistant_x").rglob("*.log"))


def test_profiles_and_init_profile(tmp_path, monkeypatch):
    """general (the default) has no domain data; oil-gas-ru has synonyms."""
    from assistant_x.cli import main

    assert {"general", "oil-gas-ru"} <= set(config.profiles())
    g = tmp_path / "g" / workspace.CONFIG
    g.parent.mkdir()
    g.write_text("", encoding="utf-8")
    assert config.load(g)[1]["profile"] == "general" and load_config(str(g))["synonyms"] == ""
    assert config.profile_file("synonyms.txt", {"profile": "oil-gas-ru"}).is_file()
    assert config.profile_file("synonyms.txt", {"profile": "general"}) is None
    assert main.main(["init", str(tmp_path / "w"), "--profile", "oil-gas-ru"]) == 0
    assert 'profile = "oil-gas-ru"' in (tmp_path / "w" / workspace.CONFIG).read_text(encoding="utf-8")
    assert main.main(["init", str(tmp_path / "v"), "--profile", "nope"]) == 2


def test_language_packs():
    """Every pack loads (a key once per pack), both languages are active by default, Russian first."""
    from assistant_x.core import lang

    assert {"ru", "en"} <= set(lang.available()) and lang.active() == ("ru", "en")
    for code in lang.available():
        p = lang.pack(code)
        assert p["stemmer"] and p["lower"] and isinstance(p["stop_words"], list)
    assert lang.alt("chapter_words").startswith(lang.get("ru", "chapter_words")[0])


def test_no_cyrillic_in_the_code():
    """The words of document languages are data (assistant_x/lang, assistant_x/profiles); the code is English only."""
    import re

    cyr = re.compile("[\u0400-\u04ff]")
    bad = [
        f"{p.relative_to(CODE)}:{i}"
        for p in (CODE / "assistant_x").rglob("*.py")
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if cyr.search(line)
    ]
    assert bad == []


def test_every_data_file_goes_into_the_package():
    """pip installs what [tool.setuptools.package-data] names: every file of assistant_x that is no Python code must
    match one of its patterns (lang/, profiles/, templates/), or an installed Assistant X would miss it."""
    import fnmatch, tomllib

    patterns = tomllib.loads((CODE / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]["package-data"][
        "assistant_x"
    ]
    root = CODE / "assistant_x"
    data = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.suffix not in (".py", ".pyc") and "__pycache__" not in p.parts
    ]
    missing = [
        d for d in data if not any(fnmatch.fnmatchcase(d, pat) and d.count("/") == pat.count("/") for pat in patterns)
    ]
    assert data and missing == []


def test_skill_of_the_profile(tmp_path):
    """The skill is written for a profile: the oil-and-gas role only in oil-gas-ru, nothing of a template left."""
    from assistant_x.setup import skill

    oil, general = skill.render("oil-gas-ru"), skill.render("general")
    assert "process engineer" in oil and "process engineer" not in general
    assert "{{" not in oil and "{{" not in general and general.startswith('---\nname: "assistant-x"')
    assert skill.main(["--profile", "general", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "SKILL.md").read_text(encoding="utf-8") == general


def test_the_workspace_option_anywhere():
    from assistant_x.cli import main

    assert main.take_workspace(["--workspace", "W", "search", "x"]) == (["search", "x"], "W")
    assert main.take_workspace(["search", "x", "--workspace", "W"]) == (["search", "x"], "W")
    assert main.take_workspace(["base", "--workspace=W", "list"]) == (["base", "list"], "W")
    assert main.take_workspace(["base", "remove", "--", "--workspace", "W"]) == (
        ["base", "remove", "--", "--workspace", "W"],
        None,
    )
    assert main.take_workspace(["doctor"]) == (["doctor"], None)
