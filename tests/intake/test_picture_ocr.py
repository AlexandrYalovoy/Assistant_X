# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The picture on a text page is read once (audit 7, M-043, M-020): one sparse reading, no orientation check and no
retries, kept only when it adds words the text layer lacks; a scan page keeps its retries. A page with a picture costs
more in the order of the work, and the OCR seconds of a file show in the status."""

import json

import pymupdf

from assistant_x.intake import review, schedule
from assistant_x.intake.state import State
from assistant_x.intake.tools import ocr_page
from assistant_x.server import intake_tools
from tests.corpus import documents
from tests.intake.intake_fixtures import FONT

LABELS = "Вход газа Выход нефти Дренаж воды Сброс давления Узел учета Линия факела Насос откачки Клапан предохранительный"


def _fake(monkeypatch, text, conf, tmp=None):
    calls = []
    monkeypatch.setenv("TESSDATA_PREFIX", str(tmp or "."))  # no Tesseract here: PyMuPDF only looks for its data

    def recognise(png, dpi, language, tmp, tag, psm=None):
        calls.append((tag, psm))
        words = [(10 + 60 * i, 10, 50, 20, w, (1, 1, 1)) for i, w in enumerate(text.split())]
        return {
            "words": words,
            "size": (2480, 3508),
            "text": text,
            "plain": text,
            "m": ocr_page.measure(text, [conf] * len(words)),
        }

    monkeypatch.setattr(ocr_page, "recognise", recognise)
    monkeypatch.setattr(ocr_page, "orientation", lambda *a, **k: calls.append(("osd", None)) or (0, 0.0))
    ocr_page.reset()
    ocr_page.DOCS.clear()
    return calls


def _figure_page():
    doc = pymupdf.open()
    page = documents.picture_page(doc, documents.SCAN_TEXT)  # the picture
    page.insert_textbox(
        pymupdf.Rect(56, 600, 540, 800), " ".join(documents.sentences(801, 2)), fontsize=11, fontname="ru", fontfile=FONT
    )
    return doc, page


def test_a_figure_on_a_text_page_is_read_once(monkeypatch):
    doc, page = _figure_page()
    calls = _fake(monkeypatch, LABELS, 40.0)  # weak: a scan page would be read again
    monkeypatch.setattr(ocr_page, "SCAN_PAGES", set())
    ocr_page.exec_ocr(page)
    assert calls == [("v0", 11)]
    st = ocr_page.STATS[0]
    assert st["layer"] == "added" and ocr_page.MIN_WORDS <= st["added"] < len(LABELS.split())  # less the layer's words


def test_a_figure_of_few_new_words_is_dropped(monkeypatch):
    doc, page = _figure_page()
    calls = _fake(monkeypatch, "Рис 1 схема", 90.0)
    monkeypatch.setattr(ocr_page, "SCAN_PAGES", set())
    ocr_page.exec_ocr(page)
    assert len(calls) == 1 and ocr_page.STATS[0]["layer"] == "kept" and 0 not in ocr_page.PLAIN


def test_a_weak_scan_page_is_still_tried_again(monkeypatch):
    doc = pymupdf.open()
    page = documents.picture_page(doc, documents.SCAN_TEXT)
    calls = _fake(monkeypatch, documents.SCAN_TEXT, 40.0)
    monkeypatch.setattr(ocr_page, "SCAN_PAGES", {0})
    ocr_page.exec_ocr(page)
    assert ("osd", None) in calls and len([c for c in calls if c[0] != "osd"]) == 3  # the first reading and two retries


def test_a_picture_page_costs_more():
    assert schedule.cost(10, 0, 4) == 10 * schedule.TEXT_SECONDS + 4 * schedule.PICTURE_SECONDS
    assert schedule.cost(10, 10, 4) == 10 * schedule.SCAN_SECONDS  # a scan page is no picture page as well


def test_ocr_seconds_in_the_status(tmp_path):
    st = State(tmp_path / "state.sqlite")
    a, b = st.add("a.pdf", 1), st.add("b.pdf", 1)
    st.update(a, status="done", ocr_seconds=40.4)
    st.update(b, status="running", stage="convert", active=True)
    (tmp_path / "cache" / b / "ocr").mkdir(parents=True)
    (tmp_path / "cache" / b / "ocr" / "00001.json").write_text(json.dumps({"1": {"seconds": 2.5}, "2": {"seconds": 3}}))
    data = review.status_data(tmp_path, st)
    assert data["ocr_seconds"] == 40 and data["running"][0]["ocr_seconds"] == 6
    words = intake_tools.batch_words(data)
    assert "(OCR 40 s)" in words and "OCR 6 s" in words
    st.close()
