# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The transfer of a batch into the library as one background job (intake_apply starts it, intake_status shows its
stage): build, apply, then the base recalculation (search/reindex.py), one after another. Each stage
goes to the progress file of AX_PROGRESS (core/progress.py), as the recalculation writes its own:

    python -m assistant_x.intake.apply_job [--personal] [--cpu]

    {"stage": "build" | "apply" | "build_index" | "embed", "done": n, "total": m, "updated": time}

An apply that stops halfway is resumed by the next one (intake apply is a transaction, intake/apply.py)."""

import sys

from assistant_x.core import proc
from assistant_x.core.progress import write_progress

STAGES = ("build", "apply", "build_index", "embed")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    intake = [sys.executable, "-m", "assistant_x.intake.pipeline"]
    write_progress("build")
    rc = proc.call([*intake, "build", *(["--personal"] if "--personal" in argv else [])])
    if rc:
        print(f"The build failed (code {rc}): nothing was moved.", flush=True)
        return rc
    write_progress("apply")
    rc = proc.call([*intake, "apply"])
    if rc:
        print(f"The apply failed (code {rc}): intake_apply again resumes it.", flush=True)
        return rc
    return proc.call([sys.executable, "-m", "assistant_x.search.reindex", *(["--cpu"] if "--cpu" in argv else [])])


if __name__ == "__main__":
    sys.exit(main())
