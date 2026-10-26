# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The wrapper of a background job of the server (intake_tools._start): it runs the command with its output appended to
the log, then writes the exit code beside it, so the status can tell a job that ended (with its code) from one that was
stopped before the end (its process gone, no code written).

    python -m assistant_x.server.jobrun LOG EXIT -- COMMAND...

The server starts this wrapper detached from itself (its own process group, out of the job object of the client where
Windows allows it), so closing Claude does not end an install or a recalculation half-way."""

import json, os, sys, time

from assistant_x.core import proc

JOB_ID = "AX_JOB_ID"  # the id of the job (its record in <kind>.json): the exit code is of that job only


def write_exit(path, code):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"code": code, "job": os.environ.get(JOB_ID, ""), "ended": time.time()}, f)
    os.replace(tmp, path)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 4 or argv[2] != "--":
        print(__doc__, file=sys.stderr)
        return 2
    log, exit_path, cmd = argv[0], argv[1], argv[3:]
    with open(log, "a", encoding="utf-8") as out:
        try:
            # the wrapper runs in the hidden console of its start (intake_tools._popen); the command never gets a window
            code = proc.call(cmd, stdout=out, stderr=proc.STDOUT, stdin=proc.DEVNULL, hidden=True)
        except OSError as e:
            out.write(f"the job could not start: {e}\n")
            code = 127
    write_exit(exit_path, code)
    return code


if __name__ == "__main__":
    sys.exit(main())
