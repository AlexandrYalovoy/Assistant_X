# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The key norms of the design topics (search/key_norms.py): a page is kept only when the quote with its value is of
the topic, a question finds its topic by the groups of its words, the pages come first in search_library in the order
of the hierarchy, and a base package carries them with its codes renamed on install."""

import json, os

import pytest

from assistant_x.server import mcp_server
from assistant_x.base import export as X, install as B, package as P
from assistant_x.core import config as settings
from assistant_x.core.common import load_config
from assistant_x.search import key_norms as K
from tests.base import libraries
from tests.search.conftest import build, make_library

TOPIC = {
    "id": "gas-velocity",
    "name": {"en": "Gas velocity"},
    "ask": [["скорост", "диаметр"], ["газ"], ["трубопров", "газопров"]],
    "queries": ["скорость газа в трубопроводах таблица"],
    "verify": [["скорост"], ["газ"]],
    "value": "\\d+(?:[,.]\\d+)?\\s*(?:-|–)?\\s*\\d*\\s*м/с|\\|\\s*\\d+(?:[,.]\\d+)?\\s*(?:-|–)\\s*\\d+",
}
PAGE = """6.2.1.9 Скорости движения технологических потоков принимать по таблице 1.

|Наименование потоков|Скорость, м/с|
|---|---|
|Газуглеводородный в трубопроводах|5-20|
"""


def test_a_page_is_kept_only_with_a_value_of_the_topic():
    assert K.evidence(TOPIC, PAGE) == "Наименование потоков | Скорость, м/с: Газуглеводородный в трубопроводах | 5-20"
    assert K.evidence(TOPIC, "Скорость газа выбирают по расчёту.") == ""  # no value
    assert K.evidence(TOPIC, "Скорость газа выбирают по расчёту. Ускорение силы тяжести 9,81 м/с.") == ""  # not of it
    assert K.evidence(TOPIC, "Давление 5 МПа.") == ""  # not the words of the topic


def test_a_question_finds_its_topic_and_its_pages_in_the_order_of_the_hierarchy():
    e = lambda code, level, page=1: dict(code=code, pdf_page=page, level=level, quote="q")  # noqa: E731
    data = {"topics": [dict(TOPIC, entries=[e("N-00390", 5.5), e("N-00001", 5), e("N-00763", 7)])]}
    assert [t["id"] for t in K.match(data, "как выбрать диаметр промыслового газопровода по скорости газа")] == [
        "gas-velocity"
    ]
    assert K.match(data, "как выбрать диаметр сепаратора") == []  # not every group
    assert [x["code"] for x in K.entries_for(data, "скорость газа в трубопроводе", n=2)] == ["N-00001", "N-00390"]


def test_merge_and_remap():
    e = lambda code, level, page=1: dict(code=code, pdf_page=page, level=level, quote="q")  # noqa: E731
    own = {"topics": [dict(TOPIC, entries=[e("N-00002", 7)])]}
    pkg = {"topics": [dict(TOPIC, entries=[e("N-00001", 5), e("N-00009", 5)]), dict(TOPIC, id="flare", entries=[])]}
    got = K.merge(own, K.remap(pkg, {"N-00001": "N-00003"}), skip={"N-00009"})
    by = {t["id"]: t for t in got["topics"]}
    assert [x["code"] for x in by["gas-velocity"]["entries"]] == ["N-00003", "N-00002"] and "flare" in by


@pytest.fixture
def server(lib, monkeypatch):
    monkeypatch.setattr(mcp_server, "_lib", lib)
    monkeypatch.setattr(mcp_server, "_owner", object())  # the models lock is this process's
    return mcp_server


def test_the_key_pages_come_first_in_search_library(server):
    """A key norm of the topic of a question leads the hits of search_library, with its quote, whatever the search
    finds; a page no longer in the library is skipped."""
    data = {
        "topics": [
            dict(
                TOPIC,
                ask=[["обводнен"]],
                entries=[
                    dict(code="N-00001", pdf_page=2, level=5, quote="обводнённости", designation="", title=""),
                    dict(code="N-00001", pdf_page=999, level=5, quote="gone", designation="", title=""),
                ],
            )
        ]
    }
    K.write(K.path_of(server.lib().cfg), data)
    try:
        hits = server.find_fragments("обводнённости газового фактора", 3, {})
        assert (hits[0]["code"], hits[0]["page"], hits[0].get("key")) == ("N-00001", 2, True)
        assert all(h["page"] != 999 for h in hits)
        assert "[N-00001, PDF 2]" in server.search_library("обводнённости газового фактора", k=3, quotes=True)
    finally:
        os.remove(K.path_of(server.lib().cfg))


def test_a_package_carries_the_key_norms_with_its_codes_renamed(tmp_path):
    a = make_library(str(tmp_path / "A"))
    build(a)
    cfg = load_config(a)
    e = dict(code="N-00001", pdf_page=1, level=5, quote="q", designation="", title="")
    K.write(K.path_of(cfg), {"topics": [dict(TOPIC, entries=[e, dict(e, code="N-07777")])]})
    pkg = str(tmp_path / "a.axbase")
    X.export(cfg, settings.load(a)[1], pkg, "test-a", "1.0", say=lambda _: None)
    carried = json.loads(P.Package(pkg).read(K.FILE).decode("utf-8"))
    assert [x["code"] for x in carried["topics"][0]["entries"]] == ["N-00001"]  # only documents of the package
    b = libraries.make_b(str(tmp_path / "B"))  # its N-00001 keeps its code: the package's becomes N-00003
    assert B.install(pkg, confirm=True, config=b, say=lambda _: None, keep="own") == 0
    got = K.read(os.path.join(str(tmp_path / "B"), "index", K.FILE))
    assert [x["code"] for x in got["topics"][0]["entries"]] == ["N-00003"]


def test_an_installed_base_gives_every_app_its_key_norms_and_hierarchy(tmp_path, monkeypatch):
    """A colleague installs the base into an empty workspace: the key norms and the hierarchy of the library it was made
    of come with it, and the search of the library server (every app: Claude, Codex, LM Studio) puts the key pages
    first."""
    from tests.base.test_install import empty

    a = make_library(str(tmp_path / "A"))
    build(a)
    cfg = load_config(a)
    e = dict(code="N-00001", pdf_page=2, level=5, quote="обводнённости", designation="", title="")
    K.write(K.path_of(cfg), {"topics": [dict(TOPIC, ask=[["обводнен"]], entries=[e])]})
    own = {"levels": [{"rank": 1, "name": {"en": "Ours"}, "patterns": ["^OUR"]}]}
    with open(os.path.join(cfg["workspace"], "hierarchy.json"), "w", encoding="utf-8") as f:
        json.dump(own, f)
    pkg = str(tmp_path / "a.axbase")
    X.export(cfg, settings.load(a)[1], pkg, "test-a", "1.0", say=lambda _: None)
    root = str(tmp_path / "colleague")
    path = empty(root)
    assert B.install(pkg, confirm=True, config=path, say=lambda _: None) == 0
    assert json.load(open(os.path.join(root, "hierarchy.json"), encoding="utf-8")) == own
    from assistant_x.search.retrieval import Library

    monkeypatch.setattr(mcp_server, "_lib", Library(load_config(path)))
    monkeypatch.setattr(mcp_server, "_owner", object())
    hits = mcp_server.find_fragments("обводнённости газового фактора", 3, {})
    assert (hits[0]["code"], hits[0]["page"], hits[0].get("key")) == ("N-00001", 2, True)
    assert mcp_server._lib.hierarchy.source == os.path.join(root, "hierarchy.json")


def test_a_reworded_question_still_finds_its_topic():
    """A small model drops a word of the user's question: a topic of three groups or more is still found when the
    first group (what is asked) is there and only one other is missing."""
    data = {"topics": [dict(TOPIC, entries=[dict(code="N-00001", pdf_page=36, level=5, quote="q")])]}
    assert K.match(data, "допустимая скорость газа")  # no pipeline word, the velocity and the gas are there
    assert not K.match(data, "газопровод для газа")  # what is asked (the velocity) is missing
    assert not K.match({"topics": [dict(TOPIC, ask=[["скорост"], ["газ"]], entries=[{}])]}, "скорость нефти")


def test_the_bridge_gives_the_first_search_of_a_question_as_the_context_of_the_next():
    from assistant_x.server import toolsets as T

    state, ctx = T.first_search((None, None), "скорость газа в газопроводе", 0)
    assert ctx is None
    state, ctx = T.first_search(state, "gas velocity table", 10)
    assert ctx == "скорость газа в газопроводе"
    state, ctx = T.first_search(state, "сепаратор", 10 + T.QUESTION_GAP + 1)  # a new question
    assert ctx is None and state[0] == "сепаратор"
    assert T.compact_tools([{"name": "search_library", "inputSchema": {"properties": {"query": {}, "context": {}}}}])[0][
        "inputSchema"
    ]["properties"] == {"query": {}}


def test_a_build_adds_the_key_norms_of_a_new_norm_and_drops_those_of_one_taken_out(tmp_path, monkeypatch):
    """After an apply the build brings the list up to date without a search: a new norm with a table of the topic gets
    an entry, the entry goes when the norm is taken out; the base check warns of an entry the base lacks."""
    from assistant_x.core import card as C
    from assistant_x.search import check_index
    from tests.search.conftest import TEXT, card, write

    monkeypatch.setattr(K, "topics_of", lambda cfg: [TOPIC])
    path = make_library(str(tmp_path / "lib"))
    cfg = load_config(path)
    K.write(K.path_of(cfg), {"topics": [dict(TOPIC, entries=[])]})  # a list made before "seen": the base is seen
    build(path)
    assert K.read(K.path_of(cfg))["topics"][0]["entries"] == []
    idx = os.path.join(str(tmp_path / "lib"), "index")
    new = card(
        "N-00009", "Field facilities", "Обустройство месторождений", "standard", "01_Standards", "N-00009.pdf", TEXT, 1
    )
    new["doc"]["designation"] = {"ru": "ГОСТ Р 99999-2026"}
    C.dump(new, os.path.join(idx, "cards", "N-00009.json"))
    write(os.path.join(idx, "texts", "N-00009.md"), "=== page 1 ===\n\n" + PAGE + "\n")
    build(path)
    got = K.read(K.path_of(cfg))
    assert [(e["code"], e["pdf_page"], e["level"]) for e in got["topics"][0]["entries"]] == [("N-00009", 1, 5)]
    assert "N-00009" in got["seen"]
    K.write(
        K.path_of(cfg),
        dict(
            got,
            topics=[
                dict(
                    got["topics"][0],
                    entries=got["topics"][0]["entries"] + [dict(got["topics"][0]["entries"][0], pdf_page=77)],
                )
            ],
        ),
    )
    rep, _ = check_index.check(load_config(path))
    assert any("N-00009 PDF 77 is not in the base" in t for k, ts in rep.items.items() for t in ts)
    os.remove(os.path.join(idx, "cards", "N-00009.json"))
    os.remove(os.path.join(idx, "texts", "N-00009.md"))
    build(path)
    got = K.read(K.path_of(cfg))
    assert got["topics"][0]["entries"] == [] and "N-00009" not in got["seen"]


def test_a_build_makes_the_key_norms_of_a_library_that_has_none(tmp_path, monkeypatch):
    """I-05: a library without index/key_norms.json (an install or update that never ran --refresh) gets one at its
    next build, its norms verified without a search; a file that cannot be read is left alone."""
    from assistant_x.core import card as C
    from tests.search.conftest import TEXT, card, write

    monkeypatch.setattr(K, "topics_of", lambda cfg: [TOPIC])
    path = make_library(str(tmp_path / "lib"))
    cfg = load_config(path)
    idx = os.path.join(str(tmp_path / "lib"), "index")
    new = card(
        "N-00009", "Field facilities", "Обустройство месторождений", "standard", "01_Standards", "N-00009.pdf", TEXT, 1
    )
    new["doc"]["designation"] = {"ru": "ГОСТ Р 99999-2026"}
    C.dump(new, os.path.join(idx, "cards", "N-00009.json"))
    write(os.path.join(idx, "texts", "N-00009.md"), "=== page 1 ===\n\n" + PAGE + "\n")
    if os.path.exists(K.path_of(cfg)):
        os.remove(K.path_of(cfg))
    build(path)
    got = K.read(K.path_of(cfg))
    assert got and [(e["code"], e["pdf_page"]) for e in got["topics"][0]["entries"]] == [("N-00009", 1)]
    assert "N-00009" in got["seen"]
    with open(K.path_of(cfg), "w", encoding="utf-8") as f:
        f.write("{not json")
    assert K.update(cfg, cfg["db"], say=lambda s: None) is None
    assert open(K.path_of(cfg), encoding="utf-8").read() == "{not json"
