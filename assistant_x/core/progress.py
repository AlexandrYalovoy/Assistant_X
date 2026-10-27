# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The progress file of a background job (AX_PROGRESS): its stage and how far it is, read by intake_status. The base
recalculation (search/reindex.py) and the transfer into the library (intake/apply_job.py) write it.

    {"stage": "...", "done": n, "total": m, "updated": time}"""

import json, os, time

PROGRESS = "AX_PROGRESS"


def write_progress(stage, done=0, total=0):
    """The stage of the job and how far it is, into the file of AX_PROGRESS (nothing when it is not set)."""
    path = os.environ.get(PROGRESS)
    if not path:
        return
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"stage": stage, "done": done, "total": total, "updated": time.time()}, f)
        os.replace(tmp, path)
    except OSError:
        pass  # a progress line is a help only


def read_progress(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
