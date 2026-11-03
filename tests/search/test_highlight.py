# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The quote of a reference marked on its page and the references gathered into a folder (server/highlight.py):
only what the text layer of a page has is marked, the originals are not changed, a file there already is not
replaced without overwrite."""

import os

import pymupdf
import pytest

from assistant_x.server import highlight as hl

PAGE = (
    "4.4.18 The speed of gas shall be at most 7 m/s for low pressure pipelines, 15 m/s for medium pressure.<br>"
    "Table 1 - Speeds<br>Gas hydrocarbon in pipelines 5-20<br>Oil in pipelines 3"
)


def pdf(path, pages=2, scan=False):
    doc = pymupdf.open()
    for i in range(pages):
        p = doc.new_page()
        if scan:  # a scan: a picture, no text layer
            p.draw_rect(pymupdf.Rect(50, 50, 300, 120), fill=(0.5, 0.5, 0.5))
        else:
            p.insert_htmlbox(pymupdf.Rect(50, 50, 550, 300), PAGE + f"<br>{i + 1}")
    doc.save(path)
    doc.close()
    return str(path)


def test_a_quote_is_found_whole_in_parts_and_never_guessed(tmp_path):
    doc = pymupdf.open(pdf(tmp_path / "a.pdf"))
    page = doc[0]
    rects, status = hl.find(page, "The speed of gas shall be at most 7 m/s for low pressure pipelines")
    assert status == "marked" and rects
    rects, status = hl.find(page, "Gashydrocarbon in pipelines | 5-20")  # run together, a table row
    assert status == "marked" and len(rects) >= 2 and max(r.y1 for r in rects) - min(r.y0 for r in rects) < 40
    assert hl.find(page, "The speed of gas | a value the page has not")[1] == "partial"
    assert hl.find(page, "nothing of this is there") == ([], "none")
    scan = pymupdf.open(pdf(tmp_path / "s.pdf", scan=True))
    assert hl.find(scan[0], "The speed of gas") == ([], "none")


def test_the_references_of_an_answer():
    answer = (
        "Found: 2 documents.\n"
        "«Gas | 5-20» (table: Name | Speed) — [N-00001, cl. 6.2.1.9, table 1, PDF 36], GOST R 58367\n"
        "«At most 7 m/s.» — [N-02201, cl. 4.4.18, p. 15, PDF 135], SP RK\n"
        "Sources: [N-00001, PDF 36]; [E-00006-02, PDF 3]"
    )
    assert hl.references([answer]) == [
        ("N-00001", 36, "Gas | 5-20"),
        ("N-02201", 135, "At most 7 m/s."),
        ("N-00001", 36, ""),
        ("E-00006-02", 3, ""),
    ]


def test_a_folder_of_the_user_only(tmp_path):
    lib = tmp_path / "library"
    assert hl.safe_folder(str(tmp_path / "out"), [str(lib)]) == str(tmp_path / "out")
    for bad in ("relative\\out", str(lib / "x"), str(lib)):
        with pytest.raises(ValueError):
            hl.safe_folder(bad, [str(lib)])


def test_the_files_and_one_pdf_of_the_pages_cited(tmp_path):
    src = pdf(tmp_path / "N-00001_gost.pdf")
    before = open(src, "rb").read()
    out = tmp_path / "out"
    refs = [("N-00001", 1, "Gas hydrocarbon in pipelines | 5-20"), ("N-00001", 2, "not on the page"), ("N-00009", 1, "")]

    def originals(code):
        return (src, None) if code == "N-00001" else (None, f"No document {code} in the catalog.")

    args = (str(out), refs, originals, lambda c, p, q: f"<b>[{c}, PDF {p}]</b> Title", "References")
    marks = {"none": "not marked", "partial": "in part"}
    got = hl.export(*args, marks)
    assert got["files"] == [str(out / "N-00001_gost.pdf")] and got["marked"] == 1 and got["none"] == 1
    assert got["missing"] == ["N-00009: No document N-00009 in the catalog."] and open(src, "rb").read() == before
    book = pymupdf.open(got["pdf"])
    assert book.page_count == 2 and "[N-00001, PDF 1]" in book[0].get_text() and "not marked" in book[1].get_text()
    assert book[0].get_drawings() and os.path.basename(got["pdf"]).startswith("References — ")
    book.close()
    again = hl.export(*args, marks)
    assert again["exists"] and not again["files"] and again["pdf"] is None
    assert hl.export(*args, marks, overwrite=True)["pdf"] == got["pdf"]
