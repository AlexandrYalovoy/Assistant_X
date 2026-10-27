# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The status of a batch for a human (audit 6, M-005, M-006, M-009, M-010, M-012, M-028): the output of a task in the
log of its file, the JSON status with the files in work, their progress and the time left, the words of intake_status
and its next step, the progress of the base recalculation, the pages read at a reduced resolution."""

import json, os, time

import pytest

from assistant_x.intake import pool as intake_pool
from assistant_x.intake import review, work as intake_work
from assistant_x.intake.state import State
from assistant_x.search import reindex
from assistant_x.server import intake_tools
from tests.intake import pool_tasks


def test_task_output_goes_to_the_log_of_its_file(tmp_path, capfd):
    ex = intake_pool.Persistent(1, 0, dict(os.environ), 1, timeout=lambda fn, args: 120)
    try:
        job = {"work": str(tmp_path), "tid": "T0007"}
        assert ex.submit(pool_tasks.noisy, job).result(timeout=180) == {"status": "ok"}
    finally:
        ex.shutdown(wait=True)
    log = (tmp_path / "log" / "T0007.log").read_text(encoding="utf-8", errors="replace")
    assert "from python" in log and "from the descriptor" in log and "from a child" in log
    out, err = capfd.readouterr()
    assert "from a child" not in out + err  # not in the output of the batch (run.log)


def _batch(tmp_path):
    st = State(tmp_path / "state.sqlite")
    a, b, c, d = (st.add(f"{x}.pdf", 1) for x in "abcd")
    st.update(a, status="done", pages=100)
    st.update(b, status="running", stage="convert", active=True, pages=300)
    st.update(c, status="queued")
    st.update(d, status="error", why="preparation: FzErrorSystem")
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / f"{b}.progress.json").write_text(json.dumps({"done": 100, "total": 300}), encoding="utf-8")
    return st, (a, b, c, d)


def test_status_data(tmp_path):
    st, (a, b, c, d) = _batch(tmp_path)
    data = review.status_data(tmp_path, st, started=1000.0, now=1200.0)
    assert data["done"] == 2 and data["total"] == 4  # done and error are final
    assert data["running"] == [
        {"tid": b, "rel": "b.pdf", "stage": "convert", "active": True, "progress": [100, 300], "pages": 300}
    ]
    assert data["queued"] == [c] and data["errors"][0]["tid"] == d
    assert data["eta_seconds"] is None  # fewer than 5 files done: the time left is not told yet (test_load_regulator)


def test_status_words():
    data = {
        "done": 34,
        "total": 41,
        "running": [
            {"tid": "T0002", "stage": "convert", "active": True, "progress": [390, 1136]},
            {"tid": "T0005", "stage": "prep", "active": True, "pages": 12},
            {"tid": "T0006", "stage": "prep", "active": False},
        ],
        "queued": ["T0009"],
        "errors": [{"tid": "T0012", "status": "error", "rel": "x.pdf", "why": "preparation: FzErrorSystem"}],
        "eta_seconds": 2400,
    }
    text = intake_tools.batch_words(data)
    assert text.startswith("34 of 41 files done; in work T0002 (conversion 390/1136 pages), T0005 (preparation, 12 pages)")
    assert "waiting 2" in text and "errors and skipped 1" in text and "about 40 min left" in text
    assert "T0012 [error] x.pdf — preparation: FzErrorSystem" in text
    assert "{" not in text  # words, not a Python dict


@pytest.mark.parametrize(
    "running, applied, todo, want",
    [
        (True, False, "0", "wait"),
        (False, True, "0", "Done: the batch is in the library"),
        (False, False, "3\nT1 T2 T3", "write the cards of 3 files"),
        (False, False, "0\n", "intake_apply()"),
    ],
)
def test_next_step(tmp_path, monkeypatch, running, applied, todo, want):
    if applied:
        (tmp_path / "out").mkdir()
        (tmp_path / "out" / "applied.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(intake_tools, "_intake", lambda *a, **k: (0, todo))
    assert want in intake_tools.next_step(str(tmp_path), {}, running, False)


def test_reindex_progress(tmp_path, monkeypatch):
    p = tmp_path / "reindex.progress.json"
    monkeypatch.setenv(reindex.PROGRESS, str(p))
    reindex.write_progress("embed", 120, 900)
    assert reindex.read_progress(str(p))["done"] == 120
    monkeypatch.setattr(intake_tools, "progress_path", lambda: str(p))
    assert intake_tools.reindex_words({}) == "Step: the meaning vectors: 120 of 900."
    monkeypatch.delenv(reindex.PROGRESS)
    reindex.write_progress("build_index")  # no file named: nothing written
    assert reindex.read_progress(str(p))["stage"] == "embed"


def test_reindex_is_a_module_not_a_script(monkeypatch):
    seen = []
    monkeypatch.setattr(intake_tools, "_job", lambda kind: None)
    monkeypatch.setattr(intake_tools, "_start", lambda kind, cmd, **env: seen.append((cmd, env)) or (False, "x"))
    intake_tools.reindex()
    cmd, env = seen[0]
    assert cmd[1:3] == ["-m", "assistant_x.search.reindex"] and env["AX_PROGRESS"].endswith("reindex.progress.json")


def test_pages_read_at_a_reduced_resolution(tmp_path):
    log = tmp_path / "T0001.log"
    log.write_text(
        "OCR on page.number=11/12.\nOCR on page.number=12/13.\nPage too large for dpi=400, reducing to dpi=321.\n"
        "OCR on page.number=13/14.\n",
        encoding="utf-8",
    )
    assert intake_work.dpi_reduced(log) == [13]
    from assistant_x.core.formats import read_pages_info, write_pages_info

    (tmp_path / "md").mkdir()
    side = tmp_path / "md" / "T0001.pages.json"
    write_pages_info(side, {12: {"flags": []}, 13: {"flags": ["formula"]}})
    intake_work.mark_pages(tmp_path, "T0001", "dpi_reduced", [13])
    assert read_pages_info(side)[13]["flags"] == ["formula", "dpi_reduced"]
    from assistant_x.search.retrieval import page_note

    assert "reduced resolution" in page_note(None, "formula,dpi_reduced")


def test_batch_marks_stage_and_activity(project, monkeypatch, capsys):
    from assistant_x.intake import pipeline as intake
    from tests.intake.test_intake_pool import FakePool

    root, cfg = project
    monkeypatch.setenv("AX_FP_CACHE", str(cfg.fingerprints))
    monkeypatch.setattr(intake.Batch, "pool", lambda self: FakePool([]))
    t0 = time.time()
    assert intake.main(["--config", str(cfg.path), "run"]) == 0
    work = sorted(cfg.work.glob("20??-??-??"))[-1]
    st = State(work / "state.sqlite")
    done = [r for r in st.all() if r["status"] == "done"]
    assert done and all(r["stage"] == "convert" and r["active"] for r in done)
    assert st.get_meta("started") >= t0
    counters = [x for x in capsys.readouterr().out.splitlines() if x.strip().endswith(" s") and " files, " in x]
    assert len(counters) == len({x.split(" files")[0] for x in counters})  # printed on change only
