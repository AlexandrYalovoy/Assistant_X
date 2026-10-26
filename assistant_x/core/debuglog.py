# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Failure and call journal in the debug folder of the workspace (.assistant_x/debug): failures.log (tracebacks), calls.log
(one line per MCP call) and changes.log (every call of a command that changes the library: planned, refused, started).
Standard library only, so it works even when the other packages are missing or broken."""

import datetime, functools, hashlib, json, os, platform, sys, threading, time, traceback

from assistant_x.core import env, workspace

# the debug folder of the workspace (.assistant_x/debug); made at the first line written
# the journals of the workspace in use, found when written (not at import); a test or a tool may set them itself
LOG_DIR = ERRORS = CALLS = None


def pc_id():
    """A short id of this PC for the names and headers of the reports meant to be passed on: a hash of its name, so
    the reports of one PC go together without telling the name of the PC."""
    return hashlib.sha256(platform.node().encode("utf-8")).hexdigest()[:8]


def log_dir():
    return LOG_DIR or str(workspace.current().debug)


def errors_path():
    return ERRORS or os.path.join(log_dir(), "failures.log")


def calls_path():
    return CALLS or os.path.join(log_dir(), "calls.log")


def changes_path():
    return os.path.join(log_dir(), "changes.log")


# AX_NO_OPEN=1: no window opens by itself (tests, trial runs, background runs): no Notepad, no Explorer
def may_open():
    return os.name == "nt" and not env.flag("NO_OPEN")


REPORT_HINT = 'run "assistant-x debug-report" and pass on the file it creates, "debug_report_….md"'


def _append(path, text, limit):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > limit:  # keep one previous file, drop older
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass  # logging must never break the search itself


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _short(args):
    try:
        s = json.dumps(args, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        s = repr(args)
    return s if len(s) <= 500 else s[:500] + "…"


def log_error(where, exc=None, args=None):
    tb = "".join(traceback.format_exception(exc)) if exc else traceback.format_exc()
    _append(errors_path(), f"=== {_now()} | {where} | pid {os.getpid()}\narguments: {_short(args or {})}\n{tb}\n", 2_000_000)


def log_text(where, trace, args=None):
    """A failure whose traceback is text already (it came from a worker process)."""
    _append(
        errors_path(), f"=== {_now()} | {where} | pid {os.getpid()}\narguments: {_short(args or {})}\n{trace}\n", 2_000_000
    )


_local = threading.local()


def note(text):
    """Add a remark to the journal line of the MCP call running in this thread (e.g. how strong the match was)."""
    _local.note = text


def log_call(tool, seconds, ok, args=None, note=""):
    _append(
        calls_path(),
        f"{_now()}\t{tool}\t{seconds * 1000:.0f} ms\t{'ok' if ok else 'FAILED'}\t{_short(args or {})}\t{note}\n",
        1_000_000,
    )


def log_change(tool, args, outcome):
    """A line of changes.log for every call of a command that changes the library (planned, refused, started)."""
    _append(changes_path(), f"{_now()}\t{tool}\t{outcome}\t{_short(args or {})}\n", 1_000_000)


def logged(fn):
    """Wrap an MCP tool: time every call, write failures to the journal and answer Claude with a readable message
    instead of a bare 'Error executing tool'."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        t = time.time()
        _local.note = ""
        shown = {k: v for k, v in kwargs.items() if k != "ctx"}  # the request context of the MCP SDK is no argument
        try:
            res = fn(*args, **kwargs)
        except Exception as e:
            log_error(fn.__name__, e, shown)
            log_call(fn.__name__, time.time() - t, False, shown, f"{type(e).__name__}: {e}")
            return (
                f"Library command failed {fn.__name__}: {type(e).__name__}: {e}\n"
                f"The failure was logged. To pass it on for a look, {REPORT_HINT}."
            )
        size = f"{len(res)} chars" if isinstance(res, str) else ""
        log_call(fn.__name__, time.time() - t, True, shown, "; ".join(x for x in (_local.note, size) if x))
        return res

    return wrapper


def run(main, name):
    """Run a script's main(): a crash goes to the journal and is still shown in the console."""
    try:
        return main()
    except SystemExit:
        raise
    except BaseException as e:
        log_error(f"{name} {' '.join(sys.argv[1:])}", e)
        print(f"\nThe failure was logged in {errors_path()}. To pass it on for a look, {REPORT_HINT}.", file=sys.stderr)
        raise
