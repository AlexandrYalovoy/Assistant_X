# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Approximate index over vectors.f16 (FAISS IVF-PQ) so that meaning search stays in milliseconds on millions
of fragments. embed.py keeps it up to date; search.py uses it when present and falls back to exact search otherwise.
Usage: python -m assistant_x.search.ann [--config assistant_x.toml] [--rebuild]"""

import argparse, json, math, os, time
import numpy as np
from assistant_x.core.common import load_config, connect, touch, vectors_path

MIN_VECTORS = 200_000  # below this an exact search over all vectors takes well under a second


def paths(cfg, con):
    v = vectors_path(cfg, con)
    return v + ".ivfpq.faiss", v + ".ivfpq.json"


def save_index(index, path):
    """faiss.write_index cannot open non-ASCII paths on Windows (a Cyrillic user folder), so write the bytes ourselves."""
    import faiss

    with open(path, "wb") as f:
        faiss.serialize_index(index).tofile(f)


def load_index(path):
    import faiss

    return faiss.deserialize_index(np.fromfile(path, dtype=np.uint8))


def open_vectors(cfg, con):
    dim = int(con.execute("SELECT value FROM meta WHERE key='dim'").fetchone()[0])
    return np.memmap(vectors_path(cfg, con), dtype=np.float16, mode="r").reshape(-1, dim)


def update(cfg, rebuild=False):
    """Add new vectors to the index; train it anew when the library has grown 4x since the last training."""
    import faiss

    con = connect(cfg["db"])
    vecs = open_vectors(cfg, con)
    n, dim = vecs.shape
    ipath, mpath = paths(cfg, con)
    if n < cfg.get("ann_min_vectors", MIN_VECTORS):  # small library: exact search, drop a stale index if any
        for p in (ipath, mpath):
            if os.path.exists(p):
                os.remove(p)
        return
    info = json.load(open(mpath)) if os.path.exists(mpath) and os.path.exists(ipath) else None
    t0 = time.time()
    if rebuild or not info or n > 4 * info["trained_on"]:
        # [search] ann_nlist: a fixed number of clusters (the tests train on a few hundred vectors)
        nlist = int(cfg.get("ann_nlist") or 2 ** round(math.log2(min(16384, max(1024, 4 * math.sqrt(n))))))
        sample = np.sort(np.random.default_rng(0).choice(n, min(n, 40 * nlist), replace=False))
        index = faiss.index_factory(dim, f"IVF{nlist},PQ{dim // 16}", faiss.METRIC_INNER_PRODUCT)
        print(f"Training the embeddings index: {nlist} clusters, {len(sample)} vectors…", flush=True)
        index.train(np.asarray(vecs[sample], np.float32))
        info = dict(trained_on=n, nlist=nlist, ntotal=0)
    else:
        index = load_index(ipath)
    for i in range(info["ntotal"], n, 200_000):  # rows are only ever appended, so FAISS ids == row numbers
        index.add(np.asarray(vecs[i : i + 200_000], np.float32))
    info["ntotal"] = index.ntotal
    save_index(index, ipath + ".tmp")
    os.replace(ipath + ".tmp", ipath)
    json.dump(info, open(mpath, "w"))
    touch(con)
    con.commit()  # a running Claude reopens the index
    print(f"Embeddings index: {index.ntotal} vectors, {time.time() - t0:.0f} s.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    from assistant_x.core import debuglog

    debuglog.run(lambda: update(load_config(a.config), rebuild=a.rebuild), "ann")
