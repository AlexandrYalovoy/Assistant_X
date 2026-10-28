# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search on the mini base by words only (dense=False): words and synonyms, filters, references, reading,
originals, and many threads at once as the MCP server calls it; the exact text of the pages, the exact column of
the word index (quotes, designations, look-alike letters), printed labels and page notes (base schema 3)."""

import concurrent.futures, os

from assistant_x.core.common import exact_tokens, tokens
from tests.search.conftest import GRADE, TEXTS


def test_fts_query_adds_synonyms(lib):
    q = lib.fts_query("производительность скважины")
    assert f'"{tokens("дебит")[0]}"' in q


def test_search_finds_document_and_page(lib):
    res = lib.search("обводнённости газового фактора", dense=False)
    assert (res[0]["code"], res[0]["page"]) == ("N-00001", 2)
    assert res[0]["heading"] == "2. Расчёт дебита"
    assert any(r["code"] == "N-00001" for r in lib.search("производительность скважины", dense=False))


def test_refs_lead_to_the_table(lib):
    r = next(r for r in lib.search("обводнённости", dense=False) if r["page"] == 2)
    assert r["refs"] == [("табл. 1", 3)]
    assert r["related_pages"] == [3]
    assert "2. Расчёт дебита" in lib.book_map("N-00001")


def test_filter_codes_with_parts(lib):
    res = lib.search("насоса", dense=False, codes=["E-00001"])
    assert res and {r["code"] for r in res} <= {"E-00001", "E-00001-02"}
    assert "E-00001-02" in {r["code"] for r in lib.search("наработка на отказ", dense=False, codes=["E-00001"])}


def test_quality_of_a_scan(lib):
    r = lib.search("коэффициент сжимаемости", dense=False)[0]
    assert r["code"] == "L-00001" and "scan" in r["quality"] and "poor scan" in r["issue"]


def test_low_recognition_score(lib):
    """ocr_quality.tsv reaches the base: a low score is a "Source quality" note, a high one is not."""
    rows = {r["code"]: r for r in lib.con.execute("SELECT code, quality, ocr_score FROM docs")}
    assert rows["L-00001"]["ocr_score"] == 42.0 and "recognition score 42 of 100" in rows["L-00001"]["quality"]
    assert rows["N-00001"]["ocr_score"] == 98.5 and "recognition score" not in (rows["N-00001"]["quality"] or "")
    assert rows["E-00001"]["ocr_score"] is None


def test_pages_whole_and_cut(lib):
    full = lib.pages("N-00001", 1, 3)
    assert "=== page 3 ===" in full and "cut at" not in full
    cut = lib.pages("N-00001", 1, 3, max_chars=200)
    assert len(TEXTS["N-00001"][0]) > 200  # so page 1 is the first one cut
    assert cut.endswith("…text cut at 200 characters: pages 1–3 are not shown, ask for them separately")
    end = len(lib.pages("N-00001", 1, 2))
    assert "page 3 is not shown" in lib.pages("N-00001", 1, 3, max_chars=end + 5)


def test_original_inside_library(lib, mini):
    path, why = lib.original("n-00001")
    assert why is None and path.startswith(os.path.realpath(mini["root"]))
    assert lib.original("E-00001-02")[0].endswith("E-00001-02_Trials.pdf")


def test_original_refuses_bad_code(lib):
    path, why = lib.original("..\\..\\N-00001")
    assert path is None and "does not follow the pattern" in why


def test_original_refuses_path_outside(lib, mini, monkeypatch, quiet_journal):
    outside = os.path.join(os.path.dirname(mini["root"]), "outside.pdf")
    open(outside, "wb").write(b"%PDF-1.4\n")
    real = lib.doc
    for field in ("file", "source"):
        fake = dict(real("N-00001"), file="", source="")
        fake[field] = "library\\..\\..\\outside.pdf"
        monkeypatch.setattr(lib, "doc", lambda code, d=fake: d)
        assert lib.original("N-00001") == (None, "The path of the original is outside the library: refused")
    assert "original outside the library" in open(quiet_journal / "failures.log", encoding="utf-8").read()


def test_many_threads(lib):
    calls = [
        lambda: lib.search("дебит скважины", dense=False),
        lambda: lib.pages("N-00001", 1, 3),
        lambda: lib.doc("E-00001-02"),
        lambda: lib.list_docs("pump"),
        lambda: lib.book_map("N-00001", 2),
        lambda: lib.search("насоса", dense=False, codes=["E-00001"]),
    ]
    with concurrent.futures.ThreadPoolExecutor(10) as ex:
        res = list(ex.map(lambda i: calls[i % len(calls)](), range(200)))
    assert len(res) == 200 and all(res)


def test_rerank_auto_on_every_question_on_a_video_card(lib, monkeypatch, tmp_path):
    from assistant_x.search import retrieval

    monkeypatch.setitem(lib.cfg, "rerank", "auto")
    monkeypatch.setitem(lib.cfg, "rerank_model", str(tmp_path))  # the model lies in models/
    monkeypatch.setattr(lib, "_cuda", True)
    for q, k in (("унос гликоля из абсорбера", 5), ("унос гликоля из абсорбера", 20), ("перечисли все", 8)):
        assert lib.want_rerank(q, k), (q, k)  # k and the wording no longer matter
    monkeypatch.setattr(lib, "no_wait", True)  # the MCP server is still loading the model: do not wait for it
    assert not lib.want_rerank("перечисли все", 8)
    monkeypatch.setattr(lib, "_reranker", object())  # once it is in, it reranks
    assert lib.want_rerank("перечисли все", 8)
    monkeypatch.setattr(lib, "_reranker", None)
    monkeypatch.setattr(lib, "no_wait", False)
    monkeypatch.setattr(lib, "_cuda", False)  # on a CPU: the first rerank_cpu_top candidates (Q3: 2.6 s, MRR 0.70)
    monkeypatch.setattr(lib, "dml", lambda: None)
    assert lib.want_rerank("перечисли все", 20)
    monkeypatch.setitem(lib.cfg, "rerank_cpu_top", 0)  # off on a CPU unless rerank = true
    assert not lib.want_rerank("перечисли все", 20)
    monkeypatch.setitem(lib.cfg, "rerank", True)
    assert lib.want_rerank("перечисли все", 20)
    monkeypatch.setitem(lib.cfg, "rerank", "auto")
    monkeypatch.setattr(lib, "_cuda", True)
    monkeypatch.setitem(lib.cfg, "rerank_model", str(tmp_path / "нет"))  # a fresh workspace has no reranker model
    assert not lib.want_rerank("перечисли все", 20) and not lib.may_rerank()
    monkeypatch.setitem(lib.cfg, "rerank", False)
    assert not lib.want_rerank("перечисли все", 20)
    # the questions for all places are still told (the snapshot of the Russian patterns keeps them)
    for q in (
        "Перечисли все источники",
        "где ещё описан унос",
        "во всех нормативах",
        "Все места о потерях",
        "List all sources",
        "where else is carry-over described",
    ):
        assert retrieval.ALL_PLACES_RX.search(q), q
    assert not retrieval.ALL_PLACES_RX.search("всесторонний анализ")  # «все» ("all") as a word only
    assert not retrieval.ALL_PLACES_RX.search("a balanced analysis")


# ---------- base schema 3: the pages, the exact column of the word index ----------


def test_results_are_the_exact_text_of_the_page(lib):
    pages = dict(lib.con.execute("SELECT page, text FROM pages WHERE code='N-00001'").fetchall())
    assert pages == {i + 1: t for i, t in enumerate(TEXTS["N-00001"])}
    for r in lib.search("обводнённости газового фактора", dense=False):
        if r["kind"] == "text" and r["code"] == "N-00001":
            assert r["text"] in pages[r["page"]]


def test_quoted_phrase_goes_to_the_exact_column(rich):
    q = rich.fts_query('"допустимой скорости газа" в сечении')
    assert q.startswith("stem : (") and f'exact : ("{" ".join(exact_tokens("допустимой скорости газа"))}")' in q
    res = rich.search('"допустимой скорости газа"', dense=False)
    assert (res[0]["code"], res[0]["page"]) == ("N-00002", 1)


def test_hyphenated_designation(rich):
    q = rich.fts_query("сталь по ГОСТ 5632-2014")
    assert '"5632-2014"' in q.split("exact : ")[1]
    res = rich.search("ГОСТ 5632-2014", dense=False)
    assert ("N-00002", 1) in [(r["code"], r["page"]) for r in res[:2]]
    # the designation of a card named in the question goes to the exact column in its own spelling
    assert f'"{" ".join(exact_tokens("ГОСТ Р 00002-2024"))}"' in rich.fts_query("что требует ГОСТ Р 00002-2024")


def test_latin_look_alike_letters_in_a_cyrillic_grade(rich):
    latin = "12X18H10T"  # Latin X, H and T as OCR or a keyboard gives them; the text has the Cyrillic letters
    assert all(c.isascii() for c in latin) and "12Х18Н10Т" in GRADE and exact_tokens(latin) == exact_tokens("12Х18Н10Т")
    assert not rich.search(latin, dense=False, codes=["N-00001"])  # the grade is in N-00002 only
    res = rich.search(f"сталь {latin}", dense=False)
    assert (res[0]["code"], res[0]["page"]) == ("N-00002", 1) and "12Х18Н10Т" in res[0]["text"]


def test_page_labels_and_notes(rich):
    res = {r["page"]: r for r in rich.search("дебит скважин способам эксплуатации", dense=False, codes=["N-00001"])}
    assert res[3]["label"] == "9" and res[3]["page_note"].startswith("recognition score 55 of 100 on this page")
    assert "complex table on this page — check numbers with page_image" in res[3]["page_note"]
    assert rich.page_info("N-00001", 1, 3) == {1: ("7", 97.0, ""), 2: ("8", 97.0, ""), 3: ("9", 55.0, "complex_table")}


def test_a_moved_original_is_found_without_walking_the_library_each_time(mini, monkeypatch):
    """When the file of a card is not where the card says, the library is searched by the file name: from a map of
    its names made once per state of the base, not by a walk of the whole library for every page image."""
    from assistant_x.search import retrieval

    lib = retrieval.Library(mini["cfg"])
    real = lib.doc
    fake = dict(real("N-00001"), file="library\\elsewhere\\" + os.path.basename(real("N-00001")["file"]), source="")
    monkeypatch.setattr(lib, "doc", lambda code: fake)
    walks = []
    walk = retrieval.os.walk
    monkeypatch.setattr(retrieval.os, "walk", lambda *a, **k: walks.append(1) or walk(*a, **k))
    for _ in range(5):
        path, why = lib.original("N-00001")
        assert why is None and path.endswith(os.path.basename(real("N-00001")["file"]))
    assert len(walks) == 1
