# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A document taken out of the library (assistant-x remove, library_remove): its original, card and text go to
inbox\\_to_delete\\removed_<code>_<date>, the events say why, the base by words has no fragment of it, its code stays
reserved, and the same file brought again is no duplicate."""

import shutil, sqlite3, sys

import pytest

from assistant_x.core import card as C, journal
from assistant_x.core.common import load_config
from assistant_x.core.formats import event_kind
from assistant_x.intake import config as intake_cfg, manifest, remove
from assistant_x.intake.prepare import known_hashes, sha256
from tests.search.conftest import make_library


@pytest.fixture
def lib(tmp_path, monkeypatch):
    from assistant_x.search import build_index

    root = tmp_path / "Библиотека"
    path = make_library(str(root))
    (root / "inbox").mkdir()
    manifest.main(["--root", str(root)])
    monkeypatch.setattr(sys, "argv", ["build_index.py", "--config", path])
    build_index.main()
    cfg = intake_cfg.load(path)
    original = root / "library" / "01_Standards"
    pdf = next(original.glob("N-00002*.pdf"))
    sha = sha256(pdf)[:16]
    journal.append_events(
        cfg.index / "intake_events.tsv", [["2026-10-23", "inbox\\x.pdf", 1, sha, "N-00002", "library\\", "done"]]
    )
    return root, path, cfg, pdf, sha


def _fragments(path, code):
    con = sqlite3.connect(load_config(path)["db"])
    try:
        return con.execute("SELECT count(*) FROM chunks WHERE code=?", (code,)).fetchone()[0]
    finally:
        con.close()


def test_a_document_goes_aside(lib, tmp_path):
    root, path, cfg, pdf, sha = lib
    assert _fragments(path, "N-00002") > 0 and known_hashes(cfg)[sha] == "N-00002"
    keep = tmp_path / "copy.pdf"
    shutil.copy2(pdf, keep)
    assert remove.main(["N-00002", "--dry-run", "--config", path]) == 0
    assert pdf.exists()  # a trial run changes nothing
    assert remove.main(["N-00002", "--why", "got in by mistake", "--config", path]) == 0
    aside = root / "inbox" / "_to_delete"
    moved = {p.name for p in aside.rglob("*") if p.is_file()}
    assert {pdf.name, "N-00002.json", "N-00002.md"} <= moved and not pdf.exists()
    assert not (cfg.index / "cards" / "N-00002.json").exists() and not (cfg.index / "texts" / "N-00002.md").exists()
    events = [ln.split("\t") for ln in (cfg.index / "intake_events.tsv").read_text(encoding="utf-8").splitlines()[1:]]
    removed = [e for e in events if event_kind(e[6]) == "removed"]
    assert removed and all(e[6] == "removed: got in by mistake" for e in removed)
    assert _fragments(path, "N-00002") == 0  # the base by words was rebuilt
    assert "N-00002" not in (cfg.index / "manifest.tsv").read_text(encoding="utf-8")
    assert C.high_water(cfg.index)["N"] >= 2  # the number never comes back
    assert sha not in known_hashes(cfg)  # the same file brought again is no duplicate
    assert not (cfg.index / remove.JOURNAL).exists()


def test_an_unknown_code_changes_nothing(lib, capsys):
    root, path, cfg, pdf, sha = lib
    assert remove.main(["N-00099", "--config", path]) == 1
    assert "No document N-00099" in capsys.readouterr().out and pdf.exists()


def test_the_server_gives_a_plan_and_a_token(lib, monkeypatch):
    from assistant_x.server import intake_tools

    root, path, cfg, pdf, sha = lib
    monkeypatch.setenv("AX_WORKSPACE", str(root))
    started = []
    monkeypatch.setattr(intake_tools, "_start", lambda kind, cmd, **env: started.append(cmd) or (True, ""))
    plan = intake_tools.library_remove(["n-00002"], why="by mistake")
    assert "N-00002 «" in plan and "Trial run: nothing changed." in plan and 'token="' in plan and pdf.exists()
    token = plan.split('token="')[1].split('"')[0]
    assert intake_tools.library_remove(["N-00002"], confirm=True, token="bad").startswith("Not confirmed")
    out = intake_tools.library_remove(["N-00002"], why="by mistake", confirm=True, token=token)
    assert out.startswith("The removal of N-00002 started in the background") and started
    assert started[0][1:] == ["-m", "assistant_x.intake.remove", "N-00002", "--why", "by mistake"]
