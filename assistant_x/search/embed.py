# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compute meaning vectors for fragments that have none yet (run on the GPU machine).
Vectors are appended to vectors.f16 (float16, normalized); chunks.vec_row points at the row. The fragments of the
pages that did not change keep their vectors (build_index.py keeps their rows). A fragment is embedded by its search
text (its lead and its piece of the page, common.chunk_search_text) under the short title of its document and its
section heading, without the Markdown markup (common.model_text: what the reranker reads too); with
[search] table_rows = true in assistant_x.toml a table becomes a line per row "header: value; …".
A fragment whose text the model read before takes its vector from the vector cache (search/vector_cache.py) instead
of the model; with every fragment there the model is not even loaded. The vectors of a base made before the cache are
put into it first (once; --seed-cache does only that).
Usage: assistant-x embed [--config assistant_x.toml] [--batch 64] [--codes L-00015 ...] [--compact] [--seed-cache]
                         [--wait | --cpu]
--wait: the video card has less free memory than gpu_min_free_gb, wait for it; --cpu: compute on the CPU (gpu_guard.py)."""

import argparse, os, time
import numpy as np
from assistant_x.core import gpu_guard
from assistant_x.search import models, vector_cache
from assistant_x.core.common import (
    load_config,
    connect,
    has_column,
    meta,
    touch,
    vectors_path,
    new_vectors_file,
    drop_stale_vectors,
    folder_bytes,
    free_space_problem,
    current_db,
    next_db,
    switch_db,
    model_text,
    require_built,
    PAGES_JOIN_SQL,
    SEARCH_TEXT_SQL,
)
from assistant_x.core.common import for_embedding, table_lines  # noqa: F401 — their former home: the names stay here


CPU_S = 0.8  # seconds per fragment of bge-m3 on a processor, until this PC has measured its own


def fragments(con, where="c.vec_row IS NULL", args=()):
    """The fragments of where: id, vec_row, kind and what the models read of them (the title of the document, the
    heading, the search text), in a base of any schema; the longest first."""
    head = "c.heading" if has_column(con, "chunks", "heading") else "'' AS heading"
    kind = "c.kind" if has_column(con, "chunks", "kind") else "'text' AS kind"
    # schema 3: the text of a fragment is a piece of its page (pages), or its own text (a card, a unit)
    text, join = ("c.text", "") if has_column(con, "chunks", "text") else (SEARCH_TEXT_SQL, PAGES_JOIN_SQL)
    sql = (
        f"SELECT c.id, c.vec_row, {kind}, {text} AS text, {head}, d.title FROM chunks c JOIN docs d ON d.code=c.code "
        f"{join} WHERE {where}"
    )
    # longest first keeps batches of similar length: noticeably faster on GPU
    return con.execute(sql + " ORDER BY length(text) DESC", args).fetchall()


def keys_of(rows, fp, table_rows):
    """The keys of the vector cache of fragments (vector_cache.key of what the model reads of each)."""
    return [vector_cache.key(fp, r["kind"], model_text(r["title"], r["heading"], r["text"], table_rows)) for r in rows]


def seed(con, cfg, cache, fp):
    """Put the vectors of the base into the cache (a base embedded before the cache was there): (rows added, None),
    or (0, why not)."""
    dim, path = meta(con, "dim"), vectors_path(cfg, con)
    if not dim or not os.path.exists(path) or not os.path.getsize(path):
        return 0, "the base has no vectors yet"
    wrong = models.model_mismatch(cfg, con)
    had = meta(con, "embed_fingerprint")
    if wrong or (had and had != fp):  # never vectors of another model under the key of this one
        return 0, wrong or "its vectors were made by another state of the model (embed_fingerprint)"
    vecs = np.memmap(path, dtype=np.float16, mode="r").reshape(-1, int(dim))
    rows = [r for r in fragments(con, "c.vec_row IS NOT NULL") if r["vec_row"] < len(vecs)]
    added, table_rows = 0, bool(cfg.get("table_rows", False))
    for i in range(0, len(rows), 10_000):
        part = rows[i : i + 10_000]
        added += cache.add(keys_of(part, fp, table_rows), np.asarray(vecs[[r["vec_row"] for r in part]]))
    del vecs
    con.execute("INSERT OR REPLACE INTO meta VALUES('vector_cache_seeded', ?)", (fp,))
    con.commit()
    return added, None


def seed_all(cfg, con, cache, fp):
    """seed() for the base being embedded and the base the search uses (when they differ: a full rebuild waiting)."""
    for db in dict.fromkeys(p for p in (current_db(cfg["index_dir"]), cfg["db"]) if os.path.exists(p)):
        c = con if db == cfg["db"] else connect(db)
        try:
            added, why = seed(c, cfg, cache, fp)
        finally:
            if c is not con:
                c.close()
        print(
            f"Vector cache: {added} vectors of {os.path.basename(db)} added, {len(cache)} in all"
            + (f" ({why})" if why else "")
            + "."
        )


def main():
    ap = argparse.ArgumentParser(prog="assistant-x embed")
    ap.add_argument("--config")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--codes", nargs="*")
    ap.add_argument("--compact", action="store_true")
    ap.add_argument("--seed-cache", action="store_true", help="only put the vectors of the base into the vector cache")
    gpu_guard.add_arguments(ap)
    a = ap.parse_args()
    gpu_guard.hold_machine("embed", wait=a.wait)
    cfg = load_config(a.config)
    pending = next_db(cfg["index_dir"])  # a full rebuild waiting for its vectors: they go there, then the search switches
    cfg["db"] = pending or cfg["db"]
    low = free_space_problem(cfg["index_dir"], folder_bytes(cfg["db"]))
    if low:
        raise SystemExit(low)
    con = connect(cfg["db"])
    require_built(con, cfg["db"])
    drop_stale_vectors(cfg, con)
    fp, cache = vector_cache.fingerprint(cfg), vector_cache.Cache(cfg)
    if a.compact:
        return compact(con, cfg, cache, fp)
    if a.seed_cache or any(meta(c, "vector_cache_seeded") != fp and meta(c, "dim") for c in _bases(cfg, con)):
        seed_all(cfg, con, cache, fp)  # once: a later full build or new codes then recompute none of these
        if a.seed_cache:
            return 0
    args, where = [], "c.vec_row IS NULL"
    if a.codes:
        where += f" AND c.code IN ({','.join('?' * len(a.codes))})"
        args = a.codes
    todo = fragments(con, where, args)
    if not todo and not pending:
        print("Nothing to compute: every fragment of the base has its embedding.")
        return 0
    wrong = models.model_mismatch(cfg, con)  # one base, one model: never vectors of two models in one file
    if wrong:
        raise SystemExit(wrong)
    rows = bool(cfg.get("table_rows", False))
    keys = keys_of(todo, fp, rows)
    hits = cache.get(keys)
    misses = [i for i, k in enumerate(keys) if k not in hits]
    seeded = meta(con, "vector_cache_seeded") == fp or not meta(con, "dim")  # the cache has every vector of the base
    model_path = cfg.get("embed_model") or ""
    print(
        f"Fragments to compute: {len(todo)}"
        + (f", {len(todo) - len(misses)} of them taken from the vector cache" if hits else "")
    )
    model, dim = None, cache.dim if hits else None
    no_model = ""
    if misses and (os.path.isabs(model_path) or os.sep in model_path) and not os.path.isdir(model_path):
        no_model = (
            f"No embedding model {model_path}: assistant-x download-models (or copy the folder of the model "
            f"there). The search by words works without it."
        )
        if not hits:
            raise SystemExit(no_model)
        misses = []  # what the cache has goes in still; the rest waits for the model
    if misses:
        # bge-m3 on a CPU: ~0.8 s per fragment until this PC has measured its own speed (gpu_guard: speed.json; a
        # laptop processor of 2025 does about 1.3 fragments/s in float32); no silent fallback from the card
        cfg["device"] = gpu_guard.check(
            cfg, "embed", units=len(misses), unit="fragments", cpu_s=CPU_S, wait=a.wait, cpu=a.cpu
        )
        model = models.load_embedder(cfg, cfg["device"])  # torch, DirectML or int8 on the processor: the same vectors
        dim = (getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension)()  # renamed in 5.x
        if cache.dim and cache.dim != dim:
            raise SystemExit(
                f"The vector cache holds vectors of dimension {cache.dim}, the model {dim}: delete the "
                f"folder {vector_cache.folder(cfg)} and run again."
            )
    old = con.execute("SELECT value FROM meta WHERE key='dim'").fetchone()
    if old and dim and int(old[0]) != dim:
        raise SystemExit(f"The base has vectors of dimension {old[0]}, the model {dim}: delete vectors.f16 and run again.")
    if dim:
        con.execute("INSERT OR REPLACE INTO meta VALUES('dim', ?)", (str(dim),))
    # the name of the model, not its folder: a base copied to another PC keeps it. The variant (fp16 on a card, fp32,
    # int8 on a processor) is only for the record: they give the vectors of one model, compatible by design
    con.execute("INSERT OR REPLACE INTO meta VALUES('embed_model', ?)", (models.model_name(model_path or "bge-m3"),))
    con.execute("INSERT OR REPLACE INTO meta VALUES('embed_fingerprint', ?)", (fp,))
    if model is not None:
        con.execute("INSERT OR REPLACE INTO meta VALUES('embed_variant', ?)", (getattr(model, "variant", ""),))
    path = vectors_path(cfg, con)
    row = os.path.getsize(path) // (dim * 2) if dim and os.path.exists(path) else 0
    t0 = time.time()
    with open(path, "ab") as f:
        found = [i for i in range(len(todo)) if keys[i] in hits]
        for i in range(0, len(found), 10_000):  # the vectors the cache has: no model needed
            part = found[i : i + 10_000]
            f.write(np.stack([hits[keys[j]] for j in part]).astype(np.float16).tobytes())
            f.flush()
            con.executemany("UPDATE chunks SET vec_row=? WHERE id=?", [(row + n, todo[j]["id"]) for n, j in enumerate(part)])
            con.commit()
            row += len(part)
        for i in range(0, len(misses), a.batch * 16):
            part = misses[i : i + a.batch * 16]
            texts = [model_text(todo[j]["title"], todo[j]["heading"], todo[j]["text"], rows) for j in part]
            v = model.encode(texts, batch_size=a.batch, normalize_embeddings=True, convert_to_numpy=True).astype(np.float16)
            f.write(v.tobytes())
            f.flush()
            con.executemany("UPDATE chunks SET vec_row=? WHERE id=?", [(row + n, todo[j]["id"]) for n, j in enumerate(part)])
            con.commit()
            cache.add([keys[j] for j in part], v)
            row += len(part)
            done = i + len(part)
            print(f"  {done}/{len(misses)}  {done / max(time.time() - t0, 1e-3):.0f} fragments/s", flush=True)
    if seeded:
        con.execute("INSERT OR REPLACE INTO meta VALUES('vector_cache_seeded', ?)", (fp,))
    con.commit()
    if misses:  # the speed of this PC for the next estimates (50 fragments or more)
        gpu_guard.record_speed("fragments", cfg["device"], (time.time() - t0) / len(misses), n=len(misses))
    update_ann(cfg)
    if todo:
        touch(con)
        con.commit()  # a running Claude reloads the vectors with the new fragments
    if pending and not a.codes and not con.execute("SELECT 1 FROM chunks WHERE vec_row IS NULL LIMIT 1").fetchone():
        con.close()
        switch_db(cfg, pending)
        print(f"The search now uses the new base {os.path.basename(pending)}.")
    if no_model:
        raise SystemExit(f"{len(keys) - len(hits)} fragments still without vectors. {no_model}")
    print("Done.")


def _bases(cfg, con):
    """The connection being embedded, and the base the search uses when it is another file (read only)."""
    yield con
    in_use = current_db(cfg["index_dir"])
    if os.path.exists(in_use) and os.path.normcase(os.path.abspath(in_use)) != os.path.normcase(os.path.abspath(cfg["db"])):
        c = connect(in_use, readonly=True)
        try:
            yield c
        finally:
            c.close()


def update_ann(cfg, rebuild=False):
    try:
        from assistant_x.search import ann

        ann.update(cfg, rebuild=rebuild)
    except ImportError:  # faiss is not installed: search stays exact, which is fine for a small library
        print("faiss is not installed: no embeddings index was built (the search compares every vector).")


def compact(con, cfg, cache=None, fp=None):
    """Drop vectors of deleted fragments (after many documents were replaced), in the base and in the vector cache
    (it keeps the vectors of the base in use and of the one being rebuilt)."""
    dim = meta(con, "dim")
    if dim and os.path.exists(vectors_path(cfg, con)):
        vecs = np.memmap(vectors_path(cfg, con), dtype=np.float16, mode="r").reshape(-1, int(dim))
        rows = con.execute("SELECT id, vec_row FROM chunks WHERE vec_row IS NOT NULL ORDER BY vec_row").fetchall()
        path = new_vectors_file(cfg, con)  # a new file: the old one may be open in Claude right now
        with open(path, "wb") as f:
            for i in range(0, len(rows), 100_000):
                part = rows[i : i + 100_000]
                f.write(np.asarray(vecs[[r["vec_row"] for r in part]]).tobytes())
        con.executemany("UPDATE chunks SET vec_row=? WHERE id=?", [(j, r["id"]) for j, r in enumerate(rows)])
        con.commit()
        del vecs  # file name and row numbers switch together
        drop_stale_vectors(cfg, con)
        print(f"Vectors left: {len(rows)}")
        update_ann(cfg, rebuild=True)  # row numbers changed
        touch(con)
        con.commit()
    else:
        print("The base has no vectors yet: nothing to compact in it.")
    if cache is not None and cache.dim:
        keep, table_rows = set(), bool(cfg.get("table_rows", False))
        for c in _bases(cfg, con):
            keep.update(keys_of(fragments(c, "1"), fp, table_rows))
        before, after = cache.compact(keep)
        print(f"Vector cache: {after} of {before} vectors kept")


if __name__ == "__main__":
    from assistant_x.core import debuglog

    debuglog.run(main, "embed")
