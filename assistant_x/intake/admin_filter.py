# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Administrative pages kept out of the library at the intake (the author, 2026-11-03): after the texts of a batch
every file of administrative pages only (core/admin_pages.py: a title page, an approval sheet, an implementation
plan, a cover letter… in any combination, a document of its own or a part of a set) goes to
inbox\\_rejected\\admin\\ with a row of manifest.tsv there; a doubt is a warning of the batch.

    [intake] admin_filter = false turns it off; admin_accept = ["name or folder", …] takes such files in anyway
"""

import csv, os

from assistant_x.core.admin_pages import classify, page_kind, pages_of, rules, scan_library  # noqa: F401


def accepted(cfg, rel):
    """[intake] admin_accept: a name or a folder of a file taken in although its pages look administrative."""
    rel = rel.replace("\\", "/").lower()
    return any(str(a).replace("\\", "/").lower() in rel for a in (cfg.get("admin_accept") or []))


def set_aside(cfg, state, work):
    """After the texts of a batch: every done file of administrative pages only to inbox\\_rejected\\admin\\ (its
    folders kept), a row of manifest.tsv there and an event of the journal; a doubt is a warning of the batch.
    Returns (events, warnings)."""
    from assistant_x.core import journal
    from assistant_x.intake.batch import today, win
    from assistant_x.intake.prepare import move_aside, sha256

    if not cfg.get("admin_filter", True):
        return [], []
    events, warnings, rows = [], [], []
    for r in state.all("done"):
        md = work / "md" / f"{r['tid']}.md"
        full = cfg.inbox / r["rel"]
        if not md.is_file() or not full.is_file():
            continue
        v = classify(os.path.basename(r["rel"]), md.read_text(encoding="utf-8", errors="replace"))
        if not v["verdict"]:
            continue
        if v["verdict"] == "warn" or accepted(cfg, r["rel"]):
            warnings.append(f"{r['tid']} {r['rel']}: administrative pages? {v['reason']} — taken in")
            continue
        size, digest = os.path.getsize(full), sha256(str(full))
        place = move_aside(cfg, str(full), r["rel"], "_rejected/admin")
        events.append([today(), "inbox\\" + win(r["rel"]), size, digest, "—", place, f"rejected: {v['reason']}"])
        rows.append([today(), r["rel"], ", ".join(v["kinds"]), v["reason"], v["rule"], place])
        state.update(r["tid"], status="skipped", why=f"administrative pages only: {v['reason']}")
    if rows:
        path = cfg.inbox / "_rejected" / "admin" / "manifest.tsv"
        new = not path.exists()
        with open(path, "a", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter="\t")
            if new:
                w.writerow(["date", "file", "page kinds", "reason", "rule", "moved to"])
            w.writerows(rows)
        journal.append_events(cfg.index / "intake_events.tsv", events)
    return events, warnings
