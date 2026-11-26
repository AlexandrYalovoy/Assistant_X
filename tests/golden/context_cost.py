# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Measure retrieved evidence separately from reviewed client answers. See docs/COST.md."""

import argparse
import json
import re
import statistics
import time
from pathlib import Path

from assistant_x.search import context

HERE = Path(__file__).resolve().parent


def score(item, out):
    expected = item["expect"]
    hits = {(h["code"], h.get("pdf_page")) for h in out["matches"] + out["pages"]}
    bodies = {(h["code"], h["pdf_page"]): re.sub(r"^=== page \d+ ===\s*", "", h["text"]) for h in out["pages"] if h["text"]}
    # Match within one expected page, with token boundaries: 5 m must not match 15 mm.
    texts = [bodies[(c, p)].casefold() for c, pages in expected for p in pages if (c, p) in bodies]
    values = item.get("values", [])
    patterns = []
    for value in values:
        literal = r"\s*".join(re.escape(w) for w in value.casefold().split())
        suffix = r"(?!\w|[.,]\d)"
        if value.rstrip()[-1:].isalpha():
            suffix += r"(?!\s*/)"
        patterns.append(r"(?<!\w)(?<!\d[.,])" + literal + suffix)
    return dict(
        pages=sum(any((c, p) in hits for p in pages) for c, pages in expected),
        read=sum(any((c, p) in bodies for p in pages) for c, pages in expected),
        pages_of=len(expected),
        values=sum(any(re.search(pattern, t) for t in texts) for pattern in patterns),
        values_of=len(values),
    )


def summarize_trials(rows):
    """Each line is one complete, independently graded attempt, including its retries."""
    groups = {}
    for row in rows:
        key = (row["client"], row["model"], row["library_version"], row["route"], row["mode"])
        if not isinstance(row["correct"], bool):
            raise ValueError("correct must be an independently reviewed boolean")
        groups.setdefault(key, []).append(row)
    reports = []
    for key, group in sorted(groups.items()):
        correct = sum(r["correct"] for r in group)
        report = dict(zip(("client", "model", "library_version", "route", "mode"), key))
        report.update(
            attempts=len(group),
            correct=correct,
            ids=[r["id"] for r in group],
            calls=sum(r["calls"] for r in group),
            median_seconds=statistics.median(r["seconds"] for r in group),
        )
        for metric in ("uncached_input", "cached_input", "output", "cost_usd"):
            measured = all(r.get(metric) is not None for r in group)
            report[metric] = sum(r[metric] for r in group) if measured else None
            report[metric + "_per_correct"] = report[metric] / correct if measured and correct else None
        reports.append(report)
    return reports


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=context.MODES, default="balanced")
    ap.add_argument("--set", choices=("engineering", "blind", "blind2"), default="engineering")
    ap.add_argument("--min-read", type=int, default=0)
    ap.add_argument("--min-values", type=int, default=0)
    ap.add_argument("--trials", type=Path, help="summarize human-graded JSONL from real client sessions")
    ap.add_argument("out", nargs="?", type=Path)
    a = ap.parse_args(argv)
    failed = False
    if a.trials:
        report = summarize_trials([json.loads(s) for s in a.trials.read_text(encoding="utf-8").splitlines() if s.strip()])
    else:
        questions = json.loads((HERE / f"{a.set}_questions.json").read_text(encoding="utf-8"))["questions"]
        rows = []
        for item in questions:
            start = time.monotonic()
            result = context.build(item["q"], *context.MODES[a.mode])
            chars = len(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
            rows.append(
                dict(
                    id=item["id"],
                    **score(item, result),
                    chars=chars,
                    tokens=round(chars / 3),
                    seconds=round(time.monotonic() - start, 3),
                )
            )
        totals = {
            k: sum(r[k] for r in rows) for k in ("pages", "read", "pages_of", "values", "values_of", "tokens", "chars")
        }
        failed = totals["read"] < a.min_read or totals["values"] < a.min_values
        report = dict(mode=a.mode, dataset=a.set, totals=totals, rows=rows)
    data = json.dumps(report, ensure_ascii=False, indent=2)
    print(data)
    if a.out:
        a.out.write_text(data + "\n", encoding="utf-8")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
