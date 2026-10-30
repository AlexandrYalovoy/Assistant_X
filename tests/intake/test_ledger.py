# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ledger of a batch: every file the batch met gets exactly one outcome, so the totals add up."""

import csv

from assistant_x.intake import ledger
from assistant_x.intake.state import State


def test_every_file_has_one_outcome(tmp_path):
    state = State(tmp_path / "state.sqlite")
    t = [state.add(f"f{i}.pdf", 10) for i in range(7)]
    state.update(t[0], status="done", pages=3, ocr_pages=1, ocr_score=91.5, prep_seconds=1.0, ocr_seconds=2.5)
    state.update(t[1], status="dup", why="the same SHA-256", dup_of="N-00001")
    state.update(t[2], status="error", why="the PDF does not open")
    state.update(t[3], status="skipped", why="the pipeline does not process .exe: decide by hand")
    state.update(t[4], status="skipped", why="a temporary Office file (~$): reject")
    state.update(t[5], status="skipped", why=ledger.HELD_SHEET)
    state.set_meta("moved", [["mail/letter.msg", 20, "to delete: a letter"]])
    counts, total = ledger.write(tmp_path, state)
    assert total == 8
    assert counts == {
        "done": 1,
        "duplicate": 1,
        "error": 1,
        "damaged": 0,
        "unsupported": 1,
        "skipped": 1,
        "held": 1,
        "moved": 1,
        "queued": 1,
    }
    with open(tmp_path / "ledger.csv", encoding="utf-8-sig") as f:
        rows = {r["file"]: r for r in csv.DictReader(f)}
    assert rows["f0.pdf"]["score"] == "91.5" and rows["f0.pdf"]["seconds"] == "3.5"
    assert rows["f1.pdf"]["why"].endswith("-> N-00001")
    assert rows["mail/letter.msg"]["outcome"] == "moved"
    assert "Ledger (ledger.csv): 8 files: done 1" in ledger.line(counts, total)
    state.close()


def test_spreadsheets_are_held_in_inbox_by_default(tmp_path, monkeypatch):
    """The author, 2026-10-29: a workbook is mostly a dataset (a monthly regime of 2 000 wells came out as 1 029
    pages), so by default it is not read: it stays in inbox untouched, "held" in the ledger, listed in the summary and
    the status with how to take it ([intake] spreadsheets = "include", or intake run --spreadsheets include)."""
    import types

    from assistant_x.core import config as settings
    from assistant_x.intake import review
    from assistant_x.intake import work as intake_work
    from assistant_x.server import intake_tools

    assert settings.INTAKE["spreadsheets"] == "skip"
    book = tmp_path / "regime.xlsx"
    book.write_bytes(b"PK\x05\x06" + b"\0" * 18)
    job = {
        "work": str(tmp_path / "w"),
        "tid": "T0001",
        "src": str(book),
        "ext": "xlsx",
        "ocr": False,
        "imgocr": False,
        "soffice": "soffice",
        "timeouts": {"soffice": 60, "hidden": 60},
        "memory_mb": 0,
        "env": {},
        "inproc": True,
        "spreadsheets": "skip",
    }
    res = intake_work.prep(job)
    assert res == {"status": "skipped", "why": ledger.HELD_SHEET} and book.exists()
    state = State(tmp_path / "state.sqlite")
    t = [state.add(rel, 10) for rel in ("data/regime.xlsx", "data/note.pdf")]
    state.update(t[0], status="skipped", why=res["why"])
    state.update(t[1], status="done", pages=1)
    counts, _ = ledger.write(tmp_path, state)
    assert counts["held"] == 1 and counts["skipped"] == 0
    cfg = types.SimpleNamespace(soffice="soffice")
    monkeypatch.setattr(review.intake_cfg, "can_ocr", lambda c: True)
    text = review.summary(cfg, tmp_path, state, {}, [], 60)
    assert "held in inbox 1" in text and "## Held in inbox (1)" in text and "data\\regime.xlsx" in text
    assert 'spreadsheets = "include"' in text
    data = review.status_data(tmp_path, state)
    assert data["held"] == ["data/regime.xlsx"] and not data["errors"]
    words = intake_tools.batch_words(data)
    assert "Held in inbox, not taken by default: 1 spreadsheets" in words and "data/regime.xlsx" in words
    state.close()


def test_damaged_files_are_set_aside_after_the_batch(tmp_path, monkeypatch):
    """The author, 2026-10-30: «повреждённые файлы откладывать автоматически». After a batch every file whose error
    says it is damaged ("... (get it again)") moves to inbox\\_to_delete\\damaged with its folders, a journal line
    with its SHA-256, "damaged" in the ledger and a list in the summary; another error stays in inbox."""
    import types

    from assistant_x.intake import prepare, review

    inbox, index = tmp_path / "inbox", tmp_path / "index"
    (inbox / "a").mkdir(parents=True)
    index.mkdir()
    (inbox / "a" / "cut.pdf").write_bytes(b"%PDF-1.7" + b"\0" * 100)
    (inbox / "a" / "other.doc").write_bytes(b"x" * 10)
    cfg = types.SimpleNamespace(inbox=inbox, index=index, soffice="soffice")
    state = State(tmp_path / "state.sqlite")
    t = [state.add(rel, 10) for rel in ("a/cut.pdf", "a/other.doc")]
    state.update(t[0], status="error", why="the PDF has no page that can be read: a damaged or cut file (get it again)")
    state.update(t[1], status="error", why="LibreOffice did not convert it to pdf (code 1)")
    events = prepare.set_aside_damaged(cfg, state)
    assert len(events) == 1 and (inbox / "_to_delete" / "damaged" / "a" / "cut.pdf").exists()
    assert not (inbox / "a" / "cut.pdf").exists() and (inbox / "a" / "other.doc").exists()
    assert "to delete: damaged" in (index / "intake_events.tsv").read_text(encoding="utf-8")
    counts, _ = ledger.write(tmp_path, state)
    assert counts["damaged"] == 1 and counts["error"] == 1
    monkeypatch.setattr(review.intake_cfg, "can_ocr", lambda c: True)
    text = review.summary(cfg, tmp_path, state, {}, [], 60)
    assert "## Damaged, moved to inbox\\_to_delete\\damaged (1)" in text and "a\\cut.pdf" in text
    state.close()
