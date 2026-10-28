# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ledger of a batch: <work>/ledger.csv, one row for every file the batch met in inbox, each with exactly one
outcome, so that the totals add up to what the folder held:

    done         its text was obtained (a card draft waits for it)
    duplicate    a copy of a file of the library or of the batch (by SHA-256 or by its content)
    error        it failed; why says where
    unsupported  a kind of file the intake does not process (a program, a drawing, a video): left in inbox
    skipped      left for another reason (no LibreOffice, a temporary Word file …)
    moved        taken aside before the work: a letter (its attachments are files of the batch), an unpacked archive
                 (its files are files of the batch), personal papers, a macOS service file
    queued       not processed yet (the batch was stopped)

The rows of moved files come from the preparation of the folder (state meta "moved"), the others from state.sqlite."""

import csv

UNSUPPORTED = "the pipeline does not process"  # the why of work.prep for an extension it does not know
COLUMNS = ("tid", "file", "size", "outcome", "why", "pages", "ocr_pages", "score", "garbled_pages", "seconds")
SECONDS = ("prep_seconds", "convert_seconds", "ocr_seconds")  # the stages of a file (state data)
OUTCOMES = ("done", "duplicate", "error", "unsupported", "skipped", "moved", "queued")


def outcome(row):
    s = row["status"]
    if s in ("done", "applied"):
        return "done"
    if s == "dup":
        return "duplicate"
    if s == "skipped":
        return "unsupported" if (row.get("why") or "").startswith(UNSUPPORTED) else "skipped"
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
