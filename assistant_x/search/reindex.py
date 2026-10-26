# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The base recalculation after an intake: build_index, then embed for the new fragments (intake_reindex starts it in
the background). Each step writes where it is to the progress file of AX_PROGRESS (intake_status shows it):

    python -m assistant_x.search.reindex [--cpu]

    {"stage": "build_index" | "embed", "done": n, "total": m, "updated": time}"""

import json, os, sys, time

from assistant_x.core import proc

PROGRESS = "AX_PROGRESS"


def write_progress(stage, done=0, total=0):
    """The step of the recalculation and how far it is, into the file of AX_PROGRESS (nothing when it is not set)."""
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


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    py = sys.executable
    write_progress("build_index")
    rc = proc.call([py, "-m", "assistant_x.search.build_index"])
    if rc:
        return rc
    write_progress("embed")
    return proc.call([py, "-m", "assistant_x.search.embed", *argv])


if __name__ == "__main__":
    sys.exit(main())
