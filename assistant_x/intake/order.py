# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The order of the batches of a big inbox by what its files cost ([intake] order = "cost", the author's rule of
2026-10-31): a run takes the fast files first (a text layer, office files, text), the next run the medium ones (small
scans, help files, pictures read on request), then the slow ones (DjVu, long scans) a few at a time ([intake]
slow_batch), so that the quick part of a library is searchable within the hour and a long scan never holds it back.
The other files stay in inbox untouched for the next batch (the summary counts them). order = "all" takes everything
at once, as before 0.5.7.

The class of a file is guessed before its preparation, from its kind and, for a PDF, from its first pages (the text
layer) and its page count; a folder of page scans is joined into one PDF before (prepare.page_folders), so a book of
pictures is never split over batches."""

import os

from assistant_x.core.formats import file_ext, file_kind

ORDERS = ("cost", "all")
CLASSES = ("fast", "medium", "slow")
SLOW_EXT = ("djvu", "djv")
SCAN_CHARS = 200  # characters of the text layer of the first pages under which a PDF counts as a scan
PROBE_PAGES = 3
LONG_SCAN = 100  # pages of a scan from which it is slow
MEDIUM_EXT = ("chm",)  # a compiled help file: hundreds of pages laid out


def pdf_class(path):
    """medium for a scan, slow for a long one, fast for a PDF with a text layer (or one that does not open: its
    preparation says why)."""
    import pymupdf

    try:
        with pymupdf.open(path) as doc:
            pages = doc.page_count
            chars = sum(len(doc[i].get_text("text").strip()) for i in range(min(PROBE_PAGES, pages)))
    except Exception:  # noqa: BLE001 — a damaged PDF is found by its preparation, quickly
        return "fast"
    if chars >= SCAN_CHARS * min(PROBE_PAGES, max(pages, 1)) / PROBE_PAGES:
        return "fast"
    return "slow" if pages > LONG_SCAN else "medium"


def cost_class(full, rel, cfg=None):
    """fast, medium or slow: what the conversion of this file is likely to cost."""
    ext = file_ext(rel)
    if ext in SLOW_EXT:
        return "slow"
    if ext == "pdf":
        return pdf_class(full)
    if ext in MEDIUM_EXT:
        return "medium"
    if file_kind(rel) == "image" and (cfg or {}).get("pictures") == "include":  # a picture set aside costs nothing
        return "medium"
    return "fast"


def pick(files, cfg=None):
    """(the files [(full, rel)] this run takes, the class taken, {class: files left for later}): the files of the
    cheapest class there is; of the slow ones at most [intake] slow_batch, the smallest first."""
    groups = {c: [] for c in CLASSES}
    for full, rel in files:
        groups[cost_class(full, rel, cfg)].append((full, rel))
    take = next((c for c in CLASSES if groups[c]), "fast")
    chosen = groups[take]
    if take == "slow":
        n = int((cfg or {}).get("slow_batch") or 12)
        chosen = sorted(chosen, key=lambda f: (os.path.getsize(f[0]), f[1]))[:n]
    taken = {rel for _, rel in chosen}
    left = {c: len([f for f in g if f[1] not in taken]) for c, g in groups.items()}
    return chosen, take, {c: n for c, n in left.items() if n}
