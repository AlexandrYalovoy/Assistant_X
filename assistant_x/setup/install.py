# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""Installation of the search on the user's PC: the Python environment, the packages (from the media, without
internet), the connection to Claude Desktop and Claude Code, a quick self-test. Started by Setup.bat; standard
library only; a second run repeats nothing that is done already.
Video card: NVIDIA with driver 570 or newer — torch for CUDA from packages\\wheels_gpu of the medium (search and
reranking on it); an AMD or Intel card with its own memory — onnxruntime-directml from packages\\wheels_dml with the
ONNX models (models\\onnx of the medium or of the PC); otherwise torch for the processor. The device is chosen after
the models are copied; the installer says what it found and what it chose. Intake of the user's own
documents: the bundled programs (Tesseract, LibreOffice, 7-Zip) checked by a trial conversion to PDF, the load
profile by this PC. The code is the folder of the package; the data (base, models, packages) is the workspace.
A medium (prepare-media --out): Setup.bat at its top, app\ (the program), packages\ (wheels, the Python installer),
models\ with MODELS.json, programs\, optionally a base package. Everything of the program goes to the PC folder
%LOCALAPPDATA%\AssistantX — app\<version> (a copy of app\), venv (the program installed from its wheel, never linked to
the medium), models (each folder copied once and checked against MODELS.json; a folder that is there, a linked one
above all, is left as it is), programs — and the workspace holds the data only.
Usage: python -m assistant_x.setup.install [--workspace DIR] [--profile NAME] [--dry-run] [--yes] [--venv DIR]
                                           [--no-register] [--online] [--cpu] [--base PACKAGE [--keep own|package]]
  --workspace DIR  the workspace of the data (default: AX_WORKSPACE, else Documents\\Assistant X); made when missing
  --profile NAME   the profile of a new workspace: general (default) or oil-gas-ru
  --dry-run      show what would be done, change nothing
  --yes          ask nothing (also AX_YES=1): for a run without a window or keyboard
  --venv DIR     put the environment into another folder (to check the installation)
  --no-register  leave the settings of Claude Desktop and Claude Code alone
  --online       install the packages from the internet even when the media has the packages folder
  --cpu          torch for the processor even when there is an NVIDIA video card
  --base PACKAGE install a base package right after (assistant-x base install --confirm; with codes that collide a
                 reference package keeps its codes, a default one needs --keep own|package)"""

import argparse, datetime, glob, json, os, platform, shutil, subprocess, sys, tempfile

from assistant_x.core import debuglog, env, workspace  # standard library only, like this file
from assistant_x.setup import constraints as K, medium as M

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # assistant_x
CODE = os.path.dirname(PACKAGE)  # the folder with pyproject.toml
LOCAL = str(workspace.machine_dir())
SERVER = "assistant-x"
IMPORTS = (
    "import mcp, numpy, snowballstemmer, pymupdf, sentence_transformers, pymupdf4llm, onnxruntime, psutil, torch; "
    "print('torch=' + torch.__version__)"
)
# the versions are those of setup/constraints.txt, the one list of a release (the online and the offline install)
TORCH = f"torch=={K.pin('torch')}"
CPU_TORCH = f"{TORCH}+cpu"
GPU_TORCH = f"{TORCH}+cu128"  # CUDA 12.8: RTX 50xx (Blackwell) and older cards; needs driver 570+
ORT = f"onnxruntime=={K.pin('onnxruntime')}"
DML_ORT = f"onnxruntime-directml=={K.pin('onnxruntime-directml')}"  # AMD and Intel cards through DirectML
MIN_DRIVER = 570
SERVE = ["-m", "assistant_x.server.mcp_server"]
NAMES = ("WS", "ROOT", "SKILL", "PACKS", "MODELS", "WHEELS", "LOCK", "PYVER", "WHEELS_GPU", "WHEELS_DML", "INBOX", "MEDIUM")


def medium():
    r"""The top folder of the medium this installation runs from (AX_MEDIUM, else the folder above app\ when it has
    packages\), or None for a folder of the code (a development checkout)."""
    given = env.get("MEDIUM")
    if given:
        return os.path.abspath(given)
    up = os.path.dirname(CODE)
    if os.path.basename(CODE).lower() == M.APP_DIR and os.path.isdir(os.path.join(up, M.PACKAGES_DIR)):
        return up
    return None


class _Paths:
    """The folders of the installation, from the workspace in use when first asked (not at import); --workspace
    (use_workspace) sets another."""

    def __getattr__(self, name):
        if name not in NAMES:
            raise AttributeError(name)
        self.use(None)
        return self.__dict__[name]

    def use(self, root):
        w = workspace.Workspace(root) if root else workspace.current()
        med = medium()
        packs = os.path.join(med, M.PACKAGES_DIR) if med else str(w.packages)
        self.__dict__.update(
            WS=w,
            ROOT=str(w.root),
            PACKS=packs,
            MODELS=str(w.models),
            INBOX=str(w.inbox),
            SKILL=os.path.join(str(w.root), "skill", "SKILL.md"),  # written for the profile (assistant-x skill)
            WHEELS=os.path.join(packs, M.WHEELS),
            LOCK=os.path.join(packs, M.LOCK_FILE),
            PYVER=os.path.join(packs, M.PYVER_FILE),
            WHEELS_GPU=os.path.join(packs, M.WHEELS_GPU),
            WHEELS_DML=os.path.join(packs, M.WHEELS_DML),
            MEDIUM=med,
        )


P = _Paths()


def __getattr__(name):  # install.ROOT and the others for the callers
    if name in NAMES:
        return getattr(P, name)
    raise AttributeError(name)


PROFILE = None  # --profile: the profile of a workspace this installation makes
YES = env.flag("YES")  # --yes: no question, no waiting for a key


class Stop(Exception):
    pass


def say(msg=""):
    print(msg, flush=True)


def writable(d):
    try:
        os.makedirs(d, exist_ok=True)
        fd, p = tempfile.mkstemp(dir=d)
        os.close(fd)
        os.remove(p)
        return True
    except OSError:
        return False


def venv_python(d):
    return os.path.join(d, "Scripts", "python.exe") if os.name == "nt" else os.path.join(d, "bin", "python")


def check(py, code="import sys", timeout=120):
    """(ok, output) of running code in that interpreter."""
    try:
        p = subprocess.run(
            [py, "-c", code], capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace"
        )
        return p.returncode == 0, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def ask(prompt):
    """input() that stops the installation cleanly when the window has no keyboard or the user pressed Ctrl+C."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        raise Stop("input interrupted. Start Setup.bat with a double click and answer the questions in its window.")


