# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the search and the intake share through common.py: the quality thresholds (common.QUALITY, used by
quality_note and intake/quality_report.py) and the free disk space check before long jobs."""

import os, sys

import pytest

from assistant_x.core import common

from assistant_x.intake import quality_report


def test_one_source_of_quality_thresholds():
    assert quality_report.QUALITY is common.QUALITY
    assert quality_report.EMPTY == common.QUALITY["empty_chars"] == 80
    assert quality_report.MIN_PAGES_HEADS == common.QUALITY["min_pages_heads"] == 5
    src = open(quality_report.__file__, encoding="utf-8").read()
    for number in ("0.2", "0.5", "0.3", "0.8", "= 80", "= 5"):  # no thresholds of its own left in the intake report
        assert number not in src.split("def summary_line")[0].split("MIN_PAGES_HEADS =")[1], number


def test_quality_values_unchanged():
    assert common.QUALITY == {
        "empty_chars": 80,
        "empty_share": 0.2,
        "fffd_per_1000": 1,
        "scan_share": 0.2,
        "scan_script": (0.3, 0.8),
        "lang_letters": 200,
        "lang_share": 0.7,
        "lang_mixed": 0.15,
        "replace_share": 0.5,
        "fallback_share": 0.2,
        "min_pages_heads": 5,
        "ocr_words_free": 0.03,
        "ocr_words_slope": 140,
        "ocr_conf_floor": 40,
        "ocr_conf_full": 92,
        "ocr_low_conf": 60,
        "ocr_conf_weight": 0.25,
        "ocr_retry_conf": 60,
        "ocr_retry_nonword": 0.25,
        "ocr_note": 70,
        "ocr_replace": 50,
        "ocr_redo_gain": 10,
        "ocr_redo_keep": 0.8,
    }


def test_both_sides_follow_the_thresholds(monkeypatch):
    m = {
        "no_ocr_pages": 0,
        "fffd": 1,
        "fffd_per_1000": 1,
        "pages": 10,
        "empty_pages": 2,
        "ocr_share": 0.0,
        "letters": {"ru": 0.9, "en": 0.1},
        "fallback": 0,
    }
    st = {"fffd_per_1000": 1, "empty_share": 0.2}
    assert len(quality_report.problems(m)) == 2 and len(common.quality_note(st).split("; ")) == 2
    # a threshold changed in the one place changes both
    monkeypatch.setitem(common.QUALITY, "fffd_per_1000", 2)
    monkeypatch.setitem(common.QUALITY, "empty_share", 0.5)
    assert quality_report.problems(m) == [] and common.quality_note(st) == ""
    monkeypatch.setitem(common.QUALITY, "empty_chars", 3)
    assert common.text_stats([(1, "мало")])["empty_share"] == 0
    assert quality_report.measure("=== page 1 ===\nмало\n", {})["empty_pages"] == 1  # EMPTY is read once, at import


def test_free_space_problem(tmp_path):
    assert common.free_space_problem(tmp_path, 10, {"factor": 3, "min_free_gb": 0}) == ""
    msg = common.free_space_problem(tmp_path / "missing" / "too", 10**15, {"factor": 3, "min_free_gb": 0})
    assert msg.startswith("Not enough disk space on") and "3 x input files" in msg
    assert common.free_space_problem(tmp_path, 0, {"factor": 3, "min_free_gb": 10**9}).startswith("Not enough disk space")


def test_disk_limits_and_folder_bytes(tmp_path):
    assert common.disk_limits(str(tmp_path / "missing" / "assistant_x.toml")) == common.DISK
    assert common.disk_limits() == common.DISK  # the workspace of the tests has no [intake.disk]
    t = tmp_path / "assistant_x.toml"
    t.write_text("[intake.disk]\nfactor = 2\n", encoding="utf-8")
    assert common.disk_limits(str(t)) == {"factor": 2, "min_free_gb": 10}
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "a.txt").write_bytes(b"x" * 100)
    (tmp_path / "b.txt").write_bytes(b"y" * 5)
    assert common.folder_bytes(str(tmp_path / "d"), str(tmp_path / "b.txt"), str(tmp_path / "missing")) == 105


def test_build_index_refused_on_low_disk(monkeypatch, tmp_path):
    from assistant_x.search import build_index
    from tests.search.conftest import make_library

    cfg = make_library(str(tmp_path / "Библиотека"))  # a mini library: the real base is never touched
    monkeypatch.setattr(common.disk_limits, "__defaults__", (str(tmp_path / "missing.json"),))
    monkeypatch.setattr(common, "DISK", {"factor": 3, "min_free_gb": 10**9})
    monkeypatch.setattr(sys, "argv", ["build_index.py", "--config", cfg, "--no-check"])
    with pytest.raises(SystemExit, match="Not enough disk space"):
        build_index.main()
    assert not os.path.exists(os.path.join(tmp_path, "Библиотека", "search", "db", "library.sqlite"))
