# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The text format "AX text 1" (core/formats.py, docs/INTAKE.md): escaped markers, LF, NFC, the dehyphenation of OCR
pages by the vocabulary, <code>.pages.json with the source, score, label and flags of every page (assemble_md.py)."""

import json, unicodedata

import pymupdf
import pytest

from assistant_x.core.common import dehyphenate, join_hyphens, split_pages
from assistant_x.core.formats import (
    PAGES_SUFFIX,
    escape_marker,
    pages_path,
    read_pages_info,
    unescape_text,
    write_pages_info,
)
from assistant_x.intake.tools import assemble_md, ocr_score


@pytest.mark.parametrize("line", ["=== page 3 ===", "\\=== page 3 ===", "\\\\=== page 12 ===", "=== page 3 === "])
def test_escape_round_trip(line):
    body = f"before\n{line}\nafter"
    written = escape_marker(body)
    assert written.splitlines()[1] == "\\" + line  # one backslash more
    assert unescape_text(written) == body
    assert split_pages(f"=== page 1 ===\n{written}\n=== page 2 ===\nnext\n") == [(1, f"\n{body}\n"), (2, "\nnext\n")]


def test_escape_leaves_other_lines():
    for text in ("=== page three ===", "text === page 3 ===", "## page 3", "\\ backslash"):
        assert escape_marker(text) == text and unescape_text(text) == text


def test_dehyphenate_with_and_without_vocabulary():
    text = "газовый сепара-\nтор и нефте-\nгазовый трубо-\n  провод"
    assert dehyphenate(text, {"сепаратор", "трубопровод"}) == "газовый сепаратор и нефте-\nгазовый трубопровод"
    assert dehyphenate(text, set()) == text and dehyphenate(text, None) == text  # a new library: no vocabulary
    assert dehyphenate("Ёлка-\nми", {"елками"}) == "Ёлками"  # the vocabulary is folded (yo as ye), the word stays as it is
    assert dehyphenate("10-\n20", {"1020"}) == "10-\n20"  # numbers are no words


def test_dehyphenate_a_word_left_on_one_line():
    """A converter joins the lines of a paragraph and leaves «забрако- ваны»: joined as the line end break is, when the
    vocabulary knows the word; a suspended compound («нефте- и газо-») and an unknown join stay."""
    known = {"забракованы", "сепаратор"}
    assert dehyphenate("должны быть забрако- ваны или", known) == "должны быть забракованы или"
    assert dehyphenate("нефте- и газопроводы", known | {"нефтеи"}) == "нефте- и газопроводы"
    assert dehyphenate("Урало- поволжский", known) == "Урало- поволжский"  # the vocabulary does not know it
    assert dehyphenate("сепара- тор и сепара-\nтор", known) == "сепаратор и сепаратор"


def test_join_hyphens_without_vocabulary():
    assert join_hyphens("забрако- ваны, ЗАБРАКО- ВАНЫ") == "забракованы, ЗАБРАКОВАНЫ"
    assert join_hyphens("нефте- и газо-, pre- and post-processing") == "нефте- и газо-, pre- and post-processing"
    assert join_hyphens("ГОСТ 1.0- 2012, слово - слово, А- Б") == "ГОСТ 1.0- 2012, слово - слово, А- Б"
    assert join_hyphens("Нефте- Газовый") == "Нефте- Газовый"  # a capital after a lower-case part: two words


def labelled_pdf(path, pages, first=None):
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    if first is not None:
        doc.set_page_labels([{"startpage": 0, "prefix": "", "style": "D", "firstpagenum": first}])
    doc.save(path)
    return str(path)


@pytest.fixture
def converted(tmp_path, monkeypatch):
    """A converted document T0001 of five pages as convert_md leaves it: the text layer, the Markdown cache, the OCR
    measures of page 2, a jobs.json with a PDF with page labels from 217."""
    monkeypatch.setattr(ocr_score, "load_vocab", lambda path=None: (frozenset({"сепаратор"}), frozenset()))
    old, cache, out = tmp_path / "txt", tmp_path / "cache", tmp_path / "out"
    old.mkdir()
    layer = {
        1: "layer one",
        2: "",
        3: "Таблица слоя\n| A | B |\n|---|---|\n| 1 | 2 |",
        4: "Текст слоя страницы четыре.",
        5: "Формула расхода\nQ = k · F (12)",
    }
    (old / "T0001.txt").write_text(
        "".join(f"\n=== page {n} ===\n{escape_marker(t)}\n" for n, t in layer.items()), encoding="utf-8"
    )
    md = {
        1: "# Глава\n\nCafe\u0301 и мягкий\u00adперенос\u200b.\n=== page 7 ===\n| Шапка | Две |\n|---|---|\n"
        "| объединённая ячейка |\n",
        2: "газовый сепара-\nтор и нефте-\nгазовый отбойник распознанный по картинке страницы",
        4: "\ufffd\ufffd\ufffd \ufffd\ufffd",  # a broken font: the text layer is taken instead
        5: "Формула расхода\n\nQ = k · F (12)",
    }
    (cache / "T0001" / "ocr").mkdir(parents=True)
    (cache / "T0001" / "00001.json").write_text(json.dumps(md, ensure_ascii=False), encoding="utf-8")
    (cache / "T0001" / "ocr" / "00001.json").write_text(
        json.dumps({"2": {"conf": 90.0, "low": 0.0, "tokens": 10}}), encoding="utf-8"
    )
    jobs = tmp_path / "jobs.json"
    jobs.write_text(
        json.dumps(
            {"T0001": {"parts": [[str(tmp_path / "none.pdf"), 1]], "label_pdf": labelled_pdf(tmp_path / "src.pdf", 5, 217)}}
        ),
        encoding="utf-8",
    )
    assemble_md.main([str(old), str(cache), str(out), "--jobs", str(jobs), "T0001"])
    return out


def test_assembled_text_is_lf_nfc_and_escaped(converted):
    raw = (converted / "T0001.md").read_bytes()
    assert b"\r\n" not in raw  # LF on Windows too
    text = raw.decode("utf-8")
    assert unicodedata.is_normalized("NFC", text) and "Café" in text and "\u200b" not in text
    assert "мягкий-перенос" in text  # the soft hyphen of the OCR font: a hyphen on every page
    assert "\n\\=== page 7 ===\n" in text  # the marker inside the body is escaped
    pages = split_pages(text)
    assert [n for n, _ in pages] == [1, 2, 3, 4, 5]
    assert "\n=== page 7 ===\n" in pages[0][1]  # and given back by the search as it is
    assert "газовый сепаратор и нефте-\nгазовый" in pages[1][1]  # joined only where the vocabulary knows the word
    assert "Текст слоя страницы четыре." in pages[3][1]
    report = json.loads((converted / "_report.json").read_text(encoding="utf-8"))["T0001"]
    assert report["pages"] == 5 and report["old_text"] == 1 and report["fallback_pages"] == [4]


def test_pages_json(converted):
    info = read_pages_info(converted / f"T0001{PAGES_SUFFIX}")
    assert json.loads((converted / f"T0001{PAGES_SUFFIX}").read_text(encoding="utf-8"))["format"] == 1
    assert {n: p["source"] for n, p in info.items()} == {1: "markdown", 2: "ocr", 3: "layer", 4: "fallback", 5: "markdown"}
    assert {n: p["label"] for n, p in info.items()} == {1: "217", 2: "218", 3: "219", 4: "220", 5: "221"}
    assert info[1]["flags"] == ["complex_table"] and info[3]["flags"] == [] and info[5]["flags"] == ["formula"]
    assert all(p["ocr_score"] is not None for n, p in info.items() if n != 3)
    assert set(info[1]) == {"source", "ocr_score", "label", "flags"}


def test_no_labels_without_page_labels(tmp_path):
    assert assemble_md.labels({"label_pdf": labelled_pdf(tmp_path / "plain.pdf", 2)}) == {}
    assert assemble_md.labels(
        {"parts": [[labelled_pdf(tmp_path / "a.pdf", 2, 5), 1], [labelled_pdf(tmp_path / "b.pdf", 1, 1), 3]]}
    ) == {1: "5", 2: "6", 3: "1"}
    assert assemble_md.labels({"label_pdf": str(tmp_path / "missing.pdf")}) == {}  # no failure of the text
    assert assemble_md.labels({}) == {}


def test_pages_info_written_and_read(tmp_path):
    p = pages_path(tmp_path / "N-00001.md")
    assert p.endswith("N-00001.pages.json")
    write_pages_info(
        p,
        {
            10: {"source": "layer", "ocr_score": None, "label": None, "flags": []},
            2: {"source": "ocr", "ocr_score": 83.5, "label": "ii", "flags": ["formula"]},
        },
    )
    assert list(json.loads(open(p, encoding="utf-8").read())["pages"]) == ["2", "10"]  # in page order
    assert read_pages_info(p)[2] == {"source": "ocr", "ocr_score": 83.5, "label": "ii", "flags": ["formula"]}
    open(p, "w", encoding="utf-8").write("{broken")
    assert read_pages_info(p) is None and read_pages_info(tmp_path / "none.pages.json") is None


def test_complex_table_flag():
    assert not assemble_md.complex_table("| a | b |\n|---|---|\n| 1 | 2 |\n\ntext\n| c |\n|---|\n| 3 |")
    assert assemble_md.complex_table("| a | b | c |\n|---|---|---|\n| merged | 2 |")


def test_a_stamp_in_a_legacy_code_page_shown_as_latin1_is_read_back():
    """Trial batch b086: a CAD export put the stamp of its sheets in its text layer in cp1251 read as Latin-1
    ("Ïðèëîæåíèå 13.2.9.1.ÒÒÒ-01.02-32.Ñ2"), 105 documents. The words come back; Western words stay as they are."""
    from assistant_x.intake.tools.assemble_md import mend_latin1

    assert mend_latin1("# Ïðèëîæåíèå 13.2.9.1.ÒÒÒ-01.02-32.Ñ2") == "# Приложение 13.2.9.1.ТТТ-01.02-32.С2"
    assert mend_latin1("Größe für été, Ñ2") == "Größe für été, Ñ2"
    assert mend_latin1("Ãàç íà ãîðåëêó\nÑ2 é") == "Газ на горелку\nÑ2 é"  # another line keeps its letters
    assert mend_latin1("Ñêâàæèíà ¹ 60808, ¸ìêîñòü") == "Скважина № 60808, ёмкость"
    assert mend_latin1("x² = 5 ¹") == "x² = 5 ¹"
