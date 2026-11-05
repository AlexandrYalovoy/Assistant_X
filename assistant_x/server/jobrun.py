# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The wrapper of a background job of the server (intake_tools._start): it runs the command with its output appended to
the log, then writes the exit code beside it, so the status can tell a job that ended (with its code) from one that was
stopped before the end (its process gone, no code written).

    python -m assistant_x.server.jobrun LOG EXIT -- COMMAND...

The server starts this wrapper detached from itself (its own process group, out of the job object of the client where
Windows allows it), so closing Claude does not end an install or a recalculation half-way.

Every end is told: the exit code with its meaning ("why": a crash, out of memory, the console closed), a signal that
ended the wrapper, and while it runs a heartbeat (EXIT.beat.json, every HEARTBEAT_S) that notes a sleep of the PC; a
job gone with no exit code is then told apart: the PC restarted after its last heartbeat, or it was ended from
outside (intake_tools.state_text)."""

import json, os, signal, sys, threading, time

from assistant_x.core import proc
from assistant_x.setup import status as S  # why_exit, boot_time: standard library only

JOB_ID = "AX_JOB_ID"  # the id of the job (its record in <kind>.json): the exit code is of that job only
HEARTBEAT_S = 30


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def write_exit(path, code, why=None, events=()):
    _write(
        path,
        {
            "code": code,
            "why": why or S.why_exit(code),
            "job": os.environ.get(JOB_ID, ""),
            "ended": time.time(),
            "events": list(events),
        },
    )


def beat_path(exit_path):
    return exit_path + ".beat.json"


def read_beat(exit_path):
    try:
        with open(beat_path(exit_path), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def gone_why(exit_path, job=None):
    """Why the job (its id) that wrote no exit code is gone, from its last heartbeat: '' when nothing tells."""
    beat = read_beat(exit_path)
    if not beat or (job and beat.get("job") != job):
        return ""
    why = S.why_dead({"heartbeat": beat.get("beat")})
    return why + "".join(f"; {e}" for e in (beat.get("events") or [])[-2:])


class Beat:
    """The heartbeat of the wrapper: written every HEARTBEAT_S, a gap of more than S.SLEEP_GAP_S noted as a sleep."""

    def __init__(self, exit_path):
        self.path, self.events, self.stop = beat_path(exit_path), [], False
        self.write()
        threading.Thread(target=self.run, daemon=True).start()

    def write(self):
        try:
            _write(
                self.path,
                {"pid": os.getpid(), "job": os.environ.get(JOB_ID, ""), "beat": time.time(), "events": self.events[-5:]},
            )
        except OSError:
            pass

    def run(self):
        last = time.time()
        while not self.stop:
            time.sleep(HEARTBEAT_S)
            now = time.time()
            if now - last > S.SLEEP_GAP_S:
                self.events.append(f"{time.strftime('%H:%M')} no heartbeat for {(now - last) / 60:.0f} min: the PC slept")
            self.write()
            last = now


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 4 or argv[2] != "--":
        print(__doc__, file=sys.stderr)
        return 2
    log, exit_path, cmd = argv[0], argv[1], argv[3:]
    beat = Beat(exit_path)

    def ended(signum, _frame):  # the wrapper itself is ended: said before it goes
        write_exit(exit_path, 128 + signum, f"the job was ended by the signal {signum}", beat.events)
        os._exit(128 + signum)

    for name in ("SIGTERM", "SIGBREAK", "SIGINT", "SIGHUP"):
        if getattr(signal, name, None) is not None:
            try:
                signal.signal(getattr(signal, name), ended)
            except (OSError, ValueError):
                pass
    with open(log, "a", encoding="utf-8") as out:
        try:
            # the wrapper runs in the hidden console of its start (intake_tools._popen); the command never gets a window
            code = proc.call(cmd, stdout=out, stderr=proc.STDOUT, stdin=proc.DEVNULL, hidden=True)
        except OSError as e:
            out.write(f"the job could not start: {e}\n")
            code = 127
        if code:
            out.write(f"the job ended with exit code {code}: {S.why_exit(code)}\n")
    beat.stop = True
    write_exit(exit_path, code, events=beat.events)
    return code


if __name__ == "__main__":
    sys.exit(main())
