# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scheduler of a batch (schedule.py, process.Batch.run; audit 6, M-011, M-014, M-020): conversions cheapest
first, heavy tasks side by side while their memory fits with a worker kept for light ones, the OCR of a long scan in
page ranges on every worker and the file assembled after them, ocr_shards = "off" for the former way."""

import json
from concurrent.futures import Future

import pytest

from assistant_x.intake import config as intake_cfg
from assistant_x.intake import pipeline as intake
from assistant_x.intake import schedule
from assistant_x.intake import work as intake_work
from assistant_x.intake.state import State

# ---------- the policy ----------


def test_cost_and_heavy():
    assert schedule.cost(100, 0) == 50.0 and schedule.cost(100, 100) == 330.0
    assert schedule.cost(10, 50) == schedule.cost(10, 10)  # no more scans than pages
    assert not schedule.heavy(600, 200, 800) and schedule.heavy(900, 10, 800) and schedule.heavy(10, 801, 800)


def test_shard_count():
    assert schedule.shard_count(29, 6) == 1  # too few pages read by OCR
    assert schedule.shard_count(848, 6) == 18  # the scan of the first batch: three short ranges a worker
    assert schedule.shard_count(100, 6) == 5  # at least SHARD_PAGES a range
    assert schedule.shard_count(848, 1) == 1  # one worker: nothing to gain


def test_shard_ranges_cover_the_document():
    scans = list(range(11, 211))  # 10 text pages, 200 scanned ones, 20 text pages
    ranges = schedule.shard_ranges(230, scans, 4)
    assert ranges[0][0] == 1 and ranges[-1][1] == 230
    assert all(b + 1 == a for (_, b), (a, _) in zip(ranges, ranges[1:]))  # one after another, no gap, no overlap
    per = [sum(a <= p <= b for p in scans) for a, b in ranges]
    assert len(ranges) == 4 and max(per) - min(per) <= 1  # about the same scanned pages each
    assert schedule.shard_ranges(10, [], 4) == [(1, 10)]


def test_heavy_admission():
    # the first heavy task always; another one while the caps fit and a worker stays for light work
    assert schedule.may_admit_heavy(8192, [], 0, True, 0, 6)
    assert schedule.may_admit_heavy(8192, [8192], 20000, True, 1, 6)
    assert not schedule.may_admit_heavy(8192, [8192, 8192], 20000, False, 2, 6)  # no memory for a third
    assert not schedule.may_admit_heavy(3072, [3072] * 5, 99999, True, 5, 6)  # the last worker stays for light work
    assert schedule.may_admit_heavy(3072, [3072] * 5, 99999, False, 5, 6)  # no light work left: it may take it
    assert schedule.heavy_budget_mb(20, 4) == pytest.approx(16 * 1024 * 0.7)


def test_ready_cheapest_first_and_light_when_heavy_may_not():
    r = schedule.Ready()
    r.push(500, "big", is_heavy=True)
    r.push(30, "small")
    r.push(200, "medium")
    assert r.take(lambda it: True) == "small"
    r.push(1, "huge", is_heavy=True)
    assert r.take(lambda it: False) == "medium"  # the heavy ones may not start: the cheapest light one
    assert r.take(lambda it: False) is None and len(r) == 2
    assert r.take(lambda it: True) == "huge"


# ---------- the batch with a fake pipeline ----------


class RecordPool:
    """Runs a task at once and notes it: (function name, tid, pages of a range)."""

    def __init__(self, seen, fail_shards=0, stop_shards=0):
        self.seen, self.fail, self.stop = seen, fail_shards, stop_shards

    def submit(self, fn, *a, **kw):
        job = a[0] if a and isinstance(a[0], dict) else None
        if job:  # the fingerprints of the library are no stage of a file
            self.seen.append((fn.__name__, job["tid"], tuple(job.get("pages") or ())))
        f = Future()
        try:
            if fn.__name__ == "convert_shard" and self.fail:
                self.fail -= 1
                raise RuntimeError("a range broke")
            if fn.__name__ == "convert_shard" and self.stop:  # the watchdog killed the worker of a range
                self.stop -= 1
                from assistant_x.intake import pool as intake_pool

                raise intake_pool.Lost("timeout", "600 s")
            f.set_result(fn(*a))
        except Exception as e:  # noqa: BLE001
            f.set_exception(e)
        return f

    def shutdown(self, wait=True, cancel_futures=False):
        pass


PAGES = {"text.pdf": 230, "Сканы/scan.pdf": 20}


@pytest.fixture
def fake(project, monkeypatch):
    """The batch of the test project with fake stages: text.pdf is a long scan (200 scanned pages of 230)."""
    root, cfg = project
    monkeypatch.setattr(intake_cfg, "can_ocr", lambda cfg: True)

    def prep(job):
        n = PAGES.get(job["rel"], 3)
        scans = list(range(11, 211)) if job["rel"] == "text.pdf" else []
        return {"status": "prepped", "pages": n, "pdf": job["src"], "scan_pages": scans, "ocr_pages": len(scans), "fp": []}

    def convert_shard(job):
        return {"status": "shard", "pages": job["pages"]}

    def convert(job):
        return {"status": "converted", "chars": 100}

    for name, fn in (("prep", prep), ("convert_shard", convert_shard), ("convert", convert)):
        fn.__name__ = name
        monkeypatch.setattr(intake_work, name, fn)

    def run(workers=4, fail_shards=0, stop_shards=0, **settings):
        if settings:
            intake_cfg.save(settings, cfg.path)
        c = intake_cfg.load(cfg.path)
        work = c.work / "batch"
        work.mkdir(parents=True, exist_ok=True)
        state = State(work / "state.sqlite")
        intake.register(c, state)
        seen = []
        b = intake.Batch(c, work, state, workers)
        b.pool = lambda: RecordPool(seen, fail_shards, stop_shards)
        b.run()
        return seen, {r["rel"]: r for r in state.all()}

    return run


def test_a_long_scan_is_read_in_page_ranges(fake):
    seen, rows = fake()
    ranges = sorted(p for fn, t, p in seen if fn == "convert_shard")
    tid = rows["text.pdf"]["tid"]
    assert len(ranges) > 4 and ranges[0][0] == 1 and ranges[-1][1] == 230  # more ranges than workers: short ones
    conv = [i for i, (fn, t, _) in enumerate(seen) if fn == "convert" and t == tid]
    shards = [i for i, (fn, t, _) in enumerate(seen) if fn == "convert_shard"]
    assert len(conv) == 1 and conv[0] > max(shards)  # assembled after every range is back
    assert rows["text.pdf"]["status"] == "done" and rows["text.pdf"]["shards"] == len(ranges)


def test_ocr_shards_off(fake):
    seen, rows = fake(ocr_shards="off")
    assert not [s for s in seen if s[0] == "convert_shard"] and rows["text.pdf"]["status"] == "done"


def test_a_broken_range_still_converts_the_file(fake):
    seen, rows = fake(fail_shards=2)
    assert rows["text.pdf"]["status"] == "done"  # the conversion reads the ranges that broke


def test_one_worker_no_ranges(fake):
    seen, rows = fake(workers=1)
    assert not [s for s in seen if s[0] == "convert_shard"]


def test_cheapest_conversion_first(fake):
    seen, rows = fake(workers=1, ocr_shards="off")  # one worker: no tail before the last task (P4)
    order = [t for fn, t, _ in seen if fn == "convert"]
    by_tid = {r["tid"]: r for r in rows.values()}
    costs = [by_tid[t]["cost"] for t in order]
    assert costs == sorted(costs) and by_tid[order[-1]]["rel"] == "text.pdf"


def test_bad_ocr_shards_setting(project):
    root, cfg = project
    intake_cfg.save({"ocr_shards": "sometimes"}, cfg.path)
    with pytest.raises(SystemExit):
        intake_cfg.load(cfg.path)


# ---------- convert_md: a range of pages ----------


def test_convert_md_converts_only_its_range(tmp_path):
    from assistant_x.intake.tools import convert_md
    from tests.intake.intake_fixtures import text_pdf

    pdf = tmp_path / "a.pdf"
    text_pdf(pdf, [f"Страница {i}" for i in range(1, 61)])  # 60 text pages: chunks from page 1 and from page 51
    cache = tmp_path / "cache"
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"T0001": {"parts": [[str(pdf), 1]], "use_ocr": False, "range": [51, 60]}}), encoding="utf-8")
    convert_md.main([str(jobs), str(cache), "0"])
    assert sorted(p.name for p in (cache / "T0001").glob("*.json")) == ["00051.json"]
    assert json.loads((cache / "T0001.51.progress.json").read_text(encoding="utf-8"))["done"] == 10


def test_ranges_give_the_chunks_of_the_whole(tmp_path):
    """The chunks converted range by range are the chunks of one conversion of the whole: the same names, the same
    text (the assembly after the ranges reads the same cache)."""
    from assistant_x.intake.tools import convert_md
    from tests.intake.intake_fixtures import text_pdf

    pdf = tmp_path / "a.pdf"
    text_pdf(pdf, [f"Раздел {i}. Сепарация нефти" for i in range(1, 61)])

    def chunks(name, ranges):
        cache = tmp_path / name
        for rng in ranges:
            job = {"parts": [[str(pdf), 1]], "use_ocr": False, **({"range": rng} if rng else {})}
            jobs = tmp_path / f"{name}.json"
            jobs.write_text(json.dumps({"T0001": job}), encoding="utf-8")
            convert_md.main([str(jobs), str(cache), "0"])
        return {p.name: p.read_text(encoding="utf-8") for p in (cache / "T0001").glob("*.json")}

    assert chunks("whole", [None]) == chunks("ranges", [[1, 50], [51, 60]])


def test_a_set_of_drawing_sheets_costs_and_is_cut():
    """Trial batches b026-b029: a set of 16-18 A1/A0 sheets drawn in curves (no picture, no text layer) was planned as
    a cheap text file on one worker (450-500 s). A sheet costs SHEET_SECONDS and a set of them goes in page ranges."""
    import pymupdf

    assert schedule.cost(16, 0, 0, 16) == 16 * schedule.SHEET_SECONDS
    assert schedule.cost(10, 0, 0, 0) == 5.0  # text pages as before
    weight = 16 + (schedule.SHEET_WEIGHT - 1) * 16
    assert schedule.shard_count(weight, 6, 16) == 6  # every worker takes a part of the set
    assert schedule.shard_count(1000, 30, 5) == 5  # never more ranges than pages read
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page(width=3370, height=2384).draw_line((10, 10), (500, 500))
    doc.new_page()  # an A4 page of text
    doc.new_page(width=3370, height=2384).insert_text((50, 50), "a sheet with a text layer " * 10)
    texts = [p.get_text() for p in doc]
    assert intake_work.sheet_pages(doc, texts) == [1, 2, 3]
    assert intake_work.sheet_pages(doc, texts, scans=[2]) == [1, 3]  # a scanned page is read as a scan


def test_the_watchdog_reads_a_stalled_file_from_its_page_images(fake):
    """Trial batch b061: one page of 88 000 vector paths held a range of a project volume for 40 minutes. A range the
    watchdog stops sends its file back to prep once, with its pages without a text layer read as images."""
    seen, rows = fake(stop_shards=1)
    row = rows["text.pdf"]
    preps = [s for s in seen if s[0] == "prep" and s[1] == row["tid"]]
    assert len(preps) == 2 and row["flatten_all"] and row["watchdog"]  # prepared once more, once only
    assert row["status"] == "done" and "took too long" in row["why"]


def test_the_watchdog_limit_follows_the_pages():
    t = {"timeouts": {"page": 180, "convert": 14400}}
    assert intake_work.task_timeout(intake_work.convert_shard, ({**t, "pages": [1, 7]},)) == 7 * 180 + 600
    assert intake_work.task_timeout(intake_work.convert_shard, ({**t, "pages": [1, 100]},)) == 3600
    assert intake_work.task_timeout(intake_work.convert, ({**t, "page_count": 10},)) == 10 * 180 + 900
    assert intake_work.task_timeout(intake_work.convert, ({**t},)) == 2 * 14400 + 1800  # pages not known yet


def test_a_page_of_many_vector_paths_is_read_from_its_image(tmp_path):
    import pymupdf

    doc = pymupdf.open()
    heavy = doc.new_page(width=3370, height=2384)
    for i in range(60):
        heavy.draw_line((10 + 5 * i, 10), (20 + 5 * i, 900))
    doc.new_page().insert_text((50, 50), "a page of text " * 20)
    texts = [p.get_text() for p in doc]
    assert intake_work.vector_pages(doc, texts, limit=50) == [1] and intake_work.vector_pages(doc, texts, limit=100) == []
    intake_work.flatten(doc, [1], tmp_path / "flat.pdf")
    flat = pymupdf.open(tmp_path / "flat.pdf")
    assert flat[0].get_images() and not flat[0].get_drawings() and "a page of text" in flat[1].get_text()
    assert flat[0].rect == doc[0].rect  # the page keeps its size: the title block of a sheet stays where it was


def test_the_tail_of_a_batch_starts_the_longest_first():
    """P4: at the end of a batch (every file prepared, no more tasks than workers) the longest task goes first, so a
    long range started last does not hold the batch alone; before that, the cheapest first as ever."""
    r = schedule.Ready()
    for cost, name in ((30, "a"), (500, "b"), (120, "c")):
        r.push(cost, name)
    assert not schedule.tail(3, 3, 4) and schedule.tail(0, 3, 4) and not schedule.tail(0, 9, 4)
    assert r.take(lambda it: True, longest=True) == "b"
    assert r.take(lambda it: True) == "a"
    assert r.take(lambda it: False, longest=True) == "c"


def test_a_page_of_text_and_too_many_lines_loses_its_line_art(tmp_path, monkeypatch):
    """Trial batch b075: a plan of 485 000 vector paths with a text layer held the layout analysis for more than half
    an hour. Past VECTOR_TEXT_MAX its line art goes in the copy; its text stays (a page of tables is far below)."""
    import pymupdf

    monkeypatch.setattr(intake_work, "VECTOR_TEXT_MAX", 50)
    doc = pymupdf.open()
    plan = doc.new_page(width=2386, height=1686)
    for i in range(80):
        plan.draw_line((10 + 5 * i, 10), (20 + 5 * i, 900))
    plan.insert_text((100, 1000), "Plan of the equipment of the gas treatment unit " * 3)
    doc.new_page().insert_text((50, 50), "a page of text " * 20)
    texts = [p.get_text() for p in doc]
    assert intake_work.line_art_pages(doc, texts) == [1]
    intake_work.flatten(doc, [], tmp_path / "copy.pdf", strip=[1])
    copy = pymupdf.open(tmp_path / "copy.pdf")
    assert not copy[0].get_drawings() and "gas treatment unit" in copy[0].get_text()
    assert "a page of text" in copy[1].get_text()


def test_a_drawing_sheet_with_text_loses_its_line_art_sooner(monkeypatch):
    """Trial batch b081: A1/A0 sheets of 20 000-90 000 paths with a text layer took 7-15 minutes a sheet in the layout
    analysis. A sheet (A2 and up) loses its line art past VECTOR_SHEET_MAX; a page of A4 keeps it to VECTOR_TEXT_MAX."""
    import pymupdf

    monkeypatch.setattr(intake_work, "VECTOR_TEXT_MAX", 200)
    monkeypatch.setattr(intake_work, "VECTOR_SHEET_MAX", 50)
    doc = pymupdf.open()
    for w, h in ((2384, 1684), (595, 842)):
        page = doc.new_page(width=w, height=h)
        for i in range(80):
            page.draw_line((10 + 5 * i, 10), (20 + 5 * i, 500))
        for k in range(3):
            page.insert_text((20, 600 + 20 * k), "Compressor casing, general arrangement")
    texts = [p.get_text() for p in doc]
    assert intake_work.line_art_pages(doc, texts) == [1]
    assert intake_work.line_art_pages(doc, texts, limit=20) == [1, 2]  # after the watchdog
    # an A0 sheet of 108 characters in its layer had its text drawn as curves: read from its image (OCR), not stripped
    assert intake_work.vector_pages(doc, texts) == [1]
    monkeypatch.setattr(intake_work, "SHEET_TEXT", 50)
    assert intake_work.vector_pages(doc, texts) == []


def test_a_long_document_of_text_pages_is_cut_into_ranges():
    """Trial batch b103: a workbook laid out on 1 029 pages of tables held one worker half an hour (1.7 s a page)
    while fifteen waited. A document of TEXT_SHARD_MIN text pages and more is cut into ranges of TEXT_SHARD_PAGES at
    least, up to SHARD_WORKERS a worker."""
    assert schedule.text_shard_count(299, 16) == 1 and schedule.text_shard_count(1029, 1) == 1
    assert schedule.text_shard_count(1029, 16) == 10
    assert schedule.text_shard_count(20000, 4) == 12
    ranges = schedule.shard_ranges(1029, list(range(1, 1030)), 10)
    assert ranges[0][0] == 1 and ranges[-1][1] == 1029 and len(ranges) == 10
    assert all(b - a + 1 >= 100 for a, b in ranges)
    assert all(ranges[i][1] + 1 == ranges[i + 1][0] for i in range(9))


def test_a_long_flattened_copy_is_built_in_parts(tmp_path, monkeypatch):
    """Trial batch b129: the page images of 2 428 pages were kept raw in memory until the save (8.7 MB an A4 page),
    a worker grew to 13 GB. The copy is built FLAT_PART pages at a time, saved compressed and joined: the same pages."""
    import pymupdf

    monkeypatch.setattr(intake_work, "FLAT_PART", 3)
    doc = pymupdf.open()
    for i in range(8):
        doc.new_page().insert_text((72, 72), f"page {i + 1} of a long document")
    out = tmp_path / "flat.pdf"
    intake_work.flatten(doc, [2, 5, 8], out)
    copy = pymupdf.open(out)
    assert copy.page_count == 8 and "page 1 of" in copy[0].get_text() and "page 7 of" in copy[6].get_text()
    assert not copy[1].get_text().strip() and copy[1].get_images() and copy[7].get_images()
    assert not list(tmp_path.glob("*.part*"))  # the parts are gone


def test_page_images_of_a_broken_layer_are_made_in_parts(tmp_path, monkeypatch):
    """Trial batch b129: the page images read instead of a broken layer (imgocr) were kept raw in memory, 2 428 pages
    failed a worker of 3 GB. They are made by flatten, FLAT_PART pages at a time."""
    import os

    import pymupdf

    monkeypatch.setattr(intake_work, "FLAT_PART", 2)
    src = tmp_path / "doc.pdf"
    doc = pymupdf.open()
    for i in range(5):
        doc.new_page().insert_text((72, 72), f"page {i + 1}")
    doc.save(src)
    (tmp_path / "w" / "src").mkdir(parents=True)
    doc.save(tmp_path / "w" / "src" / "T0001.pdf")  # the copy the batch makes
    job = {
        "work": str(tmp_path / "w"),
        "tid": "T0001",
        "ext": "pdf",
        "src": str(src),
        "soffice": None,
        "ocr": False,
        "imgocr": True,
        "timeouts": {"soffice": 60, "hidden": 300, "convert": 600},
        "memory_mb": 3000,
        "env": dict(os.environ),
        "inproc": True,
    }
    res = intake_work.prep(job)
    out = pymupdf.open(res["pdf"])
    assert res["pdf"].endswith("T0001.img.pdf") and out.page_count == 5 and all(p.get_images() for p in out)
    assert not list((tmp_path / "w" / "pdf").glob("*.part*"))
