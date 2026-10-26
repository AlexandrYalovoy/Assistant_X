# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Text helpers: pages, fragments, the catalog made from the cards, the rows of a card and of its parts, the contents
and the links of the cards."""

import os

from assistant_x.core import card as C
from assistant_x.core.common import split_pages, chunk_page, chunk_doc, chunk_search_text, ocr_share, read_ocr_scores
from assistant_x.search import catalog
from assistant_x.search.build_index import doc_rows, link_rows, load_cards, toc_rows


def test_split_pages():
    assert split_pages("=== page 1 ===\nа\n=== page 2 ===\nб\n") == [(1, "\nа\n"), (2, "\nб\n")]
    assert split_pages("no markers") == []
    # a line of a body that reads as a marker is escaped in the file (AX text 1) and given back as it is
    assert split_pages("=== page 1 ===\nа\n\\=== page 9 ===\nб\n=== page 2 ===\nв\n") == [
        (1, "\nа\n=== page 9 ===\nб\n"),
        (2, "\nв\n"),
    ]


def texts(page):
    """The search texts of the fragments of a page."""
    return [chunk_search_text(page, *c) for c in chunk_page(page)]


def test_table_stays_one_fragment():
    table = "| A | B |\n|---|---|\n" + "".join(f"| {i} | {i * 2} |\n" for i in range(120))
    chunks = texts("Вступление к таблице.\n\n" + table + "\nПосле таблицы.")
    assert 900 < len(table) <= 2000 and any(table.strip() in c for c in chunks)


def test_long_table_is_cut_by_rows_with_its_header():
    rows = [f"| {i} | значение {i * 2} |" for i in range(400)]
    table = "| A | B |\n|---|---|\n" + "\n".join(rows)
    chunks = texts(table)
    assert len(table) > 4000 and len(chunks) > 2 and all(len(c) <= 1800 for c in chunks)
    assert all(c.startswith("| A | B |\n|---|---|\n") for c in chunks)
    assert [r for c in chunks for r in c.splitlines()[2:]] == rows  # every row once, in order
    # the repeated header leads the search text only: the page holds it once
    offsets = chunk_page(table)
    assert offsets[0][2] is None and all(lead == "| A | B |\n|---|---|" for _, _, lead in offsets[1:])
    assert not any(table[s:e].startswith("| A |") for s, e, _ in offsets[1:])


def test_long_ocr_text_is_split_with_overlap():
    text = "\n".join(f"Строка распознанного текста номер {i} без пустых строк." for i in range(200))
    chunks = texts(text)
    assert len(chunks) > 3
    assert all(len(c) <= 1800 for c in chunks)
    lines = [l for c in chunks for l in c.splitlines()]
    assert set(lines) == set(text.splitlines())  # nothing lost
    for a, b in zip(chunks, chunks[1:]):  # the next fragment starts with the last sentence of the previous one
        assert b.startswith(a.splitlines()[-1])


def test_short_fragment_joins_the_next():
    para = "Сепараторы газовые применяют для отделения капельной жидкости. " * 16
    chunks = texts("# 5.3 Сепараторы\n\n" + para + "\n\n" + para)
    assert len(chunks) == 2 and chunks[0].startswith("# 5.3 Сепараторы\n\nСепараторы газовые")
    assert texts("12") == ["12"] and chunk_page("12") == [(0, 2, None)]  # the only fragment of a page stays
    assert chunk_page("") == [] and chunk_page("\n  \n") == []


def test_fragments_tile_the_page():
    """The pieces text[start:end] of the fragments of a page in order are the page exactly (base schema 3)."""
    para = "Сепараторы газовые применяют для отделения капельной жидкости. " * 16
    table = "| A | B |\n|---|---|\n" + "\n".join(f"| {i} | значение {i * 2} |" for i in range(400))
    ocr = "\n".join(f"Строка распознанного текста номер {i} без пустых строк." for i in range(200))
    for page in (
        "\n\n# 5.3 Сепараторы\n\n" + para + "\n\n\n" + para + "\n  \n",
        table,
        ocr,
        "12",
        "Таблица 1\n\n" + table + "\n\nПосле таблицы.\n\n" + ocr + "\n\n12\n",
    ):
        offsets = chunk_page(page)
        assert "".join(page[s:e] for s, e, _ in offsets) == page
        assert offsets[0][0] == 0 and offsets[-1][1] == len(page)
        assert all(a[1] == b[0] for a, b in zip(offsets, offsets[1:]))


def test_fragment_carries_its_section():
    pages = [(1, "# 1. Общие положения\n\nТекст первого раздела."), (2, "# 2. Расчёт дебита\n\nТекст второго.")]
    heads = {p: h for p, _, h, _, _, _ in chunk_doc(pages)}
    assert heads == {1: "1. Общие положения", 2: "2. Расчёт дебита"}


def test_catalog_is_made_from_the_cards(mini):
    idx = os.path.dirname(mini["cfg"]["catalog"])
    cat = open(mini["cfg"]["catalog"], encoding="utf-8").read()
    assert "Updated: 2026-10-23. Documents: 6." in cat and "do not edit" in cat
    assert (
        "| N-00001 | ГОСТ Р 00001-2024 Тестовый стандарт о дебите скважин | standard | Standards | 2024 | PDF with text |"
        in cat
    )
    upd = open(os.path.join(idx, "sources_to_update.md"), encoding="utf-8").read()
    assert (
        "Open items: 1." in upd
        and "| L-00001 | Тестовая отсканированная книга | poor scan | replace the file | medium |" in upd
    )
    cards, errors = catalog.load_cards(os.path.join(idx, "cards"))
    assert sorted(cards) == ["E-00001", "J-00001", "L-00001", "N-00001", "N-00002", "X-00001"] and errors == []
    # the same cards give the same files: nothing is rewritten, the date of the stamp alone is no change
    before = os.path.getmtime(mini["cfg"]["catalog"])
    assert catalog.write(idx, "2030-01-01", {"profile": "oil-gas-ru"}) == (6, 1)
    assert (
        os.path.getmtime(mini["cfg"]["catalog"]) == before
        and "2026-10-23" in open(mini["cfg"]["catalog"], encoding="utf-8").read()
    )


def test_rows_of_a_card_and_its_parts(mini):
    cards = load_cards(mini["cfg"]["cards_dir"])
    rows = doc_rows(*cards["E-00001"], mini["cfg"])
    assert [r["code"] for r in rows] == ["E-00001", "E-00001-02"]
    main, part = rows
    assert main["file"].endswith("E-00001_Test-Pump/E-00001-01_Manual.pdf") and main["section"] == "Equipment documents"
    assert part["parent"] == "E-00001" and part["file"].endswith("E-00001-02_Trials.pdf")
    assert part["title"] == "Паспорт тестового насоса (part 02: Trials)" and part["source"] == "Испытания.pdf"
    assert main["doc_type"] == "datasheet" and main["lang"] == "ru" and main["card_sha"] == cards["E-00001"][1]
    n = doc_rows(*cards["N-00001"], mini["cfg"])[0]
    assert n["designation"] == "GOST R 00001-2024 / ГОСТ Р 00001-2024" and n["year"] == 2024


def test_contents_and_links_of_the_cards(mini):
    cards = load_cards(mini["cfg"]["cards_dir"])
    assert toc_rows(cards["N-00001"][0], 3) == [
        ("N-00001", 1, "General provisions", "General provisions / Общие положения", 1, 2),
        ("N-00001", 1, "Well rate calculation", "Well rate calculation / Расчёт дебита", 2, 3),
    ]
    links = [x for x in link_rows(cards) if x[0] == "N-00001"]
    assert links == [("N-00001", "ГОСТ Р 00002-2024", "N-00002"), ("N-00001", "API RP 14E", "")]


def test_format_of_a_card_and_the_scores(tmp_path):
    fmt = {"kind": "pdf_mixed", "pages": 10, "ocr_pages": 3}
    line = C.format_line(fmt)
    assert line.startswith("PDF with text, some pages are scans (3 recognized)") and ocr_share(line) == 0.3
    assert C.ocr_share(fmt) == 0.3
    tsv = tmp_path / "ocr_quality.tsv"
    tsv.write_text("code\tscore\tnonword\nE-00002\t61.5\t0.2\n", encoding="utf-8")
    assert read_ocr_scores(str(tsv)) == {"E-00002": 61.5}
