# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The visible text layer of a scan is kept (audit 7, M-040): a page with a legible layer is read once and its
recognition dropped when the layer already has its words, else only the words the layer lacks are added; a page whose
every phrase appears twice gets the flag "doubled", the quality report lists it, the search weighs it less, and
intake redo accepts a text that is no longer doubled."""

import json

import pymupdf

from assistant_x.core.formats import read_pages_info, write_pages_info
from assistant_x.intake import ocr_redo, quality_report, work as intake_work
from assistant_x.intake.tools import assemble_md, convert_md, ocr_page, ocr_score
from tests.corpus import documents
from tests.intake.intake_fixtures import FONT

LAYER = documents.sentences(701, 4)
CAPTION = "Рисунок 5 Общий вид блочной установки комплексной подготовки продукции с узлом учета"


def _layer_scan(path, picture_lines, shift=4):
    """A page that is a picture of picture_lines with a visible text layer of LAYER put a little off the glyphs."""
    doc = pymupdf.open()
    page = documents.picture_page(doc, "\n".join(picture_lines))
    page.insert_textbox(
        pymupdf.Rect(56 + shift, 56 + shift, 540, 800), "\n".join(LAYER), fontsize=14, fontname="ru", fontfile=FONT
    )
    doc.save(path)


def _fake_recognise(lines):
    """recognise() that reads the given lines (a box for every word, one line each)."""

    def recognise(png, dpi, language, tmp, tag, psm=None):
        calls.append(psm)
        words = []
        for k, line in enumerate(lines):
            for i, w in enumerate(line.split()):
                words.append((100 + 120 * i, 100 + 60 * k, 100, 40, w, (1, 1, k)))
        text = "\n".join(lines)
        return {
            "words": words,
            "size": (2480, 3508),
            "text": text,
            "plain": text,
            "m": ocr_page.measure(text, [95.0] * len(words)),
        }

    calls = []
    recognise.calls = calls
    return recognise


def _convert(tmp_path, monkeypatch, pdf, read):
    monkeypatch.setattr(ocr_page, "tesseract_exe", lambda: "tesseract")
    monkeypatch.setenv("TESSDATA_PREFIX", str(tmp_path))  # no Tesseract here: PyMuPDF only looks for its data
    rec = _fake_recognise(read)
    monkeypatch.setattr(ocr_page, "recognise", rec)
    monkeypatch.setattr(ocr_page, "orientation", lambda *a, **k: (0, 0.0))
    ocr_page.DOCS.clear()
    cache, out, old = tmp_path / "cache", tmp_path / "md", tmp_path / "old"
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"T0001": {"parts": [[str(pdf), 1]]}}), encoding="utf-8")
    convert_md.main([str(jobs), str(cache), "0"])
    old.mkdir()
    (old / "T0001.txt").write_text("=== page 1 ===\n\n" + "\n".join(LAYER) + "\n", encoding="utf-8")
    assemble_md.main([str(old), str(cache), str(out), "T0001"])
    return (out / "T0001.md").read_text(encoding="utf-8"), read_pages_info(out / "T0001.pages.json"), rec.calls


def test_the_layer_of_a_scan_is_kept(tmp_path, monkeypatch):
    pdf = tmp_path / "a.pdf"
    _layer_scan(pdf, LAYER)
    md, info, calls = _convert(tmp_path, monkeypatch, pdf, LAYER)
    for s in LAYER:
        assert md.count(s[:40]) == 1, s
    assert info[1]["layer"] == "kept" and info[1]["source"] == "markdown"
    assert len(calls) == 1  # one reading: no orientation check, no retries


def test_only_the_words_the_layer_lacks_are_added(tmp_path, monkeypatch):
    pdf = tmp_path / "b.pdf"
    _layer_scan(pdf, LAYER + [CAPTION])
    md, info, _ = _convert(tmp_path, monkeypatch, pdf, [CAPTION] + LAYER[:1])
    assert md.count("комплексной подготовки") == 1 and md.count(LAYER[0][:40]) == 1
    assert info[1]["layer"] == "added"


def test_new_words_beside_the_layer():
    words = [(0, 0, 1, 1, w, 1) for w in ("Давление", "нефти", "Рисунок", "5")]
    assert [w[4] for w in ocr_page.new_words(words, {"давление", "нефти"})] == ["Рисунок", "5"]


def test_a_doubled_page_is_flagged_and_listed(tmp_path):
    once = " ".join(documents.sentences(702, 6))
    doubled = " ".join(s + " " + s for s in documents.sentences(703, 6))
    assert ocr_score.repeated(once) < 0.1 and ocr_score.repeated(doubled) >= ocr_score.DOUBLED
    md = f"=== page 1 ===\n\n{once}\n\n=== page 2 ===\n\n{doubled}\n"
    (tmp_path / "md").mkdir()
    write_pages_info(tmp_path / "md" / "T0001.pages.json", {1: {"flags": []}, 2: {"flags": []}})
    res = intake_work.ocr_measures(tmp_path, "T0001", md)
    assert res["ocr_doubled_pages"] == 1
    assert read_pages_info(tmp_path / "md" / "T0001.pages.json")[2]["flags"] == ["doubled"]
    m = {"pages": 2, "no_ocr_pages": 0, "fffd_per_1000": 0, "fffd": 0, "empty_pages": 0, "ocr_share": 0, "letters": {}}
    m.update(ocr_score=90, ocr_low_pages=0, ocr_garbled_pages=0, ocr_doubled_pages=1, fallback=0)
    assert ("re-extract the text", "high") in [p[1:] for p in quality_report.problems(m)]
    from assistant_x.search.retrieval import page_note

    assert "twice" in page_note(95, "doubled")


def test_consecutive_repeats_are_dropped():
    s = "Давление насыщения нефти определяют по пробам."
    assert assemble_md.drop_repeats(f"{s}\n{s}\nДругая строка текста здесь") == f"{s}\nДругая строка текста здесь"
    assert assemble_md.drop_repeats(f"{s} {s} Конец.") == f"{s} Конец."
    assert assemble_md.drop_repeats("| да | да | да |\n| да | да | да |").count("да") == 6  # table rows stay
    assert assemble_md.drop_repeats("Да нет.\nДа нет.") == "Да нет.\nДа нет."  # too short to tell


def test_redo_accepts_a_text_no_longer_doubled(tmp_path):
    clean = [" ".join(documents.sentences(704 + i, 3)) for i in range(8)]
    old = "".join(f"=== page {i} ===\n\n{s} {s}\n\n" for i, s in enumerate(clean, 1))
    new = "".join(f"=== page {i} ===\n\n{s}\n\n" for i, s in enumerate(clean, 1))
    (tmp_path / "X-00001.md").write_text(old, encoding="utf-8")
    r = {
        "code": "X-00001",
        "old": ocr_redo.words_score(old),
        "new": ocr_redo.words_score(new),
        "known": ocr_redo.known_words(new),
        "old_known": ocr_redo.known_words(old),
        "pages": 8,
        "variant": "pipeline",
        "old_doubled": ocr_redo.doubling(old),
        "doubled": ocr_redo.doubling(new),
    }
    assert r["old_doubled"][0] == 1.0 and r["doubled"][0] == 0.0
    assert ocr_redo.verdict(r, tmp_path, 10).startswith("recognized again: text replaced — no longer doubled")
    r["doubled"] = r["old_doubled"]
    assert "text kept" in ocr_redo.verdict(r, tmp_path, 10)
