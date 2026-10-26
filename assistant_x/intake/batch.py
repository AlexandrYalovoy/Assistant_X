# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared helpers of the intake: the work folder of a batch, the output, the kinds of files set aside."""

import datetime, sys
from pathlib import Path

from assistant_x.core.formats import extensions
from assistant_x.intake.tools import dupcheck


LETTERS = set(extensions("letter"))  # core/formats.EXTENSIONS: taken apart by prepare.py (attachments kept)
EXCEL = set(extensions("spreadsheet"))  # documents of the batch (work.prep: PDF and the sheets as tables)
SKIP_FILES = {"_readme.md", "desktop.ini", "thumbs.db"}
DUP, AUTO, PARTIAL = dupcheck.THRESHOLDS["dup"], dupcheck.THRESHOLDS["auto"], dupcheck.THRESHOLDS["partial"]
SAME, PAGES_APART = dupcheck.THRESHOLDS["same"], dupcheck.THRESHOLDS["pages_apart"]


def say(*a):
    print(*a, flush=True)


def today():
    return datetime.date.today().isoformat()


def work_dir(cfg, given=None, new=False):
    """The batch folder: given, today's for run, else the latest one."""
    if given:
        return Path(given).resolve()
    if new:
        return cfg.work / today()
    days = sorted(p for p in cfg.work.glob("20??-??-??") if (p / "state.sqlite").exists()) if cfg.work.exists() else []
    if not days:
        sys.exit(f"No batches in {cfg.work}: run assistant-x intake run first")
    return days[-1]


def win(rel):
    return rel.replace("/", "\\")
