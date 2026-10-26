# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""Locks, all in one place.

The machine lock: one heavy task on the PC at a time (intake run / redo / build / apply, embed, eval, the
whole-library hidden_scan), across every workspace. The file is %LOCALAPPDATA%\AssistantX\heavy.lock
(AX_HEAVY_LOCK_FILE overrides it), held with msvcrt.locking (fcntl elsewhere): Windows frees it when the owner dies, so
a switched-off PC leaves no stale lock. The file holds the PID, the task and its start; heavy.log beside it is the
journal of who took and gave it back.

    with lock.heavy_task("intake run", wait=False):   # busy: prints who holds it, exits with code 3
        ...

A process started by the holder (AX_HEAVY_LOCK in its environment) passes through: apply may run embed.

    python -m assistant_x.core.lock                              who holds the lock
    python -m assistant_x.core.lock [--wait] "eval" -- command   a command under the lock

The folder lock: one intake at a time in a workspace, a file made with O_EXCL in the work folder (intake.lock) for
run, requeue, build and apply. It holds the PID and the start time of its owner; a lock left by a process that is no
longer alive (the PC was switched off, the window closed) is removed by the next start.

    with lock.hold(cfg.work, "run"):
        ...

The exclusive file lock: exclusive(path) holds a byte lock for the life of the process (the MCP server that loads
the models).
"""

import contextlib, datetime, json, os, subprocess, sys, time
from pathlib import Path

from assistant_x.core import env, workspace

BUSY = 3  # exit code when the lock is held by another task
SPOT = 1 << 20  # the byte that is locked: past the text, so the text stays readable
ENV = "AX_HEAVY_LOCK"
NAME = "intake.lock"


class Busy(SystemExit):
    """Another heavy task holds the machine lock: the command stops with code 3."""

    def __init__(self, text):
        super().__init__(BUSY)
        self.text = text


class FolderBusy(SystemExit):
    """Another intake holds the folder lock: the command stops with this message."""


def lock_path():
    return Path(env.get("HEAVY_LOCK_FILE") or workspace.machine_dir() / "heavy.lock")


def server_lock_path():
    """The models lock of the search server (server/mcp_server.py): held while Claude Desktop or Claude Code runs it.
    AX_MCP_LOCK_FILE overrides it (the tests)."""
    return str(env.get("MCP_LOCK_FILE") or workspace.machine_dir() / "mcp_server.lock")


def _lock(f):
    try:
        if os.name == "nt":
            import msvcrt

            f.seek(SPOT)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(f):
    with contextlib.suppress(OSError):
        if os.name == "nt":
            import msvcrt

            f.seek(SPOT)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(f, fcntl.LOCK_UN)


def holder(path=None):
    """{pid, task, time, token} of the holder, or None when the lock is free."""
    path = Path(path or lock_path())
    if not path.exists():
        return None
    with open(path, "a+b") as f:
        if _lock(f):
            _unlock(f)
            return None
        f.seek(0)
        try:
            return json.loads(f.read(4096).decode("utf-8"))
        except ValueError:
            return {"task": "?"}


def who(h):
    return f"{h.get('task', '?')} (process {h.get('pid', '?')}, since {h.get('time', '?')})"


def log(path, text):
    with contextlib.suppress(OSError):
        with open(Path(path).with_name("heavy.log"), "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')}\t{os.getpid()}\t{text}\n")


@contextlib.contextmanager
def heavy_task(task, wait=False, poll=10, path=None, say=None):
    """Hold the machine lock for the block. wait: wait for the holder to finish; otherwise Busy (code 3)."""
    say = say or (lambda s: print(s, file=sys.stderr, flush=True))
    path = Path(path or lock_path())
    mine = env.get("HEAVY_LOCK")
    if mine:
        h = holder(path)
        if h and h.get("token") == mine:  # started by the holder: its lock covers this task
            yield path
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+b")
    told = False
    while not _lock(f):
        f.seek(0)
        try:
            h = json.loads(f.read(4096).decode("utf-8"))
        except (ValueError, OSError):
            h = {}
        if not wait:
            f.close()
            log(path, f"busy\t{task}\theld by {who(h)}")
            text = f'A heavy task is running already: {who(h)}. "{task}" was not started; wait for it or start with --wait'
            say(text)
            raise Busy(text)
        if not told:
            say(f"Waiting for the heavy task to end: {who(h)}…")
            log(path, f"waits\t{task}\theld by {who(h)}")
            told = True
        time.sleep(poll)
    now = datetime.datetime.now()
    token = f"{os.getpid()}:{now.timestamp():.3f}"
    me = {"pid": os.getpid(), "task": task, "time": now.isoformat(timespec="seconds"), "token": token}
    f.seek(0)
    f.truncate()
    f.write(json.dumps(me, ensure_ascii=False).encode("utf-8"))
    f.flush()
    log(path, f"took\t{task}")
    old = os.environ.get(ENV)
    os.environ[ENV] = token
    t0 = time.time()
    try:
        yield path
    finally:
        if old is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = old
        with contextlib.suppress(OSError):
            f.seek(0)
            f.truncate()
            f.flush()
        _unlock(f)
        f.close()
        log(path, f"released\t{task}\t{time.time() - t0:.0f} s")


def exclusive(path):
    """The open file when this process now holds a byte lock on path, None when another process holds it.
    Keep the file open for as long as the lock is needed; closing it (or the end of the process) frees it."""
    f = open(path, "a+b")
    if _lock(f):
        return f
    f.close()
    return None


def hold_for_process(task, wait=False):
    """The machine lock until this process ends. Busy: says who holds it and exits with code 3 (wait: waits)."""
    import atexit

    cm = heavy_task(task, wait=wait)
    cm.__enter__()
    atexit.register(cm.__exit__, None, None, None)


def alive(pid, since=None):
    """Is the process with this PID running (and started no later than the lock, when psutil knows its start)?"""
    try:
        import psutil
    except ImportError:
        psutil = None
    if psutil:
        try:
            p = psutil.Process(pid)
            if since and p.create_time() > since + 2:  # the PID was taken by a newer process
                return False
            return p.status() != psutil.STATUS_ZOMBIE
        except psutil.Error:
            return False
    if os.name == "nt":
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5  # access denied: the process exists
        code = ctypes.c_ulong()
        try:
            return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def acquire(folder, what):
    """Make the lock or raise FolderBusy; a dead owner's lock is removed first. Returns the lock path."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, NAME)
    now = datetime.datetime.now()
    me = {"pid": os.getpid(), "time": now.isoformat(timespec="seconds"), "ts": now.timestamp(), "command": what}
    for _ in range(3):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            owner = read(path)
            if owner is None:  # being written right now, or broken: broken only when it stays so
                import time

                time.sleep(0.5)
                owner = read(path)
            if owner and owner.get("pid") and alive(int(owner["pid"]), owner.get("ts")):
                raise FolderBusy(
                    f"An intake is running already: {owner.get('command', '?')} (process {owner['pid']}, since "
                    f"{owner.get('time', '?')}). Wait until it ends; if there is no such process, delete {path}"
                )
            with contextlib.suppress(FileNotFoundError):
                os.remove(path)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(me, f, ensure_ascii=False)
        return path
    raise FolderBusy(f"Could not take the lock {path}: another process creates it again and again")


def release(path):
    owner = read(path)
    if owner is None or owner.get("pid") == os.getpid():
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)


@contextlib.contextmanager
def hold(folder, what):
    path = acquire(folder, what)
    try:
        yield path
    finally:
        release(path)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv:
        h = holder()
        print(f"Held by: {who(h)}" if h else f"Free ({lock_path()})")
        return BUSY if h else 0
    k = argv.index("--")
    opts, cmd = argv[:k], argv[k + 1 :]
    if not cmd:
        print("lock: no command after --", file=sys.stderr)
        return 2
    wait = "--wait" in opts
    names = [o for o in opts if o != "--wait"]
    task = names[0] if names else Path(cmd[0]).name
    try:
        with heavy_task(task, wait=wait):
            try:
                return subprocess.call(cmd)
            except OSError as e:  # no such program, not executable: said in one line, the code of a shell
                print(f"cannot start {cmd[0]}: {e.strerror or e}", file=sys.stderr)
                return 127
    except Busy:
        return BUSY


if __name__ == "__main__":
    sys.exit(main())
