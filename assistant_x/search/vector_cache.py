# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""The vectors of the meaning search by content: a fragment whose text the model read before gets its vector back
instead of being encoded again — after `build --full`, after new codes (a base install), in another base of the same
workspace. The folder .assistant_x\db\vector_cache\ (never at the top of db\: the vector files there are swept):

    meta.json        {"format": 1, "dim": 1024, "generation": g}
    keys-<g>.bin     16 bytes per row: the key of the fragment
    vectors-<g>.f16  dim float16 per row, normalized, the same row order

key = sha256(model fingerprint, kind of the fragment, common.model_text of it)[:16]. Rows are only appended (a cut
row after a power cut is dropped on reading: the shorter of the two files counts); compact() writes the keys given
into the files of the next generation and switches meta.json to them at once.
One writer at a time: embed.py, under the machine lock.

The model fingerprint (fingerprint(cfg)): the name of the model, the sha256 of its config.json and tokenizer.json,
the sha256 of its weights (model.safetensors, else pytorch_model.bin: the etag HuggingFace wrote beside a download
when it is a sha256, else hashed once and kept in %USERPROFILE%\.assistant_x\model_fingerprints.json by path, size
and date — never written into the model folder, which may be read-only or linked), max_seq_length and the
normalization. A model folder without these files (a HuggingFace name, the tests) counts by its name.
"""

import hashlib, json, os, re

import numpy as np

from assistant_x.core import env, workspace

FOLDER = "vector_cache"
KEY_BYTES = 16
FORMAT = 1
WEIGHTS = ("model.safetensors", "pytorch_model.bin")
SHA_RX = re.compile(r"[0-9a-f]{64}")
GEN_RX = re.compile(r"(keys-\d+\.bin|vectors-\d+\.f16)(\.new)?")


def folder(cfg):
    return os.path.join(cfg["index_dir"], FOLDER)


# ---------- the model fingerprint ----------


def fingerprints_file():
    return env.get("MODEL_FINGERPRINTS") or str(workspace.machine_dir() / "model_fingerprints.json")


def _sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def _hf_etag(model_dir, name):
    """The sha256 HuggingFace wrote beside a downloaded file (.cache/huggingface/download/<name>.metadata: the
    commit, the etag, the time of the download), or None — also when the file is newer than the note (replaced since)."""
    p = os.path.join(model_dir, ".cache", "huggingface", "download", name + ".metadata")
    try:
        lines = [x.strip().strip('"') for x in open(p, encoding="utf-8").read().splitlines()]
        when = float(lines[2])
    except (OSError, IndexError, ValueError):
        return None
    if os.path.getmtime(os.path.join(model_dir, name)) > when + 1:
        return None
    return lines[1] if SHA_RX.fullmatch(lines[1]) else None


def weights_sha(path):
    """sha256 of a weights file, once per path, size and date (model_fingerprints.json of this PC)."""
    st = os.stat(path)
    key = f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime_ns}"
    store = fingerprints_file()
    try:
        known = json.load(open(store, encoding="utf-8"))
    except (OSError, ValueError):
        known = {}
    if key not in known:
        known[key] = _sha_file(path)
        os.makedirs(os.path.dirname(store), exist_ok=True)
        with open(store + ".tmp", "w", encoding="utf-8") as f:
            json.dump(known, f, indent=1, sort_keys=True)
        os.replace(store + ".tmp", store)
    return known[key]


def model_identity(model):
    """{name, config, tokenizer, weights} of a model folder (a HuggingFace name: its name only)."""
    from assistant_x.search.models import model_name

    out = {"name": model_name(model or "bge-m3")}
    if model and os.path.isdir(model):
        for key, name in (("config", "config.json"), ("tokenizer", "tokenizer.json")):
            p = os.path.join(model, name)
            if os.path.isfile(p):
                out[key] = _sha_file(p)
        w = next((n for n in WEIGHTS if os.path.isfile(os.path.join(model, n))), None)
        if w:
            out["weights"] = _hf_etag(model, w) or weights_sha(os.path.join(model, w))
    return out


def fingerprint(cfg):
    """16 hex characters naming the vectors cfg's embedding model gives: model, max_seq_length, normalized."""
    ident = dict(
        model_identity(cfg.get("embed_model") or "BAAI/bge-m3"),
        max_seq_length=int(cfg.get("max_seq_length", 1024)),
        normalized=True,
    )
    return hashlib.sha256(json.dumps(ident, sort_keys=True).encode()).hexdigest()[:16]


def key(fp, kind, text):
    """The key of a fragment: its model fingerprint, its kind and the text the model reads (common.model_text)."""
    return hashlib.sha256(f"{fp}\0{kind}\0{text}".encode("utf-8")).digest()[:KEY_BYTES]


# ---------- the cache ----------


