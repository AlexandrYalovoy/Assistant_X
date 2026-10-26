# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Documents the intake must not lose: another edition of a library document is no duplicate by itself
(process.Batch.dup_verdict), a scan with a stamp or a header in its text layer is still recognised by OCR, a broken
font encoding is seen before the conversion (work.prep), and the text layer of a scan stays beside its OCR text."""

import json

import pymupdf
import pytest

from assistant_x.intake import metadraft
from assistant_x.intake import work as intake_work
from assistant_x.intake.process import Batch
from assistant_x.intake.state import State
from assistant_x.intake.tools import assemble_md, ocr_score, reocr_empty
from tests.intake.intake_fixtures import FONT, scan_pdf, text_pdf

BODY = "Настоящий стандарт распространяется на нефть, подготовленную к транспортированию. "


def pages_md(first, n):
    return "".join(f"=== page {i} ===\n\n{first if i == 1 else BODY * 3}\n" for i in range(1, n + 1))


@pytest.fixture
def batch(project):
    """A batch with one file T0001 and a library text N-00005 (ГОСТ Р 51858-2002, 20 pages) of 1000 phrases."""
    _, cfg = project
    work = cfg.work / "2026-10-25"
    work.mkdir(parents=True)
    state = State(work / "state.sqlite")
    state.add("new.pdf", 1000)
    tid = state.all()[0]["tid"]
    (cfg.index / "texts" / "N-00005.md").write_text(
        pages_md("ГОСТ Р 51858-2002\n\nНЕФТЬ Общие технические условия", 20), encoding="utf-8"
    )
    b = Batch(cfg, work, state, 0)
    b.lib["N-00005"] = set(range(1000))
    return b, tid


def candidate(b, tid, share, first, pages):
    """The candidate text of tid with `share` of its 1000 phrases in N-00005; returns its fingerprint."""
    (b.work / "txt").mkdir(exist_ok=True)
    (b.work / "txt" / f"{tid}.txt").write_text(pages_md(first, pages), encoding="utf-8")
    b.state.update(tid, pages=pages)
    k = int(share * 1000)
    return set(range(k)) | set(range(5000, 6000 - k))


def test_new_edition_with_another_year_stays_suspect(batch):
    b, tid = batch
    cand = candidate(b, tid, 0.70, "ГОСТ Р 51858-2020\n\nНЕФТЬ Общие технические условия", 20)
    upd = b.dup_verdict(tid, b.state.get(tid), cand)
    assert upd.get("status") != "dup" and upd["suspect"] == "N-00005"
    assert "51858-2020" in upd["suspect_why"] and "51858-2002" in upd["suspect_why"]


def test_new_edition_even_with_most_of_the_text_in_common(batch):
    b, tid = batch
    cand = candidate(b, tid, 0.95, "ГОСТ Р 51858-2020\n\nНЕФТЬ Общие технические условия", 20)
    upd = b.dup_verdict(tid, b.state.get(tid), cand)
    assert upd.get("status") != "dup" and upd["suspect"] == "N-00005"


def test_same_pages_and_most_phrases_is_a_duplicate(batch):
    b, tid = batch
    cand = candidate(b, tid, 0.95, "ГОСТ Р 51858-2002\n\nНЕФТЬ Общие технические условия", 21)
    upd = b.dup_verdict(tid, b.state.get(tid), cand)
    assert upd["status"] == "dup" and upd["dup_of"] == "N-00005"


@pytest.mark.parametrize("share, pages, why", [(0.70, 20, "less than 90%"), (0.95, 30, "30 pages here, 20 there")])
def test_partial_overlap_or_other_length_stays_suspect(batch, share, pages, why):
    b, tid = batch
    cand = candidate(b, tid, share, "НЕФТЬ Общие технические условия", pages)
    upd = b.dup_verdict(tid, b.state.get(tid), cand)
    assert upd.get("status") != "dup" and why in upd["suspect_why"]


def test_suspect_becomes_a_question_of_the_draft(batch):
    b, tid = batch
    (b.work / "md").mkdir()
    (b.work / "md" / f"{tid}.md").write_text(pages_md("НЕФТЬ", 3), encoding="utf-8")
    b.state.update(tid, status="done", suspect="N-00005", suspect_why="70% of the phrases match")
    metadraft.write_drafts(b.work, b.state)
    d = json.loads((b.work / "meta_draft.jsonl").read_text(encoding="utf-8"))
    assert any("N-00005" in q and "70% of the phrases match" in q for q in d["question"])


# ---------- scanned pages and broken encodings (work.prep) ----------

STAMP = "КОПИЯ ВЕРНА. Документ предоставлен для служебного пользования, распечатан из системы документооборота 2026."


def stamped_scan(path):
    """A scanned page (a full-page picture) with a stamp in its text layer: more than TEXT_PAGE characters."""
    scan_pdf(path)
    doc = pymupdf.open(path)
    doc[0].insert_text((40, 30), STAMP, fontsize=6, fontname="ru", fontfile=FONT)
    doc.saveIncr()
    return path


def job(tmp_path, src, ocr=True):
    return {
        "work": str(tmp_path / "work"),
        "tid": "T0001",
        "ext": "pdf",
        "src": str(src),
        "soffice": None,
        "ocr": ocr,
        "timeouts": {"soffice": 60, "hidden": 300, "convert": 600},
        "memory_mb": 3000,
        "env": {},
        "inproc": True,
    }


def test_scan_with_stamp_text_layer_is_a_scan(tmp_path):
    path = stamped_scan(tmp_path / "scan.pdf")
    page = pymupdf.open(path)[0]
    assert len(page.get_text().strip()) > intake_work.TEXT_PAGE  # the former rule took it for a text page
    assert intake_work.image_cover(page) > 0.95 and intake_work.scanned(page, page.get_text())
    res = intake_work.prep(job(tmp_path, path))
    assert res["scan_pages"] == [1] and res["ocr_pages"] == 1 and not res.get("imgocr")


def test_text_page_over_a_picture_is_no_scan(tmp_path):
    path = tmp_path / "text.pdf"
    text_pdf(path, ["\n".join([BODY] * 40)], size=7)
    doc = pymupdf.open(path)
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 50, 50), False)
    pix.clear_with(230)
    doc[0].insert_image(
        doc[0].rect, pixmap=pix, overlay=False, keep_proportion=False
    )  # a background picture under a page of text
    page = doc[0]
    assert intake_work.image_cover(page) > 0.95 and not intake_work.scanned(page, page.get_text())
    assert not intake_work.scanned(page, page.get_text(), by_area=False)
    blank = pymupdf.open().new_page()
    assert intake_work.image_cover(blank) == 0.0 and not intake_work.scanned(blank, "")


def test_broken_encoding_is_seen_before_conversion(tmp_path):
    garbled = BODY.encode("cp1251").decode("latin-1")  # "Íàñòîÿùèé": a Cyrillic code table read as Latin-1
    path = tmp_path / "broken.pdf"
    text_pdf(path, ["\n".join([garbled[i : i + 70] for i in range(0, len(garbled), 70)] * 4)] * 2, size=9)
    with pymupdf.open(path) as d:
        assert "letters are of no document language" in intake_work.broken_encoding(d)
    res = intake_work.prep(job(tmp_path, path))
    assert res["imgocr"] and "broken font encoding" in res["why"]
    assert res["pdf"].endswith(".img.pdf") and res["scan_pages"] == [1, 2]  # the page images go to OCR
    res = intake_work.prep(job(tmp_path, path, ocr=False))  # without Tesseract the text layer is all there is
    assert not res.get("imgocr")


def test_clean_text_is_no_broken_encoding(tmp_path):
    path = tmp_path / "clean.pdf"
    text_pdf(path, ["\n".join([BODY[:70], BODY[70:], "Oil and gas separators. General requirements."] * 6)] * 2, size=9)
    with pymupdf.open(path) as d:
        assert intake_work.broken_encoding(d) == ""


def test_scan_pages_are_read_again_when_conversion_did_not(tmp_path, monkeypatch):
    pdf = tmp_path / "doc.pdf"
    text_pdf(pdf, ["one", "two", "three"])
    cache = tmp_path / "cache"
    (cache / "T0001" / "ocr").mkdir(parents=True)
    (cache / "T0001" / "00001.json").write_text(json.dumps({"1": STAMP, "2": STAMP, "3": "текст " * 20}), encoding="utf-8")
    (cache / "T0001" / "ocr" / "00001.json").write_text(json.dumps({"1": {"conf": 90}}), encoding="utf-8")
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"T0001": {"parts": [[str(pdf), 1]], "ocr_pages": [1, 2]}}), encoding="utf-8")
    forced = []
    monkeypatch.setattr(reocr_empty, "run", lambda path, shift, pages, out: forced.extend(pages) or len(pages))
    reocr_empty.main([str(jobs), str(cache), "0"])
    assert forced == [1]  # page 2 (0-based 1): a scan the conversion read from its stamp only; page 1 had OCR


def test_text_layer_of_a_scan_kept_beside_its_ocr(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_score, "load_vocab", lambda path=None: (frozenset(), frozenset()))
    old, cache, out = tmp_path / "txt", tmp_path / "cache", tmp_path / "out"
    old.mkdir()
    (old / "T0001.txt").write_text(f"\n=== page 1 ===\n{STAMP}\n", encoding="utf-8")
    (cache / "T0001" / "ocr").mkdir(parents=True)
    ocr_text = "Давление насыщения нефти газом определяют по пробам пластовой нефти. " * 3
    (cache / "T0001" / "z_force_00001.json").write_text(json.dumps({"1": ocr_text}, ensure_ascii=False), encoding="utf-8")
    (cache / "T0001" / "ocr" / "z_force_00001.json").write_text(json.dumps({"1": {"conf": 90.0}}), encoding="utf-8")
    assemble_md.main([str(old), str(cache), str(out), "T0001"])
    text = (out / "T0001.md").read_text(encoding="utf-8")
    assert "Давление насыщения" in text and "КОПИЯ ВЕРНА" in text
    assert json.loads((out / "T0001.pages.json").read_text(encoding="utf-8"))["pages"]["1"]["source"] == "ocr"
