# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run a tool (soffice, OCR, hidden.py) with a time limit and a memory limit for it and everything it starts.
Windows: a Job Object (memory cap for the whole process tree, the tree dies with the job, no crash dialogs).
POSIX (Linux, macOS): the address space of the process capped (resource.prlimit / setrlimit RLIMIT_AS), the priority
class as a nice value, the CPUs by os.sched_setaffinity where the system has it; what it lacks is noted once, not an
error. Everywhere psutil also watches a tree that is not in a Job Object and kills it over the limit.

  rc, why = run(cmd, timeout=600, memory_mb=4096, log="x.log", env=env)
  why: None | "timeout" | "memory"
"""

import os, re, subprocess, tempfile, time

try:
    import psutil
except ImportError:  # the watch then only keeps the time limit
    psutil = None

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class _Basic(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _Io(ctypes.Structure):
        _fields_ = [
            (n, ctypes.c_uint64) for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")
        ]

    class _Extended(ctypes.Structure):
        _fields_ = [
            ("Basic", _Basic),
            ("Io", _Io),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    _k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    _k32.QueryInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    )
    _k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    _k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    _k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _k32.GetCurrentProcess.restype = wintypes.HANDLE
    EXTENDED = 9
    PROCESS_MEMORY, JOB_MEMORY, DIE_ON_EXCEPTION, KILL_ON_CLOSE = 0x100, 0x200, 0x400, 0x2000
    AFFINITY, PRIORITY_CLASS = 0x10, 0x20


NICE = {0x4000: 10, 0x40: 19}  # below normal, idle: the nice value of a priority class on POSIX
_noted = set()


def note(what):
    """A limit this system cannot keep: said once on stderr, the work goes on."""
    import sys

    if what not in _noted:
        _noted.add(what)
        print(f"[limits] {what}", file=sys.stderr, flush=True)


def posix_limits(pid, memory_bytes=0, priority=0, cpu_mask=0):
    """POSIX: the memory cap (RLIMIT_AS: resource.prlimit for another process on Linux, setrlimit for this one), the
    nice value of a priority class and the CPUs of a process. Returns what was set; the rest is noted."""
    done = []
    try:
        import resource
    except ImportError:
        resource = None
    if memory_bytes:
        try:
            if resource and hasattr(resource, "prlimit"):
                resource.prlimit(pid, resource.RLIMIT_AS, (memory_bytes, memory_bytes))
                done.append("memory")
            elif resource and pid == os.getpid():
                resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
                done.append("memory")
            else:
                note("no memory cap for another process here (no resource.prlimit): psutil watches the tree")
        except (OSError, ValueError) as e:
            note(f"the memory cap was refused ({e}): psutil watches the tree")
    nice = NICE.get(priority)
    if nice:
        try:
            os.setpriority(os.PRIO_PROCESS, pid, max(nice, os.getpriority(os.PRIO_PROCESS, pid)))
            done.append("priority")
        except (AttributeError, OSError) as e:
            note(f"the priority was not lowered ({e})")
    if cpu_mask:
        if hasattr(os, "sched_setaffinity"):
            try:
                os.sched_setaffinity(pid, [i for i in range(64) if cpu_mask >> i & 1])
                done.append("cpus")
            except OSError as e:
                note(f"the CPUs were not set ({e})")
        else:
            note("no CPU affinity on this system (os.sched_setaffinity)")
    return done


class Job:
    """Windows Job Object; job=None elsewhere or when Windows refuses (then psutil watches); on POSIX assign_pid sets
    the limits of one process (posix_limits).
    priority (a *_PRIORITY_CLASS) and cpu_mask hold for every process of the tree, soffice and tesseract included."""

    def __init__(self, memory_mb, per_process=False, priority=0, cpu_mask=0):
        self.handle, self.limit = None, memory_mb * 1024 * 1024 if memory_mb else 0
        self.priority, self.cpu_mask = priority, cpu_mask
        if os.name != "nt":
            return
        h = _k32.CreateJobObjectW(None, None)
        if not h:
            return
        info = _Extended()
        info.Basic.LimitFlags = KILL_ON_CLOSE | DIE_ON_EXCEPTION
        if self.limit:
            info.Basic.LimitFlags |= PROCESS_MEMORY if per_process else JOB_MEMORY
        self.flags, self.priority, self.cpu_mask = info.Basic.LimitFlags, priority, cpu_mask
        if not self._set(h, priority, cpu_mask):
            _k32.CloseHandle(h)
            return
        self.handle = h

    def _set(self, h, priority, cpu_mask):
        info = _Extended()
        info.Basic.LimitFlags = self.flags
        info.ProcessMemoryLimit = info.JobMemoryLimit = self.limit
        if priority:
            info.Basic.LimitFlags |= PRIORITY_CLASS
            info.Basic.PriorityClass = priority
        if cpu_mask:
            info.Basic.LimitFlags |= AFFINITY
            info.Basic.Affinity = cpu_mask
        return bool(_k32.SetInformationJobObject(h, EXTENDED, ctypes.byref(info), ctypes.sizeof(info)))

    def set_memory(self, memory_mb):
        """A new memory cap for the running tree (a thick PDF gets more for its task)."""
        if not self.handle or not memory_mb:
            return False
        old, self.limit = self.limit, memory_mb * 1024 * 1024
        if self._set(self.handle, self.priority, self.cpu_mask):
            return True
        self.limit = old
        return False

    def update(self, priority=None, cpu_mask=None):
        """New priority class and CPUs for the running tree (the regulator: a paused worker goes to IDLE)."""
        if not self.handle:
            return False
        p = self.priority if priority is None else priority
        m = self.cpu_mask if cpu_mask is None else cpu_mask
        if (p, m) == (self.priority, self.cpu_mask):
            return True
        ok = self._set(self.handle, p, m)
        if ok:
            self.priority, self.cpu_mask = p, m
        return ok

    def cpu_seconds(self):
        """CPU time of every process that has been in the job (JobObjectBasicAccountingInformation)."""
        if not self.handle:
            return 0.0
        acc = (ctypes.c_int64 * 2)()  # TotalUserTime, TotalKernelTime: the first fields, in 100 ns
        buf = ctypes.create_string_buffer(48)  # the exact size of the structure, or ERROR_BAD_LENGTH
        if not _k32.QueryInformationJobObject(self.handle, 1, buf, 48, None):
            return 0.0
        ctypes.memmove(acc, buf, 16)
        return (acc[0] + acc[1]) / 1e7

    def assign(self, process_handle):
        return bool(self.handle) and bool(_k32.AssignProcessToJobObject(self.handle, process_handle))

    def assign_pid(self, pid):
        """POSIX: the memory cap, the priority and the CPUs of the job for one process (its children inherit them)."""
        return posix_limits(pid, self.limit, self.priority, self.cpu_mask) if os.name != "nt" else []

    def peak(self):
        if not self.handle:
            return 0
        info = _Extended()
        _k32.QueryInformationJobObject(self.handle, EXTENDED, ctypes.byref(info), ctypes.sizeof(info), None)
        return max(info.PeakJobMemoryUsed, info.PeakProcessMemoryUsed)

    def kill(self):
        if self.handle:
            _k32.TerminateJobObject(self.handle, 1)

    def close(self):
        if self.handle:
            _k32.CloseHandle(self.handle)  # kills what is left of the tree
            self.handle = None


def limit_this_process(memory_mb, priority=0, cpu_mask=0):
    """Memory cap for the calling process (a pool worker): past it allocations fail with MemoryError,
    which the task catches, instead of the PC swapping. The job lives as long as the process."""
    if not (memory_mb or priority or cpu_mask):
        return None
    if os.name != "nt":
        posix_limits(os.getpid(), memory_mb * 1024 * 1024 if memory_mb else 0, priority, cpu_mask)
        return None
    job = Job(memory_mb, per_process=True, priority=priority, cpu_mask=cpu_mask)
    if job.handle and _k32.AssignProcessToJobObject(job.handle, _k32.GetCurrentProcess()):
        return job
    return None


def _tree(p):
    try:
        return [p] + p.children(recursive=True)
    except psutil.Error:
        return []


def _rss(procs):
    total = 0
    for q in procs:
        try:
            total += q.memory_info().rss
        except psutil.Error:
            pass
    return total


def _kill(procs):
    for q in procs:
        try:
            q.kill()
        except psutil.Error:
            pass


# POSIX has no peak of a job: a tool that failed under the address space cap says so in its output (Python, the C
# library, C++), or the kernel killed it (SIGKILL, the OOM killer)
MEMORY_RX = re.compile(rb"MemoryError|Cannot allocate memory|std::bad_alloc|[Oo]ut of memory")


def says_memory(rc, output):
    """POSIX: a failed tool ran out of the memory cap (its output names it, or it was killed by SIGKILL)."""
    return rc != 0 and (rc == -9 or bool(MEMORY_RX.search(output or b"")))


def _tail(f, start=0, size=65536):
    """The last bytes of an open binary file written from start on."""
    try:
        f.flush()
        end = f.seek(0, os.SEEK_END)
        f.seek(max(start, end - size))
        return f.read()
    except (OSError, ValueError):
        return b""


def run(cmd, timeout=None, memory_mb=0, log=None, env=None, cwd=None, low_priority=False):
    """(return code, None | "timeout" | "memory"). Output goes to the log file (appended) or is dropped.
    The priority and CPUs come from AX_PRIORITY / AX_AFFINITY_MASK of env (balance.env), low_priority: at least below normal."""
    from assistant_x.intake import balance

    out = open(log, "a", encoding="utf-8", errors="replace") if log else subprocess.DEVNULL
    capped = os.name != "nt" and memory_mb  # POSIX: the output tells a failure of the cap (says_memory)
    start = os.path.getsize(log) if log and capped else 0
    err = tempfile.TemporaryFile() if capped and not log else None
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    cls, cpu_mask = balance.from_env(env)
    if low_priority and cls in (0, balance.PRIORITIES["normal"]):  # a long background pass must not slow the PC down
        cls = balance.PRIORITIES["below_normal"]
    flags |= balance.creation_flags(cls)
    why = None
    try:
        p = subprocess.Popen(
            [str(c) for c in cmd],
            stdout=out,
            stderr=subprocess.STDOUT if log else (err or subprocess.DEVNULL),
            stdin=subprocess.DEVNULL,
            env=env,
            cwd=cwd,
            creationflags=flags,
        )
        if cls and cls != balance.PRIORITIES["normal"]:
            balance.low_io(p.pid)
        job = Job(memory_mb, priority=cls if cls != balance.PRIORITIES["normal"] else 0, cpu_mask=cpu_mask)
        jobbed = job.assign(int(p._handle)) if os.name == "nt" else False
        if os.name != "nt":
            job.assign_pid(p.pid)  # POSIX: the memory cap, the nice value and the CPUs of the tool
        if not jobbed and cpu_mask and os.name == "nt":
            balance.set_process(int(p._handle), 0, cpu_mask)
        watch = psutil.Process(p.pid) if psutil else None
        limit, last, spent = memory_mb * 1024 * 1024, time.time(), 0.0
        while True:
            try:
                rc = p.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                pass
            now = time.time()
            spent += min(now - last, 2.0)  # time the tool could work: a pause of the worker by the regulator is not counted
            last = now
            if timeout and spent > timeout:
                why = "timeout"
            elif limit and not jobbed and watch and _rss(_tree(watch)) > limit:
                why = "memory"
            if why:
                job.kill()
                if watch:
                    _kill(_tree(watch))
                p.kill()
                rc = p.wait()
                break
        if not why and jobbed and limit and rc != 0 and job.peak() >= 0.97 * limit:
            why = "memory"  # the tree hit the cap: allocations failed and the tool gave up
        if not why and capped and rc != 0:
            if log:
                out.flush()
                with open(log, "rb") as f:
                    output = _tail(f, start)
            else:
                output = _tail(err)
            why = "memory" if says_memory(rc, output) else None
        job.close()
        return rc, why
    finally:
        if err:
            err.close()
        if log:
            if why:
                out.write(f"\n[intake] stopped: {why}\n")
            out.close()
