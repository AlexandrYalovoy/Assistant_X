# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""verify_quote (search/retrieval.py, the MCP tool): a quote compared with the page by its skeleton (common.skeleton):
Russian and English, yo and ye, the kinds of dashes and quotes, OCR Latin letters in Cyrillic words, Markdown marks;
a quote on the next page, a quote with a wrong number, a quote that is not there."""

import pytest

from assistant_x.core.common import skeleton
from assistant_x.server import mcp_server

PAGES = {  # code -> {page: text}
    "L-00009": {
        4: "Глава 3\n\nДебит скважины определяют по табл. 1 с учётом обводнённости продукции и газового фактора.",
        5: "Коэффициент сжимаемости находят по графику Стэндинга — Каца; «газовый фактор» берут по замеру.\n\n"
        "| Способ | Дебит, м3/сут |\n|---|---|\n| ЭЦН | 120 |",
        6: "Опытные испытания насоса: наработка на отказ составила 400 суток, вибрация в норме, утечек нет. "
        "Корпус сепар\u0061тора проверяют на прочность.",  # an OCR Latin "a" in a Cyrillic word
    },
    "B-00002": {
        10: "The allowable gas velocity is found by the Souders–Brown equation with the factor of the mesh pad.",
        11: "Sizing of “vertical” separators — see the chart; don’t exceed the allowable velocity.",
    },
}


@pytest.fixture
def pages(lib, monkeypatch):
    """The Library of the mini base answering with the pages above (no labels, no flags)."""
    monkeypatch.setattr(lib, "page_text", lambda code, page: PAGES.get(code, {}).get(page))
    monkeypatch.setattr(lib, "page_info", lambda code, start, end: {})
    return lib


def test_skeleton():
    assert skeleton("  С учётом\nОБВОДНЁННОСТИ ") == skeleton("с учетом обводненности")
    assert skeleton("Стэндинга — Каца") == skeleton("Стэндинга - Каца") == skeleton("Стэндинга – Каца")
    assert skeleton("«газовый фактор»") == skeleton('"газовый фактор"') == skeleton("“газовый фактор”")
    assert skeleton("сепар\u0061тор") == skeleton("сепаратор")  # a Latin a in a Cyrillic word
    assert skeleton("**Таблица** | ЭЦН | 120 |") == skeleton("Таблица ЭЦН 120")
    assert skeleton("мягкий\u00adперенос") == skeleton("мягкийперенос") and skeleton("ﬁ") == "fi"  # NFKC


@pytest.mark.parametrize(
    "code, page, quote",
    [
        ("L-00009", 4, "с учетом обводненности продукции"),  # ye for yo
        ("L-00009", 5, "по графику Стэндинга - Каца"),  # a hyphen for the dash of the page
        ("L-00009", 5, '"газовый фактор" берут по замеру'),  # straight quotes for guillemets
        ("L-00009", 5, "ЭЦН 120"),  # a row of a Markdown table
        ("L-00009", 6, "Корпус сепаратора проверяют"),  # the page has an OCR Latin letter
        ("B-00002", 10, "the allowable gas velocity is found by the Souders-Brown equation"),
        ("B-00002", 11, 'Sizing of "vertical" separators - see the chart; don\'t exceed'),
    ],
)
def test_found_word_for_word(pages, code, page, quote):
    r = pages.verify_quote(code, page, quote)
    assert (r["status"], r["page"], r["exact"], r["ratio"]) == ("found", page, True, 1.0)
    assert skeleton(quote) in skeleton(r["closest"]) or r["ratio"] == 1.0


def test_found_on_the_next_page(pages):
    r = pages.verify_quote("l-00009", 5, "наработка на отказ составила 400 суток")
    assert (r["status"], r["code"], r["page"], r["asked"], r["exact"]) == ("found_nearby", "L-00009", 6, 5, True)


def test_found_with_a_wrong_number(pages):
    r = pages.verify_quote("L-00009", 6, "наработка на отказ составила 450 суток, вибрация в норме")
    assert r["status"] == "found" and not r["exact"] and 0.9 <= r["ratio"] < 1
    assert r["diff"] == "«450» → «400»" and "400 суток" in r["closest"]


def test_not_found(pages):
    r = pages.verify_quote("B-00002", 10, "the separator is sized by the residence time of the liquid")
    assert r["status"] == "not_found" and r["page"] in (9, 10, 11) and r["ratio"] < 0.9
    assert r["closest"] and r["diff"]
    assert pages.verify_quote("B-00002", 40, "anything")["diff"] == "no text of this page in the library"
    assert pages.verify_quote("B-00002", 10, "  ")["diff"] == "an empty quote"


def test_the_tool_on_the_mini_base(lib, monkeypatch):
    monkeypatch.setattr(mcp_server, "_lib", lib)
    assert (
        mcp_server.verify_quote("N-00001", 2, "с учетом обводненности продукции")
        == "Found word for word on PDF 2 of N-00001."
    )
    near = mcp_server.verify_quote("N-00001", 1, "Замер выполняют на замерной установке")
    assert (
        near.startswith("Not on PDF 1, but on the neighbouring PDF 2 of N-00001, word for word.") and "Cite PDF 2." in near
    )
    out = mcp_server.verify_quote("N-00001", 2, "сепаратор рассчитывают по времени пребывания жидкости")
    assert out.startswith("Not found on PDF 1–3 of N-00001.") and '"(paraphrase)"' in out


def test_the_tool_warns_about_the_page(rich, monkeypatch):
    monkeypatch.setattr(mcp_server, "_lib", rich)
    out = mcp_server.verify_quote("N-00001", 3, "ЭЦН 120")
    assert out.startswith("Found word for word on PDF 3 (p. 9) of N-00001.")
    assert "\nPage: recognition score 55 of 100" in out and "complex table on this page" in out
