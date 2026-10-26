# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The golden corpus keeps its numbers: the fast metrics (the text layer, the outline, the draft, the duplicate check)
run with every test run, the full ones (the whole intake with LibreOffice and Tesseract) with the slow tests; neither
may fall below tests/corpus/baseline.json (python -m tests.corpus.report [--full] --baseline writes it on purpose)."""

import json
from pathlib import Path

import pytest

from tests.corpus import documents, metrics

BASELINE = json.loads((Path(__file__).resolve().parent / "baseline.json").read_text(encoding="utf-8"))


def test_metric_helpers():
    assert metrics.found("Давление  насыщения", "## Давление\nнасыщения нефти") and not metrics.found("газа", "нефти")
    assert metrics.heading_match("1 ОБЩИЕ ПОЛОЖЕНИЯ", "1 Общие положения") and not metrics.heading_match("", "x")
    assert metrics.char_accuracy("Давление нефти", "давление  нефти") == 1.0
    assert 0.8 < metrics.char_accuracy("Давлеиие нефти", "Давление нефти") < 1.0
    rep = {"totals": {"phrase_recall": 0.9, "ocr_accuracy": None}}
    assert metrics.below(rep, {"phrase_recall": 0.95, "ocr_accuracy": 0.9}) == [
        ("phrase_recall", 0.9, 0.95),
        ("ocr_accuracy", None, 0.9),
    ]
    assert metrics.below(rep, {"phrase_recall": 0.903}) == []  # within the tolerance


def test_corpus_has_every_kind_of_case(tmp_path):
    cases = documents.make(tmp_path)
    assert 10 <= len(cases) <= 15
    assert {c["needs"] for c in cases} == {"", "ocr", "soffice"} and any(c["library"] for c in cases)
    assert {c["verdict"][0] for c in cases if c["verdict"]} == {"dup", "suspect"}
    assert all((tmp_path / ("library" if c["library"] else "inbox") / c["file"]).exists() for c in cases)


def test_fast_corpus_keeps_its_baseline(tmp_path):
    rep = metrics.measure("fast", tmp_path)
    assert not metrics.below(rep, BASELINE["fast"]), json.dumps(rep, ensure_ascii=False, indent=1)


@pytest.mark.slow
def test_full_corpus_keeps_its_baseline(tmp_path):
    from assistant_x.intake import config as intake_cfg

    if not (intake_cfg.find_soffice() and intake_cfg.find_tesseract()):
        pytest.skip("the full corpus needs LibreOffice and Tesseract")
    rep = metrics.measure("full", tmp_path)
    assert not metrics.below(rep, BASELINE["full"]), json.dumps(rep, ensure_ascii=False, indent=1)
