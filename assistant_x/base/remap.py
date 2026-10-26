# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""New codes for documents of a workspace: what changes besides the cards and the files (core/card.remap, renames).

The live set, where an old code must not survive: the cards and their file names, the texts and their .pages.json,
the originals in library, index\manifest.tsv, index\ocr_quality.tsv, the generated views (CATALOG.md,
sources_to_update.md, journal.md: made again), the fingerprint caches of the duplicate check (dropped), the control
questions of the user (questions.md) and the saved ranks (eval_baseline.json), the search base (built again).
The history, never rewritten: source_name of the cards (the name the original had before its intake),
index\intake_events.tsv (it gets a row "renumbered A -> B" instead), reports,
.assistant_x\debug, the backups, inbox\_to_delete.

    manifest_rows(rows, mapping)   the rows of manifest.tsv with their new paths and codes (hash, size and date kept,
                                   so manifest.py does not hash a renamed file again)
    tsv_codes(text, mapping)       a TSV whose first column is "code" (ocr_quality.tsv) under mapping
    questions_text(text, mapping)  questions.md with the codes of its answer cells under mapping, and the codes it could
                                   not read as Latin ones (a code letter typed in another script)
    any_json(data, mapping)        every string of a JSON value (eval_baseline.json) under mapping
    fingerprint_files(folders, codes)  the cached fingerprints of these codes, to delete
    events(date, mapping)          the rows of intake_events.tsv that say what was renumbered
"""

import os, re

from assistant_x.core import card as C

ITEM_RX = re.compile(r"(?P<code>[^\W\d_]-\d+(?:-\d+)?)(?=:(?:\*|\d))")


def manifest_rows(rows, mapping):
    """{path: row} of a manifest (intake/manifest.load) under mapping: path and code new, the rest as it was."""
    out = {}
    for path, row in rows.items():
        new = C.map_path(path, mapping)
        out[new] = dict(row, path=new, code=C.map_code(row.get("code", ""), mapping))
    return out


def tsv_codes(text, mapping):
    """A TSV with a header whose first column is the code: every row's code under mapping."""
    lines = text.splitlines()
    if not lines or lines[0].split("\t")[0].strip().lower() != "code":
        return text
    out = [lines[0]] + ["\t".join([C.map_code(c[0], mapping)] + c[1:]) for c in (ln.split("\t") for ln in lines[1:])]
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def _canon(code):
    """'N-12', 'N-00012-2' -> 'N-00012', 'N-00012-02'; None for a code with a letter that is not A-Z."""
    m = re.fullmatch(r"([A-Z])-0*(\d+)(?:-0*(\d+))?", code.upper())
    if not m:
        return None
    return f"{m[1]}-{int(m[2]):0{C.DIGITS}d}" + (f"-{int(m[3]):02d}" if m[3] else "")


def questions_text(text, mapping):
    """(questions.md under mapping, [codes left as they are because they are not in Latin letters]): only the answer
    cells of the table lines ("| question | N-00012:5; E-00006-02:* |") change."""
    odd = []

    def item(m):
        canon = _canon(m["code"])
        if canon is None:
            odd.append(m["code"])
            return m["code"]
        new = C.map_code(canon, mapping)
        return new if new != canon else m["code"]

    out = []
    for line in text.splitlines(keepends=True):
        cells = line.split("|")
        if line.lstrip().startswith("|") and len(cells) >= 4:
            cells[2] = ITEM_RX.sub(item, cells[2])
            line = "|".join(cells)
        out.append(line)
    return "".join(out), odd


def any_json(data, mapping):
    """Every string (and key) of a JSON value with its codes under mapping."""
    if isinstance(data, str):
        return C.map_text(data, mapping)
    if isinstance(data, list):
        return [any_json(x, mapping) for x in data]
    if isinstance(data, dict):
        return {C.map_text(k, mapping): any_json(v, mapping) for k, v in data.items()}
    return data


def fingerprint_files(folders, codes):
    """The fingerprint caches of the duplicate check (intake/tools/dupcheck.py) of these codes and of their parts."""
    mains = {C.main_code(c) for c in codes}
    out = []
    for d in folders:
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            stem = name.split(".", 1)[0]
            if C.main_code(stem) in mains:
                out.append(os.path.join(d, name))
    return sorted(out)


def events(date, mapping, why="renumbered"):
    """Rows of intake_events.tsv (formats.EVENTS_HEADER) saying which document got which code."""
    return [[date, "—", "—", "—", new, "—", f"{why}: {old} -> {new}"] for old, new in sorted(mapping.items())]
