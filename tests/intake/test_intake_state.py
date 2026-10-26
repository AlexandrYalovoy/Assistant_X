# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""intake_state.py (SQLite state of a batch), journal.py (journal.md from the events and the manifest),
quality_report.py, intake_limits.py."""

import sys, time

from assistant_x.core import journal
from assistant_x.intake import quality_report
from assistant_x.intake.limits import run
from assistant_x.intake.state import State


def test_state(tmp_path):
    s = State(tmp_path / "state.sqlite")
    t1 = s.add("a/x.pdf", 10)
    t2 = s.add("b.docx", 20)
    assert (t1, t2) == ("T0001", "T0002") and s.add("a/x.pdf", 10) == "T0001"
    s.update(t1, status="running", pages=3, similar=[[0.5, "L-00001"]])
    s.update(t1, status="done", cyr=0.9, why="ok")
    r = s.get(t1)
    assert r["status"] == "done" and r["pages"] == 3 and r["cyr"] == 0.9 and r["similar"] == [[0.5, "L-00001"]]
    assert r["rel"] == "a/x.pdf" and s.by_rel("b.docx")["tid"] == t2
    s.update(t2, status="running")
    assert s.counts() == {"done": 1, "running": 1}
    assert s.reset_running() == 1 and s.get(t2)["status"] == "queued"
    assert [r["tid"] for r in s.all("queued")] == [t2]
    s.set_meta("prepare", {"letters": 2})
    s.close()
    s = State(tmp_path / "state.sqlite")  # survives a restart
    assert s.get_meta("prepare") == {"letters": 2} and s.get(t1)["cyr"] == 0.9
    assert s.add("c.pdf", 1) == "T0003"


JOURNAL = """# Intake journal

