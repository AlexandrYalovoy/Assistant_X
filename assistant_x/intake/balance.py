# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Share of the PC a heavy task takes, decided by measurements on any PC, not by its model of CPU.
Intake and search work at normal priority on every core can hang a PC.

Always: below normal priority and low I/O (the OS keeps the user's programs first), a CPU and memory reserve.
Two states, re-measured every few seconds by Regulator (intake_pool runs it):
  "free"           no input for idle_minutes and no other heavy load: total CPU kept in the corridor around
                   cpu_share_idle (75 %), not 100 %: the PC stays cool and background programs keep their room
  "at the computer" the user is working: total CPU around cpu_share_active (50 %); on a hybrid CPU the workers are
                   moved to the efficiency cores when there are enough of them
Limits on any PC: >= 2 logical CPUs and >= max(4 GB, 15 % of RAM) left free, disk <= 80 %, CPU/GPU temperature
below temp_max_c (85; back up only under temp_cool_c, 75; without a sensor a CPU clock drop under load counts as
heat). Emergencies: memory < 1.5 GB, CPU > 90 % or disk > 90 % for 15 s — half the workers stop; memory < 1 GB — all.

assistant_x.toml: profile "auto" (default) | "day" (always "at the computer") | "weak" (1-2 workers, 1 thread, always
"at the computer") | "night" (always "free"); workers = upper limit (0: by the PC); threads, priority, affinity
override the measured choice.

  probe()                      what the PC has: CPUs (and E-cores if hybrid), RAM, video card
  budget(hw, opts)             workers, threads per worker, how many work in each state
  Regulator(budget, opts).step(sample, now) -> active workers, with the reasons of a change
  Sensors().sample(ours)       one measurement
  apply_self / env / from_env / creation_flags / limit_threads / low_io / set_process   process tools
"""

import os, shutil, subprocess, sys, time

from assistant_x.core.config import INTAKE

PRIORITIES = {"normal": 0x20, "below_normal": 0x4000, "idle": 0x40}  # *_PRIORITY_CLASS
DEFAULT_PRIORITY, DEFAULT_AFFINITY = INTAKE["priority"], INTAKE["affinity"]
THREAD_VARS = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS", "ORT_NUM_THREADS")
THREADS = {**{k: "1" for k in THREAD_VARS}, "OMP_THREAD_LIMIT": "1"}  # OMP_THREAD_LIMIT: one per Tesseract
PROFILES = ("auto", "day", "weak", "night")
# the options of [intake] documented in docs/INTAKE.md take their defaults from core/config.INTAKE; the rest are the
# regulator's own
OPTIONS = {
    **{k: INTAKE[k] for k in ("profile", "idle_minutes", "cpu_share_idle", "cpu_share_active", "temp_max_c", "temp_cool_c")},
    "corridor_down": 0.10,
    "corridor_up": 0.05,
    "reserve_cpus": 2,
    "reserve_gb": 4,
    "reserve_ram_share": 0.15,
    "disk_max": 80,
    "threads": 0,
    "regulate": True,
}
FREE, ACTIVE = "free", "at the computer"
_nt = os.name == "nt"


def priority_class(name):
    name = (name or DEFAULT_PRIORITY).lower().replace("-", "_")
    if name not in PRIORITIES:
        raise ValueError(f"priority {name!r}, one of these is needed: {', '.join(PRIORITIES)}")
    return PRIORITIES[name]


# ---------- what the PC has ----------


def _cores():
    """[(efficiency class, logical CPU mask)] of the cores of group 0 (Windows), or None."""
    if not _nt:
        return None
    import ctypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    size = ctypes.c_ulong(0)
    k32.GetLogicalProcessorInformationEx(0, None, ctypes.byref(size))  # RelationProcessorCore: size first
    if not size.value:
        return None
    buf = ctypes.create_string_buffer(size.value)
    if not k32.GetLogicalProcessorInformationEx(0, buf, ctypes.byref(size)):
        return None
    raw, at, cores = buf.raw, 0, []
    while at < size.value:
        rec = int.from_bytes(raw[at + 4 : at + 8], "little")
        eff = raw[at + 9]  # PROCESSOR_RELATIONSHIP.EfficiencyClass: higher is faster
        mask, group = int.from_bytes(raw[at + 32 : at + 40], "little"), int.from_bytes(raw[at + 40 : at + 42], "little")
        if group == 0:
            cores.append((eff, mask))
        at += rec or size.value
    return cores


def ecores():
    """Logical CPU numbers of the efficiency cores, or None on a CPU with one kind of core / not Windows."""
    cores = _cores()
    classes = {e for e, _ in cores or []}
    if len(classes) < 2:
        return None
    low = min(classes)
    return sorted(i for e, m in cores if e == low for i in range(64) if m >> i & 1)


def gpu():
    """(name, free GB, total GB, temperature °C or None) of the first NVIDIA card, or None."""
    rows = _smi("--query-gpu=name,memory.free,memory.total,temperature.gpu")
    if not rows:
        return None
    name, free, total, temp = [x.strip() for x in rows[0].rsplit(",", 3)]
    return name, float(free) / 1024, float(total) / 1024, float(temp) if temp.replace(".", "").isdigit() else None


def _smi(query):
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        r = subprocess.run(
            [exe, query, "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=0x08000000 if _nt else 0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return [ln for ln in r.stdout.splitlines() if ln.strip()] if r.returncode == 0 else None


def probe():
    """CPUs, RAM and video card of this PC: the budget is computed from them, nothing is assumed."""
    import psutil

    vm = psutil.virtual_memory()
    cores = _cores()
    logical = os.cpu_count() or 1
    return {
        "logical": logical,
        "physical": len(cores) if cores else (psutil.cpu_count(logical=False) or logical),
        "ecores": ecores(),
        "ram_gb": vm.total / 2**30,
        "avail_gb": vm.available / 2**30,
        "gpu": gpu(),
    }


# ---------- how much of it ----------


def options(cfg):
    """The balance settings of assistant_x.toml with their defaults."""
    o = {k: cfg.get(k, v) if cfg.get(k) is not None else v for k, v in OPTIONS.items()}
    if o["profile"] not in PROFILES:
        raise ValueError(f"profile {o['profile']!r}, one of these is needed: {', '.join(PROFILES)}")
    return o


def reserve_gb(hw, o):
    return max(float(o["reserve_gb"]), float(o["reserve_ram_share"]) * hw["ram_gb"])


def budget(hw, o, cap=0, worker_mb=INTAKE["worker_memory_mb"]):
    """{"workers": pool size, "threads": per worker, "free": workers when "free", "active": workers "at the computer"}.
    cap: workers of assistant_x.toml as an upper limit (0: none)."""
    logical = hw["logical"]
    usable = max(1, logical - int(o["reserve_cpus"]))
    # worker_memory_mb is a ceiling a worker rarely reaches: half of it per worker, the regulator watches the rest live
    by_mem = max(1, int((hw["avail_gb"] - reserve_gb(hw, o)) * 1024 // (worker_mb / 2))) if worker_mb else usable
    if o["profile"] == "weak":
        n = max(1, min(2, by_mem, cap or 2))
        return {"workers": n, "threads": 1, "free": n, "active": n}
    n = max(1, min(hw["physical"] - 2 if hw["physical"] > 3 else 1, by_mem, usable, cap or usable))
    threads = int(o["threads"]) or max(1, usable // n)
    free = max(1, min(n, round(logical * float(o["cpu_share_idle"]) / threads)))
    active = max(1, min(free, round(logical * float(o["cpu_share_active"]) / threads)))
    return {"workers": free, "threads": threads, "free": free, "active": active}


class Regulator:
    """Active workers from measurements, with hysteresis. step() takes a sample:
    {"cpu": total %, "ours": % of the PC our processes use, "disk": %, "avail_gb", "idle_s": since the last input,
     "temp": °C or None, "throttled": bool}; returns (active workers, state, reasons or [] when nothing changed)."""

    DOWN_EVERY, UP_EVERY, SUSTAIN = 8, 45, 15  # seconds: between two removals, between two additions, of an emergency

    def __init__(self, b, o, hw):
        self.b, self.o, self.hw = b, o, hw
        self.n = b["active"] if o["profile"] != "night" else b["free"]
        self.state = None
        self.hot = False
        self.since = {}  # emergency condition -> first time seen
        self.last_down = self.last_up = -1e9

    def mode(self, s):
        if self.o["profile"] == "night":
            return FREE
        if self.o["profile"] in ("weak", "day"):
            return ACTIVE
        other = max(0.0, s["cpu"] - s.get("ours", 0))
        idle = s.get("idle_s", 0) >= float(self.o["idle_minutes"]) * 60
        return FREE if idle and other < 25 else ACTIVE

    def _held(self, key, cond, now):
        if not cond:
            self.since.pop(key, None)
            return False
        self.since.setdefault(key, now)
        return now - self.since[key] >= self.SUSTAIN

    def step(self, s, now=None):
        now = time.time() if now is None else now
        o, b, old_n, old_state = self.o, self.b, self.n, self.state
        state = self.mode(s)
        ceiling = b["free"] if state == FREE else b["active"]
        share = float(o["cpu_share_idle"] if state == FREE else o["cpu_share_active"]) * 100
        lo, hi = share - float(o["corridor_down"]) * 100, share + float(o["corridor_up"]) * 100  # 65-80 % when "free"
        why, n = [], self.n
        if state != old_state:
            why.append(f"state: {state}")
        temp = s.get("temp")
        if temp is not None and temp >= float(o["temp_max_c"]) or s.get("throttled"):
            self.hot = True
        elif self.hot and (temp is None or temp < float(o["temp_cool_c"])) and not s.get("throttled"):
            self.hot = False
            why.append("cooled down")
        mem_floor = reserve_gb(self.hw, o)
        if s["avail_gb"] < 1:
            n = 0
            why.append(f"memory {s['avail_gb']:.1f} GB < 1 GB: all paused")
        elif (
            s["avail_gb"] < 1.5
            or self._held("cpu90", s["cpu"] > 90, now)
            or self._held("disk90", s.get("disk", 0) > 90, now)
        ):
            if n > 0 and now - self.last_down >= self.DOWN_EVERY:
                n = n // 2
                why.append(
                    f"emergency: CPU {s['cpu']:.0f} %, disk {s.get('disk', 0):.0f} %, memory {s['avail_gb']:.1f} GB — half paused"
                )
        else:
            if n > ceiling:
                n = ceiling
                why.append(f'budget "{state}": {ceiling}')
            elif n == 0:
                n = 1
                why.append("memory freed")
            if now - self.last_down >= self.DOWN_EVERY and n > 1:
                if self.hot:
                    n -= 1
                    why.append(
                        f"heat {temp if temp is not None else '?'} °C"
                        + (" (the CPU frequency dropped)" if s.get("throttled") else "")
                    )
                elif s["cpu"] > hi:
                    n -= 1
                    why.append(f"CPU {s['cpu']:.0f} % > {hi:.0f} %")
                elif s.get("disk", 0) > float(o["disk_max"]):
                    n -= 1
                    why.append(f"disk {s['disk']:.0f} % > {o['disk_max']} %")
                elif s["avail_gb"] < mem_floor:
                    n -= 1
                    why.append(f"memory {s['avail_gb']:.1f} GB < the reserve {mem_floor:.1f} GB")
            up_ok = (
                not self.hot
                and s["cpu"] < lo
                and s.get("disk", 0) < float(o["disk_max"])
                and s["avail_gb"] > mem_floor + 1
                and n < ceiling
                and now - self.last_up >= self.UP_EVERY
            )
            if up_ok and n == old_n:
                n += 1
                why.append(f"CPU {s['cpu']:.0f} % < {lo:.0f} %: one worker more")
        self.state = state
        if n < old_n:
            self.last_down = now
        elif n > old_n:
            self.last_up = now
        self.n = n
        return n, state, why if (n != old_n or state != old_state or "cooled down" in why) else []


# ---------- measurements ----------


class _Pdh:
    """Two Windows counters by their English names (any language of Windows): % Disk Time and % Processor
    Performance (the clock against its base: a drop under load means the CPU is throttling)."""

    PATHS = (r"\PhysicalDisk(_Total)\% Disk Time", r"\Processor Information(_Total)\% Processor Performance")

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ct = ctypes
        self.pdh = ctypes.WinDLL("pdh")
        self.q = wintypes.HANDLE()
        self.c = []
        if self.pdh.PdhOpenQueryW(None, None, ctypes.byref(self.q)) != 0:
            raise OSError("PdhOpenQuery")
        for p in self.PATHS:
            h = wintypes.HANDLE()
            self.c.append(h if self.pdh.PdhAddEnglishCounterW(self.q, p, None, ctypes.byref(h)) == 0 else None)
        self.pdh.PdhCollectQueryData(self.q)

    def read(self):
        ct = self.ct

        class Value(ct.Structure):
            _fields_ = [("CStatus", ct.c_ulong), ("doubleValue", ct.c_double)]

        self.pdh.PdhCollectQueryData(self.q)
        out = []
        for h in self.c:
            v = Value()
            ok = h and self.pdh.PdhGetFormattedCounterValue(h, 0x200, None, ct.byref(v)) == 0  # PDH_FMT_DOUBLE
            out.append(v.doubleValue if ok else None)
        return out


CPU_TEMP_PS = (
    "$ErrorActionPreference='SilentlyContinue';"
    "foreach($ns in 'root/LibreHardwareMonitor','root/OpenHardwareMonitor'){"
    "$t=Get-CimInstance -Namespace $ns -ClassName Sensor|?{$_.SensorType -eq 'Temperature' -and $_.Name -match 'Package|Tctl|Core'}|"
    "Measure-Object Value -Maximum; if($t.Maximum){[int]$t.Maximum; exit}};"
    "$z=Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature|Measure-Object CurrentTemperature -Maximum;"
    "if($z.Maximum){[int]($z.Maximum/10-273.15)}"
)


def idle_seconds():
    """Seconds since the last keyboard or mouse input of this session (GetLastInputInfo); 0 when unknown."""
    if not _nt:
        return 0.0
    import ctypes

    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    li = LastInput(ctypes.sizeof(LastInput), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
        return 0.0
    return ((ctypes.windll.kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000.0


class Sensors:
    """One measurement of the PC; temperatures are read every TEMP_EVERY seconds (a small process each time)."""

    TEMP_EVERY = 30

    def __init__(self, has_gpu=None):
        import psutil

        self.ps = psutil
        self.times = psutil.cpu_times()  # own deltas: psutil keeps cpu_percent(None) per thread, the first call there is 0
        try:
            self.pdh = _Pdh() if _nt else None
        except Exception:  # noqa: BLE001 — no counters: disk and throttling stay unknown
            self.pdh = None
        self.has_gpu = shutil.which("nvidia-smi") is not None if has_gpu is None else has_gpu
        self.cpu_temp_ok = _nt  # turned off after the first empty answer
        self.t_temp, self.temp = -1e9, None

    def temps(self):
        now = time.time()
        if now - self.t_temp < self.TEMP_EVERY:
            return self.temp
        self.t_temp, vals = now, []
        if self.cpu_temp_ok:
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", CPU_TEMP_PS],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    creationflags=0x08000000 | 0x4000,
                )
                v = r.stdout.strip()
                if v.lstrip("-").isdigit() and 0 < int(v) < 130:
                    vals.append(float(v))
                else:
                    self.cpu_temp_ok = False
            except (OSError, subprocess.SubprocessError):
                self.cpu_temp_ok = False
        if self.has_gpu:
            g = gpu()
            if g and g[3] is not None:
                vals.append(g[3])
        self.temp = max(vals) if vals else None
        return self.temp

    def cpu(self):
        """Total CPU busy, %, since the previous call."""
        now = self.ps.cpu_times()
        total = sum(now) - sum(self.times)
        idle = now.idle - self.times.idle
        self.times = now
        return max(0.0, min(100.0, 100.0 * (1 - idle / total))) if total > 0 else 0.0

    def sample(self, ours=0.0):
        cpu = self.cpu()
        disk, perf = self.pdh.read() if self.pdh else (None, None)
        return {
            "cpu": cpu,
            "ours": ours,
            "disk": min(100.0, disk or 0.0),
            "avail_gb": self.ps.virtual_memory().available / 2**30,
            "idle_s": idle_seconds(),
            "temp": self.temps(),
            "throttled": bool(perf is not None and cpu > 60 and perf < 60),
            "perf": perf,
        }


# ---------- process tools ----------


def cpus(affinity):
    """CPU numbers for an affinity setting; None means all of them ("auto" leaves it to the regulator)."""
    n = os.cpu_count() or 1
    if affinity in (None, "", "all", "auto"):
        return None
    if affinity == "ecores":
        return ecores()
    if isinstance(affinity, str):
        affinity = [int(x) for x in affinity.replace(";", ",").split(",") if x.strip()]
    chosen = sorted({int(x) for x in affinity if 0 <= int(x) < min(n, 64)})
    if not chosen:
        raise ValueError(f"affinity {affinity!r}: no such CPUs (there are {n})")
    return chosen


def mask(affinity):
    c = cpus(affinity)
    return sum(1 << i for i in c) if c else 0


def env(priority=None, affinity=None, threads=1):
    t = str(max(1, int(threads or 1)))
    return {
        **{k: t for k in THREAD_VARS},
        "OMP_THREAD_LIMIT": "1",
        "AX_ONNX_THREADS": t,
        "AX_PRIORITY": (priority or DEFAULT_PRIORITY),
        "AX_AFFINITY_MASK": str(mask(affinity)),
    }


def from_env(environ=None):
    """(priority class or 0, CPU mask or 0) given to a worker by env(); 0, 0 when none was given."""
    e = os.environ if environ is None else environ
    try:
        cls = priority_class(e["AX_PRIORITY"]) if e.get("AX_PRIORITY") else 0
    except ValueError:
        cls = 0
    return cls, int(e.get("AX_AFFINITY_MASK") or 0)


def creation_flags(cls):
    """Priority flag for subprocess.Popen: a *_PRIORITY_CLASS value goes into creationflags as it is."""
    return cls if _nt and cls and cls != PRIORITIES["normal"] else 0


def limit_threads(n=None):
    """Thread caps of this process: variables for libraries not imported yet, torch if it is already in."""
    n = int(n or os.environ.get("AX_ONNX_THREADS") or 1)
    os.environ.update({k: str(n) for k in THREAD_VARS}, OMP_THREAD_LIMIT="1")
    torch = sys.modules.get("torch")
    if torch is not None:
        try:
            torch.set_num_threads(n)
        except Exception:  # noqa: BLE001 — a torch that refuses keeps its threads
            pass


def low_io(pid=None):
    """Low I/O priority for a process (this one by default): disk work of a background task yields to the user."""
    try:
        import psutil

        psutil.Process(pid).ionice(psutil.IOPRIO_LOW)
        return True
    except Exception:  # noqa: BLE001 — no psutil, not Windows, the process is gone: it keeps normal I/O
        pass
    if pid is None and _nt:
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        return bool(k32.SetPriorityClass(ctypes.c_void_p(k32.GetCurrentProcess()), 0x00100000))  # BACKGROUND_BEGIN
    return False


def set_process(handle, cls=0, cpu_mask=0):
    """Priority class and CPUs of a process by its Windows handle."""
    if not _nt:
        return
    import ctypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    h = ctypes.c_void_p(int(handle))
    if cls:
        k32.SetPriorityClass(h, cls)
    if cpu_mask:
        k32.SetProcessAffinityMask(h, ctypes.c_size_t(cpu_mask))


def apply_self(priority=None, affinity=None, threads=1):
    """This process and everything it starts: priority class, CPUs (both inherited by children), low I/O, threads."""
    cls, m = priority_class(priority), mask(affinity)
    os.environ.update(env(priority, affinity, threads))
    limit_threads(threads)
    if _nt:
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        set_process(k32.GetCurrentProcess(), 0 if cls == PRIORITIES["normal"] else cls, m)  # "normal" lowers nothing
    elif hasattr(os, "sched_setaffinity") and m:
        os.sched_setaffinity(0, cpus(affinity))
    if cls != PRIORITIES["normal"]:
        low_io()
    return cls, m


def describe(hw, b, o):
    kind = f"hybrid, E-cores {len(hw['ecores'])}" if hw.get("ecores") else "cores of one type"
    g = f"video card {hw['gpu'][0]}" if hw.get("gpu") else "no video card"
    return (
        f"PC: CPU {hw['logical']} logical / {hw['physical']} cores ({kind}), RAM {hw['ram_gb']:.0f} GB "
        f"({hw['avail_gb']:.0f} free), {g}. Profile {o['profile']}: up to {b['workers']} workers of {b['threads']} "
        f'threads; "{FREE}" — {b["free"]}, "{ACTIVE}" — {b["active"]}'
    )


if __name__ == "__main__":
    hw = probe()
    o = options({})
    print(describe(hw, budget(hw, o), o))
    s = Sensors()
    time.sleep(1)
    print(s.sample())
