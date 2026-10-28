# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ledger of a batch: every file the batch met gets exactly one outcome, so the totals add up."""

import csv

from assistant_x.intake import ledger
from assistant_x.intake.state import State


def test_every_file_has_one_outcome(tmp_path):
    state = State(tmp_path / "state.sqlite")
    t = [state.add(f"f{i}.pdf", 10) for i in range(6)]
    state.update(t[0], status="done", pages=3, ocr_pages=1, ocr_score=91.5, prep_seconds=1.0, ocr_seconds=2.5)
    state.update(t[1], status="dup", why="the same SHA-256", dup_of="N-00001")
    state.update(t[2], status="error", why="the PDF does not open")
    state.update(t[3], status="skipped", why="the pipeline does not process .exe: decide by hand")
    state.update(t[4], status="skipped", why="a temporary Office file (~$): reject")
    state.set_meta("moved", [["mail/letter.msg", 20, "to delete: a letter"]])
    counts, total = ledger.write(tmp_path, state)
    assert total == 7
    assert counts == {"done": 1, "duplicate": 1, "error": 1, "unsupported": 1, "skipped": 1, "moved": 1, "queued": 1}
    with open(tmp_path / "ledger.csv", encoding="utf-8-sig") as f:
        rows = {r["file"]: r for r in csv.DictReader(f)}
    assert rows["f0.pdf"]["score"] == "91.5" and rows["f0.pdf"]["seconds"] == "3.5"
    assert rows["f1.pdf"]["why"].endswith("-> N-00001")
    assert rows["mail/letter.msg"]["outcome"] == "moved"
    assert "Ledger (ledger.csv): 7 files: done 1" in ledger.line(counts, total)
    state.close()
