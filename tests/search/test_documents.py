# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Checks of document content shared by the search and the intake: duplicate thresholds and hidden text."""

import os

from tests.search.conftest import TRAP


def test_dupcheck_verdict():
    from assistant_x.intake.tools import dupcheck

    assert dupcheck.THRESHOLDS == {"partial": 0.08, "dup": 0.30, "auto": 0.60, "same": 0.90, "pages_apart": 0.10}
    assert dupcheck.verdict(0.95) == dupcheck.verdict(0.30) == "DUPLICATE"
    assert dupcheck.verdict(0.29) == dupcheck.verdict(0.08) == "partial match, check"
    assert dupcheck.verdict(0.079) == "no"


def test_hidden_text_found_in_trap(mini):
    import pymupdf
    from assistant_x.intake.tools import hidden

    lib = os.path.join(mini["root"], "library")
    trap = pymupdf.open(os.path.join(lib, "06_Other", "X-00001_Test-Trap.pdf"))
    hits = [(why, text) for why, text, _ in hidden.check(trap[0])]
    assert any(why == "text blends with the background" and TRAP in text for why, text in hits)
    assert any(why.startswith("font") and TRAP in text for why, text in hits)
    assert not any("Normal visible" in text for _, text in hits)
    normal = pymupdf.open(os.path.join(lib, "01_Standards", "N-00001_Test-Well-Rate-Standard.pdf"))
    assert all(hidden.check(p) == [] for p in normal)
    marks = pymupdf.open()  # a legal-database export: a footnote mark "1" in a 1 pt font on every page, no letters
    marks.new_page().insert_text((72, 72), "1", fontsize=1)
    assert hidden.check(marks[0]) == []
