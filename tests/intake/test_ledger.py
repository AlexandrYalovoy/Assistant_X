# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ledger of a batch: every file the batch met gets exactly one outcome, so the totals add up."""

import csv

from assistant_x.intake import ledger
from assistant_x.intake.state import State


def test_every_file_has_one_outcome(tmp_path):
    state = State(tmp_path / "state.sqlite")
    t = [state.add(f"f{i}.pdf", 10) for i in range(8)]
    state.update(t[0], status="done", pages=3, ocr_pages=1, ocr_score=91.5, prep_seconds=1.0, ocr_seconds=2.5)
    state.update(t[1], status="dup", why="the same SHA-256", dup_of="N-00001")
    state.update(t[2], status="error", why="the PDF does not open")
    state.update(t[3], status="skipped", why="the pipeline does not process .exe: decide by hand")
    state.update(t[4], status="skipped", why="a temporary Office file (~$): reject")
    state.update(t[5], status="skipped", why=ledger.HELD_SHEET)
    state.update(t[6], status="skipped", why=ledger.set_aside_why("pictures"))
    state.set_meta("moved", [["mail/letter.msg", 20, "to delete: a letter"]])
    counts, total = ledger.write(tmp_path, state)
    assert total == 9
    assert counts == {
        "done": 1,
        "duplicate": 1,
        "error": 1,
        "damaged": 0,
        "unsupported": 1,
        "skipped": 1,
        "held": 1,
        "set aside": 1,
        "moved": 1,
        "queued": 1,
    }
    with open(tmp_path / "ledger.csv", encoding="utf-8-sig") as f:
        rows = {r["file"]: r for r in csv.DictReader(f)}
    assert rows["f0.pdf"]["score"] == "91.5" and rows["f0.pdf"]["seconds"] == "3.5"
    assert rows["f1.pdf"]["why"].endswith("-> N-00001")
    assert rows["mail/letter.msg"]["outcome"] == "moved"
    assert "Ledger (ledger.csv): 9 files: done 1" in ledger.line(counts, total)
    state.close()


def test_spreadsheets_can_be_held_in_inbox(tmp_path, monkeypatch):
    """[intake] spreadsheets = "skip": a workbook is not read and stays in inbox untouched, "held" in the ledger,
    listed in the summary and the status with how to take it (spreadsheets = "include", or --spreadsheets include)."""
    import types

    from assistant_x.core import config as settings
    from assistant_x.intake import review
    from assistant_x.intake import work as intake_work
    from assistant_x.server import intake_tools

    assert settings.INTAKE["spreadsheets"] in ("reject", "skip", "include")
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


def test_pictures_web_pages_and_spreadsheets_are_set_aside_by_default(tmp_path, monkeypatch):
    """The author, 2026-10-30: loose pictures and photos, saved web pages and workbooks are not read by default; after
    the batch they go to inbox\\_rejected\\<pictures | web pages | spreadsheets>, "set aside" in the ledger, listed in
    the summary and the status as taken on request, with how to take them."""
    import types

    from assistant_x.core import config as settings
    from assistant_x.intake import review
    from assistant_x.intake import work as intake_work
    from assistant_x.server import intake_tools

    assert [settings.INTAKE[k] for k in ("pictures", "web_pages", "spreadsheets")] == ["reject"] * 3
    base = {"work": str(tmp_path / "w"), "ocr": False, "imgocr": False, "soffice": "soffice", "memory_mb": 0, "env": {}}
    base.update(inproc=True, timeouts={"soffice": 60, "hidden": 60}, pictures="reject", web_pages="reject")
    base["spreadsheets"] = "reject"
    files = {"photo.jpg": b"\xff\xd8\xff\xe0" + b"\0" * 64, "page.htm": b"<html><body>a page</body></html>"}
    files["regime.xlsx"] = b"PK\x05\x06" + b"\0" * 18
    whys = {}
    for i, (name, data) in enumerate(files.items(), 1):
        src = tmp_path / name
        src.write_bytes(data)
        res = intake_work.prep({**base, "tid": f"T{i:04d}", "src": str(src), "ext": name.rsplit(".", 1)[1]})
        assert res["status"] == "skipped" and res["why"].startswith(ledger.SET_ASIDE) and src.exists()
        whys[name] = res["why"]
    assert {n: ledger.set_aside_group(w) for n, w in whys.items()} == {
        "photo.jpg": "pictures",
        "page.htm": "web_pages",
        "regime.xlsx": "spreadsheets",
    }
    assert "--pictures include" in whys["photo.jpg"] and "_rejected" in whys["page.htm"]
    state = State(tmp_path / "state.sqlite")
    for name, why in whys.items():
        state.update(state.add(f"site/{name}", 10), status="skipped", why=why)
    counts, _ = ledger.write(tmp_path, state)
    assert counts["set aside"] == 3 and counts["skipped"] == 0
    cfg = types.SimpleNamespace(soffice="soffice")
    monkeypatch.setattr(review.intake_cfg, "can_ocr", lambda c: True)
    text = review.summary(cfg, tmp_path, state, {}, [], 60)
    assert "set aside (taken on request) 3" in text and "## Set aside, taken on request (3)" in text
    assert "pictures 1" in text and "site\\photo.jpg" in text and "ask the assistant" in text
    data = review.status_data(tmp_path, state)
    assert data["set_aside"] == {
        "site/photo.jpg": "pictures",
        "site/page.htm": "web_pages",
        "site/regime.xlsx": "spreadsheets",
    }
    assert not data["errors"]
    words = intake_tools.batch_words(data)
    assert "Set aside, taken on request" in words and "site/page.htm" in words
    state.close()


def test_include_reads_a_picture(tmp_path):
    """pictures = "include": a picture is not set aside by the setting (it goes on to its conversion)."""
    import pymupdf

    from assistant_x.intake import work as intake_work

    src = tmp_path / "scan.png"
    pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), False).save(str(src))
    job = {"work": str(tmp_path / "w"), "tid": "T0001", "src": str(src), "ext": "png", "ocr": False, "imgocr": False}
    job.update(soffice=None, timeouts={"soffice": 60, "hidden": 60}, memory_mb=0, env={}, inproc=True, pictures="include")
    res = intake_work.prep(job)
    assert not (res.get("why") or "").startswith(ledger.SET_ASIDE)
