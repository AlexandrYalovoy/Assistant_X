# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""index\\journal.md is generated: events of the intake (index\\intake_events.tsv: accepted, duplicate,
dropped, to be deleted, error…) plus index\\manifest.tsv, the truth about the files of library
(fills size and hash an event lacks, and the check at the end: library files no event mentions).

    python -m assistant_x.core.journal           take rows written into journal.md by hand into the events,
                                         then write journal.md anew
    python -m assistant_x.core.journal --check   exit 1 if journal.md is not what the events and the manifest give
    python -m assistant_x.core.journal --stats   rows by type in the events and in journal.md
"""

import argparse, collections, os, re, sys
from pathlib import Path

from assistant_x.core.formats import EVENTS_HEADER as HEADER, event_kind as kind

COLS = ["Date", "Source file", "Size, bytes", "SHA-256", "Code", "File in the library", "Status"]
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TITLE = """# Intake journal

The size and the SHA-256 (first 16 characters) of an original are there to find duplicates.
The file is generated (`python -m assistant_x.core.journal`) from `intake_events.tsv` and `manifest.tsv`: edit the events, not this file.
"""


def cell(x):
    return re.sub(r"[\t\r\n]+", " ", str(x if x not in (None, "") else "—")).strip()


def read_events(path):
    path = Path(path)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.split("\t") for ln in lines[1:] if ln.strip() and len(ln.split("\t")) == len(HEADER)]


def write_events(path, rows):
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(HEADER) + "\n")
        for r in rows:
            f.write("\t".join(cell(x) for x in r) + "\n")
    os.replace(tmp, path)


def append_events(path, rows):
    """Add events (lists of 7 values) at the end of intake_events.tsv (made from journal.md first if missing)."""
    path = Path(path)
    if not path.exists() and (path.parent / "journal.md").exists():
        sync(path.parent)  # the history of the journal goes first
    new = not path.exists()
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        if new:
            f.write("\t".join(HEADER) + "\n")
        for r in rows:
            f.write("\t".join(cell(x) for x in r) + "\n")


def parse_journal(text):
    """Rows (7 cells) of the table of a journal.md."""
    out = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) == len(HEADER) and DATE.match(c[0]):
            out.append(c)
    return out


def key(r):
    """What identifies an event: size and hash may be filled in from the manifest later."""
    return (r[0], r[1], r[4], r[5], r[6])


def read_manifest(path):
    """{path in the library: (size, sha256)}."""
    path = Path(path)
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            c = line.split("\t")
            if len(c) == 5:
                out[c[0]] = (c[1], c[3])
    return out


def render(events, manifest):
    rows = []
    for r in events:
        r = list(r)
        if kind(r[6]) == "accepted" and r[5] in manifest and "—" in (r[2], r[3]):
            size, sha = manifest[r[5]]
            r[2] = r[2] if r[2] != "—" else size
            r[3] = r[3] if r[3] != "—" else sha[:16]
        rows.append(r)
    L = [TITLE, "| " + " | ".join(COLS) + " |", "|" + "|".join("-" * (len(c) + 2) for c in COLS) + "|"]
    L += ["| " + " | ".join(r) + " |" for r in rows]
    # files of the library that no event names (by file or by the folder of a multi-file document)
    named = {r[5].rstrip("\\") for r in events if r[5].startswith("library")}
    folders = tuple(n + "\\" for n in named)
    stems = {n.rsplit(".", 1)[0] for n in named}  # the PDF made from a DOC lies beside it under the same name
    lost = sorted(
        p
        for p in manifest
        if p not in named
        and not p.startswith(folders)
        and p.rsplit(".", 1)[0] not in stems
        and not p.rsplit("\\", 1)[-1].startswith("_")
    )  # _README.md of the section folders
    gone = sorted(n for n in named if "." in n.rsplit("\\", 1)[-1] and n not in manifest) if manifest else []
    L += [
        "",
        "## Check against the manifest",
        "",
        f"Events {len(events)}: "
        + ", ".join(f"{k} {v}" for k, v in collections.Counter(kind(r[6]) for r in events).most_common())
        + ".",
        f"Files in library by the manifest: {len(manifest)}; without a journal entry: {len(lost)}; "
        f"in the journal but not in the manifest: {len(gone)}.",
    ]
    for title, items in (("Without a journal entry", lost), ("Not in the manifest", gone)):
        if items:
            L += ["", f"{title} (the first 50):", ""] + [f"- {p}" for p in items[:50]]
            if len(items) > 50:
                L.append(f"- … and {len(items) - 50} more")
    return "\n".join(L) + "\n"


def paths(index):
    index = Path(index)
    return index / "intake_events.tsv", index / "manifest.tsv", index / "journal.md"


def sync(index, write=True, import_md=True):
    """(new journal.md text, rows taken over from the old journal.md). Takes over rows the events lack
    (written by hand), so nothing written to the journal is lost."""
    ev_path, man_path, j_path = paths(index)
    events = read_events(ev_path)
    imported = []
    if import_md and j_path.exists():
        have = collections.Counter(key(r) for r in events)
        for r in parse_journal(j_path.read_text(encoding="utf-8")):
            if have[key(r)]:
                have[key(r)] -= 1
            else:
                imported.append(r)
    events += imported
    text = render(events, read_manifest(man_path))
    if write:
        if imported or not ev_path.exists():
            write_events(ev_path, events)
        tmp = j_path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, j_path)
    return text, imported


def is_current(index):
    """(True, '') or (False, why) — for check_index.py (a warning, not an error)."""
    ev_path, man_path, j_path = paths(index)
    if not ev_path.exists():
        return True, ""
    if not j_path.exists():
        return False, "no journal.md"
    text, imported = sync(index, write=False)
    if imported:
        return False, f"journal.md has {len(imported)} rows that intake_events.tsv lacks"
    if text != j_path.read_text(encoding="utf-8"):
        return False, "journal.md is behind the events or the manifest"
    return True, ""


def main(argv=None):
    ap = argparse.ArgumentParser(description="The intake journal from the events and the manifest")
    ap.add_argument("--index", help="the index folder (default: from assistant_x.toml)")
    ap.add_argument("--check", action="store_true", help="only check that journal.md is up to date")
    ap.add_argument("--stats", action="store_true", help="rows by type in the events and in journal.md")
    a = ap.parse_args(argv)
    if a.index:
        index = Path(a.index)
    else:
        from assistant_x.core import config, env

        w = config.load()[0]
        index = (w.root / env.get("INDEX")).resolve() if env.get("INDEX") else w.index  # AX_INDEX as the intake reads it
    ev_path, _, j_path = paths(index)
    if a.stats:
        ev = collections.Counter(kind(r[6]) for r in read_events(ev_path))
        jr = (
            collections.Counter(kind(r[6]) for r in parse_journal(j_path.read_text(encoding="utf-8")))
            if j_path.exists()
            else {}
        )
        for k in sorted(set(ev) | set(jr)):
            print(f"{k:14} events {ev.get(k, 0):6}  journal {jr.get(k, 0):6}")
        return 0
    if a.check:
        ok, why = is_current(index)
        print(
            "journal.md is up to date."
            if ok
            else f"journal.md is out of date: {why}. Update: python -m assistant_x.core.journal"
        )
        return 0 if ok else 1
    _, imported = sync(index)
    print(f"journal.md written; rows taken from the previous journal into the events: {len(imported)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
