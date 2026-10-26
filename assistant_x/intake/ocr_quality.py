# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recognition score of the library (tools/ocr_score.py) and the commands of intake.py around it.

assistant-x intake vocab                     rebuild the vocabulary .assistant_x/ocr_vocab.txt from index/texts
assistant-x intake ocr-score [CODE …] [--all] [--report FILE]
                                    score the library texts as they are (no new OCR) into index/ocr_quality.tsv;
                                    rows scored at intake with Tesseract confidence (source "intake", "redo")
                                    stay unless --all
assistant-x intake sample N [--out DIR] [--seed S]
                                    N random OCR pages of the library, spread over the scores: a PNG at 150 dpi and
                                    the recognised text beside it, for a check by eye (debug/ocr_quality/sample)
assistant-x intake redo CODE … | --worst N   recognise library documents again with the current pipeline (ocr_redo.py)
"""

import collections, datetime, os, random
from pathlib import Path

from assistant_x.intake import config as intake_cfg

from assistant_x.intake.tools import ocr_score
from assistant_x.core import card as C


def say(*a):
    print(*a, flush=True)


def tsv_path(cfg):
    return cfg.index / ocr_score.TSV_NAME


def _card(cfg, code):
    p = cfg.index / "cards" / f"{C.main_code(code)}.json"
    try:
        return C.load(p) if p.exists() else None
    except C.CardError:
        return None


def card_title(cfg, code):
    """Title of the card of the document (of its main document for a part)."""
    c = _card(cfg, code)
    return C.text((c or {}).get("doc", {}).get("title")) if c else ""


def card_format(cfg, code):
    """The format of a document or of a part of it in words (core/card.format_line), '' without a card."""
    c = _card(cfg, code)
    if not c:
        return ""
    f = c.get("file") or {}
    if code != c["code"]:
        f = next((p for p in f.get("parts") or [] if p["code"] == code), f)
    return C.format_line(f.get("format"))


def cmd_vocab(cfg, a):
    words, stems, docs = ocr_score.build_vocab(str(cfg.index / "texts"))
    say(f"Vocabulary: {words} word forms and {stems} stems from {docs} documents → {ocr_score.vocab_file()}")
    return 0


def cmd_ocr_score(cfg, a):
    date = datetime.date.today().isoformat()
    path = tsv_path(cfg)
    old = ocr_score.read_tsv(path)
    codes = set(a.codes) if a.codes else None
    res = ocr_score.score_library(str(cfg.index / "texts"), codes, workers=max(cfg.workers, 1))
    rows = dict(old) if codes else {c: r for c, r in old.items() if r.get("source") != "text" and not a.all}
    n = 0
    for code, r in res.items():
        if not a.all and code in old and old[code].get("source") in ("intake", "redo"):
            continue
        rows[code] = ocr_score.row_of(code, r, "text", date)
        n += 1
    texts = {p.stem for p in (cfg.index / "texts").glob("*.md")}
    rows = {c: r for c, r in rows.items() if c in texts}  # texts removed from the library leave the table
    ocr_score.write_tsv(path, rows)
    say(f"Texts scored: {n}; rows in {path}: {len(rows)}")
    if a.report:
        Path(a.report).parent.mkdir(parents=True, exist_ok=True)
        Path(a.report).write_text(library_report(cfg, rows, res), encoding="utf-8")
        say(f"Report: {a.report}")
    return 0


BUCKETS = [(0, 50), (50, 60), (60, 70), (70, 80), (80, 90), (90, 95), (95, 100.1)]


def library_report(cfg, rows, res=None, worst=30):
    """Markdown: how the scores of the library spread, the worst documents."""
    scored = {c: float(r["score"]) for c, r in rows.items() if r.get("score")}
    by_kind = collections.defaultdict(list)
    from assistant_x.core import common

    for c, s in scored.items():
        sh = common.ocr_share(card_format(cfg, c))
        by_kind["scans" if sh == 1 else "text" if sh == 0 else "partly scans" if sh else "format unknown"].append(s)
    vals = sorted(scored.values())
    L = [
        f"# Recognition score of the library ({datetime.date.today().isoformat()})",
        "",
        "A score of 0–100 from the existing texts of index\\texts, without recognizing them again (intake/tools/ocr_score.py): "
        "the share of words the library vocabulary lacks (a word in 3+ documents), mixed Latin and Cyrillic, "
        "lost symbols U+FFFD, junk of signs. The Tesseract confidence of old texts was not kept, "
        "so this is the vocabulary part only.",
        "",
        f"Documents with a score: {len(vals)} (without words, without a score: {len(rows) - len(vals)}). "
        f"**Below 50: {sum(v < 50 for v in vals)}**, **below 70: {sum(v < 70 for v in vals)}**, "
        f"below 90: {sum(v < 90 for v in vals)}; median {vals[len(vals) // 2] if vals else '—'}.",
        "",
        "| Score | Documents | " + " | ".join(sorted(by_kind)) + " |",
        "|---|---:|" + "---:|" * len(by_kind),
    ]
    for lo, hi in BUCKETS:
        cnt = lambda xs: sum(lo <= v < hi for v in xs)  # noqa: E731
        L.append(
            f"| {lo}–{min(hi, 100):.0f} | {cnt(vals)} | " + " | ".join(str(cnt(by_kind[k])) for k in sorted(by_kind)) + " |"
        )
    L += [
        "",
        f"## The {worst} worst documents",
        "",
        "| Code | Score | Nonword | Words | Pages below the threshold | Format | Title | Examples of nonwords |",
        "|---|---:|---:|---:|---:|---|---|---|",
    ]
    for c in sorted(scored, key=scored.get)[:worst]:
        r = rows[c]
        ex = ""
        if res and c in res:
            cnt = collections.Counter(e for p in res[c]["pages"] for e in p["examples"])
            ex = ", ".join(w for w, _ in cnt.most_common(6))
        L.append(
            f"| {c} | {r['score']} | {r['nonword']} | {r['words']} | {r['pages_below_threshold']}/{r['pages']} | "
            f"{card_format(cfg, c)[:40]} | {card_title(cfg, c)[:70].replace('|', '/')} | "
            f"{ex.replace('|', '¦')[:90]} |"
        )
    return "\n".join(L) + "\n"


# ---------- assistant-x intake sample: OCR pages for a check by eye ----------


def cmd_redo(cfg, a):
    from assistant_x.intake import ocr_redo

    return ocr_redo.cmd_redo(cfg, a)


SAMPLE_BUCKETS = (("worst", 0, 70), ("middle", 70, 90), ("good", 90, 101))


def bucket_of(score):
    return next(name for name, lo, hi in SAMPLE_BUCKETS if lo <= score < hi)


def scan_page(page, text_page=80):
    """A page of a scan: almost no text layer and a picture on it (as intake_work.prep counts them)."""
    return len(page.get_text().strip()) < text_page and bool(page.get_images())


def cmd_sample(cfg, a):
    """N OCR pages of the library, a third from each band of the page score; one page per document."""
    import pymupdf
    from assistant_x.core import common

    os.environ.update(intake_cfg.tool_env(cfg))
    from assistant_x.intake.tools import convert_md
    from assistant_x.intake import ocr_redo

    rng = random.Random(a.seed)
    out = Path(a.out) if a.out else cfg.root / "debug" / "ocr_quality" / "sample"
    out.mkdir(parents=True, exist_ok=True)
    rows = ocr_score.read_tsv(tsv_path(cfg))
    codes = sorted(c for c, r in rows.items() if r.get("score") and (common.ocr_share(card_format(cfg, c)) or 0) > 0)
    rng.shuffle(codes)
    want = {name: a.n // 3 + (i < a.n % 3) for i, (name, _, _) in enumerate(SAMPLE_BUCKETS)}
    picked = {name: [] for name in want}
    vocab = ocr_score.load_vocab()
    for code in codes:
        if all(len(picked[b]) >= want[b] for b in want):
            break
        path = ocr_redo.library_pdf(cfg, code)
        tp = cfg.index / "texts" / f"{code}.md"
        if not path or not tp.exists():
            continue
        doc = pymupdf.open(path)
        cands = []
        for no, text in ocr_score.pages_of(tp.read_text(encoding="utf-8")):
            n, bad, ex = ocr_score.word_counts(text, vocab)
            if n < 30 or no > doc.page_count:
                continue
            s = ocr_score.page_score(n, bad)
            b = bucket_of(s)
            if len(picked[b]) < want[b] and scan_page(doc[no - 1]):
                cands.append(
                    {
                        "code": code,
                        "page": no,
                        "score": s,
                        "words": n,
                        "bad": bad,
                        "examples": ex,
                        "bucket": b,
                        "text": text,
                        "path": path,
                    }
                )
        if cands:
            c = rng.choice(cands)
            picked[c["bucket"]].append(c)
    items = [c for name, _, _ in SAMPLE_BUCKETS for c in picked[name]]
    L = [
        f"# Sample of OCR pages ({datetime.date.today().isoformat()}, seed {a.seed})",
        "",
        'The page image at 150 dpi (.png) and its text from index\\texts (.txt) lie side by side. "Score" is the '
        'vocabulary score of the library text (no confidence); "New OCR" is the same page recognized again by the '
        "current pipeline (tools/ocr_page.py): the mean Tesseract confidence and the score with it.",
        "",
        "| No. | Code | Page | Band | Score | Nonword | Words | New OCR: confidence | New OCR: score | Examples of nonwords |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    tsv = ["no\tcode\tpage\tband\tscore\tnonword\twords\tconfidence\tnew_score\taccuracy_by_eye"]
    for k, c in enumerate(items, 1):
        stem = f"{k:02d}_{c['code']}_p{c['page']}"
        page = pymupdf.open(str(c["path"]))[c["page"] - 1]
        page.get_pixmap(dpi=150).save(str(out / f"{stem}.png"))
        (out / f"{stem}.txt").write_text(c["text"].strip() + "\n", encoding="utf-8")
        new, stats = convert_md.markdown(str(c["path"]), 0, [c["page"] - 1], True)
        st = stats.get(c["page"]) or {}
        new_res = ocr_score.score_text(f"=== page {c['page']} ===\n{new.get(c['page'], '')}", stats)
        (out / f"{stem}.new.txt").write_text(new.get(c["page"], "").strip() + "\n", encoding="utf-8")
        conf = "" if st.get("conf") is None else f"{st['conf']:.0f}"
        L.append(
            f"| {k} | {c['code']} | {c['page']} | {c['bucket']} | {c['score']:.0f} | {c['bad'] / c['words']:.2f} | "
            f"{c['words']} | {conf} | {new_res['score'] if new_res['score'] is not None else ''} | "
            f"{', '.join(c['examples'][:6]).replace('|', '¦')} |"
        )
        tsv.append(
            f"{k}\t{c['code']}\t{c['page']}\t{c['bucket']}\t{c['score']:.1f}\t{c['bad'] / c['words']:.3f}\t"
            f"{c['words']}\t{conf}\t{new_res['score'] if new_res['score'] is not None else ''}\t"
        )
        say(f"{stem}: score {c['score']:.0f}, new OCR {new_res['score']}")
    (out / "sample.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (out / "sample.tsv").write_text("\n".join(tsv) + "\n", encoding="utf-8")
    short = {b: want[b] - len(picked[b]) for b in want if len(picked[b]) < want[b]}
    say(f"Pages in the sample: {len(items)} → {out}" + (f"; not enough pages: {short}" if short else ""))
    return 0
