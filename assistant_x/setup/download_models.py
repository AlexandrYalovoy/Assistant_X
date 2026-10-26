# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""Download the embedding and reranking models once into the models folder (of this PC: %LOCALAPPDATA%\AssistantX\
models, or --dst), so the search works offline; and MODELS.json, what a medium carries of them.
Usage: python -m assistant_x.setup.download_models [--dst DIR] [--no-onnx]
       python -m assistant_x.setup.download_models --manifest DIR   only write DIR/MODELS.json (sha256 of every file)
After the download both models are exported to ONNX into DIR/onnx (search/onnx_models.export: what DirectML runs on
AMD and Intel cards) when the export packages are here (pip install -e .[export]); --no-onnx skips it.

MODELS.json: {"models": {folder: {"repo", "revision", "files": {path: {"sha256", "size"}}}}}; the installer checks every
file it copies from a medium against it."""

import argparse, hashlib, json, os

from assistant_x.core import workspace

# the models and the revisions the vectors of the bases and the quality baselines were measured with (bge-m3:
# 2026-10-23; the reranker: the revision of the same download, read from its .cache/huggingface note on 2026-10-26)
MODELS = [
    ("BAAI/bge-m3", "bge-m3", "5617a9f61b028005a4858fdac845db406aefb181"),
    ("BAAI/bge-reranker-v2-m3", "bge-reranker-v2-m3", "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"),
]
MANIFEST = "MODELS.json"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def revision_of(folder):
    """The commit a HuggingFace download noted beside its files, or None."""
    d = os.path.join(folder, ".cache", "huggingface", "download")
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if name.endswith(".metadata"):
            try:
                return open(os.path.join(d, name), encoding="utf-8").read().split()[0]
            except (OSError, IndexError):
                pass
    return None


def revisions(cfg):
    """{model name: the revision noted beside its folder, "pinned …" when the folder has no note, or "?"} of the
    embedding model and the reranker of the settings cfg: what a measurement was made with."""
    from assistant_x.search import models

    pins = {folder: rev for _, folder, rev in MODELS}
    out = {}
    for key in ("embed_model", "rerank_model"):
        path = cfg.get(key) or ""
        name = models.model_name(path)
        rev = revision_of(path) if os.path.isdir(path) else None
        out[name] = rev or (f"pinned {pins[name]}" if pins.get(name) else "?")
    return out


def manifest(models_dir):
    """{"models": {...}} of the model folders of models_dir (and of its onnx folder), every file with its sha256."""
    repos = {folder: repo for repo, folder, _ in MODELS}
    out = {}
    for name in sorted(os.listdir(models_dir)):
        top = os.path.join(models_dir, name)
        if not os.path.isdir(top):
            continue
        files = {}
        for dp, dns, fns in os.walk(top):
            dns[:] = [d for d in dns if d != ".cache"]
            for f in sorted(fns):
                p = os.path.join(dp, f)
                files[os.path.relpath(p, top).replace(os.sep, "/")] = {"sha256": sha256(p), "size": os.path.getsize(p)}
        out[name] = {"repo": repos.get(name), "revision": revision_of(top), "files": files}
    return {"models": out}


def write_manifest(models_dir, path=None):
    data = manifest(models_dir)
    path = path or os.path.join(models_dir, MANIFEST)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    return path


def check(models_dir, data, names=None, sizes_only=False):
    """[problems] of the model folders of models_dir against MODELS.json data (names: only these folders; sizes_only:
    every file there and of its size, the quick check of a folder found there already)."""
    problems = []
    for name, m in (data.get("models") or {}).items():
        if names is not None and name not in names:
            continue
        for rel, f in m["files"].items():
            p = os.path.join(models_dir, name, *rel.split("/"))
            if not os.path.isfile(p):
                problems.append(f"{name}/{rel}: missing")
            elif os.path.getsize(p) != f["size"]:
                problems.append(f"{name}/{rel}: damaged (another size)")
            elif not sizes_only and sha256(p) != f["sha256"]:
                problems.append(f"{name}/{rel}: damaged (another sha256)")
    return problems


def export_onnx(models):
    """The ONNX export of the models into models/onnx (DirectML on AMD and Intel cards); a note when the export packages
    (onnx, onnxscript: the extra "export") are not here. True when exported or there already."""
    from assistant_x.search import onnx_models

    if os.path.exists(os.path.join(models, "onnx", "bge-m3", "model.onnx")):
        print("ONNX: there already")
        return True
    try:
        import onnx  # noqa: F401 — only whether the export can run
    except ImportError:
        print(
            "ONNX: not exported (pip install -e .[export], then python -m assistant_x.search.onnx_models --export): "
            "without models/onnx a PC with an AMD or Intel card searches on the processor"
        )
        return False
    old = onnx_models.MODELS, onnx_models.ONNX_DIR
    onnx_models.MODELS, onnx_models.ONNX_DIR = models, os.path.join(models, "onnx")
    try:
        onnx_models.export()
    finally:
        onnx_models.MODELS, onnx_models.ONNX_DIR = old
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(prog="assistant-x download-models")
    ap.add_argument("--dst")
    ap.add_argument("--manifest")
    ap.add_argument("--no-onnx", action="store_true", help="do not export the models to ONNX (models/onnx)")
    a = ap.parse_args(argv)
    if a.manifest:
        print("Written", write_manifest(a.manifest))
        return 0
    from huggingface_hub import snapshot_download

    models = a.dst or str(workspace.current().models)
    for repo, folder, revision in MODELS:
        path = snapshot_download(
            repo,
            revision=revision,
            local_dir=os.path.join(models, folder),
            ignore_patterns=["onnx/*", "*.onnx", "imgs/*", "*.pt"],
        )
        print("done:", path)
    if not a.no_onnx:
        export_onnx(models)
    print("Written", write_manifest(models))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
