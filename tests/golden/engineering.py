# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The engineering questions of engineering_questions.json scored on the library of the workspace (AX_WORKSPACE, else
Documents\\Assistant X) by what an app reads, the text of search_library:

    full       search_library(q, k=8), as Claude and Codex read it
    reference  search_library(q, k=3, norms=3, quotes=True), as the reference mode of LM Studio reads it

pages   the expected norm pages among the hits (a page of the document named in a head "[code, … PDF N]")
values  the numbers the answer rests on, in the text the app reads (whitespace-insensitive)
quotes  the quote lines of the reference mode that verify_quote finds on their page
tokens  the size of what the app reads, about 3 characters a token for Russian text

python tests/golden/engineering.py [OUT.json]: one line per question and the totals."""

import json, os, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HEAD = re.compile(r"\[([A-Z]-\d{5}(?:-\d{2})?), (?:p\. [^\]\n]*?\(PDF (\d+)\)|(?:p\. [^,\]\n]+, )?PDF (\d+))\]")
QLINE = re.compile(r"«([^»]+)»(?: \(table: [^)]*\))? — \[([A-Z]-\d{5}(?:-\d{2})?), (?:p\. [^,\]]+, )?PDF (\d+)\]")
CHARS_PER_TOKEN = 3.0


def squeeze(s):
    return re.sub(r"\s+", "", s or "").lower()


def pages_of(text):
    return {(m[1], int(m[2] or m[3])) for m in HEAD.finditer(text)}


def score(item, text, quotes_ok=None):
    got = pages_of(text)
    pages = sum(any((code, p) in got for p in want) for code, want in item["expect"])
    values = sum(squeeze(v) in squeeze(text) for v in item["values"])
    out = dict(pages=pages, pages_of=len(item["expect"]), values=values, values_of=len(item["values"]))
    out["tokens"] = round(len(text) / CHARS_PER_TOKEN)
    if quotes_ok is not None:
        out["quotes"], out["quotes_of"] = quotes_ok
    return out


def verified(m, text):
    """(quote lines verify_quote finds on their page, quote lines)."""
    lines = QLINE.findall(text)
    ok = 0
    for quote, code, page in lines:
        answer = m.verify_quote(code, int(page), quote.rstrip("…")[:200])
        ok += not answer.startswith("Not found")
    return ok, len(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    from assistant_x.server import mcp_server as m

    m.lib().warm_up()
    data = json.loads((HERE / "engineering_questions.json").read_text(encoding="utf-8"))
    rows, tot = [], {}
    for item in data["questions"]:
        full = m.search_library(item["q"], k=8, quotes=False)
        ref = m.search_library(item["q"], k=3, norms=3, quotes=True)
        r = {"id": item["id"], "full": score(item, full), "reference": score(item, ref, verified(m, ref))}
        rows.append(r)
        for mode in ("full", "reference"):
            for k, v in r[mode].items():
                tot.setdefault(mode, {}).setdefault(k, 0)
                tot[mode][k] += v
        f, q = r["full"], r["reference"]
        print(
            f"{item['id']:24} full pages {f['pages']}/{f['pages_of']} values {f['values']}/{f['values_of']} "
            f"~{f['tokens']} tok | reference pages {q['pages']}/{q['pages_of']} values {q['values']}/{q['values_of']} "
            f"quotes {q['quotes']}/{q['quotes_of']} ~{q['tokens']} tok",
            flush=True,
        )
    n = len(rows)
    for mode in ("full", "reference"):
        t = tot[mode]
        line = f"{mode}: pages {t['pages']}/{t['pages_of']}, values {t['values']}/{t['values_of']}, ~{t['tokens'] // n} tokens a search"
        if mode == "reference":
            line += f", quotes verified {t['quotes']}/{t['quotes_of']}"
        print(line)
    if argv:
        Path(argv[0]).write_text(json.dumps({"rows": rows, "totals": tot}, ensure_ascii=False, indent=1), "utf-8")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    sys.exit(main())