def run(cmd, dry, **kw):
    say("   > " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    if dry:
        return 0
    return subprocess.run(cmd, **kw).returncode


# ---------------------------------------------------------------- steps
def pick_venv(arg):
    r"""The environment: the one given; .venv of a development checkout (a .git folder, or a .venv there already);
    else %LOCALAPPDATA%\AssistantX\venv — never on a medium, which may be a flash drive taken out tomorrow."""
    if arg:
        return os.path.abspath(arg)
    dev = os.path.join(CODE, ".venv")
    if not medium() and (os.path.isdir(os.path.join(CODE, ".git")) or os.path.isdir(dev)) and writable(CODE):
        return dev
    return os.path.join(LOCAL, "venv")


def make_venv(vdir, dry):
    py = venv_python(vdir)
    if check(py)[0]:
        say("   already there")
        return py
    if os.path.exists(vdir) and not os.path.exists(os.path.join(vdir, "pyvenv.cfg")):
        raise Stop(f"The folder {vdir} is taken by something else. Rename it and start the installation again.")
    from assistant_x.core.txn import links_inside

    linked = links_inside(vdir) if os.path.exists(vdir) else []
    if linked:  # venv --clear would remove what the link points at
        raise Stop(
            f"The environment {vdir} does not work and holds a link ({linked[0]}): it is not cleared. Remove the "
            "link itself (rmdir LINK), then start the installation again."
        )
    # a .venv copied from another PC points to a Python that is not here: rebuild it in place
    base = getattr(sys, "_base_executable", None) if sys.prefix != sys.base_prefix else sys.executable
    base = base or sys.executable
    if run([base, "-m", "venv", "--clear", vdir] if os.path.exists(vdir) else [base, "-m", "venv", vdir], dry):
        raise Stop("Could not create the Python environment (see the messages above).")
    return py


def nvidia():
    """{name, driver, vram_gb} of the first NVIDIA card (nvidia-smi comes with its driver), or None."""
    exe = shutil.which("nvidia-smi") or (
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe") if os.name == "nt" else None
    )
    if not exe or not os.path.exists(exe):
        return None
    try:
        p = subprocess.run(
            [exe, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        name, driver, mem = [x.strip() for x in p.stdout.splitlines()[0].rsplit(",", 2)]
        return {"name": name, "driver": driver, "vram_gb": float(mem) / 1024}
    except (OSError, subprocess.TimeoutExpired, IndexError, ValueError):
        return None


def video_cards():
    """Names of all video adapters (Windows), for the message about what was found."""
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"],
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [l.strip() for l in out.splitlines() if l.strip()]


def choose_device(cpu_asked, offline):
    """ "cuda" when torch for the video card goes in (NVIDIA, driver 570+, the wheel on the media or internet), else "cpu";
    the message says what was found and why."""
    cards = video_cards()
    say(f"   video cards: {', '.join(cards) if cards else 'none found'}")
    nv = nvidia()
    if cpu_asked:
        say("   chosen: processor (--cpu)")
        return "cpu"
    if not nv:
        return dml_or_cpu(offline)
    major = int(nv["driver"].split(".")[0]) if nv["driver"].split(".")[0].isdigit() else 0
    if major < MIN_DRIVER:
        say(
            f"   {nv['name']}: driver {nv['driver']} older than {MIN_DRIVER} — CUDA needs a newer one. For CUDA to work, "
            f"update the NVIDIA driver (nvidia.com/drivers) and run Setup.bat once more"
        )
        return dml_or_cpu(offline)
    if offline and not glob.glob(os.path.join(P.WHEELS_GPU, M.TORCH_GPU_GLOB)):
        say(
            f"   {nv['name']}: the media has no torch build for the video card (packages\\wheels_gpu) — search on the processor"
        )
        return "cpu"
    say(f"   chosen: video card {nv['name']} ({nv['vram_gb']:.0f} GB, driver {nv['driver']}) — search and reranking on it")
    return "cuda"


def onnx_models_here():
    """Is the ONNX export of bge-m3 (what DirectML runs) in the models folder of the PC or of the medium (copied by
    copy_models)?"""
    places = [P.MODELS] + ([os.path.join(P.MEDIUM, M.MODELS_DIR)] if P.MEDIUM else [])
    return any(os.path.exists(os.path.join(d, *M.ONNX_EMBEDDER)) for d in places)


def dml_or_cpu(offline):
    """ "dml" for a card with its own memory (AMD, Intel Arc; also NVIDIA with an old driver) when the media has
    onnxruntime-directml and the ONNX models; integrated graphics is no faster than the processor (measured), "cpu"."""
    try:
        from assistant_x.search import onnx_models

        found, least = onnx_models.adapters(), onnx_models.MIN_DML_GB
    except Exception:  # noqa: BLE001 — no DXGI (not Windows): the processor
        found, least = [], 2
    best = max(((m, i, n) for i, n, v, m in found), default=None)
    if not best or best[0] < least:
        why = (
            f"{best[2]} — integrated, {best[0]:.1f} GB of its own memory, no faster than the processor"
            if best
            else "no video card"
        )
        say(f"   {why}: search on the processor (0.1–0.3 s per question), without reranking")
        return "cpu"
    have = (glob.glob(os.path.join(P.WHEELS_DML, M.DML_GLOB)) or not offline) and onnx_models_here()
    if not have:
        say(
            f"   {best[2]}: the media has no DirectML or ONNX models (packages\\wheels_dml, models\\onnx) — search on the processor"
        )
        return "cpu"
    say(f"   chosen: video card {best[2]} ({best[0]:.0f} GB) through DirectML — search and reranking on it")
    return "dml"


def has_hashes(req):
    """Does a requirements file of a medium carry the sha256 of its wheels (prepare_media.hashed_lock)?"""
    try:
        return "--hash=sha256:" in open(req, encoding="utf-8").read()
    except OSError:
        return False


def hashed(folder, req):
    """The pip arguments that install req from a wheel folder of a medium: its requirements file with the sha256 of
    the wheel (pip --require-hashes); req itself only for a medium taken without the check (--allow-unverified)."""
    path = os.path.join(folder, M.HASHED_REQ)
    return ["--require-hashes", "-r", path] if has_hashes(path) else [req]


def unverified():
    """Why the packages of the medium (or of the packages folder of the workspace) cannot be checked before they are
    installed: [] when the lock and the requirements of the video card wheels carry the sha256 of every wheel and
    SHA256SUMS.txt holds (the Python installer, the wheel of the program)."""
    from assistant_x.setup import downloads

    out = [] if has_hashes(P.LOCK) else [f"{P.LOCK} carries no sha256 of its wheels"]
    for folder, pattern in ((P.WHEELS_GPU, M.TORCH_GPU_GLOB), (P.WHEELS_DML, M.DML_GLOB)):
        if glob.glob(os.path.join(folder, pattern)) and not has_hashes(os.path.join(folder, M.HASHED_REQ)):
            out.append(f"no {os.path.join(folder, M.HASHED_REQ)} with the sha256 of its wheel")
    return out + downloads.check_sums(P.PACKS)


def install_packages(py, offline, dry, device="cpu"):
    rc = 0
    if offline:
        say(f"   without internet, from {P.WHEELS}")
        if device == "cuda":  # first: the lock then finds torch of TORCH (+cu128 matches its ==) and keeps it
            rc = run(
                [
                    py,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-index",
                    "--find-links",
                    P.WHEELS_GPU,
                    "--no-deps",
                    *hashed(P.WHEELS_GPU, GPU_TORCH),
                ],
                dry,
            )
        rc = rc or run(
            [
                py,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-index",
                "--find-links",
                P.WHEELS,
                *(["--require-hashes"] if has_hashes(P.LOCK) else []),
                "-r",
                P.LOCK,
            ],
            dry,
        )
    else:
        say("   from the internet (no packages folder): pypi.org and download.pytorch.org")
        if dry or device == "cuda" or not check(py, "import torch")[0]:  # CPU build: ten times smaller
            rc = run(
                [
                    py,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    TORCH,
                    "--index-url",
                    f"https://download.pytorch.org/whl/{'cu128' if device == 'cuda' else 'cpu'}",
                ],
                dry,
            )
        # the dependencies of pyproject.toml with the package itself (an editable install), at the versions of the
        # release (constraints.txt: the same as on a medium)
        rc = rc or run(
            [py, "-m", "pip", "install", "--disable-pip-version-check", "-c", K.PATH, "-e", f"{CODE}[dense,intake]"], dry
        )
    rc = rc or (install_self(py, offline, dry) if offline else 0)
    if rc:
        raise Stop("The packages did not install (see the pip messages above).")
    if dry:
        return device
    ok, out = check(py, IMPORTS, timeout=600)
    if not ok:
        raise Stop(f"The packages are installed but do not load:\n{out[-1500:]}")
    torch = next((l.split("=", 1)[1] for l in out.splitlines() if l.startswith("torch=")), "?")  # torch also prints warnings
    say(f"   checked: the packages load, torch {torch}")
    if device == "dml":  # onnxruntime-directml replaces onnxruntime (the same module; it runs the intake models too)
        run([py, "-m", "pip", "uninstall", "-y", "--disable-pip-version-check", "onnxruntime"], dry)
        src = ["--no-index", "--find-links", P.WHEELS_DML, *hashed(P.WHEELS_DML, DML_ORT)] if offline else [DML_ORT]
        if run([py, "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", *src], dry):
            raise Stop("onnxruntime-directml did not install (see the pip messages above).")
        ok, out = check(
            py, "import onnxruntime as o; print('dml=' + str('DmlExecutionProvider' in o.get_available_providers()))"
        )
        if "dml=True" not in out:
            say("   DirectML did not work: putting onnxruntime back, the search will run on the processor")
            run([py, "-m", "pip", "uninstall", "-y", "--disable-pip-version-check", "onnxruntime-directml"], dry)
            run(
                [
                    py,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-deps",
                    *(["--no-index", "--find-links", P.WHEELS] if offline else []),
                    ORT,
                ],
                dry,
            )
            return "cpu"
        say("   DirectML works")
    elif check(py, "import importlib.metadata as m; m.version('onnxruntime-directml')")[0]:  # left from before
        run([py, "-m", "pip", "uninstall", "-y", "--disable-pip-version-check", "onnxruntime-directml"], dry)
        run(
            [
                py,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--force-reinstall",
                "--no-deps",
                *(["--no-index", "--find-links", P.WHEELS] if offline else []),
                ORT,
            ],
            dry,
        )
    if device == "cuda":
        ok, out = check(py, "import torch; print('cuda=' + str(torch.cuda.is_available()))", timeout=300)
        if "cuda=True" not in out:
            say(
                "   torch for the video card did not see it (the driver?): installing the processor build, the search runs on it"
            )
            if run(
                [
                    py,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-index",
                    "--find-links",
                    P.WHEELS,
                    "--force-reinstall",
                    "--no-deps",
                    CPU_TORCH,
                ],
                dry,
            ):
                raise Stop("Could not put torch for the processor back (see the pip messages above).")
            return "cpu"
        say("   the video card works: torch sees CUDA")
    elif "+cu" in torch and offline:  # a GPU build left from an earlier installation on a PC that has no card now
        run(
            [
                py,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-index",
                "--find-links",
                P.WHEELS,
                "--force-reinstall",
                "--no-deps",
                CPU_TORCH,
            ],
            dry,
        )
    return device


def install_self(py, offline, dry):
    r"""The package itself. From a medium: app\ copied to %LOCALAPPDATA%\AssistantX\app\<version> and the package
    installed from its wheel (packages\wheels\assistant_x-<version>-…whl), so nothing points at the medium. From a
    folder of the code: an editable install (an update of the folder needs no new installation); without internet the
    build tools come from the media (setuptools and wheel in the wheels folder)."""
    from assistant_x import __version__

    wheel = glob.glob(os.path.join(P.WHEELS, f"assistant_x-{__version__}-*.whl"))
    if P.MEDIUM and wheel:
        dst = os.path.join(LOCAL, "app", __version__)
        say(f"   the program: {dst}")
        if not dry:
            refresh_app(dst, wheel[0])
        return run(
            [
                py,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-index",
                "--find-links",
                P.WHEELS,
                "--no-deps",
                "--force-reinstall",
                wheel[0],
            ],
            dry,
        )
    if offline:
        return run(
            [
                py,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-index",
                "--find-links",
                P.WHEELS,
                "setuptools",
                "wheel",
            ],
            dry,
        ) or run(
            [py, "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", "--no-build-isolation", "-e", CODE], dry
        )
    return run([py, "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", "-e", CODE], dry)


APP_STAMP = ".wheel.sha256"  # in app\<version>: the sha256 of the wheel its copy came with


def refresh_app(dst, wheel):
    r"""app\<version> made from app\ of the medium, and made again when the wheel of the medium differs from the one
    the copy came with (the same version number built again): the program and its copy never part. A copy holding a
    link is never cleared (txn.links_inside)."""
    from assistant_x.core.txn import copy_tree, links_inside
    from assistant_x.setup import downloads

    sha = downloads.sha256(wheel)
    stamp = os.path.join(dst, APP_STAMP)
    have = open(stamp, encoding="utf-8").read().strip() if os.path.exists(stamp) else None
    if os.path.exists(dst) and have == sha:
        return
    if os.path.exists(dst):
        if links_inside(dst):
            say(f"   {dst} holds a link: left as it is")
            return
        say(f"   {dst}: another build of {os.path.basename(dst)} — copied again")
        shutil.rmtree(dst)
    copy_tree(CODE, dst)
    with open(stamp, "w", encoding="utf-8") as f:
        f.write(sha + "\n")


def copy_models(dry):
    """The model folders of the medium into the models folder of the PC, each one once, every file checked against
    MODELS.json. A folder is copied to <name>.part and renamed when whole, so an interrupted copy is never taken for a
    model (a .part left by one is copied again); a folder there already is checked against MODELS.json by its sizes and
    copied again when it is not whole (a linked one, or one holding a link, is never touched: only told). Problems
    as strings."""
    from assistant_x.core.txn import copy_tree, is_link, links_inside
    from assistant_x.setup import download_models as D

    src = os.path.join(P.MEDIUM or "", M.MODELS_DIR)
    if not P.MEDIUM or not os.path.isdir(src):
        return []
    dst = str(workspace.current().models)
    try:
        data = json.load(open(os.path.join(src, D.MANIFEST), encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    problems, copied = [], []
    for name in sorted(os.listdir(src)):
        if not os.path.isdir(os.path.join(src, name)) or name.endswith(".part"):
            continue
        target = os.path.join(dst, name)
        part = target + ".part"
        if os.path.exists(target) or is_link(target):
            bad = D.check(dst, data, names=[name], sizes_only=True) if data else []
            if not bad:
                say(f"   {name}: there already ({target}{', a link' if is_link(target) else ''}), left as it is")
                continue
            if links_inside(target):
                problems.append(
                    f"Model {name} at {target} is not whole ({bad[0]}) and is a link or holds one: "
                    "it is left as it is; copy the folder of the medium there by hand"
                )
                continue
            say(f"   {name}: there but not whole ({bad[0]}): {'would copy' if dry else 'copying'} it again")
        else:
            say(f"   {name}: {'would copy' if dry else 'copying'} to {target}")
        if dry:
            continue
        if os.path.exists(part) and not links_inside(part):
            shutil.rmtree(part)  # an interrupted copy of an earlier run: this installer's own folder
        copy_tree(os.path.join(src, name), part)
        if os.path.exists(target):  # the broken folder (no link in it, checked above) gives way to the whole one
            old = target + ".old"
            os.replace(target, old)
            os.replace(part, target)
            shutil.rmtree(old)
        else:
            os.replace(part, target)
        copied.append(name)
    if copied and data:
        bad = D.check(dst, data, names=copied)
        problems += [f"Model file {b} after copying from the medium: copy the folder again" for b in bad[:10]]
        say(f"   checked against MODELS.json: {'every file whole' if not bad else f'{len(bad)} files differ'}")
    elif copied:
        problems.append("The medium has no MODELS.json: the copied models could not be checked")
    return problems


def copy_programs(dry):
    r"""The programs of the intake of the medium (programs\: Tesseract, LibreOffice, 7-Zip, DjVuLibre) into the PC
    folder, each one once."""
    from assistant_x.core.txn import copy_tree
    from assistant_x.intake import config as intake_cfg

    src = os.path.join(P.MEDIUM or "", M.PROGRAMS_DIR)
    if not P.MEDIUM or not os.path.isdir(src):
        return
    dst = str(intake_cfg.programs_dir())
    for name in sorted(os.listdir(src)):
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if os.path.isdir(s) and not os.path.exists(d):
            say(f"   {name}: {'would copy' if dry else 'copying'} to {d}")
            if not dry:
                copy_tree(s, d)
        elif os.path.isfile(s) and not os.path.exists(d) and not dry:
            os.makedirs(dst, exist_ok=True)
            shutil.copy2(s, d)


def install_base(py, path, keep, dry):
    """A base package right after the installation (--base): assistant-x base install --confirm."""
    cmd = [py, "-m", "assistant_x.base.cli", "install", os.path.abspath(path), "--confirm"] + (
        ["--keep", keep] if keep else []
    )
    if run(cmd, dry, env=dict(os.environ, AX_WORKSPACE=P.ROOT, PYTHONUTF8="1")):
        return [f"The base package {path} was not installed (see the messages above): assistant-x base inspect shows why"]
    return []


def server_running():
    """Does a search server of Assistant X hold its models lock (Claude Desktop or Claude Code runs it)?"""
    from assistant_x.base.inspection import server_running as running

    return running()


def check_intake(py, dry):
    """Intake of the user's own documents: programs of the programs folder (or installed ones), languages of OCR, a
    trial DOCX-free conversion (a text file to PDF through LibreOffice), the load profile by this PC. Problems as
    strings; nothing here stops the installation: search works without the intake."""
    code = (
        "import json; from assistant_x.intake import config as intake_cfg, balance; c = intake_cfg.load(); "
        "hw = balance.probe(); print(json.dumps({'soffice': c.soffice, 'tesseract': c.tesseract, 'tessdata': c.tessdata, "
        "'sevenzip': c.sevenzip, 'langs': intake_cfg.ocr_languages(c), 'profile': c.balance['profile'], "
        "'logical': hw['logical'], 'ram_gb': hw['ram_gb']}, ensure_ascii=False))"
    )
    if dry:
        say("   (trial run: would check Tesseract, LibreOffice, 7-Zip and the load profile)")
        return []
    os.makedirs(P.INBOX, exist_ok=True)  # not in a trial run: it changes nothing
    try:
        p = subprocess.run([py, "-c", code], capture_output=True, text=True, timeout=300, encoding="utf-8", errors="replace")
        found = json.loads(p.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return [f"Intake: the settings cannot be read ({(p.stdout + p.stderr)[-500:] if 'p' in locals() else 'no answer'})"]
    problems = []
    for key, what, without in (
        ("tesseract", "Tesseract (OCR of scans)", "scans will have no OCR"),
        ("soffice", "LibreOffice (DOC/DOCX/PPTX → PDF)", "DOC/DOCX/PPTX will be skipped"),
        ("sevenzip", "7-Zip (7z and rar archives)", "7z and rar will not be unpacked"),
    ):
        say(f"   {what}: {found[key] or 'MISSING'}")
        if not found[key]:
            problems.append(f"Intake: no {what} — {without}. Install it or copy the programs folder of the media in full.")
    from assistant_x.core import lang

    need = lang.tesseract().split("+")  # the "tesseract" codes of the language packs in use
    if found["tesseract"] and not set(need) <= set(found["langs"]):
        problems.append(
            f"Intake: Tesseract has not the languages {' and '.join(need)} (it has: {', '.join(found['langs']) or 'none'})."
        )
    if found["soffice"]:
        tmp = tempfile.mkdtemp(prefix="ax_install_")
        src = os.path.join(tmp, "check.txt")
        with open(src, "w", encoding="utf-8") as f:
            f.write("Checking the conversion to PDF.\n")
        try:
            subprocess.run(
                [
                    found["soffice"],
                    f"-env:UserInstallation=file:///{tmp.replace(os.sep, '/')}/lo",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    tmp,
                    src,
                ],
                capture_output=True,
                timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        ok = os.path.exists(os.path.join(tmp, "check.pdf"))
        say(f"   trial conversion to PDF: {'done' if ok else 'FAILED'}")
        if not ok:
            problems.append(
                "Intake: LibreOffice did not convert the trial file to PDF — DOC/DOCX will be skipped. Make a debug report."
            )
        shutil.rmtree(tmp, ignore_errors=True)  # the temporary folder made just above
    weak = found["logical"] <= 4 or found["ram_gb"] < 8.5
    say(
        f"   PC: {found['logical']} logical CPUs, RAM {found['ram_gb']:.0f} GB; load profile of the intake: "
        + (
            "weak (a weak PC: 1–2 processes)"
            if weak
            else f"{found['profile']} (the intake gives way while you are at the computer)"
        )
    )
    if weak and found["profile"] == "auto":
        subprocess.run(
            [py, "-c", "from assistant_x.intake import config as intake_cfg; intake_cfg.save({'profile': 'weak'})"],
            capture_output=True,
            timeout=120,
        )
    return problems


def use_workspace(path):
    """--workspace: every path of the installation from that workspace (the server is registered with it)."""
    os.environ["AX_WORKSPACE"] = os.path.abspath(path)
    workspace.reset()
    P.use(os.path.abspath(path))


def check_workspace(dry):
    """The workspace of the data: made when it is not there yet (assistant-x init); an empty one is fine."""
    from assistant_x.cli import main as cli

    state, problems, _ = cli.state_of(P.WS)
    if state == "none":
        say(f"   {P.ROOT}: not made yet — {'would make it' if dry else 'making it'} (assistant-x init)")
        if not dry:
            cli.init([P.ROOT] + (["--profile", PROFILE] if PROFILE else []))
        return []
    if state == "empty":
        say(f"   {P.ROOT}: empty and in order — put documents into {P.INBOX}")
        return []
    say(f"   {P.ROOT}: " + ("in order" if state == "ready" else "has problems"))
    return problems


def check_data():
    from assistant_x.core.common import load_config, connect, vectors_path
    from assistant_x.cli import main as cli

    if cli.state_of(P.WS)[0] in ("none", "empty"):
        say("   (an empty workspace: the base and the texts come with the first intake)")
        cfg = load_config()
        ok = os.path.isdir(cfg.get("embed_model") or "")
        name = os.path.basename(cfg.get("embed_model") or "")
        if not ok and P.MEDIUM and name and os.path.isdir(os.path.join(P.MEDIUM, M.MODELS_DIR, name)):
            say(f"   embedding model: copied from the medium ({cfg.get('embed_model')})")  # copy_models above; a dry run
            return []
        say(f"   embedding model: {'present' if ok else 'MISSING'} ({cfg.get('embed_model')})")
        return (
            []
            if ok
            else [
                f"No embedding model ({cfg.get('embed_model')}): the search works by words only; "
                "assistant-x download-models fetches it (≈ 4.5 GB)."
            ]
        )
    cfg = load_config()
    if os.path.exists(cfg["db"]):
        cfg["vectors"] = vectors_path(cfg, connect(cfg["db"], readonly=True))
    problems = []
    for key, what, fix in (
        (
            "embed_model",
            "embedding model",
            "assistant-x download-models fetches it (≈ 4.5 GB), or Setup.bat of a medium with models\\ copies it",
        ),
        ("db", "search base", "assistant-x build makes it from the cards and texts of the workspace"),
        ("vectors", "embeddings of the fragments", "assistant-x embed computes them"),
        (
            "texts_dir",
            "texts of the documents",
            "the workspace has no library yet: put documents into inbox, or install a base package",
        ),
    ):
        p = cfg.get(key, "")
        ok = os.path.exists(p)
        say(f"   {what}: {'present' if ok else 'MISSING'} ({p})")
        if not ok:
            problems.append(f"Missing: {what} ({p}): {fix}.")
    return problems


def desktop_dirs():
    if os.name == "nt":  # the Microsoft Store build keeps settings inside its package folder
        dirs = [os.path.join(os.environ.get("APPDATA", ""), "Claude")] + glob.glob(
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages", "Claude_*", "LocalCache", "Roaming", "Claude")
        )
    else:
        dirs = [os.path.expanduser("~/Library/Application Support/Claude"), os.path.expanduser("~/.config/Claude")]
    found = [d for d in dirs if os.path.isdir(d)]
    return found or dirs[:1], bool(found)


def license_note():
    """AGPL-3.0 needs no agreement to install or use: one line about the license, no question."""
    say("   Assistant X is distributed under the AGPL-3.0 license (file LICENSE)")


DESKTOP_DIRS = ("\\windowsapps\\claude_", "\\anthropicclaude\\")  # the Microsoft Store build, the claude.ai/download one


def claude_running():
    """Is Claude Desktop open? Claude Code is also claude.exe (standalone, or the one Desktop keeps in
    %APPDATA%\\Claude\\claude-code), so tell them apart by the folder of the program."""
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='claude.exe'\" | ForEach-Object { [string]$_.ExecutablePath }",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return is_desktop([l.strip() for l in out.splitlines()])


def is_desktop(paths):
    """Paths of running claude.exe -> is one of them Claude Desktop."""
    return any(d in p.lower() for p in paths for d in DESKTOP_DIRS)


def wait_claude_closed(dry):
    if server_running():
        say("   the library server of Assistant X runs (Claude Desktop or Claude Code): close them, its files are in use")
    for _ in range(3):
        if not claude_running():
            say("   Claude Desktop is closed")
            return
        say("   Claude Desktop is open. Close it completely: right-click the Claude icon by the clock → Quit.")
        if dry or YES or not sys.stdin.isatty():
            say("   (going on without waiting)")
            return
        ask("   When it is closed, press Enter...")
    raise Stop("Claude Desktop is still open. Close it (the icon by the clock → Quit) and start the installation again.")


def register_desktop(py, dry):
    dirs, installed = desktop_dirs()
    if not installed:
        say(
            "   Claude Desktop is not found on this PC: writing the setting in advance, it is picked up once Claude is installed."
        )
    changed = False
    for d in dirs:
        path = os.path.join(d, "claude_desktop_config.json")
        conf = {}
        if os.path.exists(path):
            try:
                conf = json.load(open(path, encoding="utf-8-sig"))
            except ValueError as e:
                conf = None
                err = e
            if not isinstance(conf, dict):
                say(
                    f"   {path}: the settings file cannot be read ({err if conf is None else 'not a JSON object'}), leaving it alone."
                )
                say("   Add the section mcpServers → assistant-x to it by hand (see README.md).")
                continue
        servers = conf.setdefault("mcpServers", {})
        old = servers.get(SERVER) or {}
        new = dict(old, command=py, args=SERVE, env=dict(old.get("env") or {}, HF_HUB_OFFLINE="1", AX_WORKSPACE=P.ROOT))
        if old == new:
            say(f"   {path}: already set up")
            continue
        say(f"   {path}: {'would write' if dry else 'writing'} {SERVER} → {py}")
        if dry:
            continue
        os.makedirs(d, exist_ok=True)
        if os.path.exists(path):
            backup = os.path.join(d, f"{BACKUP_PREFIX}{datetime.datetime.now():%Y-%m-%d_%H%M%S}.json")
            shutil.copy2(path, backup)
            say(f"   the previous settings are saved: {backup}")
            prune_backups(d)
        servers[SERVER] = new
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(conf, f, ensure_ascii=False, indent=2)
        os.replace(path + ".tmp", path)
        changed = True
    return changed


BACKUP_PREFIX, BACKUPS_KEPT = "claude_desktop_config.backup-", 3


def prune_backups(folder, keep=BACKUPS_KEPT):
    """Only the newest keep backups of the settings of Claude Desktop that this installer made stay (one more per
    change otherwise, for ever)."""
    old = sorted(f for f in os.listdir(folder) if f.startswith(BACKUP_PREFIX) and f.endswith(".json"))
    for f in old[:-keep] if keep else old:
        os.remove(os.path.join(folder, f))


def register_code(py, dry):
    exe = shutil.which("claude")
    if not exe:
        say("   Claude Code is not installed, skipping.")
        return
    try:
        got = subprocess.run(
            [exe, "mcp", "get", SERVER], capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace"
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        say(f"   could not ask Claude Code: {e}")
        return
    if got.returncode == 0 and py in got.stdout and SERVE[1] in got.stdout and P.ROOT in got.stdout:
        say("   already set up")
        return
    if got.returncode == 0:
        run([exe, "mcp", "remove", SERVER, "-s", "user"], dry)
    if run(
        [
            exe,
            "mcp",
            "add",
            SERVER,
            "-s",
            "user",
            "-e",
            "HF_HUB_OFFLINE=1",
            "-e",
            f"AX_WORKSPACE={P.ROOT}",
            "--",
            py,
            *SERVE,
        ],
        dry,
    ):
        say("   Claude Code did not take the setting; connect it by hand (see README.md).")


def self_check(py, dry):
    if dry:
        say("   (skipped with --dry-run)")
        return []
    p = subprocess.run(
        [py, "-m", "assistant_x.setup.debug_report", "--quick", "--no-open"],
        capture_output=True,
        text=True,
        timeout=900,
        encoding="utf-8",
        errors="replace",
        env=dict(os.environ, PYTHONUTF8="1"),
    )
    report = next((l.split(":", 1)[1].strip() for l in p.stdout.splitlines() if l.startswith("Done:")), None)
    if not report or not os.path.exists(report):
        return [f"The self-test did not finish:\n{(p.stdout + p.stderr)[-1500:]}"]
    say(f"   report: {report}")
    text = open(report, encoding="utf-8").read()
    block = text.split("## What stands out", 1)[-1].split("\n## ", 1)[0]
    return [l[2:].strip() for l in block.splitlines() if l.startswith("- ") and "No obvious problems found" not in l]


def main():
    ap = argparse.ArgumentParser(prog="assistant-x install")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--venv")
    ap.add_argument("--no-register", action="store_true")
    ap.add_argument("--online", action="store_true")
    ap.add_argument("--cpu", action="store_true", help="torch for the processor even when there is an NVIDIA video card")
    ap.add_argument("--yes", action="store_true", help="ask nothing (also AX_YES=1)")
    ap.add_argument("--workspace", help="the workspace of the data (default: AX_WORKSPACE, else Documents\\Assistant X)")
    ap.add_argument("--profile", help="the profile of a new workspace: general (default) or oil-gas-ru")
    ap.add_argument("--base", help="a base package to install right after (.axbase or its folder)")
    ap.add_argument("--keep", choices=("own", "package"), help="with --base: who keeps colliding codes")
    ap.add_argument(
        "--allow-unverified",
        action="store_true",
        help="install from a medium whose packages carry no sha256 (not recommended: make the medium again)",
    )
    a = ap.parse_args()
    global YES, PROFILE
    YES = YES or a.yes
    PROFILE = a.profile
    if a.workspace:
        use_workspace(a.workspace)
    device = "cpu"
    dry = a.dry_run
    say(
        "Installation of Assistant X" + (" (trial run: changing nothing)" if dry else "") + f"\nFolder: {P.ROOT}\n"
        f"Program: {CODE}\n"
    )
    problems = []
    try:
        say("License")
        license_note()
        if not a.no_register:
            say("0. Claude Desktop must be closed")
            wait_claude_closed(dry)
        have = f"{sys.version_info[0]}.{sys.version_info[1]}"
        offline = os.path.isdir(P.WHEELS) and os.path.exists(P.LOCK) and not a.online
        bad = unverified() if offline else []
        if bad and not a.allow_unverified:
            raise Stop(
                "the packages cannot be checked before they are installed:\n  - "
                + "\n  - ".join(bad[:10])
                + "\nMake the medium again (assistant-x prepare-media --out …, then prepare-media --check), or run "
                "with --allow-unverified to install without the check."
            )
        for b in bad:
            say(f"   WARNING, not checked (--allow-unverified): {b}")
        want = open(P.PYVER, encoding="utf-8").read().strip() if os.path.exists(P.PYVER) else None
        say(f"1. Python {platform.python_version()}: {sys.executable}")
        if sys.version_info < (3, 11):
            raise Stop("Python 3.11 or newer is needed.")
        if offline and want and want != have:
            raise Stop(
                f"The packages on the media are built for Python {want}, but {have} is running. "
                f"Install Python {want} (its installer lies in the packages folder) or run with --online."
            )
        vdir = pick_venv(a.venv)
        say(f"2. Environment: {vdir}")
        py = make_venv(vdir, dry)
        say("3. Workspace and models")  # the models first: the device may need their ONNX export (DirectML)
        problems += check_workspace(dry)
        problems += copy_models(dry)
        say("4. Video card")
        device = choose_device(a.cpu, offline)
        say("5. Packages and base")
        device = install_packages(py, offline, dry, device)
        problems += check_data()
        say("6. Intake of your own documents")
        copy_programs(dry)
        problems += check_intake(py, dry)
        if a.no_register:
            say("7-8. Connection to Claude Desktop and Claude Code: skipped (--no-register)")
            changed = False
        else:
            say("7. Connection to Claude Desktop")
            changed = register_desktop(py, dry)
            say("8. Connection to Claude Code")
            register_code(py, dry)
        say("9. Self-test")
        problems += self_check(py, dry)
        if a.base:
            say("10. Base package")
            problems += install_base(py, a.base, a.keep, dry)
    except Stop as e:
        say(f"\nInstallation stopped: {e}")
        return 1
    except KeyboardInterrupt:
        say("\nInstallation interrupted (Ctrl+C). Run Setup.bat once more: what is done is not done again.")
        return 1
    say()
    if problems:
        say("The installation is finished, but there are remarks:")
        for p in dict.fromkeys(problems):
            say(f"  - {p}")
        say('If it is not clear what to do, run "assistant-x debug-report" and pass on the file it creates.')
    else:
        say("Done, no problems found.")
    say(
        "Search: "
        + {
            "cuda": "on the NVIDIA video card (CUDA), with reranking.",
            "dml": "on the video card through DirectML, with reranking.",
        }.get(device, "on the processor, without reranking.")
    )
    say('Your own documents: put them into the inbox folder, then write to Claude "AX: sort my documents".')
    if changed:
        say(
            "\nRestart Claude Desktop: close it completely (the icon by the clock → Quit) and open it again.\n"
            "After that the library commands (search_library and others) appear in the list of tools."
        )
    if not dry:
        from assistant_x.setup import skill

        skill.main([])
    say(
        f"\nThe skill for Claude: zip the folder {os.path.dirname(P.SKILL)} (it holds SKILL.md) and upload it in Claude →\n"
        'Settings → Capabilities → Skills → Upload. Then ask Claude, starting with "AX:".'
    )
    return 0


if __name__ == "__main__":
    sys.exit(debuglog.run(main, "install"))
