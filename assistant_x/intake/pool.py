# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Persistent worker processes of assistant-x intake run (stage_mode "inproc" in assistant_x.toml, the default).
A worker imports PyMuPDF, pymupdf4llm and the tools once and then takes the tasks of intake_work (prep, convert, lib_fp)
one by one, instead of starting a python process for every tool of every file (1.2-1.4 s of imports each).

  ex = Persistent(workers, memory_mb, env, threads, timeout=intake_work.task_timeout)
  f = ex.submit(intake_work.prep, job)      # a Future, as from ProcessPoolExecutor
  f.result()  -> the dict of the task | raises Lost(why) | raises TaskError(text of the exception)

Each worker is in a Windows Job Object of its own, made by this process: memory cap for the worker and what it starts
(past it allocations fail; a worker that dies near the cap counts as "memory"), priority class and CPUs of the tree
(AX_PRIORITY, AX_AFFINITY_MASK of env: balance.py), and the worker can be killed with its tree.
A task past its time (timeout(fn, args) seconds) kills the worker. Lost.why: "timeout" | "memory" | "crash";
the slot then starts a new worker for the next task, the other workers go on. Elsewhere psutil watches the memory."""

import contextlib, gc, multiprocessing, os, queue, sys, threading, time
from concurrent.futures import Future

from assistant_x.intake.limits import Job

try:
    import psutil
except ImportError:
    psutil = None

RECYCLE = 100  # tasks of one worker before it is replaced: memory a long run may leave behind is returned


class Lost(Exception):
    """The worker of the task was killed or died: why "timeout" | "memory" | "crash"."""

    def __init__(self, why, detail=""):
        super().__init__(why, detail)
        self.why, self.detail = why, detail


class TaskError(Exception):
    """An exception the task raised in the worker: its text (str(e), else the name of its type), the name of its type
    and its traceback; repr() is the text."""

    def __init__(self, text, kind="", trace=""):
        super().__init__(text, kind, trace)
        self.text, self.kind, self.trace = text, kind, trace

    def __str__(self):
        return self.text

    def __repr__(self):
        return self.text


def describe(e):
    """(text, type name, traceback) of an exception: str(e) or its type name — never a repr (the repr of a MuPDF
    error is the address of a SWIG proxy)."""
    import traceback

    kind = type(e).__name__
    return (str(e).strip() or kind)[:500], kind, "".join(traceback.format_exception(e))[-20000:]


def _task_log(args):
    """log/<tid>.log of the file a task works on (its job is the first argument), or None."""
    job = args[0] if args and isinstance(args[0], dict) else None
    if not job or not job.get("work") or not job.get("tid"):
        return None
    return os.path.join(job["work"], "log", f"{job['tid']}.log")


def _set_std(fd):
    """Windows: the standard handle of fd 1 or 2 follows the descriptor, so the processes a tool starts (the chunk
    pool of convert_md, Tesseract) write into the same file."""
    if os.name != "nt":
        return
    import ctypes, msvcrt

    ctypes.windll.kernel32.SetStdHandle(-11 if fd == 1 else -12, msvcrt.get_osfhandle(fd))


@contextlib.contextmanager
def task_output(args):
    """While a task runs, the descriptors 1 and 2 of the worker (the prints of pymupdf4llm and MuPDF, the processes
    the tools start) point at the log of its file: run.log keeps the lines of the batch only (audit 6, M-006)."""
    path = _task_log(args)
    try:
        if not path:
            raise OSError
        os.makedirs(os.path.dirname(path), exist_ok=True)
        f = open(path, "ab")
        saved = (os.dup(1), os.dup(2))
    except OSError:
        yield
        return
    for s in (sys.stdout, sys.stderr):
        try:
            s.flush()
        except (AttributeError, OSError, ValueError):
            pass
    try:
        for fd in (1, 2):
            os.dup2(f.fileno(), fd)
            _set_std(fd)
        yield
    finally:
        for s in (sys.stdout, sys.stderr):
            try:
                s.flush()
            except (AttributeError, OSError, ValueError):
                pass
        for fd, old in zip((1, 2), saved):
            os.dup2(old, fd)
            _set_std(fd)
            os.close(old)
        f.close()


def serve(conn, env, threads):
    """Loop of a worker process: (fn, args) in, ("ok" | "exc", value, recycle) out; None ends it.
    threads: kept for the callers; the threads of the math libraries and ONNX come from AX_ONNX_THREADS of env
    (the budget of balance.py: logical CPUs / workers)."""
    from assistant_x.intake import balance

    os.environ.update({k: v for k, v in env.items() if k in balance.THREADS or k == "AX_ONNX_THREADS"})
    balance.limit_threads()  # before numpy, onnxruntime and the models are imported
    if balance.from_env(env)[0] not in (0, balance.PRIORITIES["normal"]):
        balance.low_io()  # the priority class and CPUs are limits of the job this worker was put in
    from assistant_x.intake import work as intake_work

    intake_work.init_worker(0, env, limit=False)  # the memory cap is the job this worker was put in
    from assistant_x.intake.tools import onnx_threads

    onnx_threads.limit(int(os.environ.get("AX_ONNX_THREADS") or 1))
    import pymupdf, pymupdf4llm  # noqa: F401 — imported once for every task of this worker

    balance.limit_threads()  # torch, if pymupdf4llm brought it in
    for name in ("hidden", "convert_md", "reocr_empty", "assemble_md"):
        __import__(f"{intake_work.TOOLS}.{name}")
    n = 0
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg is None:
            return
        fn, args = msg
        n += 1
        recycle = n >= RECYCLE
        try:
            with task_output(args):
                out = ("ok", fn(*args))
        except MemoryError:
            why = f"{fn.__name__}: the memory cap of the worker was exceeded"
            out, recycle = (("ok", {"status": "error", "why": why, "retry": "memory"}), True)
        except BaseException as e:  # noqa: BLE001 — returned to the main process like a pool would
            out = ("exc", describe(e))
        pymupdf.TOOLS.store_shrink(100)  # MuPDF cache of this document
        gc.collect()
        try:
            conn.send(out + (recycle,))
        except (OSError, ValueError):
            return
        if recycle:
            return


class _Worker:
    def __init__(self, ctx, memory_mb, env, threads):
        from assistant_x.intake import balance

        cls, cpu_mask = balance.from_env(env)
        self.cls = 0 if cls == balance.PRIORITIES["normal"] else cls
        self.p = None
        self.conn, child = ctx.Pipe()
        self.p = ctx.Process(target=serve, args=(child, env, threads), daemon=True)
        self.p.start()
        child.close()
        self.job = Job(memory_mb, per_process=True, priority=self.cls, cpu_mask=cpu_mask)
        self.jobbed = os.name == "nt" and self.job.assign(self.p.sentinel)  # sentinel: the process handle on Windows
        if os.name == "nt" and not self.jobbed:
            balance.set_process(self.p.sentinel, self.cls, cpu_mask)
        elif os.name != "nt":
            self.job.assign_pid(self.p.pid)  # POSIX: the limits of the worker (its tools inherit them)
        self.limit = memory_mb * 1024 * 1024 if memory_mb else 0
        self.watch = psutil.Process(self.p.pid) if psutil and self.limit and not self.jobbed else None
        self.paused = None  # "soft" (IDLE priority, no new task) | "hard" (the tree is suspended)
        self.paused_since, self.paused_total = 0.0, 0.0

    def over_memory(self):
        if not self.watch:
            return False
        try:
            procs = [self.watch] + self.watch.children(recursive=True)
            return sum(q.memory_info().rss for q in procs) > self.limit
        except psutil.Error:
            return False

    def near_cap(self):
        return bool(self.jobbed and self.limit and self.job.peak() >= 0.97 * self.limit)

    def _tree(self):
        try:
            p = psutil.Process(self.p.pid)
            return [p] + p.children(recursive=True)
        except psutil.Error:
            return []

    def pause(self, how):
        """soft: the tree goes to IDLE priority (the user's programs always come first); hard: it is suspended."""
        if self.paused == how:
            return
        if self.paused == "hard" and how == "soft":
            self.resume()
        self.job.update(priority=0x40)  # IDLE_PRIORITY_CLASS
        if how == "hard" and psutil:
            for q in self._tree():
                try:
                    q.suspend()
                except psutil.Error:
                    pass
            self.paused_since = time.time()
        self.paused = how

    def resume(self):
        if self.paused == "hard" and psutil:
            for q in self._tree():
                try:
                    q.resume()
                except psutil.Error:
                    pass
            self.paused_total += time.time() - self.paused_since
        if self.paused:
            self.job.update(priority=self.cls)
        self.paused = None

    def paused_seconds(self):
        """Time this worker was suspended: not counted against the time limit of its task."""
        return self.paused_total + (time.time() - self.paused_since if self.paused == "hard" else 0.0)

    def kill(self):
        self.job.kill()
        if self.p.is_alive():
            self.p.kill()
        self.p.join(5)
        self.job.close()
        self.conn.close()

    def stop(self):
        try:
            self.conn.send(None)
        except (OSError, ValueError):
            pass
        self.p.join(5)
        self.kill()


class Persistent:
    """Executor of persistent workers: submit / shutdown like concurrent.futures.
    set_active(n, hard): only slots 0..n-1 take tasks; a busy slot past n is paused (soft: IDLE priority until its task
    ends; hard: suspended, its time limit waits too) and goes on when n grows again. regulate(...) runs a balance.Regulator
    in a thread that sets n from measurements and writes its decisions to a log."""

    def __init__(self, workers, memory_mb, env, threads=1, timeout=None):
        self.ctx = multiprocessing.get_context("spawn")
        self.args = (memory_mb, env, threads)
        self.timeout = timeout or (lambda fn, args: 0)
        self.q = queue.Queue()
        self.closed = False
        self.active, self.hard = workers, False
        self.cond = threading.Condition()
        self.workers = [None] * workers
        self.busy = [False] * workers
        self.reg_thread = None
        self.threads = [threading.Thread(target=self._slot, args=(k,), daemon=True) for k in range(workers)]
        for t in self.threads:
            t.start()

    def submit(self, fn, *args, memory_mb=None):
        """memory_mb: the memory cap of the worker for this task only (a thick document), else the pool's."""
        if self.closed:
            raise RuntimeError("the pool is stopped")
        f = Future()
        self.q.put((f, fn, args, self.timeout(fn, args), memory_mb))
        return f

    def set_active(self, n, hard=False):
        with self.cond:
            self.active, self.hard = max(0, min(n, len(self.workers))), hard
            self.cond.notify_all()
        self._apply()

    def _apply(self):
        for k, w in enumerate(self.workers):
            if w is None:
                continue
            if k < self.active:
                w.resume()
            elif self.busy[k]:
                w.pause("hard" if self.hard else "soft")

    def set_cpus(self, cpu_mask):
        """CPUs of every worker tree (0: all); the regulator moves them to the E-cores while the user works."""
        for w in self.workers:
            if w is not None:
                w.job.update(cpu_mask=cpu_mask)

    def cpu_seconds(self):
        return sum(w.job.cpu_seconds() for w in self.workers if w is not None)

    def _slot(self, k):
        while not self.closed:
            with self.cond:
                while k >= self.active and not self.closed:  # this slot is paused by the regulator: no new task
                    self.cond.wait(1)
            if self.closed:
                break
            if self.workers[k] is None:
                self.workers[k] = _Worker(self.ctx, *self.args)  # started before its first task: imports in advance
            try:
                item = self.q.get(timeout=1)
            except queue.Empty:
                continue
            if item is None:
                break
            if k >= self.active and not self.closed:  # paused while it waited for a task: the task goes back
                self.q.put(item)
                continue
            f, fn, args, limit, mem = item
            if not f.set_running_or_notify_cancel():
                continue
            w = self.workers[k]
            mem = mem or self.args[0]
            if mem != (w.limit // 2**20 if w.limit else 0) and w.job.set_memory(mem):
                w.limit = mem * 1024 * 1024  # near_cap and over_memory see the cap of this task
            self.busy[k] = True
            if k >= self.active:
                w.pause("hard" if self.hard else "soft")
            why, out, t0 = None, None, time.time()
            try:
                w.conn.send((fn, args))
                while True:
                    if w.conn.poll(0.5):
                        out = w.conn.recv()
                        break
                    if not w.p.is_alive():
                        if w.conn.poll(0):
                            out = w.conn.recv()
                        else:
                            why = "crash"
                        break
                    if limit and time.time() - t0 - w.paused_seconds() > limit:
                        why = "timeout"
                        break
                    if w.over_memory():
                        why = "memory"
                        break
            except (EOFError, OSError, ValueError):
                why = "crash"
            self.busy[k] = False
            w.resume()
            w.paused_total = 0.0
            if why:
                if why == "crash":
                    w.p.join(5)
                code = w.p.exitcode
                if why == "crash" and w.near_cap():
                    why = "memory"
                w.kill()
                self.workers[k] = None
                detail = f"{limit} s" if why == "timeout" else f"{mem} MB" if why == "memory" else f"code {code}"
                f.set_exception(Lost(why, detail))
                continue
            kind, value, recycle = out
            if recycle:
                w.stop()
                self.workers[k] = None
            if kind == "ok":
                f.set_result(value)
            else:
                f.set_exception(TaskError(*value) if isinstance(value, tuple) else TaskError(str(value)))
        w = self.workers[k]
        if w is not None:
            w.resume()
            w.stop()
            self.workers[k] = None

    def regulate(self, reg, sensors, log=None, period=4, ecores_mask=0, all_mask=0):
        """Start the regulator thread: every period seconds a measurement, reg.step, set_active; decisions to log."""

        def loop():
            from assistant_x.intake import balance

            logical, last_t, last_cpu, where = os.cpu_count() or 1, time.time(), self.cpu_seconds(), None
            while not self.closed:
                time.sleep(period)
                now, cpu = time.time(), self.cpu_seconds()
                ours = max(0.0, (cpu - last_cpu) / max(now - last_t, 0.1) / logical * 100)
                last_t, last_cpu = now, cpu
                try:
                    s = sensors.sample(ours)
                except Exception as e:  # noqa: BLE001 — a failed measurement leaves the workers as they are
                    _write(log, f"measuring failed: {e!r}")
                    continue
                n, state, why = reg.step(s, now)
                hard = s["avail_gb"] < 1.5 or reg.hot or bool(reg.since)
                self.set_active(n, hard)
                want = ecores_mask if state == balance.ACTIVE and ecores_mask else all_mask
                if want and want != where:
                    self.set_cpus(want)
                    where = want
                    why = why + [("E-cores" if want == ecores_mask else "all CPUs")]
                if why:
                    t = s.get("temp")
                    _write(
                        log,
                        f"{state}\tactive {n}/{len(self.workers)}{' pause-stop' if hard and n < len(self.workers) else ''}\t"
                        f"CPU {s['cpu']:.0f} % (ours {s['ours']:.0f}), disk {s['disk']:.0f} %, memory {s['avail_gb']:.1f} GB, "
                        f"input {s['idle_s']:.0f} s ago, t {t if t is not None else '—'}"
                        f"{', frequency ' + format(s['perf'], '.0f') + ' %' if s.get('perf') is not None else ''}\t"
                        + "; ".join(why),
                    )

        self.reg_thread = threading.Thread(target=loop, daemon=True)
        self.reg_thread.start()

    def shutdown(self, wait=True, cancel_futures=False):
        if cancel_futures:
            while True:
                try:
                    item = self.q.get_nowait()
                except queue.Empty:
                    break
                if item is not None:
                    item[0].cancel()
        with self.cond:
            self.active = len(self.workers)  # paused slots wake up to see the end
            self.cond.notify_all()
        self._apply()
        self.closed = True
        for _ in self.threads:
            self.q.put(None)
        if wait:
            for t in self.threads:
                t.join()


def _write(log, text):
    if not log:
        return
    import datetime

    try:
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')}\t{text}\n")
    except OSError:
        pass
