# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The jurisdictions filter of the search and of list_documents (doc.jurisdiction of the cards, core/jurisdiction.py):
a library of its own whose standard N-00002 is marked RU."""

import os

import pytest

from assistant_x.core import card as C
from assistant_x.core.common import load_config
from assistant_x.search.retrieval import Library
from tests.search.conftest import build, make_library


@pytest.fixture(scope="module")
def marked(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("juris"))
    config = make_library(root)
    p = os.path.join(root, "index", "cards", "N-00002.json")
    c = C.load(p)
    c["doc"]["jurisdiction"] = "RU"
    C.dump(c, p)
    build(config)
    return Library(load_config(config))


def test_the_search_filter(marked):
    """jurisdictions=[…] keeps the documents of those jurisdictions; a document without one is left out."""
    assert [d["code"] for d in marked.list_docs(jurisdictions=["ru"])] == ["N-00002"]
    assert marked.list_docs(jurisdictions=["KZ"]) == []
    res = marked.search("ГОСТ Р 00002-2024 сепаратор", dense=False, jurisdictions=["RU"])
    assert res and {r["code"] for r in res} == {"N-00002"}
    assert marked.search("сепараторов", dense=False, jurisdictions=["KZ"]) == []
