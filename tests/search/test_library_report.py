# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""assistant-x report (search/library_report.py) on the mini library: every section, the counts of the base."""

import os, sys

from assistant_x.search import library_report


def test_the_report_of_the_mini_library(mini, tmp_path, monkeypatch):
    text = library_report.report(mini["cfg"])
    for head in (
        "# State of the library on",
        "## 1. Summary",
        "## 2. Index check",
        "## 3. Text quality",
        "## 4. Sources to update",
        "## 5. Book map",
        "## 6. Old editions",
        "## 7. Manifest of the originals",
    ):
        assert head in text, head
    assert "Documents in all 6" in text and "| N — " in text
    out = tmp_path / "report.md"
    monkeypatch.setattr(sys, "argv", ["library_report.py", "--config", mini["config"], "--out", str(out)])
    library_report.main()
    assert out.read_text(encoding="utf-8") == text or out.read_text(encoding="utf-8").startswith("# State")
    assert os.path.getsize(out) > 500


def test_table_escapes_its_cells():
    assert library_report.table(["a", "b"], [("x|y", "1\n2")]) == ["| a | b |", "|---|---|", "| x/y | 1 2 |"]