| Date | Source file | Size, bytes | SHA-256 | Code | Library file | Status |
|------|---------------|--------------|---------|------|-------------------|--------|
| 2026-10-20 | inbox\\a.pdf | 100 | 0123456789abcdef | N-00001 | library\\01_Standards\\N-00001_A.pdf | done |
| 2026-10-20 | inbox\\b.pdf | — | — | L-00001 | library\\02_Literature\\L-00001_B.pdf | done |
| 2026-10-21 | inbox\\c.pdf | 5 | aaaaaaaaaaaaaaaa | — | inbox\\_duplicates\\ | duplicate N-00001 (100% of phrases in common) |
| 2026-10-21 | inbox\\d.pdf | 5 | — | — | inbox\\_rejected\\ | rejected: administrative pages only |
| 2026-10-21 | inbox\\e.msg | — | — | — | inbox\\_to_delete\\ | to delete: a letter |
| 2026-10-21 | inbox\\d.pdf | 5 | — | — | inbox\\_rejected\\ | rejected: administrative pages only |
"""  # a journal with rows the events do not have yet
MANIFEST = (
    "path\tsize\tmodified\tsha256\tcode\n"
    "library\\01_Standards\\N-00001_A.pdf\t100\t2026-10-20T10:00:00\t" + "0123456789abcdef" * 4 + "\tN-00001\n"
    "library\\02_Literature\\L-00001_B.pdf\t200\t2026-10-20T10:00:00\t" + "bbbbbbbbbbbbbbbb" * 4 + "\tL-00001\n"
    "library\\02_Literature\\L-00002_C.pdf\t300\t2026-10-20T10:00:00\t" + "cccccccccccccccc" * 4 + "\tL-00002\n"
)


def test_journal_migration_and_generation(tmp_path):
    (tmp_path / "journal.md").write_text(JOURNAL, encoding="utf-8")
    (tmp_path / "manifest.tsv").write_text(MANIFEST, encoding="utf-8")
    old = journal.parse_journal(JOURNAL)
    text, imported = journal.sync(tmp_path)
    assert len(imported) == len(old) == 6  # the repeated row is kept: rows are counted, not deduplicated
    events = journal.read_events(tmp_path / "intake_events.tsv")
    new = journal.parse_journal((tmp_path / "journal.md").read_text(encoding="utf-8"))
    kinds = lambda rows: sorted(journal.kind(r[6]) for r in rows)
    assert kinds(events) == kinds(old) == kinds(new)
    # size and hash an event lacks come from the manifest
    b = next(r for r in new if r[4] == "L-00001")
    assert b[2] == "200" and b[3] == "bbbbbbbbbbbbbbbb"
    assert "without a journal entry: 1" in text and "L-00002_C.pdf" in text
    assert journal.kind("duplicate N-00001") == "duplicate"
    assert journal.is_current(tmp_path) == (True, "")
    # a second run takes nothing over twice
    assert journal.sync(tmp_path)[1] == []
    # a row written by hand into journal.md goes into the events
    with open(tmp_path / "journal.md", "a", encoding="utf-8") as f:
        f.write("| 2026-10-22 | inbox\\f.xlsx | — | — | — | inbox\\_to_delete\\ | to delete: Excel |\n")
    ok, why = journal.is_current(tmp_path)
    assert not ok and "1 rows" in why
    assert len(journal.sync(tmp_path)[1]) == 1 and len(journal.read_events(tmp_path / "intake_events.tsv")) == 7
    # new events: the journal is stale until regenerated
    journal.append_events(tmp_path / "intake_events.tsv", [["2026-10-23", "inbox\\g.pdf", 1, "—", "—", "—", "error: x"]])
    assert not journal.is_current(tmp_path)[0]
    journal.sync(tmp_path)
    assert journal.is_current(tmp_path)[0]


def test_first_append_keeps_history_first(tmp_path):
    (tmp_path / "journal.md").write_text(JOURNAL, encoding="utf-8")
    journal.append_events(
        tmp_path / "intake_events.tsv", [["2026-10-23", "inbox\\z.eml", 1, "—", "—", "x", "to delete: a letter"]]
    )
    ev = journal.read_events(tmp_path / "intake_events.tsv")
    assert len(ev) == 7 and ev[0][0] == "2026-10-20" and ev[-1][1].endswith("z.eml")


def test_quality_measure():
    md = "=== page 1 ===\n\n# Глава 1\n\n" + "Текст страницы о сепарации нефти. " * 10 + "\n\n=== page 2 ===\n\n��\n"
    m = quality_report.measure(md, {"ocr_pages": 1, "pages": 2, "no_ocr_pages": 0, "fallback": 0})
    assert (
        m["pages"] == 2 and m["empty_pages"] == 1 and m["fffd"] == 2 and m["ocr_share"] == 0.5 and m["pages_no_heads"] == 1
    )
    assert m["letters"] == {"ru": 1.0, "en": 0.0}
    probs = quality_report.problems(m)
    assert any("almost no text" in p[0] for p in probs) and any("U+FFFD" in p[0] for p in probs)
    m = quality_report.measure("=== page 1 ===\n\n", {"ocr_pages": 1, "pages": 1, "no_ocr_pages": 1})
    assert quality_report.problems(m)[0][2] == "high"


def test_limits_timeout_and_memory(tmp_path):
    assert run([sys.executable, "-c", "print(1)"], timeout=60, memory_mb=500) == (0, None)
    t = time.time()
    rc, why = run(
        [sys.executable, "-c", "import time; time.sleep(30)"], timeout=1, memory_mb=500, log=str(tmp_path / "l.log")
    )
    assert why == "timeout" and time.time() - t < 10
    assert "stopped: timeout" in (tmp_path / "l.log").read_text(encoding="utf-8")
    # the child of the child is limited too (the whole tree)
    code = (
        "import subprocess, sys; sys.exit(subprocess.run([sys.executable, '-c', 'x = bytearray(900 * 2**20)']).returncode)"
    )
    rc, why = run([sys.executable, "-c", code], timeout=60, memory_mb=300)
    assert rc != 0 and why == "memory"


def test_posix_tells_the_memory_cap_by_the_output():
    """POSIX has no peak of a job: a failed tool's output, or SIGKILL, tells that the cap was hit."""
    from assistant_x.intake import limits

    assert limits.says_memory(1, b"Traceback ...\nMemoryError\n") and limits.says_memory(-9, b"")
    assert limits.says_memory(134, b"terminate called after throwing an instance of 'std::bad_alloc'")
    assert not limits.says_memory(1, b"Error: no such file") and not limits.says_memory(0, b"MemoryError")
