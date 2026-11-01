# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ledger of a batch: <work>/ledger.csv, one row for every file the batch met in inbox, each with exactly one
outcome, so that the totals add up to what the folder held:

    done         its text was obtained (a card draft waits for it)
    duplicate    a copy of a file of the library or of the batch (by SHA-256 or by its content)
    error        it failed; why says where
    unsupported  a kind of file the intake does not process (a program, a drawing, a video): left in inbox
    skipped      left for another reason (no LibreOffice, a temporary Office file …)
    held         a spreadsheet left in inbox, untouched ([intake] spreadsheets = "skip"): it can be taken
    set aside    a picture, a web page or a spreadsheet not taken by default ([intake] pictures, web_pages,
                 spreadsheets = "reject"): moved to inbox\\_rejected\\<pictures | web pages | spreadsheets> after the
                 batch, taken on request
    damaged      a damaged or cut file (get it again): moved to inbox\\_to_delete\\damaged after the batch
    moved        taken aside before the work: a letter (its attachments are files of the batch), an unpacked archive
                 (its files are files of the batch), personal papers, a macOS service file
    queued       not processed yet (the batch was stopped)

The rows of moved files come from the preparation of the folder (state meta "moved"), the others from state.sqlite."""

import csv

UNSUPPORTED = "the pipeline does not process"  # the why of work.prep for an extension it does not know
HELD = "held:"  # the why of work.prep for a file held in inbox by a setting
DAMAGED = "(get it again)"  # the end of the why of a damaged file (work.prep, unpack)
MOVED_DAMAGED = "damaged, moved to _to_delete\\damaged:"  # its why once moved (pipeline.set_aside_damaged)
HELD_SHEET = (
    'held: a spreadsheet, left in inbox (not taken by default; to take it: [intake] spreadsheets = "include", or '
    "intake run --spreadsheets include)"
)
SET_ASIDE = "set aside:"  # the why of work.prep for a file of a kind taken on request only
# the setting of each kind taken on request: the kinds of core/formats (or the extensions) and its folder in _rejected
TAKEN_ON_REQUEST = {
    "pictures": ("picture", "pictures"),
    "web_pages": ("web page", "web pages"),
    "spreadsheets": ("spreadsheet", "spreadsheets"),
}
WEB_PAGE_EXT = ("htm", "html", "xhtml")


def request_group(ext):
    """The setting that decides a file of this extension (pictures, web_pages, spreadsheets), or None."""
    from assistant_x.core.formats import EXTENSIONS

    if ext in WEB_PAGE_EXT:
        return "web_pages"
    return {"image": "pictures", "spreadsheet": "spreadsheets"}.get(EXTENSIONS.get(ext, ""))


def set_aside_why(group):
    """The why of a file set aside: what it is, where it goes and how to take it."""
    name, folder = TAKEN_ON_REQUEST[group]
    opt = group.replace("_", "-")
    return (
        f"{SET_ASIDE} a {name}, to inbox\\_rejected\\{folder} after the batch (taken on request: [intake] {group} = "
        f'"include", or move it back to inbox and intake run --{opt} include)'
    )


def set_aside_group(why):
    """The setting a why of a set aside file names (pictures, web_pages, spreadsheets), or None."""
    if not (why or "").startswith(SET_ASIDE):
        return None
    return next((g for g, (name, _) in TAKEN_ON_REQUEST.items() if why.startswith(f"{SET_ASIDE} a {name},")), None)


COLUMNS = ("tid", "file", "size", "outcome", "why", "pages", "ocr_pages", "score", "garbled_pages", "seconds")
SECONDS = ("prep_seconds", "convert_seconds", "ocr_seconds")  # the stages of a file (state data)
OUTCOMES = ("done", "duplicate", "error", "damaged", "unsupported", "skipped", "held", "set aside", "moved", "queued")


def applied_outcome(place):
    """The outcome of a file an apply moved (status "applied"), by where it went: a duplicate, a file set aside or a
    damaged one keeps its outcome after the apply (M-139, M-140); into the library it is done."""
    p = (place or "").replace("/", "\\").lower()
    if p.startswith("inbox\\_duplicates\\"):
        return "duplicate"
    if any(p.startswith(f"inbox\\_rejected\\{folder}\\") for _, folder in TAKEN_ON_REQUEST.values()):
        return "set aside"
    if p.startswith("inbox\\_rejected\\programs\\"):
        return "unsupported"
    if p.startswith("inbox\\_to_delete\\damaged\\"):
        return "damaged"
    return "done"


def outcome(row):
    s = row["status"]
    if s == "applied":
        return applied_outcome(row.get("place"))
    if s == "done":
        return "done"
    if s == "dup":
        return "duplicate"
    if s == "skipped":
        why = row.get("why") or ""
        if why.startswith(MOVED_DAMAGED):
            return "damaged"
        if why.startswith(SET_ASIDE):
            return "set aside"
        return "unsupported" if why.startswith(UNSUPPORTED) else "held" if why.startswith(HELD) else "skipped"
    if s == "error":
        return "error"
    return "queued"


def rows(state):
    out = []
    for r in state.get_meta("moved", []):
        out.append({"tid": "", "file": r[0], "size": r[1], "outcome": "moved", "why": r[2]})
    for r in state.all():
        out.append(
            {
                "tid": r["tid"],
                "file": r["rel"],
                "size": r.get("size"),
                "outcome": outcome(r),
                "why": (r.get("why") or "") + (f" -> {r['dup_of']}" if r.get("dup_of") else ""),
                "pages": r.get("pages", ""),
                "ocr_pages": r.get("ocr_pages", ""),
                "score": r.get("ocr_score", ""),
                "garbled_pages": r.get("ocr_garbled_pages", ""),
                "seconds": round(sum(r.get(k) or 0 for k in SECONDS), 1) if r["status"] == "done" else "",
            }
        )
    return out


def write(work, state):
    """Write <work>/ledger.csv; returns {outcome: count} (every outcome, zeros included) and the total."""
    data = rows(state)
    with open(work / "ledger.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(data)
    counts = {k: sum(r["outcome"] == k for r in data) for k in OUTCOMES}
    return counts, len(data)


def line(counts, total):
    return f"- Ledger (ledger.csv): {total} files: " + ", ".join(f"{k} {v}" for k, v in counts.items() if v)
