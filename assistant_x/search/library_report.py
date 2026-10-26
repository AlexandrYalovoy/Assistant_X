# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""State of the library, once a month or after a big intake: what to verify, replace or improve.
Writes debug/library_report_<date>.md (and opens nothing; scripts\\library_report.bat opens the folder).
Usage: assistant-x report [--config assistant_x.toml] [--out FILE]"""

import argparse, collections, datetime, os
from assistant_x.core.common import load_config, connect, has_column, meta
from assistant_x.core import config as settings
from assistant_x.search import catalog
from assistant_x.search import check_index
from assistant_x.core import debuglog


OLD_YEAR = 1990  # older editions of handbooks and norms are worth a look for a newer one
REFERENCE_TYPES = ("book", "textbook", "handbook", "standard", "guideline", "regulation", "manual")


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in r) + " |" for r in rows]
    return out


def manifest_rows(cfg):
    path = os.path.join(os.path.dirname(cfg["catalog"]), "manifest.tsv")
    if not os.path.exists(path):
        return None, path
    rows = [l.split("\t") for l in open(path, encoding="utf-8").read().splitlines()[1:]]
    return [r for r in rows if len(r) == 5], path


def report(cfg):
    con = connect(cfg["db"], readonly=True)
    has_q = has_column(con, "docs", "issue")
    main_docs = con.execute("SELECT * FROM docs WHERE coalesce(parent, '') = ''").fetchall()
    L = [
        f"# State of the library on {datetime.date.today():%Y-%m-%d}",
        "",
        f"Base of {meta(con, 'updated', '?')[:16].replace('T', ' ')}. The report is made by `search\\library_report.py`; "
        "run it once a month and after a big intake.",
        "",
    ]

    # 1. summary
    n_parts = con.execute("SELECT count(*) FROM docs WHERE coalesce(parent, '') != ''").fetchone()[0]
    n_chunks = con.execute("SELECT count(*) FROM chunks").fetchone()[0]
    by_sec = collections.Counter(d["code"][0] for d in main_docs)
    pages = collections.Counter()
    for d in main_docs:
        pages[d["code"][0]] += d["pages"] or 0
    shelves = [x["letter"] for x in settings.sections(cfg)]
    letters = shelves + sorted(set(by_sec) - set(shelves))  # a letter no shelf has: at the end
    L += ["## 1. Summary", ""] + table(
        ["Section", "Documents", "Pages"],
        [(f"{k} — {settings.section_name(k, cfg)}", by_sec[k], pages[k]) for k in letters if by_sec[k]],
    )
    L += [
        "",
        f"Documents in all {len(main_docs)}, parts of multi-file documents {n_parts}, search fragments {n_chunks}.",
        "",
    ]

    # 2. index check
    rep, _ = check_index.check(cfg)
    e, w = rep.count("error"), rep.count("warning")
    L += [
        "## 2. Index check",
        "",
        f"Errors {e}, warnings {w}." + (" Errors stop the build of the base and of a release." if e else ""),
        "",
    ]
    for line in rep.lines():  # a heading line per kind, its cases as a list under it
        L += ["- " + line.strip()] if line.startswith("    ") else ["", f"**{line}**", ""]
    L.append("")

    # 4. text quality
    if has_q:
        weak = [d for d in main_docs if d["quality"]]
        langs = collections.Counter(d["lang"] or "—" for d in main_docs)
        L += [
            "## 3. Text quality",
            "",
            "Languages of the texts: " + ", ".join(f"{k}: {v}" for k, v in langs.most_common()) + ". "
            f"With a quality note: {len(weak)} (scans among them {sum('scan' in d['quality'] for d in weak)}).",
            "",
        ]
        bad = [d for d in weak if "symbols are lost" in d["quality"] or "almost no text" in d["quality"]]
        if bad:
            L += ["Texts worth recognizing again or replacing the file of (lost symbols, empty pages):", ""]
            L += table(
                ["Code", "Document", "What is wrong with the text", "In the sources to update"],
                [(d["code"], d["title"][:70], d["quality"], "yes" if d["issue"] else "no") for d in bad],
            ) + [""]

    # 5. sources to update
    cards, _ = catalog.load_cards(cfg["cards_dir"])
    found = [(code, i) for code, _, i in catalog.issues(cards) if not i.get("closed")]
    prio = collections.Counter(i.get("priority") for _, i in found)
    L += [
        "## 4. Sources to update",
        "",
        f"Open items: {len(found)} of {len({c for c, _ in found})} documents; by priority: "
        + (", ".join(f"{k} {v}" for k, v in prio.most_common()) or "none")
        + ".",
        "",
    ]
    high = sorted({c for c, i in found if i.get("priority") == "high"})
    if high:
        L += ["High priority: " + ", ".join(high), ""]

    # 6. book maps
    if has_column(con, "docs", "pages"):
        no_map = con.execute("""SELECT d.code, d.title, d.pages FROM docs d WHERE d.pages >= 30
                                AND coalesce(d.parent, '') = ''
                                AND NOT EXISTS (SELECT 1 FROM outline o WHERE o.code = d.code)
                                ORDER BY d.pages DESC""").fetchall()
        L += [
            "## 5. Book map",
            "",
            f"Documents of 30 pages and more without an outline in the map: {len(no_map)}. "
            'These are usually scans without marked headings: references like "see table" in them lead to no page.',
            "",
        ]
        if no_map:
            L += table(["Code", "Document", "Pages"], [(r["code"], r["title"][:80], r["pages"]) for r in no_map[:30]]) + [""]

    # 7. old editions
    old = [d for d in main_docs if d["year"] and d["year"] < OLD_YEAR and d["doc_type"] in REFERENCE_TYPES]
    L += [
        "## 6. Old editions",
        "",
        f"Books, handbooks and standards before {OLD_YEAR}: {len(old)}. "
        "For the key topics a newer edition is worth looking for (the intake asks whether it replaces the old one).",
        "",
    ]
    if old:
        L += table(
            ["Code", "Year", "Document"],
            [(d["code"], d["year"], d["title"][:80]) for d in sorted(old, key=lambda d: d["year"])][:40],
        ) + [""]

    # 8. manifest
    rows, path = manifest_rows(cfg)
    L += ["## 7. Manifest of the originals", ""]
    if rows is None:
        L += [f"No manifest ({path}). Create it: `python -m assistant_x.intake.manifest`.", ""]
    else:
        by_sha = collections.defaultdict(list)
        for r in rows:
            by_sha[r[3]].append(r[0])
        same = [v for v in by_sha.values() if len(v) > 1]
        no_code = [r[0] for r in rows if not r[4]]
        last = max((r[2] for r in rows), default="")
        L += [
            f"Files {len(rows)}, {sum(int(r[1]) for r in rows) / 1e9:.2f} GB, last changed {last[:10]}. "
            f"Without a code in the name: {len(no_code)}. Groups of files with the same content: {len(same)}.",
            "Check that the files are not damaged: `python -m assistant_x.intake.manifest --check`.",
            "",
        ]
        for v in same[:20]:
            L.append("- the same: " + "; ".join(v))
        L += [f"- without a code: {p}" for p in no_code[:20]] + [""]
    con.close()
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(prog="assistant-x report")
    ap.add_argument("--config")
    ap.add_argument("--out")
    a = ap.parse_args()
    cfg = load_config(a.config)
    text = report(cfg)
    out = a.out or os.path.join(debuglog.log_dir(), f"library_report_{datetime.date.today():%Y-%m-%d}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Report: {out}")


if __name__ == "__main__":
    debuglog.run(main, "library_report")
