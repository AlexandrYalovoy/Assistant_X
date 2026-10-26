# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A full rebuild goes into a new file: the search keeps reading the old base until the new one is complete
(library.next while it waits for vectors, library.current after the switch); the base is in WAL mode. An update
chunks again only the pages that changed."""

import os, sys

import pytest

from assistant_x.search import build_index
from assistant_x.core import common
from tests.search.conftest import TEXTS, make_library
from assistant_x.search.retrieval import Library


@pytest.fixture
def own(tmp_path):
    """A mini library of this test only: the session one is shared with the other tests."""
    path = make_library(str(tmp_path / "Библиотека"))
    run(path)
    return path


def run(config, *args):
    argv = sys.argv
    sys.argv = ["build_index.py", "--config", config, "--no-check", *args]
    try:
        build_index.main()
    finally:
        sys.argv = argv


def test_wal_and_busy_timeout(own):
    cfg = common.load_config(own)
    assert common.connect(cfg["db"]).execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert common.connect(cfg["db"], readonly=True).execute("PRAGMA busy_timeout").fetchone()[0] == common.BUSY_S * 1000


def test_full_rebuild_without_vectors_switches_at_once(own):
    lib = Library(common.load_config(own))
    old = lib.cfg["db"]
    assert os.path.basename(old) == "library.sqlite" and lib.search("обводнённости", dense=False)
    run(own, "--full")
    new = common.current_db(lib.cfg["index_dir"])
    assert new != old and os.path.basename(new).startswith("library-")
    assert lib.search("обводнённости", dense=False) and lib.cfg["db"] == new  # the running search moved over
    if os.name == "nt":
        assert os.path.exists(old)  # the search still held it during the switch: kept (Windows locks an open file)
    # POSIX unlinks an open file: the old base may be gone at once, which is right too
    common.drop_stale_dbs(lib.cfg)  # the next build or embed.py: nobody holds it now
    assert not os.path.exists(old)
    assert common.load_config(own)["db"] == new


def test_full_rebuild_waits_for_vectors(own, monkeypatch):
    monkeypatch.setattr(build_index, "had_vectors", lambda cfg, db: True)
    lib = Library(common.load_config(own))
    old = lib.cfg["db"]
    run(own, "--full")
    pending = common.next_db(lib.cfg["index_dir"])
    assert pending and pending != old
    assert lib.search("обводнённости", dense=False) and lib.cfg["db"] == old  # still the old, complete base
    run(own)  # an update between the two goes into the base that is coming
    assert common.next_db(lib.cfg["index_dir"]) == pending
    common.switch_db(dict(lib.cfg), pending)  # what embed.py does when all fragments have vectors
    assert lib.search("обводнённости", dense=False) and lib.cfg["db"] == pending
    assert common.next_db(lib.cfg["index_dir"]) is None


def test_one_page_edited_only_its_fragments_are_made_anew(own):
    """Base schema 3: an edited page is chunked again (new fragment numbers, no vectors yet); the fragments of the
    other pages and of the card keep their numbers and vectors, so embed.py computes only the edited page."""
    cfg = common.load_config(own)
    con = common.connect(cfg["db"])
    con.execute("UPDATE chunks SET vec_row = id")  # as if embed.py had given every fragment its vector
    con.commit()
    before = {r[0]: (r[1], r[2], r[3]) for r in con.execute("SELECT id, code, page, kind FROM chunks")}
    con.close()
    path = os.path.join(os.path.dirname(own), "index", "texts", "N-00001.md")
    pages = TEXTS["N-00001"][:1] + [TEXTS["N-00001"][1] + " Замер повторяют после ремонта скважины."] + TEXTS["N-00001"][2:]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(f"=== page {i + 1} ===\n\n{p}\n\n" for i, p in enumerate(pages)))
    run(own)
    con = common.connect(cfg["db"], readonly=True)
    after = {r[0]: (r[1], r[2], r[3], r[4]) for r in con.execute("SELECT id, code, page, kind, vec_row FROM chunks")}
    kept = {i for i in before if i in after}
    assert {before[i] for i in set(before) - kept} == {("N-00001", 2, "text")}  # only the edited page is gone
    assert all(after[i][3] == i for i in kept)  # the others keep their vectors
    new = {i: v for i, v in after.items() if i not in before}
    assert new and all(v[:3] == ("N-00001", 2, "text") and v[3] is None for v in new.values())
    assert min(new) > max(before)  # fragment numbers are never reused
    assert con.execute("SELECT text FROM pages WHERE code='N-00001' AND page=2").fetchone()[0] == pages[1]
    con.close()
    lib = Library(cfg)
    assert lib.search("после ремонта скважины", dense=False)[0]["page"] == 2


class _Encoder:
    """A stand-in for SentenceTransformer: records what it is given, returns unit vectors of dimension 4."""

    seen = []

    def __init__(self, name, device=None):
        self.device = __import__("types").SimpleNamespace(type="cpu")

    def get_sentence_embedding_dimension(self):
        return 4

    def encode(self, texts, **kw):
        import numpy as np

        _Encoder.seen += list(texts)
        return np.tile(np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float32), (len(texts), 1))


def test_embed_takes_the_search_text_of_the_new_fragments(own, monkeypatch):
    """embed.py on a base of schema 3: every fragment once, by its search text without the Markdown marks; after an
    edit of one page only its new fragments."""
    import types
    from assistant_x.core import gpu_guard
    from assistant_x.search import embed

    os.makedirs(os.path.join(os.path.dirname(own), "models", "bge-m3"), exist_ok=True)
    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=_Encoder))
    monkeypatch.setattr(gpu_guard, "hold_machine", lambda *a, **k: None)
    monkeypatch.setattr(gpu_guard, "check", lambda *a, **k: "cpu")
    monkeypatch.setattr(embed, "update_ann", lambda cfg, rebuild=False: None)

    def embed_all():
        _Encoder.seen = []
        argv = sys.argv
        sys.argv = ["embed.py", "--config", own]
        try:
            embed.main()
        finally:
            sys.argv = argv
        return list(_Encoder.seen)

    first = embed_all()
    con = common.connect(common.load_config(own)["db"], readonly=True)
    assert len(first) == con.execute("SELECT count(*) FROM chunks").fetchone()[0]
    assert not con.execute("SELECT 1 FROM chunks WHERE vec_row IS NULL").fetchone()
    con.close()
    # the section, then the piece of the page without its "# "
    assert any(
        t.endswith(
            "\n2. Расчёт дебита\n2. Расчёт дебита\n\nДебит скважины определяют по табл. 1 с учётом "
            "обводнённости продукции и газового фактора. Замер выполняют на замерной установке не реже "
            "одного раза в сутки."
        )
        for t in first
    )
    assert not any(line.startswith("#") for t in first for line in t.splitlines())  # no heading marks
    path = os.path.join(os.path.dirname(own), "index", "texts", "N-00002.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"=== page 1 ===\n\n{TEXTS['N-00002'][0]} Изменённая строка.\n\n")
    run(own)
    again = embed_all()
    assert len(again) == 1 and "Изменённая строка." in again[0]
