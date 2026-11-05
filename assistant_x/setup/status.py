# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""The state of an installation that runs in the background (install --background), for an agent that polls it.

    assistant-x status [--json] [--tail N] [--no-resume]
    python -m assistant_x.setup.status …          the same before the program is installed (from its source folder)
    python <source>\assistant_x\setup\status.py … the same from any folder

--json prints ONE short line: {"state", "stage", "percent", "eta_min", "ok", "error": {"code", "message", "fix"},
"poll_s", ...}; "state" is running, done or failed. poll_s is when to ask again (0: do not ask again). --tail N adds
the last N lines (at most 20) of the log of the installation. A worker that died (the PC restarted, the process
killed with the session of the agent that started it) is started again from here, at most MAX_RESTARTS times: the
installation repeats nothing that is done (the base install continues its journal); --no-resume only tells.

The files, in <the folder of the PC>\install (core/workspace.machine_dir): status.json (written by the worker), its
log install.log, progress.json (the steps of the base install, build and embed: core/progress.py). Standard library
only: it runs before any package is installed."""

import json, os, sys, time

if __package__ in (None, ""):  # run as a file from any folder: the package is two folders up
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from assistant_x.core import workspace  # noqa: E402 — after the path above

FILE, LOG, PROGRESS = "status.json", "install.log", "progress.json"
MAX_RESTARTS = 3
HEARTBEAT_S = 30  # the worker writes its heartbeat this often
SLEEP_GAP_S = 180  # a heartbeat later than this: the PC slept (or hibernated), the process was frozen
TAIL_MAX = 20
# the stages of the installation in order, with their share of the whole (percent)
STAGES = (
    ("start", 1),
    ("environment", 3),
    ("packages", 14),
    ("models", 14),
    ("intake", 3),
    ("connect", 2),
    ("self-test", 3),
    ("base", 57),
    ("doctor", 3),
)
POLL_S = {"packages": 300, "models": 300, "base": 600}  # when to ask again; any other stage: DEFAULT_POLL_S
DEFAULT_POLL_S = 120
# the share of the base install at the start of each of its steps (base/install.STEPS); extract, build and embed
# fill the span up to the next one by their own progress
BASE_AT = {
    "marker": 0.0,
    "backup": 0.01,
    "extract": 0.02,
    "plan": 0.47,
    "aside": 0.47,
    "renames one": 0.47,
    "renames two": 0.47,
    "cards": 0.48,
    "package": 0.48,
    "place": 0.48,
    "tables": 0.5,
    "key norms": 0.5,
    "build": 0.5,
    "vectors": 0.75,
    "base": 0.77,
}
SPANS = {"base install: extract": (0.02, 0.45), "build_index": (0.5, 0.25), "embed": (0.77, 0.2)}
# the exit codes of a Windows process that tell why it ended (NTSTATUS)
EXIT_CODES = {
    0xC000013A: "closed: its console was closed or Ctrl+C",
    0xC0000005: "crashed (access violation)",
    0xC00000FD: "crashed (stack overflow)",
    0xC0000409: "crashed (a check of the program failed)",
    0xC0000017: "out of memory",
    0xC000009A: "out of memory",
    0xC0000142: "could not start (the desktop of the session is gone: the user logged off)",
    1: "stopped with an error (the reason is in the log)",
    -9: "killed (SIGKILL)",
    -15: "killed (SIGTERM)",
}
FIXES = {  # error code -> what to do, in one line for the agent
    "python": "Python 3.11 could not be found or installed: install it from python.org (per user), run the same command",
    "network": "a download failed: check the internet (an antivirus that scans HTTPS may hold pypi.org, "
    "files.pythonhosted.org, download.pytorch.org, huggingface.co: allow them), then run the same command",
    "disk_full": "the disk is full: free space (the base package needs about twice its size), run the same command",
    "base_choice": "the codes of the package and the library collide: ask the user --keep package or --keep own, "
    "then run the same command with it",
    "base_failed": "the base install stopped: run the same command (it continues the install); the reason is in "
    "the log (status --tail 20)",
    "died": "the installation keeps ending from outside: run the same command from a terminal of the user that stays "
    "open, or ask the user to run Setup.bat",
    "exception": "an unexpected failure: run the same command once more; if it fails again, assistant-x debug-report "
    "and pass on the file",
    "stopped": "the reason is in error.message; fix it, then run the same command (what is done is not done again)",
}


def folder():
    return os.path.join(str(workspace.machine_dir()), "install")


def path(name=FILE):
    return os.path.join(folder(), name)


def read():
    try:
        with open(path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write(data):
    """The whole status, atomically (a reader never sees half a file)."""
    os.makedirs(folder(), exist_ok=True)
    tmp = path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    for i in range(5):  # a reader that holds the file a moment (an antivirus) on Windows
        try:
            os.replace(tmp, path())
            return
        except PermissionError:
            time.sleep(0.2 * (i + 1))
    os.replace(tmp, path())


def update(**fields):
    data = read() or {}
    data.update(fields, updated=time.time())
    write(data)
    return data


def event(text):
    """A line of what happened (a sleep, a restart, a child that died) kept with the status: the last 10."""
    data = read() or {}
    data["events"] = (data.get("events") or [])[-9:] + [f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}"]
    data["updated"] = time.time()
    write(data)


# ---------- the process ----------


def _creation_time(pid):
    """The time (epoch s) process pid started, or None when there is no such process (Windows: GetProcessTimes)."""
    import ctypes
    from ctypes import wintypes

    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        code = wintypes.DWORD()
        if k.GetExitCodeProcess(h, ctypes.byref(code)) and code.value != 259:  # STILL_ACTIVE
            return None
        times = [wintypes.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(h, *[ctypes.byref(t) for t in times]):
            return None
        ft = times[0].dwHighDateTime << 32 | times[0].dwLowDateTime
        return ft / 1e7 - 11644473600
    finally:
        k.CloseHandle(h)


def own_start():
    """The time this process started (alive() compares it), or None."""
    try:
        return _creation_time(os.getpid()) if os.name == "nt" else None
    except (OSError, AttributeError):
        return None


def alive(pid, started=None):
    """Is the worker pid running (and is it the very process that started at started, not a new one of that pid)?"""
    if not pid:
        return False
    if os.name == "nt":
        t = _creation_time(int(pid))
        return t is not None and (started is None or abs(t - float(started)) < 120)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def boot_time():
    """When this PC started (epoch s), or None."""
    try:
        if os.name == "nt":
            import ctypes

            ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_uint64
            return time.time() - ctypes.windll.kernel32.GetTickCount64() / 1000
        with open("/proc/uptime") as f:
            return time.time() - float(f.read().split()[0])
    except (OSError, ValueError, AttributeError):
        return None


def why_exit(code):
    """The meaning of the exit code of a process, in words."""
    if code is None:
        return "unknown"
    c = code & 0xFFFFFFFF if code < 0 and os.name == "nt" else code
    return EXIT_CODES.get(c, EXIT_CODES.get(code, f"ended with code {code}"))


def why_dead(data):
    """Why a worker that wrote no end is gone: the PC restarted after its last heartbeat, or it was ended from
    outside."""
    beat = data.get("heartbeat") or data.get("updated") or 0
    boot = boot_time()
    if boot and beat and boot > beat:
        return "the PC was restarted or shut down while it ran"
    return (
        "the process ended without a word: ended from outside (the session of the agent that started it, the Task "
        "Manager, an antivirus) or the PC lost power"
    )


# ---------- the worker side ----------


class Worker:
    """The status of the worker process: its stage, its heartbeat (a thread that also notes a sleep of the PC), its
    end — normal, an exception, a signal — always written (atexit as the last resort)."""

    def __init__(self, argv):
        import atexit, signal, threading

        self.ended = False
        data = read() or {}
        now = time.time()
        if not (data.get("argv") == argv and data.get("state") == "running"):  # a new installation, not a restart
            data = {"stage": "start", "stage_started": now, "restarts": 0}
        data.update(
            state="running",
            ok=None,
            error=None,
            pid=os.getpid(),
            started=own_start() or now,
            heartbeat=now,
            updated=now,
            argv=argv,
            python=sys.executable,
            cwd=os.getcwd(),
            log=path(LOG),
        )
        data.setdefault("restarts", 0)
        write(data)
        try:
            os.remove(path(PROGRESS))
        except OSError:
            pass
        os.environ["AX_PROGRESS"] = path(PROGRESS)  # the base install, build and embed write their progress there
        for name in ("SIGTERM", "SIGBREAK", "SIGINT", "SIGHUP"):
            sig = getattr(signal, name, None)
            if sig is not None:
                try:
                    signal.signal(sig, self._signal)
                except (OSError, ValueError):
                    pass
        atexit.register(self._atexit)
        threading.Thread(target=self._beat, daemon=True).start()

    def _beat(self):
        last = time.time()
        while not self.ended:
            time.sleep(HEARTBEAT_S)
            now = time.time()
            try:
                if now - last > SLEEP_GAP_S:
                    event(f"no heartbeat for {(now - last) / 60:.0f} min: the PC slept or hibernated (the work goes on)")
                update(heartbeat=now)
            except OSError:
                pass
            last = now

    def stage(self, name):
        if name not in dict(STAGES):
            raise ValueError(name)
        update(stage=name, stage_started=time.time())
        try:
            os.remove(path(PROGRESS))
        except OSError:
            pass

    def child_ended(self, what, code):
        """A child process (the base install) ended with code: its meaning noted."""
        if code not in (0, None):
            event(f"{what}: {why_exit(code)} (exit code {code})")

    def finish(self, ok, summary=None, error=None):
        self.ended = True
        update(state="done" if ok else "failed", ok=ok, error=error, summary=summary, ended=time.time())

    def _signal(self, signum, _frame):
        self.ended = True
        try:
            update(state="failed", ok=False, error=error("died", f"killed by the signal {signum}"), ended=time.time())
        finally:
            os._exit(128 + signum)

    def _atexit(self):
        if self.ended:
            return
        self.ended = True
        try:
            update(state="failed", ok=False, error=error("exception", "the installation ended without its summary"))
        except OSError:
            pass


def error(code, message):
    return {"code": code, "message": str(message)[:400], "fix": FIXES.get(code, FIXES["stopped"])}


# ---------- the reader side ----------


def base_share(prog):
    """The share of the base install done (0..1) from its progress file."""
    if not prog:
        return 0.0
    st, done, total = prog.get("stage") or "", prog.get("done") or 0, prog.get("total") or 0
    if st in SPANS:
        start, span = SPANS[st]
        return start + span * (min(done / total, 1.0) if total else 0.0)
    if st.startswith("base install: "):
        return BASE_AT.get(st[len("base install: ") :], 0.0)
    return 0.0


def percent(data, prog):
    """(percent of the whole installation, share of the current stage) from the status and the progress file."""
    stage = data.get("stage") or "start"
    names = [s for s, _ in STAGES]
    before = sum(w for s, w in STAGES[: names.index(stage)]) if stage in names else 0
    share = 0.0
    if stage == "base":
        share = base_share(prog)
    elif prog and prog.get("total"):
        share = min((prog.get("done") or 0) / prog["total"], 1.0)
    return min(99, int(before + dict(STAGES).get(stage, 0) * share)), share


def eta_min(data, share):
    """Minutes left of the current stage, by its pace so far; None when too early to tell."""
    began = data.get("stage_started")
    if not began or share < 0.03:
        return None
    spent = time.time() - began
    return max(1, round(spent / share * (1 - share) / 60))


ENV_PASSED = ("AX_", "PYTHON", "HF_", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "PIP_", "SSL_CERT", "REQUESTS_CA")


def spawn(python, argv, cwd):
    """The worker as a process of its own that outlives the agent (core/proc.start_outside), no window, its output
    into the log, the environment it needs in launch.json (setup/launch.py); (pid, how)."""
    from assistant_x.core import proc

    os.makedirs(folder(), exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k.upper().startswith(ENV_PASSED)}
    env.update(PYTHONUTF8="1", AX_YES="1", AX_NO_OPEN="1")  # AX_MACHINE_DIR and AX_WORKSPACE, when set, go with it
    spec = path("launch.json")
    with open(spec, "w", encoding="utf-8") as f:
        json.dump({"env": env, "log": path(LOG), "cwd": cwd or ""}, f, ensure_ascii=False, indent=1)
    return proc.start_outside([python, "-m", "assistant_x.setup.launch", spec, *argv], cwd=cwd or None)


def restart(data):
    """Start the worker again with its arguments (the installation repeats nothing done); its pid."""
    pid, how = spawn(data.get("python") or sys.executable, data.get("argv") or [], data.get("cwd"))
    return pid


def short(data, resume=True, tail=0):
    """The one line an agent reads (a dict), restarting a worker that died when resume."""
    if not data:
        return {"state": "none", "ok": None, "message": "no installation started on this PC", "poll_s": 0}
    state = data.get("state")
    if state == "running" and not alive(data.get("pid"), data.get("started")):
        why = why_dead(data)
        n = data.get("restarts", 0)
        if resume and n < MAX_RESTARTS:
            data.update(restarts=n + 1)
            write(data)
            event(f"the worker was gone ({why}): started again ({n + 1} of {MAX_RESTARTS})")
            data["pid"] = restart(data)
            data = update(pid=data["pid"], started=time.time(), heartbeat=time.time(), restarts=n + 1)
        else:
            data = update(
                state="failed",
                ok=False,
                error=error("died" if resume else "stopped", why + ("" if resume else ": run the same command again")),
            )
        state = data.get("state")
    prog = None
    try:
        with open(path(PROGRESS), encoding="utf-8") as f:
            prog = json.load(f)
    except (OSError, ValueError):
        pass
    out = {"state": state, "stage": data.get("stage"), "ok": data.get("ok")}
    if state == "running":
        pc, share = percent(data, prog)
        out.update(percent=pc, eta_min=eta_min(data, share), poll_s=POLL_S.get(data.get("stage"), DEFAULT_POLL_S))
        if prog and prog.get("stage"):
            out["step"] = prog["stage"]
        if data.get("restarts"):
            out["restarts"] = data["restarts"]
    else:
        out.update(percent=100 if state == "done" else None, poll_s=0)
        summary = data.get("summary") or {}
        if summary.get("problems"):
            out["problems"] = [p[:200] for p in summary["problems"][:5]]
        if summary.get("next"):
            out["next"] = summary["next"][:5]
        if summary.get("command"):
            out["command"] = summary["command"]
    if data.get("error"):
        out["error"] = data["error"]
    if data.get("events"):
        out["last_event"] = data["events"][-1]
    if tail:
        out["tail"] = log_tail(min(int(tail), TAIL_MAX))
    out["log"] = path(LOG)
    return out


def log_tail(n):
    try:
        with open(path(LOG), encoding="utf-8", errors="replace") as f:
            return [line.rstrip()[:300] for line in f.readlines()[-n:]]
    except OSError:
        return []


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(prog="assistant-x status")
    ap.add_argument("--json", action="store_true", help="one short JSON line")
    ap.add_argument("--tail", type=int, default=0, help=f"the last lines of the log (at most {TAIL_MAX})")
    ap.add_argument("--no-resume", action="store_true", help="do not start a worker that died again")
    a = ap.parse_args(argv)
    out = short(read(), resume=not a.no_resume, tail=a.tail)
    if a.json:
        print(json.dumps(out, ensure_ascii=False), flush=True)
    else:
        print(
            f"{out['state']}: {out.get('stage') or ''} {out.get('percent') if out.get('percent') is not None else ''}%"
            + (f", about {out['eta_min']} min left of this stage" if out.get("eta_min") else "")
        )
        if out.get("error"):
            print(f"{out['error']['code']}: {out['error']['message']}\n  {out['error']['fix']}")
        for line in out.get("tail") or []:
            print("  " + line)
        print(f"log: {out['log']}")
    return 1 if out.get("state") == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
