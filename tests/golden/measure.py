# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ranks of the governing norm pages for the design questions of norms_questions.json, on the library of the
workspace (AX_WORKSPACE, else Documents\\Assistant X), by the path of search_library (mcp_server.find_fragments):

    full     k=8, as Claude and Codex search
    compact  k=3 and 3 of shelf N, as the reference mode of LM Studio searches
    pool     k=50 over the whole library and k=50 on shelf N: where the page is before the cut

A rank is the place of the first hit of an expected page (the document alone in brackets), "-" when absent.
python tests/golden/measure.py [OUT.json]: one line per question and a summary; OUT.json keeps the numbers."""

import json, os, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def rank(res, code, pages):
    page = next((i for i, r in enumerate(res, 1) if r["code"] == code and r.get("page") in pages), None)
    if page:
        return str(page)
    doc = next((i for i, r in enumerate(res, 1) if r["code"] == code), None)
    return f"({doc})" if doc else "-"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    from assistant_x.server import mcp_server as m

    m.lib().warm_up()
    data = json.loads((HERE / "norms_questions.json").read_text(encoding="utf-8"))
    rows, hits = [], {"full": 0, "compact": 0, "total": 0}
    for item in data["questions"]:
        t0 = time.monotonic()
        modes = {
            "full": m.find_fragments(item["q"], 8, {}),
            "compact": m.find_fragments(item["q"], 3, {}, norms=3),
            "pool": m.find_fragments(item["q"], 50, {}),
            "pool_n": m.find_fragments(item["q"], 50, {}, sections=["N"]),
        }
        seconds = round(time.monotonic() - t0, 1)
        for code, pages in item["expect"]:
            r = {mode: rank(res, code, pages) for mode, res in modes.items()}
            hits["total"] += 1
            hits["full"] += r["full"].isdigit()
            hits["compact"] += r["compact"].isdigit()
            rows.append(dict(id=item["id"], code=code, seconds=seconds, **r))
            print(
                f"{item['id']:18} {code}  full {r['full']:>4}  compact {r['compact']:>4}  "
                f"pool {r['pool']:>4}  pool N {r['pool_n']:>4}  ({seconds} s)",
                flush=True,
            )
    print(f"pages found: full {hits['full']} of {hits['total']}, compact {hits['compact']} of {hits['total']}")
    if argv:
        Path(argv[0]).write_text(json.dumps({"rows": rows, "hits": hits}, ensure_ascii=False, indent=1), "utf-8")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    sys.exit(main())
