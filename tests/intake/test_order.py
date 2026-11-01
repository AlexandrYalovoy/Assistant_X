# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The batches of a big inbox by cost ([intake] order = "cost", the author's rule of 2026-10-31): the fast files first
(a text layer, office files), then the medium ones (small scans, help files), then a few slow ones a run (DjVu, long
scans); the files a run does not take stay in inbox, untouched, for the next one."""

import pymupdf
import pytest

from assistant_x.intake import order
from assistant_x.intake.process import register
from assistant_x.intake.state import State
from tests.intake.intake_fixtures import scan_pdf, text_pdf


def long_scan(path, pages):
    one = pymupdf.open()
    one.new_page()
    pix = one[0].get_pixmap(dpi=20)
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page().insert_image(pymupdf.Rect(0, 0, 595, 842), pixmap=pix)
    doc.save(path)


@pytest.fixture
def inbox(tmp_path):
    d = tmp_path / "inbox"
    d.mkdir()
    text_pdf(d / "text.pdf", ["Насос центробежный: назначение и параметры. " * 8])
    (d / "note.docx").write_bytes(b"PK\x05\x06" + b"\0" * 18)
    scan_pdf(d / "scan.pdf")
    (d / "help.chm").write_bytes(b"ITSF")
    for name in ("book1.djvu", "book2.djvu", "book3.djvu"):
        (d / name).write_bytes(b"AT&TFORM" + b"\0" * (100 + len(name)))
    long_scan(d / "long.pdf", order.LONG_SCAN + 1)
    return d


def files(d):
    return sorted((str(p), p.name) for p in d.iterdir() if p.is_file())


def test_the_cost_of_a_file(inbox):
    want = {
        "text.pdf": "fast",
        "note.docx": "fast",
        "scan.pdf": "medium",
        "help.chm": "medium",
        "book1.djvu": "slow",
        "long.pdf": "slow",
    }
    assert {rel: order.cost_class(full, rel) for full, rel in files(inbox) if rel in want} == want
    assert order.cost_class(str(inbox / "x.jpg"), "x.jpg", {"pictures": "reject"}) == "fast"  # set aside: no cost
    assert order.cost_class(str(inbox / "x.jpg"), "x.jpg", {"pictures": "include"}) == "medium"


def test_a_run_takes_the_cheapest_class_and_a_few_slow_files(inbox):
    chosen, took, left = order.pick(files(inbox))
    assert took == "fast" and {r for _, r in chosen} == {"text.pdf", "note.docx"}
    assert left == {"medium": 2, "slow": 4}
    rest = [f for f in files(inbox) if f[1] not in {"text.pdf", "note.docx"}]
    chosen, took, left = order.pick(rest)
    assert took == "medium" and {r for _, r in chosen} == {"scan.pdf", "help.chm"} and left == {"slow": 4}
    slow = [f for f in rest if f[1] not in {"scan.pdf", "help.chm"}]
    chosen, took, left = order.pick(slow, {"slow_batch": 2})
    assert took == "slow" and [r for _, r in chosen] == ["book1.djvu", "book2.djvu"] and left == {"slow": 2}


def test_register_takes_only_the_chosen_files(tmp_path, inbox):
    import types

    cfg = types.SimpleNamespace(inbox=inbox)
    state = State(tmp_path / "state.sqlite")
    assert register(cfg, state, only={"text.pdf", "note.docx"}) == 2
    assert sorted(r["rel"] for r in state.all()) == ["note.docx", "text.pdf"]
    assert (inbox / "long.pdf").exists() and (inbox / "book1.djvu").exists()  # the others wait in inbox
    state.close()


def test_a_run_by_cost_leaves_the_scans_for_the_next_batch(tmp_path):
    from assistant_x.intake import config as intake_cfg
    from assistant_x.intake import pipeline as intake
    from tests.intake.intake_fixtures import make_project

    path = make_project(tmp_path / "Проект")
    cfg = intake_cfg.load(path)
    assert intake.main(["--config", str(path), "run", "--workers", "0", "--order", "cost"]) == 0
    work = sorted(cfg.work.glob("20??-??-??"))[-1]
    state = State(work / "state.sqlite")
    assert "Сканы/scan.pdf" not in {r["rel"] for r in state.all()} and (cfg.inbox / "Сканы" / "scan.pdf").exists()
    assert "Order by cost: this batch took the fast files; left in inbox for the next batches: medium 1" in (
        (work / "summary.md").read_text(encoding="utf-8")
    )
    state.close()


def test_the_settings_of_the_order(tmp_path):
    from assistant_x.core import config as settings

    assert settings.INTAKE["order"] == "cost" and settings.INTAKE["slow_batch"] >= 1
    assert set(order.ORDERS) == {"cost", "all"}
