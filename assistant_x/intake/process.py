# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Processing a batch (intake run, step 2): the files of inbox registered, the exact and the content duplicates,
the pool of workers (PDF, hidden text, Markdown, OCR), the state of every file."""

import collections, os, time
from array import array
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, ThreadPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from assistant_x.core.formats import PAGES_SUFFIX
from assistant_x.intake import config as intake_cfg
from assistant_x.intake import pool as intake_pool
from assistant_x.intake import schedule, versions
from assistant_x.intake.batch import AUTO, DUP, PAGES_APART, PARTIAL, SAME, say, win
from assistant_x.intake.prepare import KIT, THICK, known_hashes, sha256, walk
from assistant_x.intake.results import Convert, Job, Prep


def fp_path(work, tid):
    return Path(work) / "fp" / f"{tid}.bin"


def save_fp(work, tid, fp):
    fp_path(work, tid).parent.mkdir(exist_ok=True)
    fp_path(work, tid).write_bytes(array("Q", fp).tobytes())


def load_fp(work, tid):
    p = fp_path(work, tid)
    if not p.exists():
        return set()
    a = array("Q")
    a.frombytes(p.read_bytes())
    return set(a)


STAGES = {"prep": "preparation", "convert": "conversion to Markdown"}
POLL = 10  # seconds the batch waits for a task before it looks at which tasks a worker holds


def lost_why(stage, e):
    """Reason of a file whose persistent worker was killed (time, memory) or died twice."""
    what = {
        "timeout": f"time exceeded ({e.detail})",
        "memory": f"memory cap exceeded ({e.detail})",
        "crash": f"the worker process crashed twice ({e.detail}, a broken file?)",
    }[e.why]
    return f"{STAGES.get(stage, stage)}: {what}; the worker process was restarted"


class Inline:
    """Executor that runs the task at once (--workers 0: tests, debugging)."""

    def __init__(self, init=None, args=()):
        if init:
            init(*args)

    def submit(self, fn, *a):
        f = Future()
        try:
            f.set_result(fn(*a))
        except BaseException as e:  # noqa: BLE001 — returned to the loop like a pool would
            f.set_exception(e)
        return f

    def shutdown(self, wait=True, cancel_futures=False):
        pass


# ---------- processing ----------


class Batch:
    def __init__(self, cfg, work, state, workers):
        self.cfg, self.work, self.state, self.workers = cfg, Path(work), state, workers
        fpc = cfg.fingerprints
        fpc.mkdir(parents=True, exist_ok=True)
        self.env = {**intake_cfg.tool_env(cfg), "AX_FP_CACHE": str(fpc), "AX_TEXTS": str(cfg.index / "texts")}
        self.base = {
            "work": str(self.work),
            "soffice": cfg.soffice,
            "ddjvu": cfg.get("ddjvu"),
            "ocr": intake_cfg.can_ocr(cfg),
            "timeouts": cfg.timeouts,
            "memory_mb": cfg.worker_memory_mb,
            "env": self.env,
            "ocr_threads": cfg.ocr_threads,
            "inproc": cfg.stage_mode == "inproc",
        }
        self.lib, self.mine, self.crashed = {}, {}, collections.Counter()
        self.lib_editions = {}  # code -> (pages, designation) of a library text, read once
        self.ex = None

    def pool(self):
        from assistant_x.intake import work as intake_work

        args = (self.cfg.worker_memory_mb, self.env)
        if self.workers <= 0:  # no memory cap on this process: it is the main one
            return Inline(intake_work.init_worker, args + (False,))
        if self.base["inproc"]:
            from assistant_x.intake import balance
            from assistant_x.intake import pool as intake_pool

            o = self.cfg.get("balance") or balance.options({})
            hw = balance.probe()
            b = balance.budget(hw, o, cap=self.workers, worker_mb=self.cfg.worker_memory_mb)
            self.env.update(balance.env(self.cfg.priority, self.cfg.affinity, b["threads"]))
            ex = intake_pool.Persistent(
                b["workers"], self.cfg.worker_memory_mb, self.env, b["threads"], timeout=intake_work.task_timeout
            )
            log = self.work / "balance.log"
            intake_pool._write(log, balance.describe(hw, b, o))
            say(f"Load: {balance.describe(hw, b, o)}; journal {log}")
            self.workers = b["workers"]
            if o.get("regulate", True):
                reg = balance.Regulator(b, o, hw)
                ex.set_active(reg.n)
                auto = self.cfg.affinity in (None, "", "auto")
                e = hw["ecores"] if auto else None
                emask = sum(1 << i for i in e) if e and len(e) >= b["active"] * b["threads"] else 0
                amask = (1 << hw["logical"]) - 1 if auto and hw["logical"] <= 64 else 0
                ex.regulate(reg, balance.Sensors(has_gpu=bool(hw["gpu"])), log=log, ecores_mask=emask, all_mask=amask)
            return ex
        return ProcessPoolExecutor(self.workers, initializer=intake_work.init_worker, initargs=args)

    def library_fingerprints(self):
        from assistant_x.intake import work as intake_work

        texts = sorted(p for p in (self.cfg.index / "texts").glob("*.md") if not p.name.startswith("_"))
        t0 = time.time()
        futs = [self.ex.submit(intake_work.lib_fp, str(p)) for p in texts]
        for p, f in zip(texts, futs):
            try:
                k, fp = f.result()
            except Exception as e:  # noqa: BLE001 — one text without a fingerprint must not stop the batch
                say(f"  fingerprint of {p.name} not taken: {e!r}"[:300])
                continue
            self.lib[k] = set(fp)
        say(f"library fingerprints: {len(self.lib)} texts in {time.time() - t0:.0f} s")

    def similar(self, cand, tid):
        if len(cand) < 30:
            return []
        best = sorted(
            (
                (len(cand & fp) / len(cand), k)
                for k, fp in list(self.lib.items()) + list(self.mine.items())
                if k != tid and fp
            ),
            reverse=True,
        )[:3]
        return [(round(a, 2), k) for a, k in best if a >= PARTIAL]

    def dup_verdict(self, tid, row, cand):
        """Status update for the content check: dup, or suspect/rival notes. A file is a duplicate by itself only
        when it is the same edition: SAME of the phrases, the page count within PAGES_APART and no other year in the
        designation; another edition of a document (70 % of the text in common, a new year) stays a suspect for
        Claude to ask about."""
        sim = self.similar(cand, tid)
        upd = {"similar": sim}
        if not sim or row.get("nodup"):
            return upd
        share, other = sim[0]
        if DUP <= share < AUTO:
            upd.update(suspect=other, suspect_why=f"{share:.0%} of the phrases match")
        if share >= AUTO:
            # a text original (doc/docx) beats an earlier-processed scan of the same document: keep both
            if other.startswith("T") and row["rel"].rsplit(".", 1)[-1].lower() in ("doc", "docx"):
                upd["rival"] = other
                return upd
            apart = self.editions_apart(tid, other, share)
            if apart:
                upd.update(suspect=other, suspect_why=f"{share:.0%} of the phrases match, but {apart}: another edition?")
            else:
                upd.update(status="dup", dup_of=other, why=f"{share:.0%} of the phrases match")
        return upd

    def edition(self, key):
        """(pages, designation) of a file of the batch (tid) or of a library text (code): what tells two editions of
        one document apart. The designation is read from the first pages of the text, as the draft reads it."""
        from assistant_x.core.common import split_pages
        from assistant_x.intake import metadraft

        if key in self.lib_editions:
            return self.lib_editions[key]
        if key in self.lib:
            path, pages = self.cfg.index / "texts" / f"{key}.md", None
        else:
            md = self.work / "md" / f"{key}.md"
            path = md if md.exists() else self.work / "txt" / f"{key}.txt"
            pages = (self.state.get(key) or {}).get("pages")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return pages, None
        if pages is None:
            pages = len(split_pages(text)) or None
        out = pages, metadraft.own_designation(metadraft.pages_of(text))
        if key in self.lib:
            self.lib_editions[key] = out
        return out

    def editions_apart(self, tid, other, share):
        """Why two texts sharing most of their phrases may be two editions (a reason), or "" when they are one."""
        (p1, d1), (p2, d2) = self.edition(tid), self.edition(other)
        if d1 and d2 and versions.key(d1) == versions.key(d2) and versions.norm(d1) != versions.norm(d2):
            return f"the designations differ ({d1} here, {d2} there)"
        if p1 and p2 and abs(p1 - p2) > PAGES_APART * max(p1, p2):
            return f"{p1} pages here, {p2} there"
        if share < SAME:
            return f"less than {SAME:.0%} of the phrases"
        return ""

    def job(self, row, **kw) -> Job:
        return {
            **self.base,
            "tid": row["tid"],
            "rel": row["rel"],
            "src": str(self.cfg.inbox / row["rel"]),
            "ext": row["rel"].rsplit(".", 1)[-1].lower() if "." in row["rel"] else "",
            "imgocr": row.get("imgocr"),
            **kw,
        }

    def hash_all(self):
        rows = [r for r in self.state.all("queued") if not r.get("sha256")]
        known = known_hashes(self.cfg)
        with ThreadPoolExecutor(4) as ex:
            sums = dict(zip([r["tid"] for r in rows], ex.map(lambda r: sha256(self.cfg.inbox / r["rel"]), rows)))
        firsts = {}
        for r in self.state.all():  # ordered by tid: the earliest file with a hash is the original
            if r.get("sha"):
                firsts.setdefault(r["sha"], r)
        n = 0
        for r in rows:
            full = sums[r["tid"]]
            sha = full[:16]
            upd = {"sha": sha, "sha256": full}
            if sha in known:
                upd.update(status="dup", dup_of=known[sha], why="SHA-256 matches the journal or the manifest")
                n += 1
            elif sha in firsts and firsts[sha]["tid"] < r["tid"]:
                upd.update(
                    status="dup",
                    dup_of=firsts[sha]["tid"],
                    why="SHA-256 matches a file of the batch: " + win(firsts[sha]["rel"]),
                )
                n += 1
            else:
                firsts.setdefault(sha, r)
            self.state.update(r["tid"], **upd)
        return n

    def run(self):
        """Every queued file through prep and convert on the pool. The order and the concurrency are those of
        schedule.py: prep of the small files first, then the conversions cheapest first, heavy ones side by side while
        their memory caps fit, the OCR of a long scan in page ranges on every worker."""
        from assistant_x.intake import work as intake_work

        n_sha = self.hash_all()
        if n_sha:
            say(f"Exact duplicates by SHA-256: {n_sha}")
        heavy_bytes = float(self.cfg["heavy_mb"]) * 2**20
        rows = self.state.all("queued")
        big = {r["tid"] for r in rows if (r.get("size") or 0) > heavy_bytes}  # before prep only the size is known
        # small files first, the scan images of a standard's kit last
        order = sorted(rows, key=lambda r: (bool(KIT) and KIT["scan"] in r["rel"], r.get("size") or 0, r["tid"]))
        queue = [r["tid"] for r in order]
        if not queue:
            return
        self.ex = self.pool()
        try:
            self.library_fingerprints()
            for r in self.state.all("done"):
                self.mine[r["tid"]] = load_fp(self.work, r["tid"])
            inflight, total, t0 = {}, len(queue), time.time()
            active, shown = set(), (None, 0.0)  # the tids a worker holds; the counter last printed and when
            tasks, retried = {}, {}  # future -> (fn, args, memory); the memory cap of a file tried once more
            ready, shards = schedule.Ready(), {}  # conversions waiting for a worker; tid -> [ranges left, its convert]
            heavy_caps = {}  # future -> the memory cap of a heavy task in flight
            workers = max(self.workers, 1)
            budget0 = self.heavy_budget()
            sharding = self.cfg.get("ocr_shards", "auto") != "off" and workers > 1 and not isinstance(self.ex, Inline)
            say(
                f"Files in work: {total}, processes {workers}, OCR {'yes' if self.base['ocr'] else 'NO'}, "
                f"LibreOffice {'yes' if self.base['soffice'] else 'NO'}"
            )

            def send(stage, tid, fn, *args, memory=None, is_heavy=False):
                memory = memory or self.memory_for(tid)
                kw = {"memory_mb": memory} if isinstance(self.ex, intake_pool.Persistent) else {}
                f = self.ex.submit(fn, *args, **kw)
                inflight[f], tasks[f] = (stage, tid), (fn, args, memory)
                if is_heavy:
                    heavy_caps[f] = memory
                self.state.update(tid, stage=stage, active=False)
                active.discard(tid)  # a new task of the file: in work again once a worker takes it

            def retry(stage, tid, fn, args, mem, why):
                """Once more with the double memory cap, in a fresh worker; the tools of the job get it too."""
                retried[tid] = min(2 * (mem or self.cfg.worker_memory_mb), self.memory_ceiling())
                say(f"  {tid}: {STAGES.get(stage, stage)} — {why}, once more with a cap of {retried[tid]} MB")
                self.state.update(tid, memory_retry=retried[tid])
                args = tuple(
                    {**a, "memory_mb": retried[tid]} if isinstance(a, dict) and "memory_mb" in a else a for a in args
                )
                ready.push(0, (stage, tid, fn, args, retried[tid], True), is_heavy=True)  # with its big cap

            def plan(tid, fn, job):
                """A conversion after prep: in page ranges (a long scan) or whole, into the ready tasks by its cost."""
                row = self.state.get(tid)
                pages, scans = row.get("pages") or 0, len(job.get("scan_pages") or []) if job.get("ocr") else 0
                c = schedule.cost(pages, scans)
                self.state.update(tid, cost=c)
                k = schedule.shard_count(scans, workers) if sharding and fn is intake_work.convert else 1
                if k > 1:
                    ranges = schedule.shard_ranges(pages, job["scan_pages"], k)
                    shards[tid] = [len(ranges), (fn, job)]
                    self.state.update(tid, shards=len(ranges))
                    say(f"  {tid}: OCR of {scans} scanned pages in {len(ranges)} page ranges")
                    for a, b in ranges:
                        n = sum(a <= p <= b for p in job["scan_pages"])
                        part = {**job, "pages": [a, b], "memory_mb": self.cfg.worker_memory_mb}
                        item = ("convert_shard", tid, intake_work.convert_shard, (part,), self.cfg.worker_memory_mb, False)
                        ready.push(schedule.cost(b - a + 1, n), item)
                    return
                hv = schedule.heavy(c, pages, THICK) or tid in retried
                ready.push(c, (fn.__name__, tid, fn, (job,), retried.get(tid), hv), is_heavy=hv)

            def shard_back(tid, res):
                """A range is back (or lost): when all are, the conversion of the file reads the cache."""
                if isinstance(res, dict) and res.get("status") == "error":
                    say(f"  {tid}: a page range was not read ({res.get('why')}); the conversion reads it")
                left = shards.get(tid)
                if left is None:
                    return
                left[0] -= 1
                if left[0] <= 0:
                    fn, job = shards.pop(tid)[1]
                    pages = self.state.get(tid).get("pages") or 0
                    hv = pages > THICK or tid in retried  # the OCR is done: the assembly of a thick text still needs memory
                    ready.push(schedule.cost(pages, 0), (fn.__name__, tid, fn, (job,), retried.get(tid), hv), is_heavy=hv)

            def light_left():
                return bool(queue) or ready.light()

            def may_heavy(item):
                cap = item[4] or self.memory_for(item[1])
                budget = min(budget0, self.heavy_budget(sum(heavy_caps.values())))
                return schedule.may_admit_heavy(
                    cap, list(heavy_caps.values()), budget, light_left(), len(heavy_caps), workers
                )

            while queue or inflight or len(ready):
                while len(inflight) < workers + 1:  # the pool has its own queue: one task more keeps it busy
                    item = ready.take(lambda it: False)  # a light conversion first
                    if item is None and queue:
                        tid = queue[0]
                        if not (tid in big and heavy_caps and not may_heavy(("prep", tid, None, (), None, True))):
                            queue.pop(0)  # small files first: a big one waits while the memory of heavy tasks is taken
                            self.state.update(tid, status="running")
                            send("prep", tid, intake_work.prep, self.job(self.state.get(tid)), is_heavy=tid in big)
                            continue
                    if item is None:
                        item = ready.take(may_heavy)
                    if item is None:
                        break
                    stage, tid, fn, args, mem, hv = item
                    send(stage, tid, fn, *args, memory=mem, is_heavy=hv)
                if not inflight:
                    if queue or len(ready):
                        continue
                    break
                done, _ = wait(list(inflight), timeout=POLL, return_when=FIRST_COMPLETED)
                self.mark_active(inflight, active)
                broken = False
                for f in done:
                    stage, tid = inflight.pop(f)
                    heavy_caps.pop(f, None)
                    fn0, args0, mem0 = tasks.pop(f, (None, (), None))
                    try:
                        res = f.result()
                    except BrokenProcessPool:
                        broken = True
                        if stage == "convert_shard":
                            shard_back(tid, {"status": "error", "why": "the worker process crashed"})
                            continue
                        self.crashed[tid] += 1
                        if self.crashed[tid] > 1:
                            self.state.update(tid, status="error", why="the worker process crashed twice (a broken file?)")
                        else:
                            queue.append(tid)
                        continue
                    except intake_pool.Lost as e:  # only the worker of this file was killed or died; it is replaced
                        if stage == "convert_shard":  # the conversion of the file reads the range once more
                            shard_back(tid, {"status": "error", "why": lost_why(stage, e)})
                            continue
                        self.crashed[tid] += e.why == "crash"
                        if e.why == "crash" and self.crashed[tid] == 1:
                            queue.append(tid)
                            continue
                        if e.why == "memory" and fn0 and tid not in retried:  # once more, double cap, a fresh worker
                            retry(stage, tid, fn0, args0, mem0, f"memory cap exceeded ({mem0} MB)")
                            continue
                        res = {"status": "error", "why": lost_why(stage, e)}
                    except Exception as e:  # noqa: BLE001 — one file must not stop the batch
                        if stage == "convert_shard":
                            shard_back(tid, {"status": "error", "why": f"{type(e).__name__}: {e}"})
                            continue
                        res = self.failed(stage, tid, e)
                    if stage == "convert_shard":
                        shard_back(tid, res)
                        continue
                    if isinstance(res, dict) and res.get("status") == "error" and res.pop("retry", None) == "memory":
                        if fn0 and tid not in retried:  # a tool past its cap, a MuPDF allocation failure: as above
                            retry(stage, tid, fn0, args0, mem0, res.get("why") or "memory")
                            continue
                    nxt = self.handle(stage, tid, res)
                    if nxt:
                        plan(tid, nxt[0], nxt[1])
                if broken:
                    for f, (stage, tid) in inflight.items():  # the rest of the broken pool goes back to the queue
                        if stage == "convert_shard":
                            shard_back(tid, {"status": "error", "why": "the pool broke"})
                        else:
                            queue.append(tid)
                    inflight.clear()
                    tasks.clear()
                    heavy_caps.clear()
                    self.ex.shutdown(wait=False, cancel_futures=True)
                    self.ex = self.pool()
                busy = {t for _, t in inflight.values()} | {it[1] for *_, it in ready.heap} | set(shards)
                ready_n = total - len(queue) - len(busy)
                if ready_n != shown[0] or time.time() - shown[1] >= 60:  # on change, else once a minute
                    say(f"  {ready_n}/{total} files, {time.time() - t0:.0f} s")
                    shown = (ready_n, time.time())
        finally:
            self.ex.shutdown(wait=True, cancel_futures=True)
            self.state.reset_running()
        self.batch_pairs()

    def heavy_budget(self, held_mb=0):
        """The memory heavy tasks may take together now (schedule.heavy_budget_mb): the free memory past the reserve of
        balance.py, plus what the heavy tasks in flight hold (their caps, held_mb) — they count against the budget
        themselves."""
        try:
            import psutil

            from assistant_x.intake import balance

            o = self.cfg.get("balance") or balance.options({})
            vm = psutil.virtual_memory()
            hw = {"ram_gb": vm.total / 2**30, "avail_gb": vm.available / 2**30}
            return schedule.heavy_budget_mb(hw["avail_gb"] + held_mb / 1024, balance.reserve_gb(hw, o))
        except Exception:  # noqa: BLE001 — no psutil, no measurement: one heavy task at a time
            return 0.0

    def mark_active(self, inflight, active):
        """The files a worker holds now (their task started) apart from those waiting in the queue of the pool: the
        status counts the first as in work (audit 6, M-010)."""
        now = {tid for f, (_, tid) in inflight.items() if f.running() or f.done()}
        for tid in now - active:
            self.state.update(tid, active=True, started=time.time())
        active.intersection_update({tid for _, tid in inflight.values()})
        active |= now

    def failed(self, stage, tid, e):
        """The error dict of a stage that raised: the text of the exception (never its repr), its traceback in the
        file's log and in debug/failures.log; a memory failure (MemoryError, MuPDF's FzErrorSystem) asks for one more
        try with the double cap."""
        from assistant_x.core import debuglog
        from assistant_x.intake import work as intake_work

        trace = e.trace if isinstance(e, intake_pool.TaskError) and e.trace else None
        if trace is None:
            import traceback

            trace = "".join(traceback.format_exception(e))
        log = self.work / "log" / f"{tid}.log"
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8", errors="replace") as f:
                f.write(f"{STAGES.get(stage, stage)} failed:\n{trace}\n")
        except OSError:
            pass
        debuglog.log_text(f"intake {tid} {stage}", trace)
        res = {
            "status": "error",
            "why": f"{STAGES.get(stage, stage)}: {intake_work.error_text(e)} (see log/{tid}.log)"[:300],
        }
        if intake_work.memory_like(e):
            res["retry"] = "memory"
        return res

    def memory_for(self, tid):
        """Memory cap of the worker for a task of this file: by the pages known after prep — up to 300 the cap of
        assistant_x.toml, up to 800 6 GB, more 8 GB (such a file also goes alone)."""
        pages = (self.state.get(tid) or {}).get("pages") or 0
        base = self.cfg.worker_memory_mb
        want = base if pages <= 300 else max(base, 6144) if pages <= THICK else max(base, 8192)
        return min(want, self.memory_ceiling())

    def memory_ceiling(self):
        """A cap a worker may get at most: half of the RAM (the regulator keeps the reserve for the rest)."""
        try:
            import psutil

            return max(self.cfg.worker_memory_mb, int(psutil.virtual_memory().total / 2**20 / 2))
        except ImportError:
            return self.cfg.worker_memory_mb * 2

    def batch_pairs(self):
        """Pairs of done files of this batch with ≥ DUP of common phrases (the same national standard from two sources passed as
        two documents: files running at the same time do not see each other). The smaller one of a pair gets
        "pair": [[share, other tid]], the draft asks which one to keep. Through an inverted index: no n² comparisons."""
        done = {r["tid"]: r for r in self.state.all("done")}
        fps = {t: fp for t, fp in self.mine.items() if t in done and len(fp) >= 30}
        index = collections.defaultdict(list)
        for t, fp in fps.items():
            for h in fp:
                index[h].append(t)
        common = collections.Counter()
        for tids in index.values():
            if 1 < len(tids) <= 50:  # a phrase in very many files says nothing about two of them
                for i, a in enumerate(tids):
                    for b in tids[i + 1 :]:
                        common[(a, b) if a < b else (b, a)] += 1
        n = 0
        for (a, b), k in common.items():
            share = k / min(len(fps[a]), len(fps[b]))
            if share < DUP:
                continue
            small, big = (a, b) if len(fps[a]) <= len(fps[b]) else (b, a)
            pairs = done[small].get("pair") or []
            if big not in [p[1] for p in pairs]:
                self.state.update(small, pair=pairs + [[round(share, 2), big]])
                n += 1
        if n:
            say(
                f'Similar pairs inside the batch (≥ {DUP:.0%} common phrases): {n} — the question "which to keep" in meta_draft.jsonl'
            )
        return n

    def handle(self, stage, tid, res: Prep | Convert):
        """Write a result of a stage (results.py); the next task (fn, job) or None."""
        from assistant_x.intake import work as intake_work

        row = self.state.get(tid)
        fp = res.pop("fp", None)
        if res.get("status") in ("error", "skipped"):
            self.state.update(tid, **res)
            return None
        if stage == "prep":
            self.state.update(tid, **{k: v for k, v in res.items() if k != "status"})
            cand = set(fp or [])
            if fp is not None:
                save_fp(self.work, tid, fp)
            upd = self.dup_verdict(tid, row, cand)
            self.state.update(tid, **upd)
            if upd.get("status") == "dup":
                return None
            return intake_work.convert, self.job(
                row,
                pdf=res["pdf"],
                ocr_pages=res.get("ocr_pages"),
                scan_pages=res.get("scan_pages"),
                phrases=res.get("phrases", 0),
            )
        # convert
        if res.get("fffd", 0) > 100 and not row.get("imgocr") and self.base["ocr"]:
            self.state.update(tid, imgocr=True, nodup=True, why="broken font encoding, recognizing the page images again")
            return intake_work.prep, self.job(self.state.get(tid))
        res.pop("status", None)
        self.state.update(tid, **res)
        cand = set(fp) if fp is not None else load_fp(self.work, tid)
        if fp is not None:
            save_fp(self.work, tid, fp)
            upd = self.dup_verdict(tid, self.state.get(tid), cand)
            if upd.get("status") == "dup":
                md = self.work / "md" / f"{tid}.md"
                (self.work / "mdtmp" / tid).mkdir(parents=True, exist_ok=True)
                if md.exists():
                    os.replace(md, self.work / "mdtmp" / tid / f"{tid}.dup.md")
                if md.with_suffix(PAGES_SUFFIX).exists():  # what is known of its pages goes with the text
                    os.replace(md.with_suffix(PAGES_SUFFIX), self.work / "mdtmp" / tid / f"{tid}.dup{PAGES_SUFFIX}")
                upd["why"] += " (after OCR)"
                self.state.update(tid, **upd)
                return None
            self.state.update(tid, **upd)
        self.mine[tid] = cand
        self.state.update(tid, status="done", why=row.get("why") if row.get("imgocr") else None)
        self.draft(tid)
        return None

    def draft(self, tid):
        """The card draft of a done file at once (meta_draft.jsonl, appended): Claude can write the cards of the files
        that are ready while the big scans still run; the pass at the end of the batch writes the file anew."""
        from assistant_x.intake import metadraft

        try:
            metadraft.write_drafts(self.work, self.state, tids=[tid], index=self.cfg.index, profile=self.cfg, append=True)
        except Exception as e:  # noqa: BLE001 — a draft is a help: it never stops the batch
            say(f"  {tid}: the card draft was not written now ({type(e).__name__}: {e}); it comes at the end")


def register(cfg, state):
    """Files of inbox into the state (a file seen before keeps its tid and status)."""
    n = 0
    for full, rel in walk(cfg.inbox):
        if state.by_rel(rel) is None:
            state.add(rel, os.path.getsize(full))
            n += 1
        name = rel.rsplit("/", 1)[-1]
        if name.startswith("~$"):
            r = state.by_rel(rel)
            if r["status"] == "queued":
                state.update(r["tid"], status="skipped", why="a temporary Word file (~$): reject")
    return n
