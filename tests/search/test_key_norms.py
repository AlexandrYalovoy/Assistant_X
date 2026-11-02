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
