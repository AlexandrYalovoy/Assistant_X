# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Persistent workers of the intake (intake_pool.py, stage_mode "inproc"): a worker that dies or hangs is replaced and
its file gets an error with the reason, an exception of a stage is an error of the file, and the text is the same as
with a python process per tool (stage_mode "subprocess")."""

import gc, os, time
from concurrent.futures import Future

import pytest

from assistant_x.intake import pipeline as intake
from assistant_x.intake import config as intake_cfg
from assistant_x.intake import pool as intake_pool
from assistant_x.intake import work as intake_work
from tests.intake import pool_tasks
from tests.intake.intake_fixtures import GOST_PAGES, scan_pdf, text_pdf
from assistant_x.intake.state import State


@pytest.fixture
def pool():
    made = []

    def make(workers=1, memory_mb=0, timeout=30, only=None):
        """timeout: seconds of a task; only: the task it applies to (the others get 120 s: a worker that is still
        importing PyMuPDF on a busy PC must not count as a hung one)."""
        limit = (lambda fn, args: timeout if fn is only else 120) if only else (lambda fn, args: timeout)
        ex = intake_pool.Persistent(workers, memory_mb, dict(os.environ), 1, timeout=limit)
        made.append(ex)
        return ex

    yield make
    for ex in made:
        ex.shutdown(wait=True, cancel_futures=True)


def test_worker_replaced_after_crash(pool):
    ex = pool()
    first = ex.submit(pool_tasks.pid).result(timeout=120)
    with pytest.raises(intake_pool.Lost) as e:
        ex.submit(pool_tasks.crash, 3).result(timeout=60)
    assert e.value.why == "crash" and e.value.detail == "code 3"
    second = ex.submit(pool_tasks.pid).result(timeout=120)
    assert second != first  # a new worker took the next task


def test_worker_reused_between_tasks(pool):
    ex = pool()
    assert len({ex.submit(pool_tasks.pid).result(timeout=120) for _ in range(3)}) == 1


def test_task_timeout_kills_worker(pool):
    ex = pool(timeout=2, only=pool_tasks.nap)
    first = ex.submit(pool_tasks.pid).result(timeout=120)
    t0 = time.time()
    with pytest.raises(intake_pool.Lost) as e:
        ex.submit(pool_tasks.nap, 60).result(timeout=60)
    assert e.value.why == "timeout" and e.value.detail == "2 s" and time.time() - t0 < 15
    assert ex.submit(pool_tasks.pid).result(timeout=120) != first


def test_memory_cap_of_worker(pool):
    ex = pool(memory_mb=1500)
    try:
        res = ex.submit(pool_tasks.hog, 4000).result(timeout=120)
    except intake_pool.Lost as e:  # no Job Object (not Windows): psutil saw the worker past the cap and killed it
        assert e.why == "memory"
    else:
        assert res["status"] == "error" and "memory cap of the worker was exceeded" in res["why"]
    assert ex.submit(pool_tasks.hog, 10).result(timeout=120) == 10 * 1024 * 1024  # a fresh worker


def test_paused_slot_takes_no_task(pool):
    """The regulator lets one of two slots work: every task goes to that one worker."""
    ex = pool(workers=2)
    ex.set_active(1)
    assert len({ex.submit(pool_tasks.pid).result(timeout=120) for _ in range(4)}) == 1


@pytest.mark.skipif(not intake_pool.psutil, reason="psutil suspends the tree")
def test_hard_pause_not_counted_against_time_limit(pool):
    ex = pool(timeout=4, only=pool_tasks.nap)
    ex.submit(pool_tasks.pid).result(timeout=120)  # the worker is up
    f = ex.submit(pool_tasks.nap, 2)
    time.sleep(0.8)
    ex.set_active(0, hard=True)  # suspended mid-task, as on a memory emergency
    time.sleep(5)
    assert not f.done()
    ex.set_active(1)
    assert f.result(timeout=60) == 2  # 2 s of work + 5 s of pause, limit 4 s: not a timeout


def test_task_exception_returned(pool):
    ex = pool()
    with pytest.raises(intake_pool.TaskError) as e:
        ex.submit(pool_tasks.boom).result(timeout=120)
    assert repr(e.value) == "ValueError('broke inside the task')"


# ---------- stages as functions ----------


def job(tmp_path, src, **kw):
    w = tmp_path / "work"
    return {
        "work": str(w),
        "tid": "T0001",
        "rel": src.name,
        "src": str(src),
        "ext": "pdf",
        "ocr": False,
        "soffice": None,
        "timeouts": {"hidden": 60, "convert": 120, "soffice": 60},
        "memory_mb": 0,
        "env": dict(os.environ),
        "ocr_threads": 1,
        "inproc": True,
        **kw,
    }


def test_stage_exception_is_error_of_file(tmp_path, monkeypatch):
    from assistant_x.intake.tools import hidden
    from assistant_x.intake.tools import assemble_md

    pdf = tmp_path / "a.pdf"
    text_pdf(pdf, GOST_PAGES)

    def broken(argv):
        raise RuntimeError("the check fell over")

    monkeypatch.setattr(hidden, "main", broken)
    res = intake_work.prep(job(tmp_path, pdf))
    assert res["status"] == "error" and res["why"].startswith("the hidden text check: RuntimeError('the check fell over')")
    monkeypatch.undo()
    res = intake_work.prep(job(tmp_path, pdf))
    assert res["status"] == "prepped"
    monkeypatch.setattr(assemble_md, "main", broken)
    res = intake_work.convert(job(tmp_path, pdf, pdf=res["pdf"]))
    assert res["status"] == "error" and res["why"].startswith("assembling the Markdown: RuntimeError")
    assert not (tmp_path / "work" / "md" / "T0001.md").exists()


def test_stage_exit_code_is_error_of_file(tmp_path, monkeypatch):
    from assistant_x.intake.tools import convert_md

    pdf = tmp_path / "a.pdf"
    text_pdf(pdf, GOST_PAGES)
    res = intake_work.prep(job(tmp_path, pdf))

    def chunk_fails(*a):
        raise OSError("disk disconnected")

    monkeypatch.setattr(convert_md, "run", chunk_fails)
    res = intake_work.convert(job(tmp_path, pdf, pdf=res["pdf"]))
    assert res["status"] == "error" and res["why"].startswith("conversion to Markdown: code 1: ")
    assert "pieces not converted: 1 of 1" in res["why"]


@pytest.mark.slow
def test_same_text_inproc_and_subprocess(tmp_path, monkeypatch):
    cfg = intake_cfg.load()  # programs of this PC only; its folders are not touched
    env = intake_cfg.tool_env(cfg)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    ocr = intake_cfg.can_ocr(cfg)
    src = tmp_path / "src"
    src.mkdir()
    text_pdf(src / "text.pdf", GOST_PAGES)
    scan_pdf(src / "scan.pdf")
    out = {}
    for mode in ("inproc", "subprocess"):
        for name in ("text.pdf", "scan.pdf"):
            j = job(tmp_path / mode, src / name, env=env, ocr=ocr, inproc=mode == "inproc", ocr_threads=2)
            res = intake_work.prep(j)
            assert res["status"] == "prepped", res
            res = intake_work.convert({**j, "pdf": res["pdf"], "ocr_pages": res["ocr_pages"], "phrases": res["phrases"]})
            assert res["status"] == "converted", res
            out[mode, name] = (tmp_path / mode / "work" / "md" / "T0001.md").read_text(encoding="utf-8")
            gc.collect()
            os.replace(tmp_path / mode / "work", tmp_path / mode / name)
    assert out["inproc", "text.pdf"] == out["subprocess", "text.pdf"] and "Область применения" in out["inproc", "text.pdf"]
    assert out["inproc", "scan.pdf"] == out["subprocess", "scan.pdf"]
    if ocr:
        assert "давление" in out["inproc", "scan.pdf"].lower()


# ---------- the batch: a lost worker ----------


class FakePool:
    """Executor that runs tasks at once, but loses the worker on the prep of text.pdf as told."""

    def __init__(self, lost):
        self.lost = list(lost)

    def submit(self, fn, *a):
        f = Future()
        if fn.__name__ == "prep" and a[0]["rel"] == "text.pdf" and self.lost:
            f.set_exception(intake_pool.Lost(*self.lost.pop(0)))
            return f
        try:
            f.set_result(fn(*a))
        except Exception as e:  # noqa: BLE001
            f.set_exception(e)
        return f

    def shutdown(self, wait=True, cancel_futures=False):
        pass


@pytest.mark.parametrize(
    "lost, status, why",
    [
        ([("timeout", "1500 s")], "error", "preparation: time exceeded (1500 s); the worker process was restarted"),
        ([("memory", "3000 MB")], "done", None),  # once more with a doubled cap
        (
            [("memory", "3000 MB"), ("memory", "6000 MB")],
            "error",
            "preparation: memory cap exceeded (6000 MB); the worker process was restarted",
        ),
        ([("crash", "code 3")], "done", None),  # once: the file goes back to the queue
        (
            [("crash", "code 3"), ("crash", "code 5")],
            "error",
            "preparation: the worker process crashed twice (code 5, a broken file?)",
        ),
    ],
)
def test_batch_lost_worker(project, monkeypatch, lost, status, why):
    root, cfg = project
    monkeypatch.setenv("AX_FP_CACHE", str(cfg.fingerprints))  # a pool worker takes it from the job environment
    monkeypatch.setattr(intake.Batch, "pool", lambda self: FakePool(lost))
    assert intake.main(["--config", str(cfg.path), "run"]) == 0
    work = sorted(cfg.work.glob("20??-??-??"))[-1]
    rows = {r["rel"]: r for r in State(work / "state.sqlite").all()}
    assert rows["text.pdf"]["status"] == status
    if why:
        assert rows["text.pdf"]["why"].startswith(why)
    assert rows["Сканы/scan.pdf"]["status"] == "done"  # the other files went on


class OrderPool(FakePool):
    """Runs tasks at once and notes the order of the preps."""

    def __init__(self, seen):
        super().__init__([])
        self.seen = seen

    def submit(self, fn, *a):
        if fn.__name__ == "prep":
            self.seen.append(a[0]["rel"])
        return super().submit(fn, *a)


def test_heavy_files_last(project, monkeypatch):
    root, cfg = project
    big = max(((p.stat().st_size, p) for p in cfg.inbox.rglob("*.pdf")))[1]
    intake_cfg.save({"heavy_mb": (big.stat().st_size - 1) / 2**20}, cfg.path)  # only the biggest file is heavy
    monkeypatch.setenv("AX_FP_CACHE", str(cfg.fingerprints))
    seen = []
    monkeypatch.setattr(intake.Batch, "pool", lambda self: OrderPool(seen))
    assert intake.main(["--config", str(cfg.path), "run"]) == 0
    assert seen[-1] == big.relative_to(cfg.inbox).as_posix() and len(seen) > 1


def test_run_resume_takes_the_latest_batch(project, monkeypatch):
    root, cfg = project
    monkeypatch.setenv("AX_FP_CACHE", str(cfg.fingerprints))
    old = cfg.work / "2026-01-02"
    old.mkdir(parents=True)
    st = State(old / "state.sqlite")
    st.update(st.add("x.pdf", 1), status="done")  # a batch of another day with a file done: it stays done
    st.con.close()
    seen = []
    monkeypatch.setattr(intake.Batch, "pool", lambda self: OrderPool(seen))
    from assistant_x.intake import batch

    monkeypatch.setattr(batch, "today", lambda: "2026-01-01")  # today's folder would sort before it
    assert intake.main(["--config", str(cfg.path), "run", "--resume"]) == 0
    rows = {r["rel"]: r["status"] for r in State(old / "state.sqlite").all()}
    assert rows["x.pdf"] == "done" and rows["text.pdf"] == "done"
    assert not (cfg.work / "2026-01-01").exists()


def test_memory_cap_by_pages(project, tmp_path):
    """3 GB up to 300 pages, 6 GB up to 800, 8 GB past it (never more than half the RAM)."""
    root, cfg = project
    state = State(tmp_path / "state.sqlite")
    batch = intake.Batch(cfg, tmp_path, state, 0)
    caps = {}
    for pages in (0, 120, 300, 301, 800, 1260):
        t = state.add(f"{pages}.pdf", 1)
        state.update(t, pages=pages)
        caps[pages] = batch.memory_for(t)
    half = batch.memory_ceiling()
    assert caps[0] == caps[120] == caps[300] == cfg.worker_memory_mb
    assert caps[301] == caps[800] == min(6144, half) and caps[1260] == min(8192, half)


@pytest.mark.skipif(os.name != "nt", reason="Windows job objects")
def test_task_gets_its_own_memory_cap(pool):
    """A task with memory_mb runs under that cap; the next one is back under the pool's."""
    ex = pool(memory_mb=1500)
    res = ex.submit(pool_tasks.hog, 2000, memory_mb=3000).result(timeout=120)
    assert res == 2000 * 1024 * 1024  # fits the 3000 MB of this task, not the 1500 MB of the pool
    try:
        res = ex.submit(pool_tasks.hog, 2000).result(timeout=120)
    except intake_pool.Lost as e:
        assert e.why == "memory" and e.detail == "1500 MB"
    else:
        assert res["status"] == "error" and "memory cap of the worker was exceeded" in res["why"]


def test_stage_mode_setting(project, monkeypatch):
    root, cfg = project
    assert cfg.stage_mode == "inproc"  # the default
    monkeypatch.setenv("AX_STAGE_MODE", "subprocess")
    assert intake_cfg.load(cfg.path).stage_mode == "subprocess"
    monkeypatch.setenv("AX_STAGE_MODE", "something")
    with pytest.raises(SystemExit):
        intake_cfg.load(cfg.path)
