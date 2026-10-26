# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""assistant-x base export: the library of this workspace as a base package (base/package.py, "axbase/1").

    assistant-x base export OUT.axbase --id ID --version V [--name-en ..] [--name-ru ..] [--about-en ..] [--about-ru ..]
                            [--include-personal]
                            [--strip-names] [--no-vectors] [--codes default|reference]
    assistant-x base export --folder DIR ...        the same layout as a folder (a FAT32 flash drive: no file over 4 GB)

The cards must pass `assistant-x check` first. Personal documents (intake.personal) stay out unless
--include-personal; a card's other_versions that are not exported are dropped; intake.batch is cleared (the folder
names of the batches are of this PC), --strip-names also clears source_name (the names the originals had). The
events keep only date, code and status. The vectors come from the vector cache of the workspace (embed.py fills it;
the vectors of the base are put into it first): a package installed on a PC with the same model needs no embedding.
Never in a package: assistant_x.toml and assistant_x.local.toml, the debug journals, the query logs, the work folder."""

import argparse, datetime, hashlib, json, os, re, shutil, sys, zipfile

from assistant_x.base import package as P
from assistant_x.core import card as C
from assistant_x.core import config as settings
from assistant_x.core.formats import PAGES_SUFFIX, TEXT_FORMAT
from assistant_x.core.txn import lp

FAT32_LIMIT = 4 * 1024**3 - 1


def readme(name, version, documents, created):
    """README.txt of a package: its name, then how to install it in every language whose pack has the text
    (lang/<code>/package.json, English first)."""
    from assistant_x.core import lang

    lines = [f"Assistant X base package: {name}", f"Version {version}, {documents} documents, made {created}.", ""]
    for code in sorted(lang.available(), key=lambda c: (c != "en", c)):
        part = lang.get(code, "package_readme")
        if part:
            lines += [*part, ""]
    return "\n".join(lines)


def text_sha(texts_dir, code):
    """sha256 of a text and its .pages.json, as build_index.read_text computes it ('' when there is no text)."""
    for ext in (".md", ".txt"):
        p = os.path.join(texts_dir, code + ext)
        if os.path.exists(p):
            from assistant_x.core.common import strip_invisible

            raw = strip_invisible(open(p, encoding="utf-8").read())
            side = os.path.join(texts_dir, code + PAGES_SUFFIX)
            extra = open(side, "rb").read() if os.path.exists(side) else b""
            return hashlib.sha256(raw.encode() + b"\0" + extra).hexdigest()
    return ""


def select(cards, include_personal=False):
    """{code: card} of the documents that go into the package."""
    return {c: card for c, card in cards.items() if include_personal or not (card.get("intake") or {}).get("personal")}


def exported_card(card, chosen, ident, version, strip_names=False):
    """The card as the package has it: intake.package names the package, intake.batch cleared, other_versions only of
    exported documents (the dropped ones are returned), source_name cleared with strip_names."""
    card = json.loads(json.dumps(card))
    intake = card["intake"]
    intake["batch"] = ""
    intake["package"] = {"id": ident, "version": version, "code": card["code"]}
    doc = card.get("doc") or {}
    dropped = [c for c in doc.get("other_versions") or [] if c not in chosen]
    if dropped:
        doc["other_versions"] = [c for c in doc["other_versions"] if c in chosen]
    if strip_names:
        for entry in [card.get("file") or {}] + list((card.get("file") or {}).get("parts") or []):
            if "source_name" in entry:
                entry["source_name"] = ""
    return card, dropped


def file_entries(card):
    """[(code of the document or the part, the entry of the file)] of a card."""
    file = card.get("file") or {}
    return [(card["code"], file)] + [(p["code"], p) for p in file.get("parts") or []]


def fs_type(path):
    """The file system of the disk of path ("FAT32", "NTFS", "exFAT"...), or "" when unknown (not Windows)."""
    if os.name != "nt":
        return ""
    import ctypes

    root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
    name = ctypes.create_unicode_buffer(64)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(root), None, 0, None, None, None, name, 64)
    return name.value if ok else ""


class Writer:
    """The files of a package into a zip (stored) or a folder, with the sha256 of each."""

    def __init__(self, out, folder):
        self.out, self.folder, self.sums, self.bytes = out, folder, {}, 0
        if folder:
            os.makedirs(out, exist_ok=True)
            self.zip = None
        else:
            self.part = out + ".part"
            self.zip = zipfile.ZipFile(self.part, "w", compression=zipfile.ZIP_STORED, allowZip64=True)

    def add_bytes(self, name, data):
        self.sums[name] = hashlib.sha256(data).hexdigest()
        self.bytes += len(data)
        if self.zip:
            self.zip.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), data)
        else:
            dst = lp(os.path.join(self.out, *name.split("/")))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)

    def add_file(self, name, src):
        h = hashlib.sha256()
        with open(lp(src), "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        self.sums[name] = h.hexdigest()
        self.bytes += os.path.getsize(lp(src))
        if self.zip:
            self.zip.write(lp(src), name)
        else:
            dst = lp(os.path.join(self.out, *name.split("/")))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(lp(src), dst)

    def finish(self):
        text = "".join(f"{self.sums[n]}  {n}\n" for n in sorted(self.sums))
        if self.zip:
            self.zip.writestr(P.CHECKSUMS, text)
            self.zip.close()
            os.replace(self.part, self.out)
        else:
            with open(os.path.join(self.out, P.CHECKSUMS), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)


def vectors_of(cfg, codes):
    """(meta of the vectors, keys bytes, vectors bytes) of the fragments of codes in the vector cache, or None when
    the cache has none of them. The vectors of the base are put into the cache first."""
    import numpy as np
    from assistant_x.core.common import connect, meta
    from assistant_x.search import embed, models, vector_cache as V

    if not os.path.exists(cfg["db"]):
        return None
    fp, cache = V.fingerprint(cfg), V.Cache(cfg)
    con = connect(cfg["db"])
    try:
        if meta(con, "dim") and meta(con, "vector_cache_seeded") != fp:
            embed.seed(con, cfg, cache, fp)
        mains = sorted(codes)
        rows = []
        for i in range(0, len(mains), 500):
            part = mains[i : i + 500]
            q = ",".join("?" * len(part))
            rows += embed.fragments(con, f"(c.code IN ({q}) OR d.parent IN ({q}))", part + part)
    finally:
        con.close()
    keys = list(dict.fromkeys(embed.keys_of(rows, fp, bool(cfg.get("table_rows", False)))))
    found = cache.get(keys)
    if not found:
        return None
    keys = [k for k in keys if k in found]
    vecs = np.stack([found[k] for k in keys]).astype(np.float16)
    info = {
        "format": 1,
        "dim": int(vecs.shape[1]),
        "fingerprint": fp,
        "rows": len(keys),
        "model": models.model_name(cfg.get("embed_model") or "bge-m3"),
        "max_seq_length": int(cfg.get("max_seq_length", 1024)),
        "table_rows": bool(cfg.get("table_rows", False)),
    }
    return info, b"".join(keys), vecs.tobytes()


CODES = ("default", "reference")


def export(
    cfg,
    raw,
    out,
    ident,
    version,
    folder=False,
    include_personal=False,
    strip_names=False,
    vectors=True,
    name=None,
    about=None,
    codes="default",
    say=print,
):
    """Write the package; returns its manifest. Raises SystemExit with the reason when it cannot. codes: "reference"
    — a reference base, its codes meant to be the same for everyone who installs it (inspect recommends keeping
    them); "default" — the installer chooses, with no recommendation."""
    if codes not in CODES:
        raise SystemExit(f"--codes {codes!r}: one of {', '.join(CODES)}")
    from assistant_x import __version__
    from assistant_x.core import journal
    from assistant_x.core.common import CHUNK_VERSION, read_ocr_scores
    from assistant_x.search import check_index

    if not re.fullmatch(P.ID_RX, ident or ""):
        raise SystemExit(f"--id {ident!r}: lower-case letters, digits, '.', '_' and '-' (up to 64), e.g. oil-gas-norms")
    if not re.fullmatch(P.VERSION_RX, version or ""):
        raise SystemExit(f"--version {version!r}: letters, digits, '.', '_', '+' and '-' (up to 40), e.g. 2026.10")
    if check_index.run(cfg, quiet=True) > 0:
        raise SystemExit("Export stopped: the library has errors (assistant-x check shows them).")
    all_cards = {c: C.load(p) for c, p in C.paths(cfg["cards_dir"]).items()}
    chosen = select(all_cards, include_personal)
    if not chosen:
        raise SystemExit(
            "Nothing to export: the library has no documents"
            + ("" if include_personal else " besides personal ones (--include-personal)")
        )
    root, idx, texts = cfg["library_root"], os.path.dirname(cfg["catalog"]), cfg["texts_dir"]
    files = []  # (name in the package, source path)
    for code in sorted(chosen):
        for sub, entry in file_entries(chosen[code]):
            for ext in (".md", PAGES_SUFFIX):
                p = os.path.join(texts, sub + ext)
                if os.path.exists(p):
                    files.append((f"texts/{sub}{ext}", p))
            for k in ("library", "pdf_copy"):
                place = (entry.get(k) or "").replace("\\", "/")
                if place.startswith("library/"):
                    files.append((place, os.path.join(root, *place.split("/"))))
    files = list(dict.fromkeys(files))
    total = sum(os.path.getsize(lp(p)) for _, p in files)
    if not folder and total > FAT32_LIMIT and fs_type(out).upper().startswith("FAT"):
        raise SystemExit(
            f"{out}: a FAT32 disk takes no file over 4 GB and the package is {total / 1024**3:.1f} GB: "
            "export with --folder DIR instead (or onto an NTFS or exFAT disk)."
        )
    probe = os.path.dirname(os.path.abspath(out)) if not folder else os.path.abspath(out)
    while not os.path.exists(probe):
        probe = os.path.dirname(probe)
    if shutil.disk_usage(probe).free < total * 1.05 + 50 * 2**20:
        raise SystemExit(f"Not enough disk space at {probe} for a package of {total / 1024**3:.1f} GB.")
    if folder and os.path.isdir(out) and os.listdir(out):
        raise SystemExit(f"--folder {out}: the folder must be empty or new.")
    if not folder and os.path.exists(out):
        raise SystemExit(f"{out} exists already: give another name or delete it first.")
    w = Writer(out, folder)
    dropped, docs, shelves = {}, [], {}
    for code in sorted(chosen):
        card, gone = exported_card(chosen[code], chosen, ident, version, strip_names)
        if gone:
            dropped[code] = gone
        data = C.dumps(card).encode("utf-8")
        w.add_bytes(f"cards/{code}.json", data)
        shelves[card["section"]] = shelves.get(card["section"], 0) + 1
        docs.append(
            {
                "code": code,
                "sha256": (card.get("file") or {}).get("sha256") or "",
                "card_sha": hashlib.sha256(data).hexdigest(),
                "text_sha": text_sha(texts, code),
                "parts": [p["code"] for p in (card.get("file") or {}).get("parts") or []],
            }
        )
    for name_, src in files:
        w.add_file(name_, src)
    subs = {sub for code in chosen for sub, _ in file_entries(chosen[code])}
    scores = read_ocr_scores(os.path.join(idx, "ocr_quality.tsv"))
    if any(s in scores for s in subs):
        lines = open(os.path.join(idx, "ocr_quality.tsv"), encoding="utf-8").read().splitlines()
        keep = [lines[0]] + [ln for ln in lines[1:] if ln.split("\t")[0] in subs]
        w.add_bytes("ocr_quality.tsv", ("\n".join(keep) + "\n").encode("utf-8"))
    events = [
        [r[0], "—", "—", "—", r[4], "—", r[6]]
        for r in journal.read_events(os.path.join(idx, "intake_events.tsv"))
        if C.main_code(r[4]) in chosen
    ]
    if events:
        from assistant_x.core.formats import EVENTS_HEADER

        w.add_bytes(
            "events.tsv",
            ("\t".join(EVENTS_HEADER) + "\n" + "".join("\t".join(journal.cell(x) for x in e) + "\n" for e in events)).encode(
                "utf-8"
            ),
        )
    vec = vectors_of(cfg, set(chosen)) if vectors else None
    if vec:
        info, keys, blob = vec
        w.add_bytes("vectors/meta.json", json.dumps(info, indent=1).encode("utf-8"))
        w.add_bytes("vectors/keys.bin", keys)
        w.add_bytes("vectors/vectors.f16", blob)
    topics = settings.topics(raw)
    manifest = {
        "format": P.FORMAT,
        "id": ident,
        "version": version,
        "codes": codes,
        "name": {k: v for k, v in (name or {}).items() if v} or {"en": ident},
        "about": {k: v for k, v in (about or {}).items() if v},
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "requires": {"app": __version__, "card_schema": C.SCHEMA_VERSION, "text_format": TEXT_FORMAT},
        "chunk_version": CHUNK_VERSION,
        "profile": raw.get("profile") or settings.PROFILE,
        "card_languages": settings.card_languages(raw),
        "topics": sorted(topics) if topics else sorted({t for c in chosen.values() for t in c["doc"].get("topics") or []}),
        "topics_controlled": bool(topics),
        "languages": sorted({x for c in chosen.values() for x in c["doc"].get("lang") or []}),
        "embed": vec[0] if vec else None,
        "shelves": dict(sorted(shelves.items())),
        "documents": len(docs),
        "bytes": total + sum(len(x) for x in (vec[1], vec[2])) if vec else total,
        "docs": docs,
    }
    w.add_bytes(
        P.README, readme(manifest["name"].get("en") or ident, version, len(docs), manifest["created"][:10]).encode("utf-8")
    )
    w.add_bytes(P.MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"))
    w.finish()
    say(
        f"Package {ident} {version}: {len(docs)} documents, {len(files)} files, "
        f"{w.bytes / 1024**2:.0f} MB" + (f", {vec[0]['rows']} vectors" if vec else ", no vectors") + f" → {out}"
    )
    for code, gone in sorted(dropped.items()):
        say(f"  {code}: other versions not in the package dropped from its card: {', '.join(gone)}")
    return manifest


def main(argv=None):
    from assistant_x.core import lock
    from assistant_x.core.common import load_config

    ap = argparse.ArgumentParser(prog="assistant-x base export")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--folder")
    ap.add_argument("--id", required=True)
    ap.add_argument("--version", required=True)
    for k in ("name-en", "name-ru", "about-en", "about-ru", "config"):
        ap.add_argument(f"--{k}")
    ap.add_argument("--include-personal", action="store_true")
    ap.add_argument("--strip-names", action="store_true")
    ap.add_argument("--no-vectors", action="store_true")
    ap.add_argument(
        "--codes",
        choices=CODES,
        default="default",
        help="reference: a reference base, whose codes the installers are recommended to keep",
    )
    a = ap.parse_args(argv)
    if bool(a.out) == bool(a.folder):
        ap.error("give either OUT.axbase or --folder DIR")
    out = os.path.abspath(a.folder or a.out)
    if a.out and not out.lower().endswith(P.SUFFIX):
        out += P.SUFFIX
    cfg = load_config(a.config)
    raw = settings.load(a.config)[1]
    with lock.heavy_task("base export"):  # reads the whole library, hashes every file
        export(
            cfg,
            raw,
            out,
            a.id,
            a.version,
            folder=bool(a.folder),
            include_personal=a.include_personal,
            strip_names=a.strip_names,
            vectors=not a.no_vectors,
            name={"en": a.name_en, "ru": a.name_ru},
            about={"en": a.about_en, "ru": a.about_ru},
            codes=a.codes,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
