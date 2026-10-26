# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Before a task loads its models (embed.py, eval.py): is there room on the video card? Two library servers and eval
on one card can hang a PC. No silent move to the CPU: the task either gets the card, waits for it
(--wait), runs on the CPU because it was told to (--cpu, or "y" at the question), or does not start (code 3).

  device = gpu_guard.check(cfg, "embed", units=n, unit="fragments", cpu_s=0.4, wait=a.wait, cpu=a.cpu)
  -> "cuda" | "cpu"  (put into cfg["device"]); exits with code 3 when the task must not run here

assistant_x.toml [search]: gpu_min_free_gb (5), gpu_wait_minutes (60). The decision goes to heavy.log, the journal of
the machine lock (core/lock.py). The estimates of the time use the speeds measured on this PC (speed.json in its
folder: record_speed, measured, estimate), the constant of the caller only until one is measured."""

import datetime, json, os, shutil, sys, time

from assistant_x.core import proc

BUSY = 3
POLL = 30  # seconds between the checks of --wait


def journal(text):
    from assistant_x.core import lock

    try:
        with open(lock.lock_path().with_name("heavy.log"), "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')}\t{os.getpid()}\tvideo card\t{text}\n")
    except OSError:
        pass


def _smi(*query):
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        r = proc.run(
            [exe, *query, "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
    except (OSError, proc.SubprocessError):
        return None
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()] if r.returncode == 0 else None


def card():
    """(name, free GB, total GB) of the first video card, or None when there is no NVIDIA card."""
    rows = _smi("--query-gpu=name,memory.free,memory.total")
    if rows:
        name, free, total = [x.strip() for x in rows[0].rsplit(",", 2)]
        return name, float(free) / 1024, float(total) / 1024
    try:  # no nvidia-smi on PATH: ask torch (it makes a CUDA context, a few hundred MB)
        import torch

        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            return torch.cuda.get_device_name(0), free / 2**30, total / 2**30
    except Exception:  # noqa: BLE001 — torch without CUDA, a broken driver: no card for us
        pass
    return None


NO_CUDA = (
    "torch has no CUDA: install the CUDA build of torch (Setup.bat does it for an NVIDIA card; with pip: torch from "
    "download.pytorch.org, README)"
)


def torch_lacks_cuda():
    """True when torch is installed without CUDA (the CPU build PyPI gives on Windows): an NVIDIA card nvidia-smi
    reports is then of no use to it. False when torch sees CUDA, and when there is no torch at all."""
    try:
        import torch
    except ImportError:
        return False
    try:
        return not torch.cuda.is_available()
    except Exception:  # noqa: BLE001 — a broken CUDA build: no card for it either
        return True


def _dml(cfg):
    """("dml:N", name, dedicated GB) of the card DirectML would use (onnx_models.dml_device), or None."""
    try:
        from assistant_x.search import onnx_models

        dev = onnx_models.dml_device(cfg)
        if not dev:
            return None
        hit = onnx_models.pick_adapter(dev.split(":", 1)[1])
        return (dev, hit[1], hit[2]) if hit else None
    except Exception:  # noqa: BLE001 — DirectML is an option: without it the CPU question below
        return None


def holders():
    """Lines "PID program (memory)" of the processes on the card, with their command line when psutil knows it."""
    out = []
    for row in _smi("--query-compute-apps=pid,process_name,used_memory") or []:
        pid, name, used = [x.strip() for x in row.split(",")]
        what = name
        try:
            import psutil

            what = " ".join(psutil.Process(int(pid)).cmdline())[-160:] or name
        except Exception:  # noqa: BLE001 — gone or not ours to read
            pass
        out.append(f"  {pid}  {what}" + (f"  ({used} MB)" if used.isdigit() else ""))
    return out


def low_priority():
    """A CPU run must not take the PC from the user: below normal priority, low I/O."""
    try:
        import psutil

        p = psutil.Process()
        if os.name == "nt":
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            p.ionice(psutil.IOPRIO_LOW)
        else:
            p.nice(10)
    except Exception:  # noqa: BLE001 — no psutil: the run keeps normal priority
        pass


def duration(seconds):
    m = seconds / 60
    return f"about {seconds:.0f} s" if m < 2 else f"about {m:.0f} min" if m < 120 else f"about {m / 60:.1f} h"


def ask(text):
    """ "y" / "n" from a person at the console; None when nobody can answer (hook, skill, background)."""
    if not (sys.stdin and sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    try:
        return input(text).strip().lower().startswith("y")
    except EOFError:
        return None


def stop(text, task):
    print(text, file=sys.stderr, flush=True)
    journal(f"{task}: not started — {text.splitlines()[0]}")
    raise SystemExit(BUSY)


# ---------- measured speeds: the estimates of the time a task takes on this PC ----------
# speed.json in the folder of the PC (workspace.machine_dir): {unit: {device kind: {"s": seconds per unit, "n": units
# measured, "date"}}}; embed.py records every run of 50 fragments or more, onnx_models.py --check the int8 model.
SPEED_FILE = "speed.json"
MIN_MEASURED = 50  # fewer units say more about the loading of the model than about its speed


def speed_path():
    """speed.json of this PC (AX_SPEED_FILE overrides it: the tests)."""
    from pathlib import Path
    from assistant_x.core import env, workspace

    return Path(env.get("SPEED_FILE") or workspace.machine_dir() / SPEED_FILE)


def device_kind(device):
    """ "cuda", "dml" or "cpu" of a device name ("cuda:1", "dml:0")."""
    return str(device or "cpu").split(":", 1)[0]


def speeds():
    try:
        with open(speed_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record_speed(unit, device, seconds, n=MIN_MEASURED):
    """Remember seconds per unit of device on this PC (the last measurement counts: a new model, a new driver)."""
    if n < MIN_MEASURED or seconds <= 0:
        return
    data = speeds()
    data.setdefault(unit, {})[device_kind(device)] = {
        "s": float(f"{seconds:.3g}"),
        "n": int(n),
        "date": datetime.date.today().isoformat(),
    }
    try:
        path = speed_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass  # an estimate, never a reason to fail the task


def measured(unit, device):
    """Seconds per unit measured on this PC for device, or None."""
    s = (speeds().get(unit) or {}).get(device_kind(device), {}).get("s")
    return float(s) if isinstance(s, (int, float)) and s > 0 else None


def measure_speed(model, texts, device=None, unit="fragments"):
    """Seconds per text of model.encode on texts (at least MIN_MEASURED of them to be recorded), remembered for device
    (default: the device of the model)."""
    t0 = time.perf_counter()
    model.encode(list(texts), normalize_embeddings=True)
    s = (time.perf_counter() - t0) / max(len(texts), 1)
    record_speed(unit, device or getattr(getattr(model, "device", None), "type", "cpu"), s, n=len(texts))
    return s


def estimate(units, unit, device, cpu_s):
    """Seconds units take on device: the measured speed of this PC, else cpu_s per unit on a processor (no estimate
    of a video card without a measurement: None)."""
    s = measured(unit, device)
    if s is None and device_kind(device) == "cpu":
        s = cpu_s
    return units * s if s is not None else None


def check(cfg, task, units=0, unit="fragments", cpu_s=0.4, wait=False, cpu=False, say=print):
    """Device for the models of the task, or SystemExit(3). cfg["device"] = "cpu" in assistant_x.toml counts as --cpu.
    cpu_s: seconds per unit on a processor when this PC has measured none (speed.json)."""
    cpu_s = measured(unit, "cpu") or cpu_s
    if cpu or str(cfg.get("device") or "").startswith("cpu"):
        low_priority()
        journal(f"{task}: on the processor as told (--cpu or device in assistant_x.toml), {units} {unit}")
        say(f"{task}: computing on the processor (low priority), estimate {duration(units * cpu_s)}.")
        return "cpu"
    c = card()
    no_cuda = c is not None and torch_lacks_cuda()
    if no_cuda:  # the card is there, torch cannot use it: as if there were none
        say(f"{task}: the video card {c[0]} is not used — {NO_CUDA}.")
        journal(f"{task}: the video card {c[0]} not used: torch has no CUDA")
        c = None
    if c is None:
        dml = _dml(cfg)  # an AMD or Intel card with its own memory: the ONNX models through DirectML
        if dml:
            dev, name, vram = dml
            if vram >= float(cfg.get("gpu_min_free_gb", 5)) * 0.8:  # DXGI tells the size, not what is free
                journal(
                    f"{task}: on the video card {name} through DirectML ({vram:.1f} GB of its own memory), {units} {unit}"
                )
                say(f"{task}: computing on the video card {name} (DirectML).")
                return dev
            say(f"{task}: the video card {name} has {vram:.1f} GB of its own memory — too little for the model, not used.")
        est = duration(units * cpu_s)
        text = (
            f"{task}: no video card{' torch can use' if no_cuda else ''}, everything will be computed on the processor: "
            f"{units} {unit}, estimate {est} (~{cpu_s:g} s per unit). "
            + (
                "With the CUDA build of torch the card would do it."
                if no_cuda
                else "Better run it on a machine with an NVIDIA video card."
            )
        )
        say(text)
        yes = ask("Compute here on the processor? [y/n] ")
        if not yes:
            stop(
                f"{task}: not started ({'the answer was no' if yes is False else 'nobody to answer the question: not started from a console'}, "
                f"no video card, estimate on the processor {est}). To compute on the processor add --cpu.",
                task,
            )
        low_priority()
        journal(f'{task}: no video card, on the processor after the answer "y", {units} {unit}, estimate {est}')
        return "cpu"
    need = float(cfg.get("gpu_min_free_gb", 5))
    deadline = time.time() + float(cfg.get("gpu_wait_minutes", 60)) * 60
    told = False
    while True:
        name, free, total = c
        if free >= need:
            journal(f"{task}: on the video card {name}, {free:.1f} of {total:.1f} GB free")
            return str(cfg.get("device") or "cuda")
        text = (
            f"{task}: the video card {name} has {free:.1f} GB of {total:.1f} free, at least {need:g} GB needed "
            f"(gpu_min_free_gb in assistant_x.toml). The memory is held by:\n"
            + ("\n".join(holders()) or "  (nvidia-smi did not say)")
        )
        if not wait:
            stop(
                text
                + f"\nOptions: --wait — wait until it is free (a check every {POLL} s); --cpu — compute on the processor "
                f"at low priority ({units} {unit}, estimate {duration(units * cpu_s)}).",
                task,
            )
        if time.time() > deadline:
            stop(text + f"\nWaited {cfg.get('gpu_wait_minutes', 60)} min, the memory was not freed.", task)
        if not told:
            say(text + f"\nWaiting for it to be freed, a check every {POLL} s…")
            journal(f"{task}: waits for the video card, {free:.1f} GB free")
            told = True
        time.sleep(POLL)
        c = card() or c


def hold_machine(task, wait=False):
    """The machine lock (core/lock.py) until this process ends: one heavy task on the PC at a time.
    Busy: says who holds it and exits with code 3 (wait: waits)."""
    from assistant_x.core import lock

    lock.hold_for_process(task, wait=wait)


def add_arguments(ap):
    ap.add_argument("--wait", action="store_true", help="the video card is busy: wait until its memory is free")
    ap.add_argument("--cpu", action="store_true", help="compute on the processor (low priority), without the video card")
