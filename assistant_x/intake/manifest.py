# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Manifest of the originals: path, size, date and SHA-256 of every file of library with the code of its document.
It lies in index\\manifest.tsv and goes into Git, so a replaced or damaged file shows even a year later,
and a duplicate is caught by the full hash at the intake.

    python -m assistant_x.intake.manifest            update: hash new and changed files (by size and date)
    python -m assistant_x.intake.manifest --check    check every file by its hash again, write nothing
    python -m assistant_x.intake.manifest --dry-run  show what would change, write nothing
    --root DIR                             another workspace (the intake apply, tests)

Exit code 1 when --check finds a file changed or missing.
"""

import argparse
import datetime as dt
import hashlib
import os
import re
import sys
import time
from pathlib import Path

from assistant_x.core import workspace

LIB = "library"
HEADER = ["path", "size", "modified", "sha256", "code"]  # = formats.MANIFEST_HEADER; older manifests: Russian names
CODE_RX = re.compile(r"^([A-Z]-\d{5}(?:-\d{2,3})?)_")
SLACK = 2.0  # seconds: FAT, the network and copying round the time of a file


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def code_of(rel):
    """The code from the file name (N-00001_…), else from the folder of a multi-file document (E-00006_…\\E-00006-02_…)."""
    parts = rel.split("\\")
    for name in (parts[-1], *reversed(parts[:-1])):
        m = CODE_RX.match(name)
        if m:
            return m.group(1)
    return ""


def manifest_path(root):
    return Path(root) / "index" / "manifest.tsv"


def load(path):
    """{path: row} of a manifest file; {} when there is none."""
    rows = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            cells = line.split("\t")
            if len(cells) == len(HEADER):
                rows[cells[0]] = dict(zip(HEADER, cells))
    return rows


def save(rows, path):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(HEADER) + "\n")
        for rel in sorted(rows):
            f.write("\t".join(rows[rel][k] for k in HEADER) + "\n")
    os.replace(tmp, path)


def scan(root):
    """{relative path with \\: (size, mtime, full path)} of all the files of library of the workspace root."""
    out = {}
    # \\?\ on Windows: paths in deep folders of multi-file documents are longer than 260 characters at times
    top = ("\\\\?\\" if os.name == "nt" else "") + str(root / LIB)
    for dp, dns, fns in os.walk(top):
        dns[:] = [d for d in dns if not d.startswith(".")]
        for f in fns:
            p = os.path.join(dp, f)
            st = os.stat(p)
            rel = os.path.relpath(p.replace("\\\\?\\", ""), root).replace("/", "\\")
            out[rel] = (st.st_size, st.st_mtime, p)
    return out


def stamp(mtime):
    return dt.datetime.fromtimestamp(mtime).isoformat(timespec="seconds")


def same_date(row, mtime):
    try:
        return abs(dt.datetime.fromisoformat(row["modified"]).timestamp() - mtime) <= SLACK
    except ValueError:
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="Manifest of the originals of library")
    ap.add_argument("--check", action="store_true", help="hash every file again and compare, write nothing")
    ap.add_argument("--dry-run", action="store_true", help="show the changes, write nothing")
    ap.add_argument("--root", help="the workspace (default: the one in use)")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve() if a.root else workspace.current().root
    path = manifest_path(root)
    if not (root / LIB).is_dir():
        sys.exit(f"No folder {root / LIB}")
    old, now, t0 = load(path), scan(root), time.time()
    new_rows, added, changed, touched, hashed, size = {}, [], [], [], 0, 0
    for rel, (sz, mt, full) in sorted(now.items()):
        row = old.get(rel)
        if row and not a.check and int(row["size"]) == sz and same_date(row, mt):
            new_rows[rel] = row
            continue
        digest = sha256(full)
        hashed += 1
        size += sz
        if row is None:
            added.append(rel)
        elif row["sha256"] != digest:
            changed.append(rel)
        elif not same_date(row, mt) or int(row["size"]) != sz:
            touched.append(rel)  # the same file, another date: e.g. after a restore from a backup
        new_rows[rel] = dict(path=rel, size=str(sz), modified=stamp(mt), sha256=digest, code=code_of(rel))
        if hashed % 200 == 0:
            print(f"  hashed {hashed} files, {size / 1e9:.1f} GB", flush=True)
    removed = sorted(set(old) - set(now))
    print(f"Files in {LIB}: {len(now)}; hashed {hashed} ({size / 1e9:.2f} GB) in {time.time() - t0:.0f} s.")
    print(f"New {len(added)}, changed {len(changed)}, missing {len(removed)}, with a new date but unchanged {len(touched)}.")
    for title, items in (("CHANGED (other content, the same name)", changed), ("MISSING", removed), ("new", added)):
        for rel in items[:30]:
            print(f"  {title}: {rel}")
        if len(items) > 30:
            print(f"  … and {len(items) - 30} more")
    no_code = [r for r in new_rows if not new_rows[r]["code"]]
    if no_code:
        print(f"Without a code in the name of the file or the folder: {len(no_code)}, e.g. {no_code[0]}")
    if a.check:
        sys.exit(1 if changed or removed else 0)
    if a.dry_run:
        print("Trial run: the manifest is not written.")
        return
    save(new_rows, path)
    print(f"Written {path.relative_to(root)}.")


if __name__ == "__main__":
    main()
