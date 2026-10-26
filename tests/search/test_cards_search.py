# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The cards in the search (words only, dense=False): an English question finds a Russian document through its card
and a question in Russian finds what only the card says, a designation in the question puts its card first, the
articles of a journal issue are found as units at their page, the filters of genre and language, the terms of the
cards as synonyms, the boost of a chapter of the contents, document_info and list_documents of the MCP server, and
the rebuild that reads again only the changed cards."""

import json, sys

import pytest

from assistant_x.core import card as C
from assistant_x.core import common
from assistant_x.core.common import tokens
from assistant_x.search import build_index
from assistant_x.server import mcp_server
from tests.search.conftest import make_library


def kinds(res):
    return [(r["code"], r["kind"], r["page"]) for r in res]


def test_card_fragments_are_in_the_base(lib):
    """Every card: a fragment per language (English, Russian) and one of its questions and topics, all at page 0."""
    rows = lib.con.execute("SELECT code, kind, page, n FROM chunks WHERE kind != 'text' ORDER BY code, kind, n").fetchall()
    cards = [("E-00001",), ("J-00001",), ("L-00001",), ("N-00001",), ("N-00002",), ("X-00001",)]
    assert [tuple(r) for r in rows] == [
        x
        for (c,) in cards
        for x in [(c, "card", 0, 0), (c, "card", 0, 1), (c, "card_q", 0, 2)]
        + ([(c, "unit", 2, 0), (c, "unit", 3, 1)] if c == "J-00001" else [])
    ]
    en, ru = [r[0] for r in lib.con.execute("SELECT own_text FROM chunks WHERE code='N-00001' AND kind='card' ORDER BY n")]
    assert "Test standard on well rates" in en and "Тестовый" not in en and "electric submersible pump" in en
    assert "Тестовый стандарт о дебите скважин" in ru and "Test standard on well rates\n" not in ru and "ЭЦН" in ru
    assert "electric submersible pump" not in ru  # the summary (one language) is in both, the title and terms not
    assert "card" not in lib.pages("N-00001", 0, 3) and "Test standard on well rates" not in lib.pages("N-00001", 0, 3)


def test_english_question_finds_the_russian_document_by_its_card(lib):
    res = lib.search("test standard on well rates", dense=False)
    assert ("N-00001", "card", 0) in kinds(res)
    assert res[0]["code"] == "N-00001"


def test_russian_question_finds_what_only_the_card_says(lib):
    """The Russian title of the card is in no text: the card fragment finds it."""
    res = lib.search("тестовая отсканированная книга", dense=False)
    assert kinds(res)[0] == ("L-00001", "card", 0)


def test_designation_in_the_question_comes_first(lib):
    for q in ("ГОСТ Р 00002-2024 сепаратор", "what does gost r 00002-2024 say", "GOST R 00002–2024"):
        res = lib.search(q, dense=False)
        assert kinds(res)[0] == ("N-00002", "card", 0) and res[0]["named"], q
    assert lib.designations_in("ГОСТ Р 00002-20245") == []  # another number: no exact match
    assert lib.designations_in("API RP 14E") == []  # no document of the library has it
    stats = {}
    lib.search("ГОСТ Р 00001-2024", dense=False, stats=stats)
    assert stats["designation"] == ["N-00001"]
    # the filters still hold: a standard named in a search of books is not put in
    assert "N-00001" not in {r["code"] for r in lib.search("ГОСТ Р 00001-2024", dense=False, doc_types=["book"])}


def test_unit_of_a_journal_issue(lib):
    res = lib.search("Souders-Brown equation gas velocity", dense=False)
    unit = next(r for r in res if r["kind"] == "unit")
    assert (unit["code"], unit["page"], unit["heading"]) == ("J-00001", 2, "Sizing of gas separators")
    assert unit["refs"] == []
    assert ("J-00001", "text", 3) in kinds(lib.search("углекислотная коррозия труб", dense=False))


def test_filters_of_genre_and_language(lib):
    assert {r["code"] for r in lib.search("сепараторов", dense=False, doc_types=["serial_issue"])} == {"J-00001"}
    assert lib.search("сепараторов", dense=False, langs=["en"]) == []
    assert lib.search("сепараторов", dense=False, langs=["RU"])
    docs = lib.list_docs(doc_types=["standard"])
    assert [d["code"] for d in docs] == ["N-00001", "N-00002"] and docs[0]["doc_type"] == "standard"
    assert [d["code"] for d in lib.list_docs("pump")] == ["E-00001"]  # the English title of a Russian document
    assert [d["code"] for d in lib.list_docs("журнал")] == ["J-00001"]


def test_terms_of_the_cards_are_synonyms(lib):
    q = lib.fts_query("electric submersible pump")
    assert f'"{tokens("ЭЦН")[0]}"' in q
    assert any(r["code"] == "N-00001" and r["page"] == 3 for r in lib.search("electric submersible pump", dense=False))


def test_chapter_of_the_contents_raises_its_fragments(lib):
    ids = {r["page"]: r["id"] for r in lib.con.execute("SELECT id, page FROM chunks WHERE code='N-00001' AND kind='text'")}
    fused = {ids[1]: 1.0, ids[2]: 1.0}
    lib._weigh("расчёт дебита", fused)
    assert fused[ids[2]] == pytest.approx(1.25) and fused[ids[1]] == 1.0
    card_id = lib.con.execute("SELECT id FROM chunks WHERE code='N-00001' AND kind='card'").fetchone()[0]
    fused = {card_id: 1.0}
    lib._weigh("x", fused)
    assert fused[card_id] == pytest.approx(0.7)


@pytest.fixture
def server(lib, monkeypatch):
    monkeypatch.setattr(mcp_server, "_lib", lib)
    monkeypatch.setattr(mcp_server, "_owner", object())
    return mcp_server


def test_document_info_is_the_brief_of_the_card(server):
    out = server.document_info("N-00001")
    assert out.startswith("N-00001 · Test standard on well rates")
    assert "GOST R 00001-2024 / ГОСТ Р 00001-2024" in out and "ЭЦН (электроцентробежный насос)" in out
    assert "Contents: 2 entries" in out and "library/" not in out and "Расчёт дебита — PDF 2" not in out
    toc = server.document_info("N-00001", ["toc"])
    assert "Well rate calculation / Расчёт дебита — PDF 2" in toc and "Summary" not in toc
    assert "E-00001-02" in server.document_info("E-00001", ["file"])
    part = server.document_info("E-00001-02")
    assert part.startswith("E-00001-02 is part 02 of the document E-00001") and "Datasheet of a test pump" in part
    assert "Source quality" in server.document_info("L-00001") and "poor scan" in server.document_info("L-00001")
    assert "a personal document of the user" in server.document_info("X-00001")
    issue = server.document_info("J-00001", ["units"])
    assert "PDF 2: Sizing of gas separators / Расчёт газовых сепараторов — Petrov P. P." in issue


def test_search_and_list_show_kinds_and_flags(server):
    out = server.search_library("ГОСТ Р 00002-2024").partition("to compute them.\n\n")[2]  # after the note: no vectors
    assert out.startswith("[N-00002, card] ") and "its designation is in the question" in out
    assert "[J-00001, PDF 2]" in server.search_library("Souders-Brown") and "Unit (an article" in server.search_library(
        "Souders-Brown"
    )
    listed = server.list_documents()
    assert "X-00001 (personal) |" in listed and "| serial_issue |" in listed
    assert server.list_documents(doc_types=["datasheet"]).startswith("E-00001 |")


def run(config, *args):
    argv = sys.argv
    sys.argv = ["build_index.py", "--config", config, "--no-check", *args]
    try:
        build_index.main()
    finally:
        sys.argv = argv


def test_rebuild_reads_again_only_the_changed_cards(tmp_path, capsys):
    path = make_library(str(tmp_path / "Библиотека"))
    run(path)
    cfg = common.load_config(path)
    con = common.connect(cfg["db"], readonly=True)
    before = {(r[0], r[1]): r[2] for r in con.execute("SELECT code, kind, id FROM chunks")}
    sha = dict(con.execute("SELECT code, card_sha FROM docs"))
    con.close()
    capsys.readouterr()
    p = tmp_path / "Библиотека" / "index" / "cards" / "N-00002.json"
    card = C.load(p)
    card["doc"]["summary"] = "A changed summary about vertical gas-oil separators."
    card["doc"]["toc"] = [{"level": 1, "pdf_from": 1, "title": {"en": "Separators", "ru": "Сепараторы"}}]
    C.dump(card, p)
    run(path)
    assert "texts updated 0, cards read 1" in capsys.readouterr().out
    con = common.connect(cfg["db"], readonly=True)
    after = {(r[0], r[1]): r[2] for r in con.execute("SELECT code, kind, id FROM chunks")}
    assert after[("N-00002", "card")] != before[("N-00002", "card")]  # the card fragment made again
    assert after[("N-00002", "text")] == before[("N-00002", "text")]  # its text was not chunked again
    assert after[("N-00001", "card")] == before[("N-00001", "card")]  # another card was not read again
    assert dict(con.execute("SELECT code, card_sha FROM docs"))["N-00002"] != sha["N-00002"]
    assert [tuple(r) for r in con.execute("SELECT title_en, pdf_from, pdf_to FROM toc WHERE code='N-00002'")] == [
        ("Separators", 1, 1)
    ]
    assert (
        "changed summary"
        in json.loads(con.execute("SELECT card FROM docs WHERE code='N-00002'").fetchone()[0])["doc"]["summary"]
    )
    links = con.execute("SELECT designation, target_code FROM links WHERE code='N-00001' ORDER BY designation").fetchall()
    assert [tuple(x) for x in links] == [("API RP 14E", ""), ("ГОСТ Р 00002-2024", "N-00002")]
    con.close()
    p.unlink()  # a card removed: its document leaves the base, the catalog is made again
    run(path)
    con = common.connect(cfg["db"], readonly=True)
    assert not con.execute("SELECT 1 FROM chunks WHERE code='N-00002'").fetchone()
    assert not con.execute("SELECT 1 FROM toc WHERE code='N-00002'").fetchone()
    con.close()
    assert "| N-00002 |" not in (tmp_path / "Библиотека" / "index" / "CATALOG.md").read_text(encoding="utf-8")


def test_a_base_of_markdown_cards_is_built_anew(tmp_path):
    path = make_library(str(tmp_path / "Библиотека"))
    run(path)
    cfg = common.load_config(path)
    con = common.connect(cfg["db"])
    con.execute("UPDATE meta SET value='1' WHERE key='base_schema'")
    con.commit()
    con.close()
    with pytest.raises(SystemExit, match="earlier version"):
        run(path)
    from assistant_x.search.retrieval import Library, OldBase

    with pytest.raises(OldBase, match="build it anew"):  # the search does not read it half-way either
        Library(cfg)
    run(path, "--full")
