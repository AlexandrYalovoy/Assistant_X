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
    --reuse <redo folder>                                     take the texts an earlier (stopped) run finished

Old and new texts are compared by the word part of the score (tools/ocr_score.py without the Tesseract confidence:
the old texts have none). A document with a broken font (U+FFFD, Latin Extended-B), or with a text layer whose new
text lost known words, is tried once more with the page images recognised instead of the layer (as the intake does
for a broken font encoding). Known words count once per page, so a doubled old text is not "richer". Every document gets a
row in index/intake_events.tsv ("recognized again: …", why the text was or was not replaced); a replaced one gets
its new row in ocr_quality.tsv (source "redo"). The work goes to intake/work/redo/<date>_<time>/; the library PDF is
copied there, library is only read. A replaced text and its page file are copied to inbox/_to_delete/redo_<date>/
first.

The documents are read as the intake reads them (process.Batch): the tasks prep, convert and, for a long scan, the OCR
in page ranges (schedule.shard_count) on the persistent workers with the load regulator (process.regulated_pool); the
biggest documents start first, so a long scan does not make the tail of the run. Each document is decided and its
text replaced as soon as its last reading is back (a stopped run keeps what it finished; results.jsonl of the work
folder has a line a document). After replacements: build_index.py and embed.py.
"""

import datetime, hashlib, heapq, itertools, json, os, re, shutil, time
from concurrent.futures import FIRST_COMPLETED, wait
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
REDO_LOSS = 5  # a new text this much below the old score by words is worse: it is not taken
# a pipeline text of a document with a text layer this much below the old score: its page images are read too. Run 2a2
# (62 doubled scans with a layer): 25 lost 1-5 points without that reading, the page images of the same scans scored
# about 3 points more (N-00006 88.6 against 91.7, N-00019 94.9 against 98.6)
SECOND_LOSS = 1
VARIANTS = {"pipeline": "", "page images": "_img"}  # a variant of the reading and the suffix of its tid


def words_score(md):
    return ocr_score.score_text(md)["score"]


def doubling(md):
    """(share of the pages whose text is doubled, mean share of repeated word 3-grams of the pages) of a text."""
    pages = ocr_score.score_text(md)["pages"]
    if not pages:
        return 0.0, 0.0
    rep = [p.get("repeated", 0.0) for p in pages]
    return round(sum(map(ocr_score.doubled_page, pages)) / len(rep), 3), round(sum(rep) / len(rep), 3)


def undoubled(old, new):
    """True when the new text is no longer doubled as the old one was ((share, mean) of doubling())."""
    return old[0] - new[0] >= UNDOUBLED_DROP or (old[1] - new[1] >= UNDOUBLED_MEAN and new[1] < UNDOUBLED_MEAN)


def known_words(md):
    """Known words of a text, each once per page (ocr_score.known_distinct): a doubled old text does not count its
    words twice against its clean recognition."""
    return ocr_score.known_distinct(md)


def broken(md):
    return ocr_score.LOST in md or bool(ocr_score.BROKEN_FONT.search(md))


def second_reading(md, conv, old_score=None, old_known=0, old_broken=False):
    """Are the page images read as a second variant after the pipeline text md (conv: pages, ocr_pages)? Only when a
    font is broken (old or new text), or the new text of a document with a text layer lost known words or fell
    SECOND_LOSS below the old score (a poor visible layer): a score that merely did not grow is no reason for a second,
    longer reading."""
    layer = (conv.get("ocr_pages") or 0) < (conv.get("pages") or 0)
    worse = old_score is not None and (words_score(md) or 0) < old_score - SECOND_LOSS
    lost = known_words(md) < QUALITY["ocr_redo_keep"] * old_known
    return old_broken or broken(md) or (layer and (worse or lost))


def best_variant(texts, old_known):
    """The name of the variant taken of texts {name: Markdown}: one that keeps the known words first, then by score;
    the pipeline on a tie."""
    keep = QUALITY["ocr_redo_keep"] * old_known

    def rank(name):
        return known_words(texts[name]) >= keep, words_score(texts[name]) or 0, name == "pipeline"

    return max(texts, key=rank)


def keep_aside(texts, code, aside):
    """Copy the text of a code and its page file into aside (inbox\\_to_delete\\redo_<date>) before they are replaced;
    a copy of an earlier run of the same day is kept, the new one gets the time in its name."""
    aside.mkdir(parents=True, exist_ok=True)
    for name in (f"{code}.md", f"{code}{PAGES_SUFFIX}"):
        src = texts / name
        if not src.exists():
            continue
        dst = aside / name
        if dst.exists():
            dst = aside / f"{time.strftime('%H%M%S')}_{name}"
        shutil.copy2(src, dst)


def sha16(path):
    h = hashlib.sha256()
    with open(intake_cfg.lp(path), "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:16]


def reuse_finished(old_work, work, code):
    """Copy the finished readings of a code from an earlier redo folder (md, page file, OCR detail, the variant
    record) into this run: those variants are not read again. The page cache is not taken: an older run may have read
    with other settings. Returns the variants found."""
    found = []
    for name, suffix in VARIANTS.items():
        tid = f"{code}{suffix}"
        src = Path(old_work) / code
        if not (src / "md" / f"{tid}.md").exists():
            continue
        for sub, fname in (
            ("md", f"{tid}.md"),
            ("md", f"{tid}{PAGES_SUFFIX}"),
            ("ocr", f"{tid}.json"),
            (".", f"variant_{tid}.json"),
        ):
            if (src / sub / fname).exists():
                (Path(work) / code / sub).mkdir(parents=True, exist_ok=True)
                shutil.copy2(src / sub / fname, Path(work) / code / sub / fname)
        found.append(name)
    return found


class Redo:
    """The documents of one run through the pool, each decided and written as soon as its readings are back."""

    def __init__(self, cfg, work, base, ex, workers, texts, finish):
        from assistant_x.intake import schedule

        self.cfg, self.work, self.base, self.ex, self.workers = cfg, Path(work), base, ex, max(1, workers)
        self.texts, self.finish = texts, finish
        self.sharding = cfg.get("ocr_shards", "auto") != "off" and self.workers > 1
        self.schedule = schedule
        self.ready, self.seq = [], itertools.count()  # (rank of the document, order, task)
        self.inflight = {}  # future -> task
        self.shards = {}  # tid -> [ranges left, the convert job]
        self.retried = set()

    # ---------- the readings of a document ----------

    def start(self, d):
        w = Path(d["w"])
        (w / "src").mkdir(parents=True, exist_ok=True)
        src = w / "src" / f"{d['code']}.pdf"
        if not src.exists():
            shutil.copy2(intake_cfg.lp(d["pdf"]), src)  # a copy: the work never links to library
        d["base"] = {**self.base, "work": str(w), "src": str(src), "rel": f"{d['code']}.pdf", "ext": "pdf"}
        d["t0"], d["texts"], d["convs"], d["busy"] = time.time(), {}, {}, 0.0
        self.variant(d, "pipeline")

    def variant(self, d, name):
        w, tid = Path(d["w"]), d["code"] + VARIANTS[name]
        if name != "pipeline":
            img_src = w / "src" / f"{tid}.pdf"  # prep of a variant takes the file under its own name
            if not img_src.exists():
                shutil.copy2(w / "src" / f"{d['code']}.pdf", img_src)
        rec, md = w / f"variant_{tid}.json", w / "md" / f"{tid}.md"
        if rec.exists() and md.exists():  # read by an earlier run (--reuse)
            conv = json.loads(rec.read_text(encoding="utf-8"))
            return self.read(d, name, md.read_text(encoding="utf-8"), conv)
        job = {**d["base"], "tid": tid, "imgocr": name != "pipeline"}
        self.push(d, ("prep", d, name, tid, None, job))

    def prepped(self, d, name, tid, job, res):
        from assistant_x.intake import work as intake_work

        if res.get("status") in ("error", "skipped"):
            return self.failed(d, name, res.get("why"))
        d["busy"] += res.get("prep_seconds") or 0
        job = {
            **job,
            "pdf": res["pdf"],
            "ocr_pages": res.get("ocr_pages"),
            "scan_pages": res.get("scan_pages"),  # the scanned pages and the text pages with a picture: as the intake
            "picture_pages": res.get("picture_pages"),
            "phrases": res.get("phrases", 0),
            "pages_total": res.get("pages"),
        }
        md = Path(d["w"]) / "md" / f"{tid}.md"
        if d.get("reused") and md.exists():  # a text of a run before the variant records: its pages from this prep
            conv = {"pages": res.get("pages"), "ocr_pages": res.get("ocr_pages"), "reused": True}
            return self.read(d, name, md.read_text(encoding="utf-8"), conv)
        read = sorted(set(res.get("scan_pages") or []) | set(res.get("picture_pages") or []))
        k = self.schedule.shard_count(len(read), self.workers) if self.sharding else 1
        if k > 1:
            ranges = self.schedule.shard_ranges(res.get("pages") or 0, read, k)
            self.shards[tid] = [len(ranges), job, len(ranges)]
            d["ranges"] = d.get("ranges", 0) + len(ranges)
            for a, b in ranges:
                part = {**job, "pages": [a, b], "memory_mb": self.cfg.worker_memory_mb}
                self.push(d, ("convert_shard", d, name, tid, intake_work.convert_shard, part))
            return None
        self.push(d, ("convert", d, name, tid, intake_work.convert, job))

    def shard_back(self, d, name, tid, res):
        from assistant_x.intake import work as intake_work

        if isinstance(res, dict) and res.get("status") == "error":
            say(f"  {tid}: a page range was not read ({res.get('why')}); the conversion reads it")
        elif isinstance(res, dict):
            d["busy"] += res.get("seconds") or 0
        left = self.shards.get(tid)
        if left is None:
            return
        left[0] -= 1
        say(f"  {tid}: page ranges read {left[2] - left[0]}/{left[2]}")  # a long scan is written only when all are back
        if left[0] <= 0:
            job = self.shards.pop(tid)[1]
            self.push(d, ("convert", d, name, tid, intake_work.convert, job))

    def converted(self, d, name, tid, job, res):
        if res.get("status") == "error":
            return self.failed(d, name, res.get("why"))
        d["busy"] += res.get("convert_seconds") or 0
        md = Path(d["w"]) / "md" / f"{tid}.md"
        conv = {
            **{k: v for k, v in res.items() if k not in ("fp", "letters")},
            "pages": job.get("pages_total"),
            "ocr_pages": job.get("ocr_pages"),
        }
        (Path(d["w"]) / f"variant_{tid}.json").write_text(json.dumps(conv, ensure_ascii=False), encoding="utf-8")
        self.read(d, name, md.read_text(encoding="utf-8") if md.exists() else "", conv)

    def read(self, d, name, md, conv):
        d["texts"][name], d["convs"][name] = md, conv
        if name == "pipeline" and second_reading(md, conv, d["old_score"], d["old_known"], d["old_broken"]):
            return self.variant(d, "page images")
        self.done(d)

    def failed(self, d, name, why):
        if name == "pipeline":
            d["why"] = f"recognition failed: {why}"
        else:
            d["variants_failed"] = why
        self.done(d)

    def done(self, d):
        """The result of a document as the old redo_one gave it; the run decides and writes it at once."""
        if d.get("finished"):
            return
        d["finished"] = True
        w, code = Path(d["w"]), d["code"]
        out = {"code": code, "variants": {n: words_score(t) for n, t in d["texts"].items()}}
        out["seconds"], out["busy"], out["ranges"] = round(time.time() - d["t0"]), round(d["busy"]), d.get("ranges", 0)
        if d.get("variants_failed"):
            out["variants_failed"] = d["variants_failed"]
        if d.get("why") or not d["texts"]:
            out["why"] = d.get("why") or "recognition failed"
            return self.finish(d, out)
        name = best_variant(d["texts"], d["old_known"])
        md, conv, tid = d["texts"][name], d["convs"][name], code + VARIANTS[name]
        detail = w / "ocr" / f"{tid}.json"
        full = json.loads(detail.read_text(encoding="utf-8"))["score"] if detail.exists() else None
        out.update(
            variant=name,
            new=out["variants"][name],
            full=full,
            md=str(w / "md" / f"{tid}.md"),
            detail=str(detail) if detail.exists() else None,
            pages=len(PAGE_RX.findall(md)),
            ocr_pages=conv.get("ocr_pages"),
            retried=conv.get("ocr_retried"),
            rotated=conv.get("ocr_rotated"),
            conf=conv.get("ocr_conf"),
            known=known_words(md),
            doubled=doubling(md),
        )
        self.finish(d, out)

    # ---------- the pool ----------

    def push(self, d, task):
        heapq.heappush(self.ready, (d["rank"], next(self.seq), task))

    def send(self):
        while self.ready and len(self.inflight) < self.workers + 1:  # one task more keeps the pool busy
            *_, task = heapq.heappop(self.ready)
            stage, d, name, tid, fn, job = task
            if stage == "prep":
                from assistant_x.intake import work as intake_work

                fn = intake_work.prep
            mem = job.get("memory_mb") if tid in self.retried else None
            kw = {"memory_mb": mem} if mem else {}
            self.inflight[self.ex.submit(fn, job, **kw)] = task

    def run(self, docs):
        from assistant_x.intake import pool as intake_pool

        for d in docs:
            self.start(d)
        self.send()
        while self.inflight or self.ready:
            done, _ = wait(list(self.inflight), timeout=10, return_when=FIRST_COMPLETED)
            for f in done:
                task = self.inflight.pop(f)
                stage, d, name, tid, fn, job = task
                if d.get("finished"):  # a failed document: the rest of its tasks are of no use
                    continue
                try:
                    res = f.result()
                except intake_pool.Lost as e:
                    if e.why == "memory" and stage != "convert_shard" and tid not in self.retried:
                        self.retried.add(tid)
                        mem = 2 * self.cfg.worker_memory_mb
                        say(f"  {tid}: {stage} — memory cap exceeded, once more with a cap of {mem} MB")
                        self.push(d, (stage, d, name, tid, fn, {**job, "memory_mb": mem}))
                        continue
                    res = {"status": "error", "why": f"{stage}: {e.why} ({e.detail}); the worker process was restarted"}
                except Exception as e:  # noqa: BLE001 — one document must not stop the others
                    res = {"status": "error", "why": f"{stage}: {e!r}"[:300]}
                try:
                    if stage == "prep":
                        self.prepped(d, name, tid, job, res)
                    elif stage == "convert_shard":
                        self.shard_back(d, name, tid, res)
                    else:
                        self.converted(d, name, tid, job, res)
                except Exception as e:  # noqa: BLE001 — a broken result of one document must not stop the others
                    d["why"] = f"failure: {e!r}"[:300]
                    d["texts"] = {}
                    self.done(d)
            self.send()


def cmd_redo(cfg, a):
    from assistant_x.core import journal

    date = datetime.date.today().isoformat()
    gain = QUALITY["ocr_redo_gain"]
    tsv = cfg.index / ocr_score.TSV_NAME
    rows = ocr_score.read_tsv(tsv)
    codes = list(dict.fromkeys(a.codes or []))
    if getattr(a, "worst", None):
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
    reuse = getattr(a, "reuse", None)
    if reuse and not Path(reuse).is_dir():
        say(f"No such redo folder: {reuse}")
        return 1
    work = cfg.work / "redo" / f"{date}_{time.strftime('%H%M%S')}"  # a fresh folder: no page cache of an older run
    while work.exists():  # two runs in one second
        work = work.with_name(work.name + "b")
    work.mkdir(parents=True)
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
    aside = Path(cfg.inbox) / "_to_delete" / f"redo_{date}"  # the replaced texts, never deleted
    docs, results, reused = [], {}, 0
    for code in codes:
        tp, pdf = texts / f"{code}.md", library_pdf(cfg, code)
        if not tp.exists() or pdf is None:
            results[code] = {
                "code": code,
                "why": "no text in index\\texts" if not tp.exists() else "found no PDF of the document by manifest.tsv",
            }
            continue
        old = tp.read_text(encoding="utf-8")
        d = {
            "code": code,
            "pdf": str(pdf),
            "w": str(work / code),
            "old_score": words_score(old),
            "old_known": known_words(old),
            "old_doubled": doubling(old),
            "old_broken": broken(old),
            "old_pages": len(PAGE_RX.findall(old)),
        }
        if reuse and reuse_finished(reuse, work, code):
            d["reused"] = True
            reused += 1
        docs.append(d)
    # the documents read by an earlier run first (seconds of prep each: they are written at once), then the biggest: a
    # long scan starts early and its page ranges fill the workers, it does not make the tail
    for i, d in enumerate(sorted(docs, key=lambda d: (not d.get("reused"), -d["old_pages"]))):
        d["rank"] = i
    t0 = time.time()
    events_path, results_path = cfg.index / "intake_events.tsv", work / "results.jsonl"
    replaced = 0

    def finish(d, r):
        nonlocal replaced
        code = d["code"]
        r.update(old=d["old_score"], old_known=d["old_known"], old_doubled=d["old_doubled"], pdf=d["pdf"])
        r["status"] = verdict(r, texts, gain)
        r["replaced"] = r["status"].startswith("recognized again: text replaced")
        if r["replaced"] and not a.dry_run:
            apply_text(texts, code, r, aside, rows, date)
            ocr_score.write_tsv(tsv, rows)
            replaced += 1
        if not a.dry_run and (texts / f"{code}.md").exists():
            dropped = clear_doubled_issue(cfg.index / "cards", code, (texts / f"{code}.md").read_text(encoding="utf-8"))
            if dropped:
                say(f"    the card no longer says the text is doubled ({dropped} issue)")
        if not a.dry_run:
            journal.append_events(events_path, [event(cfg, date, code, r)])
        results[code] = r
        with open(results_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({k: v for k, v in r.items() if k != "md"}, ensure_ascii=False) + "\n")
        say(
            f"  {code}: was {r.get('old')}, now {r.get('new')} ({r.get('variant') or r.get('why')}), {r.get('seconds', 0)} s"
            f" — {len(results)}/{len(codes)}, {time.time() - t0:.0f} s"
        )
        say(f"    {r['status'].split(': ', 1)[-1]}; worker s {r.get('busy', 0)}, page ranges {r.get('ranges', 0)}")

    ex = None
    if docs:
        from assistant_x.intake import process

        ex, n_workers = process.regulated_pool(cfg, cfg.workers or 1, env, work / "balance.log", tasks=len(docs))
        say(
            f"Recognizing documents again: {len(docs)} in {n_workers} processes, the biggest first"
            + (f", {reused} with readings of {reuse}" if reuse else "")
            + f" → {work}"
        )
        try:
            Redo(cfg, work, base, ex, n_workers, texts, finish).run(docs)
        finally:
            ex.shutdown(cancel_futures=True)
    for code in codes:  # the documents without a text or a PDF
        r = results.get(code)
        if r is None:
            continue
        if "status" not in r:
            r["status"] = verdict(r, texts, gain)
            r["replaced"] = False
            if not a.dry_run:
                journal.append_events(events_path, [event(cfg, date, code, r)])
    if not a.dry_run:
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


def apply_text(texts, code, r, aside, rows, date):
    """Put the new text of a code (and what is known of its pages) into index/texts, the old one aside first."""
    keep_aside(texts, code, aside)
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
    detail = json.loads(Path(r["detail"]).read_text(encoding="utf-8")) if r.get("detail") else ocr_score.score_text(new_md)
    rows[code] = ocr_score.row_of(code, detail, "redo", date)


# an issue of a card that says the text is doubled (written with the card at the intake; the issues are in English)
DOUBLED_ISSUE = re.compile(r"appears twice|doubled", re.I)


def clear_doubled_issue(cards, code, md):
    """Drop the issues "the text is doubled" from the card of a code whose text md is no longer doubled (run 2a4: 125
    cards kept the issue after their text was replaced, and every hit of those documents warned of it). Returns how
    many were dropped."""
    from assistant_x.core import card

    path = Path(cards) / f"{code}.json"
    if not path.exists() or doubling(md)[0] >= UNDOUBLED_MEAN:
        return 0
    c = card.load(path)
    issues = (c.get("file") or {}).get("issues") or []
    keep = [i for i in issues if not DOUBLED_ISSUE.search(str(i.get("what", "")))]
    if len(keep) == len(issues):
        return 0
    c["file"]["issues"] = keep
    card.dump(c, path)
    return len(issues) - len(keep)


def event(cfg, date, code, r):
    """The row of index/intake_events.tsv of a document read again."""
    if r.get("pdf"):
        place = "library\\" + place_of(str(Path(r["pdf"]).relative_to(cfg.library)))
        size, sha = os.path.getsize(intake_cfg.lp(r["pdf"])), sha16(r["pdf"])
    else:
        place, size, sha = "—", "—", "—"
    return [date, place, size, sha, code, f"index\\texts\\{code}.md", r["status"]]


def verdict(r, texts, gain):
    """The event line of one document read again: "recognized again: text replaced — …" or "… text kept — why"."""
    old_s, new_s, code = r.get("old"), r.get("new"), r["code"]
    if r.get("why"):
        return f"recognized again: text kept — {r['why']}"
    tp = texts / f"{code}.md"
    old_pages = len(PAGE_RX.findall(tp.read_text(encoding="utf-8"))) if tp.exists() else 0
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
    rs = [results[c] for c in codes if c in results]
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
