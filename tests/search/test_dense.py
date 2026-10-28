# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The meaning search with the fake model (tests/search/fake_embedder.py): the exact and the FAISS path of
dense_search (vectors added after the index too), the filters, the fusion of the two lists, the weights of the kinds
and of the chapters, a named designation against the reranker, the merging of a page and the size of the pool."""

import os

import numpy as np
import pytest

from assistant_x.core import common
from tests.search.conftest import build, dense_library
from tests.search.fake_embedder import FAKE_DIM


def ids_of(lib):
    """{(code, page, kind): id} of the fragments of the base."""
    return {(r[1], r[2], r[3]): r[0] for r in lib.con.execute("SELECT id, code, page, kind FROM chunks")}


def where(lib, ids):
    rows = {r[0]: (r[1], r[2], r[3]) for r in lib.con.execute("SELECT id, code, page, kind FROM chunks")}
    return [rows[i] for i in ids]


PUMP = "насос центробежный секционный перекачки пластовой воды"  # the words of E-00001, page 1


def test_dense_search_exact_path(dense):
    st = {}
    ids = dense.dense_search(PUMP, stats=st)
    assert where(dense, ids)[0] == ("E-00001", 1, "text")
    assert dense._load_vectors()[2] is None  # a few vectors: no FAISS index, every vector compared
    assert 0.5 < st["dense_top"] <= 1.0
    total = dense.con.execute("SELECT count(*) FROM chunks").fetchone()[0]
    assert len(ids) == len(set(ids)) == total  # every fragment has a vector, each once


def test_dense_filters(dense):
    assert {c for c, _, _ in where(dense, dense.dense_search(PUMP, codes=["E-00001"]))} == {"E-00001", "E-00001-02"}
    assert {c for c, _, _ in where(dense, dense.dense_search(PUMP, sections=["N"]))} == {"N-00001", "N-00002"}
    assert {c for c, _, _ in where(dense, dense.dense_search(PUMP, doc_types=["serial_issue"]))} == {"J-00001"}
    res = dense.search(PUMP, doc_types=["serial_issue"])  # the words and the meaning under the same filter
    assert res and {r["code"] for r in res} == {"J-00001"}


@pytest.fixture
def indexed(tmp_path):
    """A library of its own with a FAISS index over its vectors and 400 rows of noise (no fragment points at them:
    IVF-PQ needs a few hundred vectors to train its codebooks)."""
    pytest.importorskip("faiss")
    from assistant_x.search import ann

    lib = dense_library(str(tmp_path / "Библиотека"))
    lib.cfg.update(ann_min_vectors=10, ann_nlist=8, ann_nprobe=8)
    noise = np.random.default_rng(1).standard_normal((400, FAKE_DIM)).astype(np.float32)
    noise /= np.linalg.norm(noise, axis=1, keepdims=True)
    with open(common.vectors_path(lib.cfg, lib.con), "ab") as f:
        f.write(noise.astype(np.float16).tobytes())
    ann.update(lib.cfg)
    return lib


def test_dense_search_faiss_path(indexed, monkeypatch):
    from assistant_x.search import embed

    vecs, _, index = indexed._load_vectors()
    assert index is not None and index.ntotal == len(vecs)
    assert where(indexed, indexed.dense_search(PUMP))[0] == ("E-00001", 1, "text")
    assert {c for c, _, _ in where(indexed, indexed.dense_search(PUMP, doc_types=["serial_issue"]))} == {"J-00001"}
    # a page edited after the index was made: its new vector lies past the index and is still found
    path = os.path.join(indexed.cfg["texts_dir"], "N-00002.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("=== page 1 ===\n\nКалибровка расходомера кориолисового типа на эталонной установке.\n\n")
    config = os.path.join(indexed.cfg["workspace"], "assistant_x.toml")
    build(config)
    monkeypatch.setattr(embed, "update_ann", lambda cfg, rebuild=False: None)
    from tests.search.fake_embedder import embed as fake_embed

    fake_embed(config)
    indexed.refresh()  # what every public method does first
    vecs, _, index = indexed._load_vectors()
    assert index.ntotal < len(vecs)
    assert where(indexed, indexed.dense_search("калибровка расходомера кориолисового"))[0] == ("N-00002", 1, "text")


def test_filters_inside_the_faiss_index(indexed, monkeypatch):
    """A filter letting many fragments through: the index looks among them only (IDSelectorBatch); where FAISS lacks
    the search parameters, 20x more candidates are kept when allowed. Either way nothing outside the filter."""
    import faiss
    from assistant_x.search import retrieval

    monkeypatch.setattr(retrieval, "EXACT_ROWS", 0)  # never the exact path over the allowed rows
    made = []
    real = faiss.IDSelectorBatch
    monkeypatch.setattr(faiss, "IDSelectorBatch", lambda rows: made.append(len(rows)) or real(rows))
    got = {c for c, _, _ in where(indexed, indexed.dense_search(PUMP, sections=["N"]))}
    assert got == {"N-00001", "N-00002"} and made == [len(indexed.allowed_rows(sections=["N"]))]

    def old_faiss(**kw):
        raise AttributeError("SearchParametersIVF")

    monkeypatch.setattr(faiss, "SearchParametersIVF", old_faiss)
    assert {c for c, _, _ in where(indexed, indexed.dense_search(PUMP, sections=["N"]))} == {"N-00001", "N-00002"}


def test_one_model_call_at_a_time(dense, monkeypatch):
    """The MCP server calls the tools from worker threads: encode and predict run under the model lock."""
    held = []
    enc, rer = dense._embedder.encode, dense._reranker.predict
    monkeypatch.setattr(dense._embedder, "encode", lambda *a, **k: held.append(dense._model_lock.locked()) or enc(*a, **k))
    monkeypatch.setattr(dense._reranker, "predict", lambda *a, **k: held.append(dense._model_lock.locked()) or rer(*a, **k))
    dense.search(PUMP, rerank=True)
    assert held == [True, True]


def card_fragment(lib, cid):
    """(code, kind, n, own text) of a fragment."""
    return tuple(lib.con.execute("SELECT code, kind, n, own_text FROM chunks WHERE id=?", (cid,)).fetchone())


def test_an_english_question_meets_the_english_fragment_of_a_russian_card(dense):
    """The texts of N-00001 are Russian; its card has an English fragment of its own, which the meaning finds."""
    code, kind, n, text = card_fragment(dense, dense.dense_search("test standard on well rates")[0])
    assert (code, kind) == ("N-00001", "card") and text.splitlines()[1] == "Test standard on well rates"
    code, kind, n, text = card_fragment(dense, dense.dense_search("тестовый стандарт о дебите скважин")[0])
    assert (code, kind) == ("N-00001", "card") and "Тестовый стандарт о дебите скважин" in text


def test_the_questions_of_a_card_are_a_fragment(dense):
    code, kind, _, text = card_fragment(dense, dense.dense_search("How is the flow rate of a well measured?")[0])
    assert (code, kind) == ("N-00001", "card_q") and text.startswith("How is the flow rate")


def test_the_fragments_of_a_card_are_one_hit(dense):
    """Its two language fragments and its questions in the pool: one result of kind 'card', its texts joined."""
    res = dense.search("test standard well rates flow rate measured", k=10)
    cards = [r for r in res if r["code"] == "N-00001" and r["page"] == 0]
    assert len(cards) == 1 and cards[0]["kind"] == "card"
    assert {r["kind"] for r in res} <= {"card", "text", "unit"}


def test_fusion_has_both_lists(dense, monkeypatch):
    ids = ids_of(dense)
    monkeypatch.setattr(dense, "word_search", lambda q, n=200, **f: [ids[("L-00001", 1, "text")]])
    monkeypatch.setattr(dense, "dense_search", lambda q, n=200, stats=None, **f: [ids[("E-00001-02", 1, "text")]])
    assert {r["code"] for r in dense.search("что угодно")} == {"L-00001", "E-00001-02"}


def test_weigh_kinds_and_chapters(dense):
    ids = ids_of(dense)
    card, unit, text = ids[("N-00001", 0, "card")], ids[("J-00001", 2, "unit")], ids[("N-00002", 1, "text")]
    fused = {card: 1.0, unit: 1.0, text: 1.0}
    dense._weigh("что угодно", fused)
    assert fused == {card: 0.7, unit: 1.0, text: 1.0}
    # «Расчёт дебита» is chapter 2 of the contents of N-00001 (page 2 on): its page is raised, the first page is not
    first, second = ids[("N-00001", 1, "text")], ids[("N-00001", 2, "text")]
    fused = {first: 1.0, second: 1.0}
    dense._weigh("расчёт дебита", fused)
    assert fused == {first: 1.0, second: 1.25}
    # a long question naming the chapter in two words: two shared stems are enough (half of seven was not)
    fused = {first: 1.0, second: 1.0}
    dense._weigh("как выполняют расчёт дебита скважины на кустовой площадке зимой", fused)
    assert fused == {first: 1.0, second: 1.25}


def test_toc_match():
    from assistant_x.search.retrieval import toc_match

    assert toc_match({"a", "b", "c", "d", "e", "f", "g"}, {"a", "b"})  # two shared stems
    assert toc_match({"a", "b"}, {"a", "x"})  # 50 % of the question
    assert not toc_match({"a", "b", "c", "d", "e", "f", "g"}, {"a", "x"})  # one stem of seven
    assert not toc_match({"a"}, set()) and not toc_match(set(), {"a"})


def test_designation_first_survives_reranking(dense):
    """The reranker prefers page 2 (more shared words), but the named card stays first: it goes first after the
    reranking; a filter that excludes the document drops it."""
    q = "ГОСТ Р 00001-2024 обводнённости продукции газового фактора замерной установке"
    assert dense.search(q, k=5, rerank=False)[0]["kind"] == "card"
    res = dense.search(q, k=5, rerank=True)
    assert (res[0]["code"], res[0]["kind"]) == ("N-00001", "card") and res[1]["code"] == "N-00001"
    assert "N-00001" not in {r["code"] for r in dense.search(q, k=5, rerank=True, doc_types=["book"])}


def test_rerank_refines_the_fused_order(dense, monkeypatch):
    """final = fused / max(fused) + weight * sigmoid(logit): with weight 0 the reranker changes nothing, with a big
    weight its order wins; it reads the fragment as the vector was made of it (title, heading, search text)."""
    q = "газового фактора сепаратора"
    plain = [(r["code"], r["page"]) for r in dense.search(q, k=6, rerank=False)]
    monkeypatch.setitem(dense.cfg, "rerank_weight", 0.0)
    assert [(r["code"], r["page"]) for r in dense.search(q, k=6, rerank=True)] == plain
    seen, title = [], dense.doc("N-00002")["title"]
    monkeypatch.setattr(
        dense._reranker,
        "predict",
        lambda pairs, **k: seen.extend(pairs) or np.array([10.0 if d.startswith(title) else -10.0 for _, d in pairs]),
    )
    monkeypatch.setitem(dense.cfg, "rerank_weight", 100.0)
    assert dense.search(q, k=6, rerank=True)[0]["code"] == "N-00002"
    titles = {r[0] for r in dense.con.execute("SELECT title FROM docs")}
    assert len(seen) >= len(plain) and all(d.splitlines()[0] in titles for _, d in seen)  # the title first


def test_on_a_processor_the_reranker_reads_the_first_candidates_only(dense, monkeypatch):
    """Q3, measured on 40 control questions of the author's library on the processor: no reranking MRR 0.591 (0.18 s),
    the first 8 candidates 0.703 (2.6 s), 12 the same 0.703 (4.6 s), the whole pool on a video card 0.734. On a processor
    the reranker reads rerank_cpu_top candidates (8); the others keep their order behind them."""
    q = "газового фактора сепаратора"
    dense.search(q, k=6, rerank=True)  # the reranker loaded
    seen = []
    monkeypatch.setattr(dense._reranker, "predict", lambda pairs, **k: seen.append(len(pairs)) or np.zeros(len(pairs)))
    monkeypatch.setattr(dense, "_cuda", False)
    monkeypatch.setattr(dense, "dml", lambda: None)
    plain = [(r["code"], r["page"]) for r in dense.search(q, k=6, rerank=False)]
    out = dense.search(q, k=6, rerank=True)
    assert seen and seen[-1] <= 8 and len(out) == len(plain)
    monkeypatch.setitem(dense.cfg, "rerank_cpu_top", 3)
    dense.search(q, k=6, rerank=True)
    assert seen[-1] <= 3
    monkeypatch.setattr(dense, "_cuda", True)  # on a video card: the whole pool
    dense.search(q, k=6, rerank=True)
    assert seen[-1] > 8 or seen[-1] == len(plain)


def test_a_page_and_a_document_once(dense):
    res = dense.search("обводнённости продукции сепаратора", k=10, max_per_doc=1)
    assert len({r["code"] for r in res}) == len(res)
    res = dense.search("обводнённости продукции сепаратора", k=10)
    assert len({(r["code"], r["page"], r["kind"]) for r in res}) == len(res)
    # 3 pages a document; a 4th one only after every other document (M-080: a book that fills the candidates alone)
    first_over, count = None, {}
    for i, r in enumerate(res):
        count[r["code"]] = count.get(r["code"], 0) + 1
        if count[r["code"]] > 3 and first_over is None:
            first_over = i
    if first_over is not None:
        assert len(res) == 10 and all(
            sum(x["code"] == r["code"] for x in res[: i + 1]) > 3 for i, r in enumerate(res) if i >= first_over
        )


def test_stats_of_the_meaning_search(dense):
    st = {}
    dense.search(PUMP, stats=st)
    assert st["words"] > 0 and isinstance(st["dense_top"], float) and st["rerank"] is False
    assert "dense_pending" not in st and "dense_error" not in st


def test_model_still_loading_answers_by_words(dense, monkeypatch):
    import threading

    monkeypatch.setattr(dense, "no_wait", True)
    monkeypatch.setattr(dense, "dense_ready", threading.Event())
    monkeypatch.setattr(dense, "dense_search", lambda *a, **k: pytest.fail("searched by meaning before the model was in"))
    st = {}
    assert dense.search(PUMP, stats=st) and st["dense_pending"] is True


@pytest.fixture
def one_big(tmp_path):
    """A library whose N-00001 has 30 pages of nearly the same words: the closest 20 fragments are all of it."""
    from assistant_x.core.common import load_config
    from tests.search.conftest import make_library
    from tests.search.fake_embedder import embed, fake_library

    path = make_library(str(tmp_path / "Библиотека"))
    pages = [f"Обводнённость продукции скважины номер {i + 1} растёт после ремонта." for i in range(30)]
    with open(os.path.join(os.path.dirname(path), "index", "texts", "N-00001.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(f"=== page {i + 1} ===\n\n{p}\n\n" for i, p in enumerate(pages)))
    build(path)
    embed(path)
    return fake_library(load_config(path))


def test_k_results_when_enough_distinct_pages_exist(one_big):
    res = one_big.search("обводнённость продукции скважины", k=5)
    assert len(res) == 5 and len({r["code"] for r in res}) >= 3
