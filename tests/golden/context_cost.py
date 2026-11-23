# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Quality and size of the one-command context on the real engineering questions.

    python tests/golden/context_cost.py [--mode balanced|deep] [OUT.json]

Expected pages may occur in the full page bodies or the match metadata. Values must occur in the bounded JSON.
"""

import argparse, json
from pathlib import Path

from assistant_x.search import context

HERE = Path(__file__).resolve().parent


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=tuple(context.MODES), default="balanced")
    ap.add_argument("out", nargs="?")
    a = ap.parse_args(argv)
    data = json.loads((HERE / "engineering_questions.json").read_text(encoding="utf-8"))
    rows, totals = [], dict(pages=0, pages_of=0, values=0, values_of=0, chars=0, tokens=0)
    for item in data["questions"]:
        out = context.build(item["q"], *context.MODES[a.mode])
        text = json.dumps(out, ensure_ascii=False)
        got = {(x["code"], x["pdf_page"]) for x in out["matches"] + out["pages"]}
        pages = sum(any((code, p) in got for p in wanted) for code, wanted in item["expect"])
        values = sum("".join(v.split()).lower() in "".join(text.split()).lower() for v in item["values"])
        row = dict(
            id=item["id"],
            pages=pages,
            pages_of=len(item["expect"]),
            values=values,
            values_of=len(item["values"]),
            chars=len(text),
            tokens=round(len(text) / 3),
        )
        rows.append(row)
        for key in totals:
            totals[key] += row[key]
        print(
            f"{item['id']:24} pages {pages}/{len(item['expect'])} values {values}/{len(item['values'])} ~{row['tokens']} tok",
            flush=True,
        )
    n = len(rows)
    print(
        f"{a.mode}: pages {totals['pages']}/{totals['pages_of']}, values {totals['values']}/{totals['values_of']}, "
        f"~{totals['tokens'] // n} tokens a context, max {max(r['tokens'] for r in rows)}"
    )
    if a.out:
        Path(a.out).write_text(
            json.dumps({"mode": a.mode, "rows": rows, "totals": totals}, ensure_ascii=False, indent=1), "utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
