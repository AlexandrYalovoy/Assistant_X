# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cards in an answer (audit 6, M-030): at most [search] max_cards of them, the rest of the k are pages; the server
shows them after the pages as "Documents on the topic", unless the question names the document."""

from assistant_x.search import retrieval
from tests.search.test_server import server  # noqa: F401 — the fixture


def test_card_weight():
    assert retrieval.KIND_WEIGHT["card_q"] < retrieval.KIND_WEIGHT["text"] and retrieval.MAX_CARDS == 2


def test_at_most_max_cards(lib):
    query = "сепаратор нефть газ давление"
    every = lib.search(query, k=25, dense=False, rerank=False, max_cards=99, max_per_doc=99)
    cards = [r for r in every if r["kind"] == "card"]
    assert cards, "the test library answers this question with cards"
    for n in (0, 1):
        got = lib.search(query, k=25, dense=False, rerank=False, max_cards=n, max_per_doc=99)
        assert sum(r["kind"] == "card" for r in got) == n


def test_cards_after_the_pages(server, lib, monkeypatch):  # noqa: F811
    from assistant_x.server import mcp_server

    hits = [
        {"code": "N-00001", "page": 0, "kind": "card", "text": "card", "named": False},
        {"code": "N-00002", "page": 3, "kind": "text", "text": "page", "named": False},
    ]
    rows = [
        dict(
            title="T",
            section="N",
            year=2000,
            page_numbering=None,
            heading="",
            quality="",
            issue="",
            doc_type="",
            personal=False,
            label=None,
            page_note="",
            refs=[],
            **h,
        )
        for h in hits
    ]
    monkeypatch.setattr(lib, "search", lambda *a, **k: rows)
    monkeypatch.setattr(mcp_server, "full_mode", lambda: True)
    out = mcp_server.search_library("сепаратор")
    # the heads of the fragments start a line; the hint above them cites the best page in the same form
    page, card = "\n[N-00002, PDF 3]", "\n[N-00001, card]"
    assert out.index(page) < out.index("## Documents on the topic") < out.index(card)
    rows[0]["named"] = True  # the question names the document: its card leads
    out = mcp_server.search_library("ГОСТ 1")
    assert "## Documents on the topic" not in out and out.index(card) < out.index(page)
