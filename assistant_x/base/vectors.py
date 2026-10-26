# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The vectors of a base package (vectors/meta.json, keys.bin, vectors.f16): checked before they reach the vector
cache of the workspace. A package is data from someone else, and a vector decides where a fragment ranks for every
question, so its vectors are trusted only as far as they are checked:

  problems(pkg, man, cfg)   inspect: the three files together, meta.json against the manifest, the sizes against
                            rows and dim, the dimension against the model here (when the vectors are of it), unique
                            keys, every vector finite and of length 1 (the model gives normalized vectors)
  install(config, pkg_dir, ident)   the install and the update, after the base is built with the package documents:
                            only the keys of fragments of this package's documents that have no vector yet are taken
                            (a key of another document, the user's own above all, is never set by a package); a random
                            sample of them (sample_size) is encoded again with the model here when it is on this PC (cosine >= 0.99
                            to the package's vector), and all the package's vectors are dropped when one is not —
                            embed then computes them. Without the model the sample is skipped and the report says so.

What this does not guarantee: a package whose vectors pass may still rank its own fragments by their real meaning,
and its texts are what Claude reads (docs/PACKAGES.md, SECURITY.md)."""

import json, math, os, random

import numpy as np

FILES = ("vectors/meta.json", "vectors/keys.bin", "vectors/vectors.f16")
NORM_TOLERANCE = 0.02  # float16 of a normalized vector: its length within 1 +- this
MIN_COSINE = 0.99  # a vector encoded again here against the package's one (fp16 and the variants give >= 0.99)
# the vectors encoded again: a share of the package's own, at least SAMPLE_MIN (all of a small package), at most
# SAMPLE_MAX (about 3 minutes on a processor, seconds on a video card)
SAMPLE_MIN, SAMPLE_SHARE, SAMPLE_MAX = 32, 0.05, 256
BLOCK = 4096  # rows read at a time


def sample_size(n):
    """How many of n package vectors are encoded again: SAMPLE_SHARE of them within SAMPLE_MIN and SAMPLE_MAX."""
    return min(n, max(SAMPLE_MIN, math.ceil(n * SAMPLE_SHARE)), SAMPLE_MAX)


def expected_dim(cfg):
    """The dimension of the vectors of this workspace: of its vector cache, else of its base, else of the config of
    its model folder; None when nothing tells."""
    from assistant_x.core.common import connect, has_meta, meta
    from assistant_x.search import vector_cache as V

    dim = V.Cache(cfg).dim
    if dim:
        return int(dim)
    if os.path.exists(cfg.get("db") or ""):
        con = connect(cfg["db"], readonly=True)
        try:
            if has_meta(con) and meta(con, "dim"):
                return int(meta(con, "dim"))
        finally:
            con.close()
    p = os.path.join(cfg.get("embed_model") or "", "config.json")
    try:
        return int(json.load(open(p, encoding="utf-8"))["hidden_size"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def problems(pkg, man, cfg):
    """[problems] of the vectors of a package (an empty list: none, or they are whole)."""
    from assistant_x.search import vector_cache as V

    names = set(pkg.names())
    have = [f for f in FILES if f in names]
    if not have:
        return ["axbase.json describes vectors the package has not"] if man.get("embed") else []
    if len(have) != len(FILES):
        return [f"the vectors are not whole: {', '.join(sorted(set(FILES) - set(have)))} missing"]
    try:
        info = json.loads(pkg.read("vectors/meta.json").decode("utf-8"))
        dim, rows = info["dim"], info["rows"]
        assert isinstance(dim, int) and isinstance(rows, int) and dim > 0 and rows >= 0
    except (ValueError, KeyError, TypeError, AssertionError):
        return ["vectors/meta.json does not read (dim and rows are needed)"]
    emb = man.get("embed") or {}
    out = []
    for k in ("fingerprint", "dim", "rows"):
        if emb.get(k) != info.get(k):
            out.append(f"vectors/meta.json {k} {info.get(k)!r}, axbase.json {emb.get(k)!r}")
    if pkg.size("vectors/keys.bin") != rows * V.KEY_BYTES:
        out.append(f"vectors/keys.bin has {pkg.size('vectors/keys.bin')} bytes, {rows} keys need {rows * V.KEY_BYTES}")
    if pkg.size("vectors/vectors.f16") != rows * dim * 2:
        out.append(
            f"vectors/vectors.f16 has {pkg.size('vectors/vectors.f16')} bytes, {rows} vectors of dimension "
            f"{dim} need {rows * dim * 2}"
        )
    if out:
        return out
    if info.get("fingerprint") == V.fingerprint(cfg):
        here = expected_dim(cfg)
        if here and here != dim:
            out.append(f"the vectors have dimension {dim}, the model here {here}")
    keys = pkg.read("vectors/keys.bin")
    if len({keys[i : i + V.KEY_BYTES] for i in range(0, len(keys), V.KEY_BYTES)}) != rows:
        out.append("vectors/keys.bin names a key twice")
    bad = 0
    with pkg.open("vectors/vectors.f16") as f:
        for start in range(0, rows, BLOCK):
            n = min(BLOCK, rows - start)
            v = np.frombuffer(f.read(n * dim * 2), dtype=np.float16).astype(np.float32).reshape(n, dim)
            norm = np.linalg.norm(v, axis=1)
            bad += int((~np.isfinite(v).all(axis=1) | (np.abs(norm - 1) > NORM_TOLERANCE)).sum())
    if bad:
        out.append(f"{bad} vectors are not of length 1 (the model gives normalized vectors)")
    return out


def _encoder(cfg):
    """The embedding model of this workspace on the processor in float32 when its folder is on this PC, else
    (None, why): nothing is downloaded for a check."""
    from assistant_x.search import models

    path = cfg.get("embed_model") or ""
    if not os.path.isdir(path):
        return None, f"no embedding model at {path or '?'}"
    try:
        return models.load_embedder(dict(cfg, cpu_int8=False), "cpu"), ""
    except Exception as e:  # noqa: BLE001 — a model that does not load: the check is skipped and said
        return None, f"the embedding model does not load ({type(e).__name__}: {e})"


def install(config, pkg_dir, ident, codes):
    """The checked vectors of the package into the vector cache, after the base is built with its documents (codes:
    their codes here). {added, offered, foreign, verified, note}."""
    from assistant_x.base.install import Stop
    from assistant_x.core.common import connect, has_meta, load_config, model_text, next_db
    from assistant_x.search import embed, vector_cache as V

    out = {"added": 0, "offered": 0, "foreign": 0, "verified": "", "note": ""}
    meta_p = os.path.join(pkg_dir, "vectors", "meta.json")
    if not os.path.exists(meta_p):
        return out
    cfg = load_config(config)
    info = json.load(open(meta_p, encoding="utf-8"))
    fp = V.fingerprint(cfg)
    if info.get("fingerprint") != fp:
        out["note"] = "the vectors of the package are of another state of the model: embed computes them"
        return out
    dim = int(info["dim"])
    raw = open(os.path.join(pkg_dir, "vectors", "keys.bin"), "rb").read()
    keys = [raw[i : i + V.KEY_BYTES] for i in range(0, len(raw), V.KEY_BYTES)]
    vecs = np.fromfile(os.path.join(pkg_dir, "vectors", "vectors.f16"), dtype=np.float16)
    if vecs.size != len(keys) * dim:
        raise Stop(f"the vectors of package {ident} do not match their keys ({vecs.size} values, {len(keys)} keys)")
    vecs = vecs.reshape(-1, dim)
    out["offered"] = len(keys)
    db = next_db(cfg["index_dir"]) or cfg["db"]  # a full rebuild waiting for its vectors: its fragments
    con = connect(db, readonly=True)
    try:
        if not has_meta(con):
            raise Stop("the search base is not built: the vectors of the package wait (assistant-x build)")
        mains, rows = sorted(codes), []
        for i in range(0, len(mains), 500):
            part = mains[i : i + 500]
            q = ",".join("?" * len(part))
            rows += embed.fragments(con, f"c.vec_row IS NULL AND (c.code IN ({q}) OR d.parent IN ({q}))", part + part)
    finally:
        con.close()
    table_rows = bool(cfg.get("table_rows", False))
    own = dict(zip(embed.keys_of(rows, fp, table_rows), rows))
    take = [i for i, k in enumerate(keys) if k in own]
    out["foreign"] = len(keys) - len(take)
    if not take:
        return out
    model, why = _encoder(cfg)
    if model is None:
        out["verified"] = f"skipped: {why}"
    else:
        sample = random.Random().sample(take, sample_size(len(take)))
        texts = [
            model_text(own[keys[i]]["title"], own[keys[i]]["heading"], own[keys[i]]["text"], table_rows) for i in sample
        ]
        fresh = np.asarray(model.encode(texts, normalize_embeddings=True, convert_to_numpy=True), dtype=np.float32)
        given = vecs[sample].astype(np.float32)
        given /= np.linalg.norm(given, axis=1, keepdims=True)
        cos = float((fresh * given).sum(axis=1).min()) if fresh.shape == given.shape else -1.0
        if cos < MIN_COSINE:
            out["verified"] = f"rejected: a vector encoded again here differs (cosine {cos:.3f} < {MIN_COSINE})"
            out["note"] = "the vectors of the package do not match the model here: none is used, embed computes them"
            return out
        out["verified"] = f"{len(sample)} of {len(take)} encoded again, cosine >= {cos:.3f}"
    cache = V.Cache(cfg)
    if cache.dim and cache.dim != dim:
        raise Stop(
            f"the vector cache holds vectors of dimension {cache.dim}, the package {dim}: its vectors are not "
            "used (assistant-x base install … --rollback)"
        )
    try:
        out["added"] = cache.add([keys[i] for i in take], vecs[take])
    except ValueError as e:
        raise Stop(f"the vectors of package {ident}: {e}") from e
    if out["foreign"]:
        out["note"] = f"{out['foreign']} vectors of the package are not of fragments of its own documents here: left out"
    return out
