# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""assistant-x intake redo: recognise library documents again with the current pipeline (prep and convert of intake_work: OCR
with word confidence, retries of weak pages, turned pages, plain text where the layout analysis lost the words) and
replace index/texts/<code>.md only when the recognition score grew by QUALITY["ocr_redo_gain"] or more, or the text
is no longer doubled (the share of its pages whose every phrase appears twice fell by UNDOUBLED_DROP, or their mean
share of repeated word 3-grams from above ocr_score.DOUBLED to below UNDOUBLED_MEAN: a scan's text layer extracted
together with its recognition), and the new text keeps QUALITY["ocr_redo_keep"] of the known words of the old one (a
clean but nearly empty text is no gain).

    assistant-x intake redo N-00101-21 E-00016 …        these documents
    assistant-x intake redo --worst 100 [--below 70]   the worst of index/ocr_quality.tsv below the threshold
    --dry-run                                                 recognise and score, change nothing

Old and new texts are compared by the word part of the score (tools/ocr_score.py without the Tesseract confidence:
the old texts have none). A document with a broken font (U+FFFD, Latin Extended-B), or with a text layer whose new
text lost known words, is tried once more with the page images recognised instead of the layer (as the intake does
for a broken font encoding). Known words count once per page, so a doubled old text is not "richer". Every document gets a
row in index/intake_events.tsv ("recognized again: …", why the text was or was not replaced); a replaced one gets
its new row in ocr_quality.tsv (source "redo"). The work goes to intake/work/redo/<date>_<time>/; the library PDF is
copied there, library is only read. After replacements: build_index.py and embed.py.
"""

import datetime, hashlib, json, os, shutil, time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from assistant_x.intake import config as intake_cfg

from assistant_x.intake.tools import ocr_score
from assistant_x.core.common import QUALITY
from assistant_x.core.formats import PAGE_RX, PAGES_SUFFIX, pages_path, place_of


def say(*a):
    print(*a, flush=True)


def library_pdf(cfg, code):
    """Path of the PDF of a library text by index/manifest.tsv: the file of the code (of its first part for a
    multi-file document), or the PDF made from a DOC/DOCX beside it; None when there is none."""
    man = cfg.index / "manifest.tsv"
    if not man.exists():
        return None
    rows = [ln.split("\t") for ln in man.read_text(encoding="utf-8").splitlines()[1:]]
    for want in (code, f"{code}-01"):
        places = [r[0] for r in rows if len(r) == 5 and r[4] == want]
        for place in sorted(places, key=lambda p: not p.lower().endswith(".pdf")):
            p = cfg.library.joinpath(*place.split("\\")[1:])
            pdf = p if p.suffix.lower() == ".pdf" else p.with_suffix(".pdf")
            if os.path.exists(intake_cfg.lp(pdf)):
                return pdf
    return None


UNDOUBLED_DROP = 0.3  # the share of doubled pages falls by this much: the text is no longer doubled
UNDOUBLED_MEAN = 0.1  # … or the mean share of repeated 3-grams falls by this much, to below this
REDO_LOSS = 5  # a new text this much below the old score by words is worse: the page images are read, it is not taken


def words_score(md):
    return ocr_score.score_text(md)["score"]


def doubling(md):
    """(share of the pages whose text is doubled, mean share of repeated word 3-grams of the pages) of a text."""
    pages = ocr_score.score_text(md)["pages"]
    if not pages:
        return 0.0, 0.0
    rep = [p.get("repeated", 0.0) for p in pages]
    return round(sum(r >= ocr_score.DOUBLED for r in rep) / len(rep), 3), round(sum(rep) / len(rep), 3)


def undoubled(old, new):
    """True when the new text is no longer doubled as the old one was ((share, mean) of doubling())."""
    return old[0] - new[0] >= UNDOUBLED_DROP or (old[1] - new[1] >= UNDOUBLED_MEAN and new[1] < UNDOUBLED_MEAN)


def known_words(md):
    """Known words of a text, each once per page (ocr_score.known_distinct): a doubled old text does not count its
    words twice against its clean recognition."""
    return ocr_score.known_distinct(md)


def broken(md):
    return ocr_score.LOST in md or bool(ocr_score.BROKEN_FONT.search(md))


def _variant(base, tid, imgocr):
    """prep and convert of one variant in this process: (Markdown, the result of convert) or (None, why)."""
    from assistant_x.intake import work as intake_work

    job = {**base, "tid": tid, "imgocr": imgocr}
    res = intake_work.prep(job)
    if res.get("status") in ("error", "skipped"):
        return None, res.get("why")
    conv = intake_work.convert(
        {**job, "pdf": res["pdf"], "ocr_pages": res.get("ocr_pages"), "phrases": res.get("phrases", 0)}
    )
    if conv.get("status") == "error":
        return None, conv.get("why")
    md = Path(base["work"]) / "md" / f"{tid}.md"
    return md.read_text(encoding="utf-8"), {**conv, "pages": res.get("pages"), "ocr_pages": res.get("ocr_pages")}


def redo_one(code, pdf, work, base, old_score=None, old_known=0, old_broken=False):
    """Recognise one document; the main process decides. {'code', 'new', 'variant', 'md', 'detail', 'why', …}
    The page images are read as a second variant only when a font is broken (old or new text), or the new text of a
    document with a text layer lost known words or fell REDO_LOSS below the old score (a poor visible layer): a score
    that merely did not grow is no reason for a second, longer reading."""
    t0 = time.time()
    w = Path(work) / code
    (w / "src").mkdir(parents=True, exist_ok=True)
    src = w / "src" / f"{code}.pdf"
    if not src.exists():
        shutil.copy2(intake_cfg.lp(pdf), src)  # a copy: the work never links to library
    base = {**base, "work": str(w), "src": str(src), "rel": f"{code}.pdf", "ext": "pdf"}
    out = {"code": code, "variants": {}}
    md, conv = _variant(base, code, False)
    if md is None:
        return {**out, "why": f"recognition failed: {conv}", "seconds": round(time.time() - t0)}
    keep = QUALITY["ocr_redo_keep"] * old_known

    def rank(name, text):  # a variant that keeps the known words first, then by score
        return known_words(text) >= keep, out["variants"][name] or 0

    best = ("pipeline", md, conv, code)
    out["variants"]["pipeline"] = words_score(md)
    layer = (conv.get("ocr_pages") or 0) < (conv.get("pages") or 0)
    worse = old_score is not None and (out["variants"]["pipeline"] or 0) < old_score - REDO_LOSS
    if old_broken or broken(md) or (layer and (worse or not rank("pipeline", md)[0])):
        img_src = w / "src" / f"{code}_img.pdf"  # prep of a variant takes the file under its own name
        if not img_src.exists():
            shutil.copy2(src, img_src)
        md2, conv2 = _variant(base, f"{code}_img", True)  # the text layer may be the trouble: read the page images
        if md2 is None:
            out["variants_failed"] = conv2
        else:
            out["variants"]["page images"] = words_score(md2)
            if rank("page images", md2) > rank("pipeline", md):
                best = ("page images", md2, conv2, f"{code}_img")
    name, md, conv, tid = best
    detail = w / "ocr" / f"{tid}.json"
    full = json.loads(detail.read_text(encoding="utf-8"))["score"] if detail.exists() else None
    return {
        **out,
        "variant": name,
        "new": out["variants"][name],
        "full": full,
        "md": str(w / "md" / f"{tid}.md"),
        "detail": str(detail) if detail.exists() else None,
        "pages": len(PAGE_RX.findall(md)),
        "ocr_pages": conv.get("ocr_pages"),
        "retried": conv.get("ocr_retried"),
        "rotated": conv.get("ocr_rotated"),
        "conf": conv.get("ocr_conf"),
        "known": known_words(md),
        "doubled": doubling(md),
        "seconds": round(time.time() - t0),
    }


def _init(env):
    os.environ.update(env)  # AX_FP_CACHE and AX_TEXTS of dupcheck among them


def sha16(path):
    h = hashlib.sha256()
    with open(intake_cfg.lp(path), "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:16]


def cmd_redo(cfg, a):
    from assistant_x.core import journal

    date = datetime.date.today().isoformat()
    gain = QUALITY["ocr_redo_gain"]
    tsv = cfg.index / ocr_score.TSV_NAME
    rows = ocr_score.read_tsv(tsv)
    codes = list(dict.fromkeys(a.codes or []))
    if a.worst:
        below = a.below if a.below is not None else QUALITY["ocr_note"]
        worst = sorted(
            (float(r["score"]), c)
            for c, r in rows.items()  # one read again stays out unless named
            if r.get("score") and float(r["score"]) < below and r.get("source") != "redo"
        )
        picked, drawings = [], 0
        for _, c in worst:  # a drawing sheet does not get better from a second reading: left out
            if len(picked) >= a.worst:
                break
            if c in codes:
                continue
            words = int(rows[c].get("words") or 0) or None
            pdf = library_pdf(cfg, c)
            if pdf and ocr_score.pdf_is_drawing(str(pdf), words):
                drawings += 1
                continue
            picked.append(c)
        codes += picked
        if drawings:
            say(f"Drawings among the worst skipped: {drawings}")
    if not codes:
        say("Nothing to recognize: give codes or --worst N")
        return 1
    if not intake_cfg.can_ocr(cfg):
        say("No Tesseract (assistant_x.toml, tesseract): nothing to recognize with")
        return 1
    work = cfg.work / "redo" / f"{date}_{time.strftime('%H%M%S')}"  # a fresh folder: no page cache of an older run
    work.mkdir(parents=True, exist_ok=True)
    env = {**intake_cfg.tool_env(cfg), "AX_FP_CACHE": str(cfg.fingerprints)}
    base = {
        "soffice": None,
        "ocr": True,
        "timeouts": cfg.timeouts,
        "memory_mb": cfg.worker_memory_mb,
        "env": env,
        "ocr_threads": 1,
        "inproc": True,
    }
    texts = cfg.index / "texts"
    jobs, results = [], {}
    for code in codes:
        tp, pdf = texts / f"{code}.md", library_pdf(cfg, code)
        if not tp.exists() or pdf is None:
            results[code] = {
                "code": code,
                "why": "no text in index\\texts" if not tp.exists() else "found no PDF of the document by manifest.tsv",
            }
            continue
        old = tp.read_text(encoding="utf-8")
        jobs.append((code, pdf, old, words_score(old), known_words(old), doubling(old)))
    n_workers = max(1, min(cfg.workers or 1, len(jobs), 6))
    say(f"Recognizing documents again: {len(jobs)} in {n_workers} processes → {work}")
    t0 = time.time()
    with ProcessPoolExecutor(n_workers, initializer=_init, initargs=(env,)) as ex:
        futs = {
            ex.submit(redo_one, code, str(pdf), str(work), base, old_s, old_k, broken(old)): (
                code,
                pdf,
                old_s,
                old_k,
                old_d,
            )
            for code, pdf, old, old_s, old_k, old_d in jobs
        }
        for f in as_completed(futs):
            code, pdf, old_s, old_k, old_d = futs[f]
            try:
                r = f.result()
            except Exception as e:  # noqa: BLE001 — one document must not stop the others
                r = {"code": code, "why": f"failure: {e!r}"[:300]}
            r.update(old=old_s, old_known=old_k, old_doubled=old_d, pdf=str(pdf))
            results[code] = r
            say(
                f"  {code}: was {old_s}, now {r.get('new')} ({r.get('variant') or r.get('why')}), {r.get('seconds', 0)} s"
                f" — {len(results)}/{len(codes)}, {time.time() - t0:.0f} s"
            )
    events, replaced = [], 0
    for code in codes:
        r = results[code]
        r["status"] = verdict(r, texts, gain)
        r["replaced"] = r["status"].startswith("recognized again: text replaced")
        if r["replaced"] and not a.dry_run:
            new_md = Path(r["md"]).read_text(encoding="utf-8")
            tmp = texts / f"{code}.md.tmp"
            tmp.write_text(new_md, encoding="utf-8", newline="\n")
            os.replace(tmp, texts / f"{code}.md")
            # what is known of the pages is replaced with the text; a text without it leaves none of the old one
            info, old_info = Path(pages_path(r["md"])), texts / f"{code}{PAGES_SUFFIX}"
            if info.exists():
                shutil.copyfile(info, str(old_info) + ".tmp")
                os.replace(str(old_info) + ".tmp", old_info)
            elif old_info.exists():
                old_info.unlink()
            detail = (
                json.loads(Path(r["detail"]).read_text(encoding="utf-8"))
                if r.get("detail")
                else ocr_score.score_text(new_md)
            )
            rows[code] = ocr_score.row_of(code, detail, "redo", date)
            replaced += 1
        if r.get("pdf"):
            place = "library\\" + place_of(str(Path(r["pdf"]).relative_to(cfg.library)))
            size, sha = os.path.getsize(intake_cfg.lp(r["pdf"])), sha16(r["pdf"])
        else:
            place, size, sha = "—", "—", "—"
        events.append([date, place, size, sha, code, f"index\\texts\\{code}.md", r["status"]])
    if not a.dry_run:
        if replaced:
            ocr_score.write_tsv(tsv, rows)
        journal.append_events(cfg.index / "intake_events.tsv", events)
        journal.sync(cfg.index)
    rep = report(results, codes, date, a.dry_run, time.time() - t0)
    cfg.reports.mkdir(parents=True, exist_ok=True)
    rp = cfg.reports / f"ocr_redo_{date}_{time.strftime('%H%M')}.md"
    rp.write_text(rep, encoding="utf-8")
    would = sum(r.get("replaced", False) for r in results.values())
    say(
        f"Texts replaced: {replaced} of {len(codes)}"
        + (f" (trial run: {would} would be replaced, nothing changed)" if a.dry_run else "")
        + f". Report: {rp}"
    )
    if replaced and not a.dry_run:
        say("Next: assistant-x build and assistant-x embed")
    return 0


def verdict(r, texts, gain):
    """The event line of one document read again: "recognized again: text replaced — …" or "… text kept — why"."""
    old_s, new_s, code = r.get("old"), r.get("new"), r["code"]
    tp = texts / f"{code}.md"
    old_pages = len(PAGE_RX.findall(tp.read_text(encoding="utf-8"))) if tp.exists() else 0
    if r.get("why"):
        return f"recognized again: text kept — {r['why']}"
    if new_s is None:
        return "recognized again: text kept — the new text has no words"
    if r["pages"] != old_pages:
        return f"recognized again: text kept — {r['pages']} pages, but the previous text has {old_pages}"
    old_d, new_d = tuple(r.get("old_doubled") or (0.0, 0.0)), tuple(r.get("doubled") or (0.0, 0.0))
    if r["known"] < QUALITY["ocr_redo_keep"] * r["old_known"]:  # known words count once per page: doubling aside
        return (
            f"recognized again: text kept — the new one has fewer known words ({r['known']} against "
            f"{r['old_known']}), score {fmt(old_s)} → {fmt(new_s)}"
        )
    if new_s < (old_s or 0) + gain and undoubled(old_d, new_d) and new_s >= (old_s or 0) - REDO_LOSS:
        return (
            f"recognized again: text replaced — no longer doubled: doubled pages {old_d[0]:.0%} → {new_d[0]:.0%}, "
            f"score by words {fmt(old_s)} → {fmt(new_s)} ({r['variant']})"
        )
    if new_s < (old_s or 0) + gain:
        return (
            f"recognized again: text kept — score {fmt(old_s)} → {fmt(new_s)}, "
            f"{'growth below ' + str(gain) if new_s >= (old_s or 0) else 'the new one is worse'}"
        )
    return (
        f"recognized again: text replaced — score by words {fmt(old_s)} → {fmt(new_s)}, with the OCR confidence "
        f"{fmt(r.get('full'))} ({r['variant']})"
    )


def fmt(x):
    return "—" if x is None else f"{x:.0f}"


def report(results, codes, date, dry, seconds):
    rs = [results[c] for c in codes]
    done = [r for r in rs if r.get("replaced")]
    L = [
        f"# Library documents recognized again ({date})",
        "",
        f"Documents {len(rs)}, text replaced in {len(done)}"
        + (" (trial run: nothing changed)" if dry else "")
        + f"; replacement threshold: the vocabulary score grows by {QUALITY['ocr_redo_gain']} or more. Time {seconds / 60:.0f} min.",
        '"Was" and "Now" are the scores by words (old texts have no confidence); "With confidence" is the score of '
        "the new text with the Tesseract confidence, it is written to ocr_quality.tsv.",
        "",
        "| Code | Was | Now | With confidence | Known words: was → now | Variant | Pages | OCR pages | Retries | "
        "Rotations | Confidence | Time, s | Result |",
        "|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in rs:
        known = f"{r['old_known']} → {r['known']}" if r.get("known") is not None and r.get("old_known") is not None else ""
        L.append(
            f"| {r['code']} | {fmt(r.get('old'))} | {fmt(r.get('new'))} | {fmt(r.get('full'))} | {known} | "
            f"{r.get('variant') or ''} | "
            f"{r.get('pages') or ''} | "
            f"{r.get('ocr_pages') if r.get('ocr_pages') is not None else ''} | {r.get('retried') or ''} | "
            f"{r.get('rotated') or ''} | {fmt(r.get('conf')) if r.get('conf') is not None else ''} | "
            f"{r.get('seconds') or ''} | {r.get('status', r.get('why', '')).split(' — ', 1)[-1]} |"
        )
    return "\n".join(L) + "\n"
