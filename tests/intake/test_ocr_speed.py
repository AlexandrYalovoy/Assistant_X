# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The faster OCR keeps its outputs: the orientation sampled on the first pages of a document, the retry variant chosen
per document, the first reading of the scanned pages of a chunk in one Tesseract process, chunks of text and of scans,
no hidden text check of a PDF of page images."""

import os

import pymupdf
import pytest

from assistant_x.intake import work as intake_work
from assistant_x.intake.tools import convert_md, ocr_page
from tests.corpus import documents
from tests.intake.intake_fixtures import text_pdf


def test_orientation_sample_agrees_or_not():
    st = {"osd": [(0, 20.0)] * 4, "wins": []}
    assert ocr_page.sampled_turn(st) is None  # four pages are no sample yet
    st["osd"].append((0, 12.5))
    assert ocr_page.sampled_turn(st) == (0, 12.5)
    st["osd"][2] = (90, 30.0)
    assert ocr_page.sampled_turn(st) is None  # the sample disagrees: every page is checked itself


def test_retry_variant_chosen_per_document():
    assert ocr_page.retry_choice({"wins": ["bw"] * 9}) is None
    assert ocr_page.retry_choice({"wins": ["bw"] * 7 + ["dpi", "", ""]}) == "bw"
    assert ocr_page.retry_choice({"wins": ["dpi"] * 6 + ["bw"] * 4}) is None
    assert [ocr_page.win_kind(k) for k in ("400", "400 rotate 90", "b/w", "b/w rotate 90", "300", "rotate 90")] == [
        "dpi",
        "dpi",
        "bw",
        "bw",
        "",
        "",
    ]


def test_doc_state_keeps_a_few_documents():
    ocr_page.DOCS.clear()
    for i in range(10):
        ocr_page.doc_state(f"d{i}")["osd"].append((0, 1.0))
    assert len(ocr_page.DOCS) == 8 and "d9" in ocr_page.DOCS and "d0" not in ocr_page.DOCS


def test_tsv_of_a_list_of_images_splits_by_page():
    head = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
    rows = [
        head,
        "1\t1\t0\t0\t0\t0\t0\t0\t10\t10\t-1\t",
        "5\t1\t1\t1\t1\t1\t1\t1\t5\t5\t91.0\tнефть",
        "5\t2\t1\t1\t1\t1\t1\t1\t5\t5\t88.0\tгаз",
    ]
    pages = ocr_page.split_tsv("\n".join(rows))
    assert sorted(pages) == [1, 2] and pages[1].splitlines()[0] == head
    assert ocr_page.parse_tsv(pages[2])[0] == "газ" and ocr_page.parse_tsv(pages[1])[1] == [91.0]


def test_chunks_of_text_and_of_scans():
    assert convert_md.chunks(120, set()) == [list(range(0, 50)), list(range(50, 100)), list(range(100, 120))]
    got = convert_md.chunks(14, {3, 4, 5, 6, 7, 8, 9})
    assert got == [[0, 1, 2], [3, 4, 5, 6, 7], [8, 9], [10, 11, 12, 13]]


def test_no_hidden_check_for_page_images(tmp_path):
    scan = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    documents.picture_page(doc, documents.SCAN_TEXT)
    doc.save(scan)
    text = tmp_path / "text.pdf"
    text_pdf(text, ["Текст страницы"])
    assert not intake_work.has_text_layer(scan) and intake_work.has_text_layer(text)
    job = {
        "work": str(tmp_path / "w"),
        "tid": "T0001",
        "ext": "pdf",
        "src": str(scan),
        "soffice": None,
        "ocr": False,
        "timeouts": {"soffice": 60, "hidden": 300, "convert": 600},
        "memory_mb": 3000,
        "env": dict(os.environ),
        "inproc": True,
    }
    res = intake_work.prep(job)
    assert res["status"] == "prepped" and res["hidden"] == 0 and not (tmp_path / "w" / "log" / "T0001.hidden.json").exists()


@pytest.mark.slow
def test_batched_reading_is_the_page_by_page_one(tmp_path, monkeypatch):
    from assistant_x.intake import config as intake_cfg

    exe = intake_cfg.find_tesseract()
    if not exe:
        pytest.skip("no Tesseract")
    data = intake_cfg.find_tessdata(None, exe)
    monkeypatch.setenv("TESSERACT", exe)
    monkeypatch.setenv("TESSDATA_PREFIX", data)
    monkeypatch.setenv("PATH", os.path.dirname(exe) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setattr(ocr_page, "_tess", None)
    pdf = tmp_path / "s.pdf"
    doc = pymupdf.open()
    for i in range(3):
        documents.picture_page(doc, "\n".join(documents.sentences(300 + i, 5)), seed=i)
    doc.save(pdf)
    ocr_page.DOCS.clear()
    one, s1 = convert_md.markdown(str(pdf), 0, [0, 1, 2], False, True, None)
    convert_md.close_all()
    ocr_page.DOCS.clear()
    batched, s2 = convert_md.markdown(str(pdf), 0, [0, 1, 2], False, True, {0, 1, 2})
    convert_md.close_all()
    assert batched == one and all(s1[k]["tried"] == s2[k]["tried"] for k in s1)
