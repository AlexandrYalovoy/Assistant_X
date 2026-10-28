# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The notes on the quality of a text made again from the text in the library, without any OCR: the page flags
"garbled" and "doubled" of its <code>.pages.json (tools/ocr_score.py, as the intake marks them) and, on its card, the
issues the quality report of the intake writes about a text (recognition score, garbled pages, pages that appear
twice, almost empty pages, pages that fell back to the plain text layer: quality_report.problems) and the recognition
score of its file (file.format.ocr_score, from index/ocr_quality.tsv). A redo calls it for every document it reads
(a replaced text, or a kept one with notes of an older code); assistant-x intake reflag for the whole library.

The step 1 audit of the library (2026-10-28): 150 cards counted another number of garbled pages than their page
flags after the redo, 7 cards had a recognition score of an older text in their issues, 64 a recognition score of
the file other than ocr_quality.tsv; the page files of the first intake had no "garbled" flag at all and those of the
first two no "doubled" one.

    assistant-x intake reflag [--dry-run] [CODE ...]       (default: every card of the library)

A changed card and page file are copied to inbox\\_to_delete\\reflag_<date>_<time>\\ first; CATALOG.md and
sources_to_update.md are made again from the cards. The search sees the flags and the issues after assistant-x build."""

import re, shutil, time
from pathlib import Path

from assistant_x.core import card as C
from assistant_x.core.formats import PAGES_SUFFIX, read_outline, read_pages_info, write_pages_info
from assistant_x.intake import quality_report
from assistant_x.intake.tools import ocr_score

# the issues a card has from the quality of its text (quality_report.problems, and the doubled one written by hand at
# an intake): made again from the text; every other issue of the card stays as it is
OWNED = re.compile(
    r"^recognition score \d+ of 100|pages with garbled recognition|appears twice|doubled|pages have almost no text"
    r"|pages fell back to the plain text layer",
    re.I,
)


def text_flags(md):
    """({page: score_text page}, [garbled pages], [doubled pages]) of a text by the rules of the intake
    (work.ocr_measures)."""
    pages = ocr_score.score_text(md)["pages"]
    garbled = [p["page"] for p in pages if p["words"] >= 20 and p["bad"] / p["words"] > ocr_score.GARBLED]
    doubled = [p["page"] for p in pages if ocr_score.doubled_page(p)]
    return {p["page"]: p for p in pages}, garbled, doubled


def measures(md, info, fmt, row, garbled, doubled):
    """The metrics of quality_report.measure for a library text: its page file (fallback pages), the format of its
    card (OCR pages), its row of ocr_quality.tsv (the score with the OCR confidence, pages below the threshold)."""
    words = sum(len(ocr_score.TOKEN.findall(t)) for _, t in ocr_score.pages_of(md))
    score = float(row["score"]) if row.get("score") else None
    m = quality_report.measure(
        md,
        {
            "pages": fmt.get("pages"),
            "ocr_pages": fmt.get("ocr_pages") or 0,
            "fallback": sum((v or {}).get("source") == "fallback" for v in (info or {}).values()),
            "ocr_score": score,
            "ocr_low_pages": int(row.get("pages_below_threshold") or 0),
            "ocr_garbled_pages": len(garbled),
            "ocr_doubled_pages": len(doubled),
            # a drawing sheet: little text on one or two pages, its score is no sign of a bad scan
            "drawing": len(info or {}) <= 2 and words < ocr_score.DRAWING_WORDS,
        },
    )
    return m


def owned_problems(m):
    return [(w, n, p) for w, n, p in quality_report.problems(m) if OWNED.search(w)]


def refresh(index, code, date=None, dry_run=False, aside=None, rows=None):
    """Make the page flags and the text notes of the card of a code (and of its parts) again from its texts. Returns
    {"flags": pages whose flags changed, "removed": [issues], "added": [issues], "score": (old, new) or None,
    "changed": [files written]}; {} when the code has no card. aside: the folder a changed file is copied to first."""
    index = Path(index)
    path = index / "cards" / f"{code}.json"
    if not path.exists():
        return {}
    date = date or time.strftime("%Y-%m-%d")
    rows = ocr_score.read_tsv(index / ocr_score.TSV_NAME) if rows is None else rows
    c = C.load(path)
    file = c.setdefault("file", {})
    entries = [(code, file)] + [(p["code"], p) for p in file.get("parts") or []]
    out = {"flags": 0, "removed": [], "added": [], "score": None, "changed": []}
    wanted, files, scored = [], [], False
    for sub, entry in entries:
        tp = index / "texts" / f"{sub}.md"
        if not tp.exists():
            continue
        md = tp.read_text(encoding="utf-8")
        side = index / "texts" / f"{sub}{PAGES_SUFFIX}"
        info = read_pages_info(side)
        _, garbled, doubled = text_flags(md)
        if info:
            new = {}
            for n, v in info.items():
                flags = [f for f in v.get("flags") or [] if f not in ("garbled", "doubled")]
                flags += ["garbled"] * (n in garbled) + ["doubled"] * (n in doubled)
                if sorted(flags) != sorted(v.get("flags") or []):
                    out["flags"] += 1
                new[n] = {**v, "flags": flags}
            if new != info:
                files.append((side, lambda side=side, new=new: write_pages_info(side, new, read_outline(side))))
        fmt = entry.setdefault("format", {})
        row = rows.get(sub) or {}
        if row.get("score"):
            s = round(float(row["score"]) / 100, 3)
            if fmt.get("ocr_score") != s:
                scored = True
                if sub == code:
                    out["score"] = (fmt.get("ocr_score"), s)
                fmt["ocr_score"] = s
        for what, need, prio in owned_problems(measures(md, info, fmt, row, garbled, doubled)):
            wanted.append({"what": what, "need": need, "priority": prio, **({"code": sub} if sub != code else {})})
    old = file.get("issues") or []
    kept = [i for i in old if not OWNED.search(str(i.get("what", "")))]
    mine = [i for i in old if OWNED.search(str(i.get("what", "")))]
    same = {(i["what"], i.get("code")): i for i in mine}
    made = [same.get((w["what"], w.get("code"))) or {**w, "noted": date} for w in wanted]
    out["removed"] = [i["what"] for i in mine if i not in made]
    out["added"] = [i["what"] for i in made if i not in mine]
    file["issues"] = kept + made
    if out["removed"] or out["added"] or scored:
        files.append((path, lambda: C.dump(c, path)))
    if not dry_run:
        for f, write in files:
            if aside is not None:
                Path(aside).mkdir(parents=True, exist_ok=True)
                if not (Path(aside) / f.name).exists():
                    shutil.copy2(f, Path(aside) / f.name)
            write()
    out["changed"] = [str(f) for f, _ in files]
    return out


def reflag(cfg, codes=None, dry_run=False, say=print):
    """refresh() for the codes (every card of the library by default); CATALOG.md and sources_to_update.md made again.
    Returns the totals."""
    index = Path(cfg.index)
    date = time.strftime("%Y-%m-%d")
    aside = Path(cfg.inbox) / "_to_delete" / f"reflag_{date}_{time.strftime('%H%M%S')}"
    rows = ocr_score.read_tsv(index / ocr_score.TSV_NAME)
    codes = codes or sorted(p.stem for p in (index / "cards").glob("*.json"))
    tot = {"cards": 0, "flags": 0, "removed": 0, "added": 0, "scores": 0, "files": 0}
    for code in codes:
        r = refresh(index, code, date, dry_run, aside, rows)
        if not r:
            continue
        if r["changed"]:
            say(
                f"{code}: page flags {r['flags']}, issues -{len(r['removed'])} +{len(r['added'])}"
                + (f", score {r['score'][0]} -> {r['score'][1]}" if r["score"] else "")
            )
        tot["cards"] += any(f.endswith(".json") and "cards" in f for f in r["changed"])
        tot["flags"] += r["flags"]
        tot["removed"] += len(r["removed"])
        tot["added"] += len(r["added"])
        tot["scores"] += bool(r["score"])
        tot["files"] += len(r["changed"])
    if not dry_run and tot["files"]:
        from assistant_x.intake.apply import write_views

        write_views(cfg, date)
    say(
        f"{'Trial run: would change' if dry_run else 'Changed'} {tot['files']} files: {tot['cards']} cards "
        f"(issues -{tot['removed']} +{tot['added']}, file scores {tot['scores']}), page flags of {tot['flags']} pages"
        + (f"; the old files in {aside}" if tot["files"] and not dry_run else "")
    )
    return tot
