# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The vector of a fragment is of what the model reads of it: the short title of its document, its heading, its
text. A new title in a card left the vectors of the text fragments of the document as they were (a library of 0.6:
412 fragments of 4 documents with vectors of the old title, cosine 0.97 to their text; a package exported from it
had none for them). The build drops them now, and embed finds once what an older build left."""

import os

from assistant_x.core import card as C
from assistant_x.core.common import connect, load_config
from assistant_x.search import embed as E, vector_cache as V
from tests.search.conftest import build, make_library
from tests.search.fake_embedder import embed


def retitle(root, code, title):
    p = os.path.join(root, "index", "cards", f"{code}.json")
    card = C.load(p)
    card["doc"]["title"] = {k: title for k in card["doc"]["title"]} if isinstance(card["doc"]["title"], dict) else title
    C.dump(card, p)


def unkeyed(cfg):
    """The fragments with a vector whose key the cache has not."""
    con = connect(cfg["db"], readonly=True)
    rows = E.fragments(con, "c.vec_row IS NOT NULL")
    con.close()
    fp = V.fingerprint(cfg)
    keys = E.keys_of(rows, fp, False)
    found = V.Cache(cfg).get(list(dict.fromkeys(keys)))
    return [r["id"] for r, k in zip(rows, keys) if k not in found]


def nulls(cfg, code):
    con = connect(cfg["db"], readonly=True)
    n = con.execute("SELECT count(*) FROM chunks WHERE code=? AND kind='text' AND vec_row IS NULL", (code,)).fetchone()[0]
    con.close()
    return n


def test_a_new_title_has_the_text_fragments_embedded_again(tmp_path):
    root = str(tmp_path / "A")
    path = make_library(root)
    build(path)
    embed(path)
    cfg = load_config(path)
    assert not unkeyed(cfg) and nulls(cfg, "N-00001") == 0
    retitle(root, "N-00001", "Quite another title of the standard")
    build(path)
    assert nulls(cfg, "N-00001") > 0  # their vectors were of the old title
    embed(path)
    assert nulls(cfg, "N-00001") == 0 and not unkeyed(cfg)


def test_embed_finds_once_the_stale_vectors_an_older_build_kept(tmp_path, monkeypatch):
    from assistant_x.search import build_index

    root = str(tmp_path / "A")
    path = make_library(root)
    build(path)
    embed(path)
    cfg = load_config(path)
    monkeypatch.setattr(build_index, "MODEL_TITLE_CHARS", 0)  # a build of 0.6: a new title kept the vectors
    retitle(root, "N-00002", "A title changed after the vectors")
    build(path)
    monkeypatch.undo()
    stale = unkeyed(cfg)
    assert stale and nulls(cfg, "N-00002") == 0
    embed(path)  # the first embed of this version: checks every key once, computes the stale ones
    assert not unkeyed(cfg)
    con = connect(cfg["db"], readonly=True)
    assert con.execute("SELECT value FROM meta WHERE key='vector_keys_checked'").fetchone()[0] == V.fingerprint(cfg)
    con.close()