class KeyIndex:
    """key -> row of the keys file without a Python object per row (a dict of 5 million keys took about 0.5 GB): the
    first 8 bytes of every key as a sorted uint64 array with the row of each, searched with searchsorted and confirmed
    on the whole key; the rows added after it was read in a small dict."""

    def __init__(self, raw):
        self.raw = raw
        n = len(raw) // KEY_BYTES
        heads = (
            np.frombuffer(raw, dtype=">u8", count=n * (KEY_BYTES // 8))[:: KEY_BYTES // 8] if n else np.zeros(0, dtype=">u8")
        )
        self.order = np.argsort(heads, kind="stable")
        self.heads = heads[self.order]
        self.added = {}

    def get(self, key, default=None):
        row = self.added.get(key)
        if row is not None:
            return row
        h = int.from_bytes(key[:8], "big")
        i = int(np.searchsorted(self.heads, h, side="left"))
        while i < len(self.heads) and int(self.heads[i]) == h:
            row = int(self.order[i])
            if self.raw[row * KEY_BYTES : (row + 1) * KEY_BYTES] == key:
                return row
            i += 1
        return default

    def __contains__(self, key):
        return self.get(key) is not None

    def __getitem__(self, key):
        row = self.get(key)
        if row is None:
            raise KeyError(key)
        return row

    def __setitem__(self, key, row):
        self.added[key] = row

    def __len__(self):
        return len(self.heads) + len(self.added)


class Cache:
    """The cache of a workspace: get(keys) -> {key: vector}, add(keys, vectors), compact(keep)."""

    def __init__(self, cfg):
        self.dir = folder(cfg)
        self.meta_path = os.path.join(self.dir, "meta.json")
        try:
            meta = json.load(open(self.meta_path, encoding="utf-8"))
            self.dim, gen = int(meta["dim"]), int(meta.get("generation", 0))
        except (OSError, ValueError, KeyError, TypeError):
            self.dim, gen = None, 0
        self._use(gen)

    def _use(self, gen):
        self.generation = gen
        self.keys_path = os.path.join(self.dir, f"keys-{gen}.bin")
        self.vecs_path = os.path.join(self.dir, f"vectors-{gen}.f16")
        self._index = None

    def _write_meta(self, dim, gen):
        os.makedirs(self.dir, exist_ok=True)
        with open(self.meta_path + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"format": FORMAT, "dim": dim, "generation": gen}, f)
        os.replace(self.meta_path + ".tmp", self.meta_path)

    def __len__(self):
        return len(self.index())

    def rows(self):
        """Rows complete in both files."""
        if not self.dim or not os.path.exists(self.keys_path) or not os.path.exists(self.vecs_path):
            return 0
        return min(os.path.getsize(self.keys_path) // KEY_BYTES, os.path.getsize(self.vecs_path) // (self.dim * 2))

    def index(self):
        """key -> row (KeyIndex: the keys of the file as a sorted array, the rows added since in a dict)."""
        if self._index is None:
            n = self.rows()
            self._index = KeyIndex(open(self.keys_path, "rb").read(n * KEY_BYTES) if n else b"")
        return self._index

    def get(self, keys):
        """{key: float16 vector} of the keys the cache has."""
        idx = self.index()
        found = [(k, idx[k]) for k in dict.fromkeys(keys) if k in idx]
        if not found:
            return {}
        vecs = np.memmap(self.vecs_path, dtype=np.float16, mode="r").reshape(-1, self.dim)
        out = {k: np.array(vecs[r]) for k, r in found}
        del vecs
        return out

    def add(self, keys, vectors):
        """Append the rows of the keys it does not have yet; vectors: an array (n, dim)."""
        vectors = np.asarray(vectors, dtype=np.float16)
        if not len(keys):
            return 0
        dim = vectors.shape[1]
        if self.dim is None:
            self._write_meta(dim, self.generation)
            self.dim = dim
            self._truncate(0)
            self._index = KeyIndex(b"")
        elif dim != self.dim:
            raise ValueError(f"the vector cache holds vectors of dimension {self.dim}, not {dim}")
        idx = self.index()
        n = self.rows()
        self._truncate(n)  # a cut row of an interrupted write goes
        new, seen = [], set()
        for i, k in enumerate(keys):
            if k not in idx and k not in seen:
                new.append(i)
                seen.add(k)
        if not new:
            return 0
        with open(self.vecs_path, "ab") as f:  # the vectors first: a key never points past them
            f.write(vectors[new].tobytes())
        with open(self.keys_path, "ab") as f:
            f.write(b"".join(keys[i] for i in new))
        for j, i in enumerate(new):
            idx[keys[i]] = n + j
        return len(new)

    def _truncate(self, n):
        for p, size in ((self.keys_path, n * KEY_BYTES), (self.vecs_path, n * (self.dim or 0) * 2)):
            if os.path.exists(p) and os.path.getsize(p) > size:
                with open(p, "r+b") as f:
                    f.truncate(size)

    def compact(self, keep):
        """Keep only the rows of the keys in keep; returns (rows before, rows after)."""
        idx, before = self.index(), self.rows()
        rows = sorted(idx[k] for k in set(keep) if k in idx)
        if len(rows) == before:
            return before, before
        vecs = np.memmap(self.vecs_path, dtype=np.float16, mode="r").reshape(-1, self.dim)
        raw = open(self.keys_path, "rb").read(before * KEY_BYTES)
        old = (self.keys_path, self.vecs_path)
        gen = self.generation + 1
        keys_new = os.path.join(self.dir, f"keys-{gen}.bin")
        with open(os.path.join(self.dir, f"vectors-{gen}.f16"), "wb") as f:
            for i in range(0, len(rows), 100_000):
                f.write(np.asarray(vecs[rows[i : i + 100_000]]).tobytes())
        with open(keys_new, "wb") as f:
            f.write(b"".join(raw[r * KEY_BYTES : (r + 1) * KEY_BYTES] for r in rows))
        del vecs
        self._write_meta(self.dim, gen)  # the switch: before it the old files count, after it the new ones
        self._use(gen)
        live = {os.path.basename(self.keys_path), os.path.basename(self.vecs_path)}
        for p in set(old) | {os.path.join(self.dir, n) for n in os.listdir(self.dir) if GEN_RX.fullmatch(n)}:
            if os.path.basename(p) not in live:  # the files of earlier generations (one left by a power cut too)
                try:
                    os.remove(p)
                except OSError:
                    pass
        return before, len(rows)
