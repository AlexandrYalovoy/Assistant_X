# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The apply as a transaction: an apply interrupted at any step is continued with --resume and ends as an
uninterrupted one would (no row twice), a second apply without --resume is refused, missing index files are made."""

import json

import pytest

from assistant_x.intake import apply as intake_apply
from assistant_x.intake import build as intake_build
from assistant_x.intake import pipeline as intake
from assistant_x.intake.state import State
from tests.intake.intake_fixtures import doc_line
from tests.intake.test_intake_flow import GOST_MD


def built_batch(cfg, name="w"):
    work = cfg.work / name
    (work / "md").mkdir(parents=True)
    state = State(work / "state.sqlite")
    intake.register(cfg, state)
    t = state.by_rel("text.pdf")["tid"]
    (work / "md" / f"{t}.md").write_text(GOST_MD, encoding="utf-8")
    state.update(t, status="done", pages=2, ocr_pages=0)
    s = state.by_rel("Сканы/scan.pdf")["tid"]
    (work / "md" / f"{s}.md").write_text("=== page 1 ===\n\nСКАН\n", encoding="utf-8")
    state.update(s, status="done", pages=1, ocr_pages=1)
    state.con.close()
    (work / "meta.jsonl").write_text(
        json.dumps(doc_line(t, "L", "Сепараторы нефтегазовые", "Book", year=2020), ensure_ascii=False)
        + "\n"
        + json.dumps(doc_line(s, "X", "Скан", "Scan"), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    assert intake_build.build(cfg, work, date="2026-10-25") == 0
    return work


def index_state(cfg):
    """The index files without what differs between two copies of a test project: hashes, times, sizes of the PDFs
    made by the fixture."""
    import re

    idx = cfg.index
    out = {}
    for p in ("CATALOG.md", "sources_to_update.md", "intake_events.tsv", "manifest.tsv", "journal.md"):
        text = (idx / p).read_text(encoding="utf-8")
        text = re.sub(r"[0-9a-f]{16,64}", "<sha>", text)
        text = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", "<time>", text)
        out[p] = re.sub(r"(?m)(\t|\| )\d{3,}(\t| \|)", r"\1<size>\2", text)
    return out


@pytest.mark.parametrize("fail_at", ["moves", "catalog", "events", "manifest", "dirs"])
def test_interrupted_apply_resumes(project, monkeypatch, tmp_path, fail_at):
    root, cfg = project
    work = built_batch(cfg)
    # the reference: the same batch applied without a break in a copy of the project
    from tests.intake.intake_fixtures import make_project
    from assistant_x.intake import config as intake_cfg

    ref_cfg = intake_cfg.load(make_project(tmp_path / "ref"))
    ref_work = built_batch(ref_cfg)
    assert intake_apply.apply(ref_cfg, ref_work, date="2026-10-25") == 0
    expected = index_state(ref_cfg)

    calls = {"n": 0}
    real = {
        "moves": intake_apply.move,
        "catalog": intake_apply.write_views,
        "events": intake_apply.journal.append_events,
        "manifest": intake_apply.manifest.main,
        "dirs": intake_apply.remove_empty_dirs,
    }[fail_at]

    def broken(*a, **k):
        calls["n"] += 1
        if fail_at != "moves" or calls["n"] == 2:  # the moves: the PC goes off after the first file
            raise OSError("the PC was switched off")
        return real(*a, **k)

    target = {
        "moves": (intake_apply, "move"),
        "catalog": (intake_apply, "write_views"),
        "events": (intake_apply.journal, "append_events"),
        "manifest": (intake_apply.manifest, "main"),
        "dirs": (intake_apply, "remove_empty_dirs"),
    }[fail_at]
    monkeypatch.setattr(*target, broken)
    with pytest.raises(OSError):
        intake_apply.apply(cfg, work, date="2026-10-25")
    monkeypatch.setattr(*target, real)
    assert not (work / "out" / "applied.json").exists()
    assert intake_apply.apply(cfg, work) == 1  # interrupted: refused without --resume
    assert intake_apply.apply(cfg, work, resume=True) == 0
    got = index_state(cfg)
    for name in expected:
        assert got[name] == expected[name], name
    assert (cfg.library / "02_Literature" / "L-00002_Book_2020.pdf").exists() or any(
        (cfg.library / "02_Literature").glob("L-*_Book_2020.pdf")
    )
    assert intake_apply.apply(cfg, work, resume=True) == 1  # applied: nothing to resume


def test_resume_without_an_interrupted_apply(project):
    root, cfg = project
    work = built_batch(cfg)
    assert intake_apply.apply(cfg, work, resume=True) == 1


def test_apply_makes_missing_index_files(project):
    """An index without CATALOG.md and sources_to_update.md (a workspace made by hand): the apply makes them from
    all the cards, the one of the library among them."""
    root, cfg = project
    work = built_batch(cfg)
    (cfg.index / "CATALOG.md").unlink()
    (cfg.index / "sources_to_update.md").unlink()
    assert intake_apply.apply(cfg, work, dry=True) == 0 and not (cfg.index / "CATALOG.md").exists()
    assert intake_apply.apply(cfg, work, date="2026-10-25") == 0
    cat = (cfg.index / "CATALOG.md").read_text(encoding="utf-8")
    assert "Updated: 2026-10-25. Documents: 3." in cat and "| L-00001 |" in cat and "| N-00001 | Старый стандарт |" in cat
    upd = (cfg.index / "sources_to_update.md").read_text(encoding="utf-8")
    assert "Open items: 0." in upd and "## Open" in upd and "## Closed" in upd
