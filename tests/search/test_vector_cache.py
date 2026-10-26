# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The vector cache by content (search/vector_cache.py, embed.py): the model fingerprint (its files, never written
into the model folder; max_seq_length counts), the cache files (appended, a cut row dropped, compacted by switching
generations), embed taking the vectors of a full rebuild from the cache without loading the model, the vectors of an
existing base put into the cache (--seed-cache) and never under the key of another model."""

import hashlib, json, os, shutil

import numpy as np
import pytest

from assistant_x.core.common import connect, load_config, meta, vectors_path
from assistant_x.search import models, vector_cache as V
from tests.search.conftest import build, make_library
from tests.search.fake_embedder import embed


def model_folder(root, weights=b"weights"):
    d = os.path.join(root, "bge-m3")
    os.makedirs(d, exist_ok=True)
    for name, data in (("config.json", b'{"hidden_size": 64}'), ("tokenizer.json", b"{}"), ("pytorch_model.bin", weights)):
        with open(os.path.join(d, name), "wb") as f:
            f.write(data)
    return d


def listing(d):
    return sorted(
        (os.path.relpath(os.path.join(dp, f), d), os.path.getmtime(os.path.join(dp, f)))
        for dp, _, fns in os.walk(d)
        for f in fns
    )


def test_fingerprint_of_a_model_folder(tmp_path, monkeypatch):
    store = tmp_path / "machine" / "model_fingerprints.json"
    monkeypatch.setenv("AX_MODEL_FINGERPRINTS", str(store))
    d = model_folder(str(tmp_path))
    before = listing(d)
    fp = V.fingerprint({"embed_model": d})
    assert len(fp) == 16 and fp == V.fingerprint({"embed_model": d, "max_seq_length": 1024})
    assert listing(d) == before  # nothing is written into the model folder
    known = json.loads(store.read_text(encoding="utf-8"))
    assert list(known.values()) == [hashlib.sha256(b"weights").hexdigest()]  # hashed once, kept per PC
    assert V.fingerprint({"embed_model": d, "max_seq_length": 512}) != fp  # truncation gives other vectors
    model_folder(str(tmp_path), b"other weights")
    os.utime(os.path.join(d, "pytorch_model.bin"), (1, 2_000_000_000))
    assert V.fingerprint({"embed_model": d}) != fp
    # the name only: a HuggingFace name, or a folder without the files (the tests)
    assert V.fingerprint({"embed_model": "BAAI/bge-m3"}) == V.fingerprint({"embed_model": str(tmp_path / "x" / "bge-m3")})


def test_fingerprint_takes_the_sha256_huggingface_wrote(tmp_path, monkeypatch):
    store = tmp_path / "model_fingerprints.json"
    monkeypatch.setenv("AX_MODEL_FINGERPRINTS", str(store))
    d = model_folder(str(tmp_path))
    meta_dir = os.path.join(d, ".cache", "huggingface", "download")
    os.makedirs(meta_dir)
    sha = hashlib.sha256(b"weights").hexdigest()
    with open(os.path.join(meta_dir, "pytorch_model.bin.metadata"), "w", encoding="utf-8") as f:
        f.write(f"{'5' * 40}\n{sha}\n{os.path.getmtime(os.path.join(d, 'pytorch_model.bin')) + 5}\n")
    fp = V.fingerprint({"embed_model": d})
    assert not store.exists()  # no hashing of the weights
    os.remove(os.path.join(meta_dir, "pytorch_model.bin.metadata"))
    assert V.fingerprint({"embed_model": d}) == fp  # the same sha256, now computed


def test_cache_files(tmp_path):
    cache = V.Cache({"index_dir": str(tmp_path)})
    keys = [V.key("fp", "text", f"t{i}") for i in range(5)]
    vecs = np.eye(5, 4, dtype=np.float16)
    assert cache.add(keys, vecs) == 5 and cache.add(keys[:2], vecs[:2]) == 0 and len(cache) == 5
    got = cache.get([keys[3], V.key("fp", "text", "none")])
    assert list(got) == [keys[3]] and np.array_equal(got[keys[3]], vecs[3])
    with pytest.raises(ValueError):
        cache.add([V.key("fp", "text", "x")], np.zeros((1, 3)))
    with open(cache.keys_path, "ab") as f:  # a cut row after a power cut
        f.write(b"\1\2\3")
    again = V.Cache({"index_dir": str(tmp_path)})
    assert len(again) == 5 and again.add([V.key("fp", "text", "new")], np.ones((1, 4))) == 1
    assert np.array_equal(
        V.Cache({"index_dir": str(tmp_path)}).get([V.key("fp", "text", "new")])[V.key("fp", "text", "new")],
        np.ones(4, np.float16),
    )
    old_files = (again.keys_path, again.vecs_path)
    assert again.compact(keys[1:3]) == (6, 2)
    assert not any(os.path.exists(p) for p in old_files)
    fresh = V.Cache({"index_dir": str(tmp_path)})
    assert len(fresh) == 2 and fresh.generation == 1 and np.array_equal(fresh.get([keys[2]])[keys[2]], vecs[2])
    assert V.folder({"index_dir": str(tmp_path)}) == str(tmp_path / "vector_cache")


def embedded(root):
    path = make_library(root)
    build(path)
    embed(path)
    return path, load_config(path)


def base_vectors(cfg):
    """{(code, page, n, kind): vector} of the base in use."""
    con = connect(cfg["db"], readonly=True)
    dim = int(meta(con, "dim"))
    v = np.memmap(vectors_path(cfg, con), dtype=np.float16, mode="r").reshape(-1, dim)
    out = {
        (r["code"], r["page"], r["n"], r["kind"]): np.array(v[r["vec_row"]])
        for r in con.execute("SELECT code, page, n, kind, vec_row FROM chunks")
    }
    con.close()
    return out


def no_model(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the model was loaded")

    monkeypatch.setattr(models, "load_embedder", refuse)


def test_a_full_rebuild_takes_every_vector_from_the_cache(tmp_path, monkeypatch):
    path, cfg = embedded(str(tmp_path / "lib"))
    before = base_vectors(cfg)
    assert len(V.Cache(cfg)) == len(before)
    build(path, "--full")
    no_model(monkeypatch)
    embed(path)
    after = base_vectors(load_config(path))
    assert after.keys() == before.keys() and all(np.array_equal(after[k], before[k]) for k in before)
    con = connect(load_config(path)["db"], readonly=True)
    assert meta(con, "embed_fingerprint") == V.fingerprint(cfg) and meta(con, "vector_cache_seeded") == V.fingerprint(cfg)
    con.close()


def test_the_cache_stays_when_vector_files_are_swept(tmp_path):
    path, cfg = embedded(str(tmp_path / "lib"))
    n = len(V.Cache(cfg))
    build(path, "--full")
    embed(path, "--compact")
    assert len(V.Cache(cfg)) == n and os.path.isdir(V.folder(cfg))


def test_seed_cache_from_a_base_embedded_before_the_cache(tmp_path, monkeypatch, capsys):
    path, cfg = embedded(str(tmp_path / "lib"))
    shutil.rmtree(V.folder(cfg))  # a base of 2026-10-24: vectors, no cache, no note
    con = connect(cfg["db"])
    con.execute("DELETE FROM meta WHERE key IN ('vector_cache_seeded', 'embed_fingerprint')")
    con.commit()
    con.close()
    capsys.readouterr()
    embed(path, "--seed-cache")
    assert "vectors of" in capsys.readouterr().out
    assert len(V.Cache(cfg)) == len(base_vectors(cfg))
    build(path, "--full")
    no_model(monkeypatch)
    embed(path)


def test_a_base_without_the_note_is_seeded_by_embed_itself(tmp_path, monkeypatch):
    path, cfg = embedded(str(tmp_path / "lib"))
    shutil.rmtree(V.folder(cfg))
    con = connect(cfg["db"])
    con.execute("DELETE FROM meta WHERE key='vector_cache_seeded'")
    con.commit()
    con.close()
    build(path, "--full")  # the new base waits for its vectors; the base in use is seeded first
    no_model(monkeypatch)
    embed(path)
    assert len(V.Cache(cfg)) == len(base_vectors(load_config(path)))


def test_no_seeding_from_vectors_of_another_state_of_the_model(tmp_path):
    path, cfg = embedded(str(tmp_path / "lib"))
    shutil.rmtree(V.folder(cfg))
    con = connect(cfg["db"])
    con.execute("UPDATE meta SET value='0000000000000000' WHERE key='embed_fingerprint'")
    con.commit()
    con.close()
    embed(path, "--seed-cache")
    assert len(V.Cache(cfg)) == 0


def test_without_the_model_what_the_cache_has_goes_in(tmp_path):
    path, cfg = embedded(str(tmp_path / "lib"))
    build(path, "--full")
    text = os.path.join(os.path.dirname(path), "index", "texts", "N-00002.md")
    with open(text, "a", encoding="utf-8") as f:
        f.write("A new paragraph about the gas outlet of the separator.\n")
    build(path)
    shutil.rmtree(cfg["embed_model"])
    import sys
    from assistant_x.search import embed as embed_mod
    from tests.search.fake_embedder import fake_models

    argv, sys.argv = sys.argv, ["embed.py", "--config", path]
    try:
        with fake_models(), pytest.raises(SystemExit, match="still without vectors"):
            embed_mod.main()  # not embed(): it would make the folder of the model
    finally:
        sys.argv = argv
    con = connect(
        cfg["db"]
        if not os.path.exists(os.path.join(cfg["index_dir"], "library.next"))
        else os.path.join(cfg["index_dir"], open(os.path.join(cfg["index_dir"], "library.next")).read().strip()),
        readonly=True,
    )
    left = con.execute("SELECT count(*) FROM chunks WHERE vec_row IS NULL").fetchone()[0]
    total = con.execute("SELECT count(*) FROM chunks").fetchone()[0]
    con.close()
    assert 0 < left < total


def test_the_index_of_the_keys():
    """KeyIndex finds every row of the keys file (keys that share their first 8 bytes too) and the rows added since,
    and nothing else, without a dict of every key."""
    rng = np.random.default_rng(3)
    keys = [rng.bytes(V.KEY_BYTES) for _ in range(5000)]
    keys[10] = keys[20][:8] + bytes(8)  # the same head, trailing zero bytes
    keys[11] = keys[20][:8] + b"\xff" * 8
    idx = V.KeyIndex(b"".join(keys))
    assert all(idx[k] == i for i, k in enumerate(keys)) and len(idx) == 5000
    assert b"x" * V.KEY_BYTES not in idx and idx.get(keys[20][:8] + b"\x01" * 8) is None
    idx[b"y" * V.KEY_BYTES] = 5000
    assert idx[b"y" * V.KEY_BYTES] == 5000 and len(idx) == 5001
    with pytest.raises(KeyError):
        idx[b"z" * V.KEY_BYTES]
    assert len(V.KeyIndex(b"")) == 0
