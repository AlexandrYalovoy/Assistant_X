# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Quality of the texts of an intake batch: the shares of the letters of the language packs, U+FFFD, empty pages, share of pages through OCR
(ocr_share), pages without headings, pages that fell back to the plain text layer, the recognition score 0-100
(tools/ocr_score.py: unknown words and Tesseract confidence, written by intake_work.convert).
Writes <work>/intake_quality.md and <work>/quality.json; problem documents get a proposed row
for index\\sources_to_update.md, which assistant-x intake apply writes under the document's code.
Usage: python -m assistant_x.intake.quality_report <work dir>"""

import json, re, sys
from pathlib import Path

from assistant_x.core import lang
from assistant_x.core.common import QUALITY, letter_shares  # the thresholds are shared with the search
from assistant_x.core.formats import PAGE_SPLIT_RX

MARK = PAGE_SPLIT_RX
KEEP = [c for c in lang.active() if lang.get(c, "keep_share")]  # letters a bad recognition turns into Latin
HEAD = re.compile(r"(?m)^\s*(#{1,6}\s+\S|\*\*[^*\n]{3,}\*\*\s*$)")
EMPTY = QUALITY["empty_chars"]
MIN_PAGES_HEADS = QUALITY["min_pages_heads"]


def pages_of(md):
    parts = MARK.split(md)
    return [parts[i + 1] for i in range(1, len(parts) - 1, 2)] if len(parts) > 1 else ([md] if md.strip() else [])


def measure(md, row):
    """Metrics of one document from its Markdown and its state row."""
    pages = pages_of(md)
    body = "".join(pages)
    n = len(pages) or int(row.get("pages") or 0)
    ocr = int(row.get("ocr_pages") or 0)
    return {
        "pages": n,
        "letters": {c: round(s, 2) for c, s in letter_shares(body).items()},
        "fffd": body.count("�"),
        "fffd_per_1000": round(1000 * body.count("�") / max(len(body), 1), 2),
        "empty_pages": sum(len(p.strip()) < EMPTY for p in pages),
        "ocr_share": round(ocr / n, 2) if n else 0.0,
        "no_ocr_pages": int(row.get("no_ocr_pages") or 0),
        "pages_no_heads": sum(not HEAD.search(p) for p in pages),
        "fallback": int(row.get("fallback") or 0),
        "hidden": int(row.get("hidden") or 0),
        "ocr_score": row.get("ocr_score"),
        "ocr_low_pages": int(row.get("ocr_low_pages") or 0),
        "ocr_retried": int(row.get("ocr_retried") or 0),
        "ocr_rotated": int(row.get("ocr_rotated") or 0),
        "drawing": bool(row.get("drawing")),
    }


def problems(m):
    """[(what is wrong, what is needed, priority)] for sources_to_update; [] when the text is fine.
    A drawing sheet has none: little text and a low score are its nature, it is counted apart."""
    out = []
    if m.get("drawing"):
        return out
    if m["no_ocr_pages"]:
        out.append(
            (
                f"{m['no_ocr_pages']} scan pages without OCR (no Tesseract at the intake)",
                "improve the text: recognize it again",
                "high",
            )
        )
    if m["fffd_per_1000"] >= QUALITY["fffd_per_1000"]:
        out.append(
            (
                f"symbols are lost in the text (U+FFFD: {m['fffd']}, {m['fffd_per_1000']:g} per 1000 characters)",
                "replace the file or improve the text",
                "medium",
            )
        )
    if m["pages"] and m["empty_pages"] / m["pages"] >= QUALITY["empty_share"]:
        out.append(
            (
                f"{m['empty_pages']} of {m['pages']} pages have almost no text",
                "replace the file" if m["ocr_share"] >= QUALITY["replace_share"] else "improve the text",
                "medium",
            )
        )
    lo, hi = QUALITY["scan_script"]
    for c in KEEP:
        share = m["letters"].get(c, 0.0)
        if m["ocr_share"] >= QUALITY["scan_share"] and lo <= share < hi:
            out.append(
                (
                    f"a scan with {share:.0%} of {lang.get(c, 'name', c)} letters: recognition garbage is possible",
                    "replace the file: a better scan",
                    "low",
                )
            )
    if m.get("ocr_score") is not None and m["ocr_score"] < QUALITY["ocr_note"]:
        out.append(
            (
                f"recognition score {m['ocr_score']:.0f} of 100 ({m['ocr_low_pages']} pages below "
                f"{QUALITY['ocr_note']}): many unknown words or a low OCR confidence",
                "replace the file: a better scan" if m["ocr_score"] < QUALITY["ocr_replace"] else "improve the text",
                "medium" if m["ocr_score"] < QUALITY["ocr_replace"] else "low",
            )
        )
    if m["pages"] and m["fallback"] / m["pages"] >= QUALITY["fallback_share"]:
        out.append(
            (
                f"{m['fallback']} pages fell back to the plain text layer (the layout analysis failed)",
                "improve the text",
                "low",
            )
        )
    return out


def report(work, state):
    """Write intake_quality.md and quality.json for the done files; returns the summary dict."""
    work = Path(work)
    rows, res = state.all("done"), {}
    for r in rows:
        md = work / "md" / f"{r['tid']}.md"
        m = measure(md.read_text(encoding="utf-8") if md.exists() else "", r)
        res[r["tid"]] = {"rel": r["rel"], **m, "problems": problems(m)}
    (work / "quality.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(v["pages"] for v in res.values())
    ocr = sum(round(v["ocr_share"] * v["pages"]) for v in res.values())
    bad = {t: v for t, v in res.items() if v["problems"]}
    s = {
        "docs": len(res),
        "pages": total,
        "ocr_share": round(ocr / total, 2) if total else 0.0,
        "problem_docs": len(bad),
        "fffd_docs": sum(v["fffd"] > 0 for v in res.values()),
        "empty_pages": sum(v["empty_pages"] for v in res.values()),
        "no_ocr_pages": sum(v["no_ocr_pages"] for v in res.values()),
        "no_heads_docs": sum(v["pages"] >= MIN_PAGES_HEADS and v["pages_no_heads"] == v["pages"] for v in res.values()),
        "ocr_low_docs": sum(
            v["ocr_score"] is not None and v["ocr_score"] < QUALITY["ocr_note"] and not v["drawing"] for v in res.values()
        ),
        "drawings": sum(v["drawing"] for v in res.values()),
        "ocr_retried": sum(v["ocr_retried"] for v in res.values()),
        "ocr_rotated": sum(v["ocr_rotated"] for v in res.values()),
    }
    L = [
        "# Intake quality",
        "",
        f"Documents {s['docs']}, pages {s['pages']}, through OCR {s['ocr_share']:.0%} of the pages. "
        f"Problem documents: {s['problem_docs']} (proposed for index\\sources_to_update.md at apply).",
        "",
        f"Recognition score 0–100 (words by the library vocabulary and the Tesseract confidence): below {QUALITY['ocr_note']} — "
        f"{s['ocr_low_docs']} docs; pages recognized again {s['ocr_retried']}, rotated {s['ocr_rotated']}.",
        "",
        f"Drawings: {s['drawings']} (a sheet bigger than A3, 1–2 pages, little text: recognized once as sparse text, "
        "they go neither into the problems nor into the sources to update).",
        "",
        "| tid | File | Pages | Letters | U+FFFD | Empty pages | OCR | No OCR | Pages without headings | Fallback text | Hidden text | OCR score |",
        "|-----|------|-------|---------|--------|-------------|-----|--------|------------------------|---------------|-------------|-----------|",
    ]
    for t, v in sorted(res.items()):
        score = "" if v["ocr_score"] is None else f"{v['ocr_score']:.0f}"
        shares = " ".join(f"{c} {s:.0%}" for c, s in v["letters"].items() if s >= 0.05)
        L.append(
            f"| {t} | {v['rel'][-70:]} | {v['pages']} | {shares} | {v['fffd']} | {v['empty_pages']} | "
            f"{v['ocr_share']:.0%} | {v['no_ocr_pages'] or ''} | {v['pages_no_heads']} | {v['fallback'] or ''} | "
            f"{v['hidden'] or ''} | {score} |"
        )
    if bad:
        L += ["", "## Problem documents", ""]
        for t, v in sorted(bad.items()):
            L.append(f"- **{t}** {v['rel']}: " + "; ".join(f"{a} → {b} ({c})" for a, b, c in v["problems"]))
    (work / "intake_quality.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return s


def summary_line(s):
    return (
        f"Quality: documents {s['docs']}, pages {s['pages']}, through OCR {s['ocr_share']:.0%}; "
        f"problem ones {s['problem_docs']} (with U+FFFD {s['fffd_docs']}, empty pages {s['empty_pages']}, "
        f"scans without OCR {s['no_ocr_pages']} pages, without headings {s['no_heads_docs']} docs, "
        f"with a recognition score below {QUALITY['ocr_note']} {s.get('ocr_low_docs', 0)} docs)"
    )


def main(argv):
    if not argv:
        sys.exit(__doc__)
    from assistant_x.intake.state import State

    s = report(argv[0], State(Path(argv[0]) / "state.sqlite"))
    print(summary_line(s))


if __name__ == "__main__":
    main(sys.argv[1:])
