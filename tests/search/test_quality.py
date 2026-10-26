# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The quality stand (tests/search/quality.py): the control questions of the golden corpus keep their hit@5 and MRR
in every mode and form, never below tests/search/quality_baseline.json (python -m tests.search.quality --baseline
writes it on purpose). The fake model: the plumbing of the search is measured, not bge-m3."""

import json

from tests.search import quality


def test_loose_form_of_a_phrase():
    assert quality.loose("Давление насыщения нефти газом") == "газом нефти насыщения Давление"
    assert quality.loose("один два три четыре пять шесть") == "пять три один"
    assert quality.loose("(12)") == ""


def test_the_search_keeps_its_quality_baseline(tmp_path):
    lib, qs = quality.make_base(str(tmp_path))
    assert len(qs) >= 30 and {f for f, *_ in qs} == {"phrase", "loose"}
    res, _ = quality.measure(lib, qs)
    base = json.loads(quality.BASELINE.read_text(encoding="utf-8"))
    assert set(base) == set(res)
    assert not quality.below(res, base), quality.table(res)
