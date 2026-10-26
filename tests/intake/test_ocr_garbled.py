# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Garbled recognition (audit 6, M-015) and a shifted text layer (M-007): the seed vocabulary of an open dictionary
judges the words of a new library, glued and repeated tokens are errors, a page of garbage gets the flag "garbled"
(listed by the quality report, weighed less by the search); a text layer off the page box is one line, not hidden."""

import json

import pymupdf

from assistant_x.core import lang
from assistant_x.intake import quality_report, work as intake_work
from assistant_x.intake.tools import hidden, ocr_score
from assistant_x.search.retrieval import page_note

NOTHING = (frozenset(), frozenset())


def test_the_seed_is_an_open_dictionary():
    assert len(lang.vocab("ru")) + len(lang.vocab_stems("ru")) >= ocr_score.SEED_FULL
    assert "ru" in ocr_score.seeded() and ocr_score.judged_by_vocab(NOTHING, "давление")
    head = (lang.LANG_DIR / "ru" / "vocab.txt").read_text(encoding="utf-8").splitlines()[:3]
    assert any("Lebedev" in x for x in head)  # the notice its license asks to keep


def test_glued_and_repeated_tokens():
    assert ocr_score.glued("газгаз")  # a piece read twice
    assert not ocr_score.glued("кукуруза")
    assert ocr_score.glued("установкаосушкигазаводы", True, NOTHING)  # known words glued together
    assert not ocr_score.glued("установкаосушкигазаводы", False, NOTHING)  # not judged: a compound is a word
    assert not ocr_score.glued("сепарация", True, NOTHING)  # short: never a glued one


def test_an_unknown_word_is_half_an_error_by_the_seed_alone():
    n, bad, _ = ocr_score.word_counts("давление нефти qwzrtx", NOTHING)
    assert (n, bad) == (3, ocr_score.SEED_ONLY)
    library = (frozenset(f"w{i}x" for i in range(ocr_score.MIN_VOCAB_WORDS)), frozenset())
    assert ocr_score.word_counts("давление нефти qwzrtx", library)[1] == 1  # the library's vocabulary: a whole error
    assert ocr_score.word_counts("газгаз давление", NOTHING)[1] == 1  # a repeat is a whole error anyway


def test_garbled_page_flag(tmp_path):
    from assistant_x.core.formats import read_pages_info, write_pages_info

    good = " ".join(["Давление насыщения нефти газом определяют по таблице"] * 6)
    bad = " ".join(["газгаз qwzrtx bluvtap ывапр"] * 8)
    md = f"=== page 1 ===\n\n{good}\n\n=== page 2 ===\n\n{bad}\n"
    (tmp_path / "md").mkdir()
    write_pages_info(tmp_path / "md" / "T0001.pages.json", {1: {"flags": []}, 2: {"flags": []}})
    res = intake_work.ocr_measures(tmp_path, "T0001", md)
    assert res["ocr_garbled_pages"] == 1
    info = read_pages_info(tmp_path / "md" / "T0001.pages.json")
    assert info[2]["flags"] == ["garbled"] and info[1]["flags"] == []
    assert "garbled recognition" in page_note(95, "garbled")
    from assistant_x.search import retrieval

    assert retrieval.GARBLED_WEIGHT < 1  # its fragments weigh less in the search


def test_quality_report_lists_garbled_pages_under_a_good_mean():
    m = {"pages": 100, "no_ocr_pages": 0, "fffd_per_1000": 0, "fffd": 0, "empty_pages": 0, "ocr_share": 1.0, "letters": {}}
    m.update(ocr_score=88, ocr_low_pages=0, ocr_garbled_pages=7, fallback=0)
    assert any("7 pages with garbled recognition" in p[0] for p in quality_report.problems(m))


def _shifted_pdf(path, words=60, inside=()):
    doc = pymupdf.open()
    page = doc.new_page()
    for i in range(words):  # a text layer off the page box: every word above the page
        page.insert_text((20 + (i % 10) * 50, -50 - (i // 10) * 15), f"слово{i}", fontsize=10, fontname="helv")
    for k, t in enumerate(inside):
        page.insert_text((60, 100 + 20 * k), t, fontsize=12, fontname="helv")
    doc.save(path)


def test_a_shifted_text_layer_is_one_line_and_no_hidden_text(tmp_path, capsys):
    pdf, rep, clean = tmp_path / "a.pdf", tmp_path / "a.json", tmp_path / "a.clean.pdf"
    _shifted_pdf(pdf)
    hidden.main([str(pdf), "--clean", str(clean), "--json", str(rep)])
    r = json.loads(rep.read_text(encoding="utf-8"))
    assert r["hidden"] == 0 and r["shifted_pages"] == [1] and r["shifted"]["1"]["spans"] == 60
    assert not clean.exists()  # no copy made for a shifted layer alone
    assert capsys.readouterr().out.count(hidden.SHIFTED_WHY) == 1


def test_a_few_words_off_the_page_stay_hidden(tmp_path):
    pdf, rep = tmp_path / "b.pdf", tmp_path / "b.json"
    _shifted_pdf(pdf, words=2, inside=[f"Normal text line {i}" for i in range(10)])
    hidden.main([str(pdf), "--json", str(rep)])
    r = json.loads(rep.read_text(encoding="utf-8"))
    assert r["hidden"] == 2 and "shifted_pages" not in r


def test_the_report_keeps_200_spans(tmp_path, monkeypatch):
    pdf, rep = tmp_path / "c.pdf", tmp_path / "c.json"
    doc = pymupdf.open()
    for _ in range(3):
        page = doc.new_page()
        for i in range(90):  # tiny text: hidden, and not a shifted layer
            page.insert_text((20 + (i % 10) * 50, 60 + (i // 10) * 20), f"w{i}", fontsize=1, fontname="helv")
    doc.save(pdf)
    hidden.main([str(pdf), "--json", str(rep)])
    r = json.loads(rep.read_text(encoding="utf-8"))
    assert r["hidden"] == 270 and sum(len(v) for v in r["found"].values()) == hidden.MAX_SPANS
