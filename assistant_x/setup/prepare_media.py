# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Prepare the media. With --out MEDIUM the whole medium in one command:

    MEDIUM\\Setup.bat           the installer (a double-click on the target PC)
    MEDIUM\\app\\               the program (the files of the code under Git, the tests aside)
    MEDIUM\\packages\\          the Python packages of the same versions that work on this PC (torch in its CPU
                               version), the wheel of the program, THIRD_PARTY_LICENSES.txt (the license of every
                               package, its license texts and where the source code of the AGPL ones is), the
                               installer of Python itself
    MEDIUM\\models\\            the models (copied from --models, else the models of this PC; --download-models
                               fetches them) and MODELS.json (the sha256 of every file, checked at the install)
    MEDIUM\\packages\\wheels_gpu  --gpu: torch for NVIDIA cards (the CUDA build install.GPU_TORCH, driver
                               install.MIN_DRIVER or newer); wheels_dml, --dml: onnxruntime for AMD and Intel cards
                               through DirectML (install.DML_ORT); --all: --programs, --gpu and --dml
    MEDIUM\\README.txt         what is on the medium and which build Setup.bat chooses for the search
    MEDIUM\\programs\\          with --programs: Tesseract, LibreOffice, 7-Zip, DjVuLibre (collect_programs), VERSIONS.txt
                               (each with its license and where its source is) and sources\\ (the source archives
                               of DjVuLibre and 7-Zip, pinned by sha256; --no-sources leaves them off)
    MEDIUM\\base\\              with --base PACKAGE: a base package to install with Setup.bat --base

Without --out only the packages, into the packages folder of the workspace (.assistant_x/packages), as before. Run it on
the build PC with internet: scripts\\prepare_media.bat --out E:\\.
Usage: python -m assistant_x.setup.prepare_media [--out MEDIUM [--models DIR | --download-models | --no-models]
                                                 [--programs] [--gpu] [--dml] [--all] [--base PACKAGE]
                                                 [--no-sources]]
       python -m assistant_x.setup.prepare_media --check MEDIUM   the medium against this code, changing nothing
                                                 (also run at the end of --out)"""

import argparse, fnmatch, json, os, platform, re, shutil, sys, urllib.error, urllib.request
from importlib import metadata

from assistant_x.core import proc

from assistant_x.core import workspace
from assistant_x.setup import downloads, medium as ML

CODE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the folder with pyproject.toml
PACKS = WHEELS = LOCK = None  # the packages folder of the workspace in use: set by main() (not at import)
SOURCES = {  # the AGPL packages: where the source code of the version on the media is (AGPL-3.0, section 6)
    "pymupdf": "https://pypi.org/project/PyMuPDF/{v}/#files",
    "pymupdf4llm": "https://pypi.org/project/pymupdf4llm/{v}/#files",
    "pymupdf_layout": "https://pypi.org/project/pymupdf-layout/{v}/#files",
}
LICENSE_NAMES = ("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS")
TORCH_CPU = "https://download.pytorch.org/whl/cpu"


def torch_cuda_index():
    """The index of the CUDA build install.GPU_TORCH names ("torch==2.11.0+cu128" -> .../whl/cu128)."""
    from assistant_x.setup import install

    return f"https://download.pytorch.org/whl/{install.GPU_TORCH.split('+', 1)[1]}"


BUILD_TOOLS = ("setuptools", "wheel")  # for pip install -e of the package without internet
PYTHON_PUBLISHER = "Python Software Foundation"  # the signer of the installers of python.org
LAST_INSTALLER = {"3.11": "3.11.9", "3.12": "3.12.10"}  # later 3.x.y releases ship no installer


def norm(name):
    return re.sub(r"[-_.]+", "_", name).lower()


def pip(*args, python=None):
    cmd = [python or sys.executable, "-m", "pip", "--disable-pip-version-check", *args]
    print("  >", " ".join(cmd[3:]), flush=True)
    if proc.run(cmd).returncode:
        raise SystemExit("pip ended with an error (see above). Check the internet connection and run again.")


def lock_file():
    """The exact versions of a medium: setup/constraints.txt, the one list of the release (the online install uses it
    too), not what happens to be installed on the build PC; torch apart (its CPU build is downloaded from its own
    index) and onnxruntime-directml apart (packages/wheels_dml, --dml). Returns (pins, torch version)."""
    from assistant_x.setup import constraints

    pins, torch = [], None
    for key, (name, ver) in sorted(constraints.read().items()):
        if key == "torch":
            torch = ver
        elif key != "onnxruntime-directml":
            pins.append(f"{name}=={ver}")
    if not torch:
        raise SystemExit(f"{constraints.PATH} names no torch: python -m assistant_x.setup.constraints --write")
    return pins, torch


def license_of(dist):
    """The license of an installed package: License-Expression, else a one-line License field, else the classifiers."""
    meta = dist.metadata
    text = meta.get("License-Expression") or ""
    if not text:
        field = (meta.get("License") or "").strip()
        text = field if field and "\n" not in field and len(field) < 100 else ""
    if not text:
        text = "; ".join(c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License ::"))
    return text or "see the license texts below"


def license_texts(dist):
    """[(file, text)] of the license files a package ships in its dist-info (LICENSE, COPYING, NOTICE, AUTHORS)."""
    out = []
    for f in dist.files or []:
        if ".dist-info" in str(f) and f.name.upper().startswith(LICENSE_NAMES):
            try:
                out.append((str(f).replace("\\", "/"), f.locate().read_text(encoding="utf-8", errors="replace").strip()))
            except (OSError, AttributeError):
                pass
    return out


def third_party(pins, torch, extra=()):
    """THIRD_PARTY_LICENSES.txt of the media: every package with its version, license, license texts and, for the
    AGPL packages, where their source code is; extra: "name==version" of more packages on the medium (the builds of
    the video cards), listed with their version even when they are not installed here."""
    names = sorted([p.split("==")[0] for p in pins if norm(p.split("==")[0]) != "assistant_x"] + ["torch"], key=norm)
    more = {norm(e.split("==")[0]): e.split("==", 1)[1] for e in extra}
    from assistant_x.setup import medium as M

    lines = [
        "Third-party Python packages on the media of Assistant X, with their licenses.",
        "The programs of the intake (Tesseract-OCR, LibreOffice, 7-Zip, DjVuLibre) are in programs/VERSIONS.txt,",
        "each with its license and where its source code is; the source archives of DjVuLibre (GPL-2.0-or-later)",
        f"and 7-Zip (LGPL-2.1) are in programs/{M.SOURCES_DIR}/. " + M.VC_RUNTIME,
        "The models carry their own LICENSE files. Assistant X itself: LICENSE and NOTICE of its folder.",
        "",
    ]
    for name in names:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            lines += [f"== {name}: not installed here, see its page on pypi.org", ""]
            continue
        ver = torch if norm(name) == "torch" else dist.version
        lines.append(f"== {dist.metadata['Name']} {ver}: {license_of(dist)}")
        if norm(name) in SOURCES:
            lines.append(f"   The source code of this version: {SOURCES[norm(name)].format(v=ver)}")
        for path, text in license_texts(dist):
            lines += ["", f"--- {path}", text]
        lines.append("")
    for name, ver in sorted(more.items()):
        if name == "torch":
            lines.append(
                f"== torch {ver} (the CUDA build, packages/wheels_gpu): the license of torch above; it carries "
                "the NVIDIA CUDA runtime libraries under the NVIDIA license (inside the wheel)"
            )
        else:
            try:
                dist = metadata.distribution(name)
                lines.append(f"== {dist.metadata['Name']} {ver}: {license_of(dist)}")
            except metadata.PackageNotFoundError:
                lines.append(f"== {name} {ver}: MIT (onnxruntime, Microsoft), see its page on pypi.org")
        lines.append("")
    path = os.path.join(PACKS, ML.THIRD_PARTY)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  {len(names)} packages in {path}")


def python_installer():
    if os.name != "nt":
        print("  not Windows: no Python installer needed")
        return
    have = platform.python_version()
    minor = ".".join(have.split(".")[:2])
    for ver in dict.fromkeys([have, LAST_INSTALLER.get(minor, have)]):
        name = f"python-{ver}-amd64.exe"
        path = os.path.join(PACKS, name)
        if os.path.exists(path):
            print(f"  already here: {name}")
            return
        url = f"https://www.python.org/ftp/python/{ver}/{name}"
        part = path + ".part"
        try:
            print(f"  downloading {url}", flush=True)
            urllib.request.urlretrieve(url, part)
        except urllib.error.HTTPError as e:
            print(f"  no such file ({e.code}), trying another version {minor}")
            continue
        why = downloads.signed_by(part, PYTHON_PUBLISHER)  # python.org signs its installers; no sha256 is published
        if why:
            os.remove(part)
            raise SystemExit(f"{url}: {why}, not by {PYTHON_PUBLISHER}: not put on the medium")
        os.replace(part, path)
        return
    print(
        f"  Python installer {minor} not found: put python-{minor}.x-amd64.exe into {PACKS} by hand (then make "
        f"the medium again: {downloads.SUMS} names it)"
    )


APP_SKIP = ("tests/", ".github/", "private/")  # not on a medium


PROGRAM_WHEEL = "assistant_x-"  # the wheel of the program in packages/wheels


def build_python():
    """The interpreter that builds the wheel of the program: the base one of this environment when it has pip (a .pth
    of an environment can put its own old build tools before those of the isolated build), else this one."""
    base = getattr(sys, "_base_executable", None) or ""
    if base and os.path.normcase(os.path.abspath(base)) != os.path.normcase(os.path.abspath(sys.executable)):
        if proc.run([base, "-m", "pip", "--version"], capture_output=True).returncode == 0:
            return base
    return sys.executable


def app_files(code):
    """The files of the program for a medium: the ones under Git (the tests aside), else every file but the
    environment, the build folders and the private notes."""
    try:
        out = proc.run(["git", "-C", code, "ls-files"], capture_output=True, text=True, check=True).stdout.split("\n")
        files = [f for f in out if f and not f.startswith(APP_SKIP)]
        if files:
            return files
    except (OSError, proc.CalledProcessError):
        pass
    files = []
    for dp, dns, fns in os.walk(code):
        dns[:] = [
            d
            for d in dns
            if d not in (".venv", ".git", "build", "private", "tests", "__pycache__") and not d.endswith(".egg-info")
        ]
        files += [os.path.relpath(os.path.join(dp, f), code).replace(os.sep, "/") for f in fns]
    return files


def gpu_wheels(packs, cuda=True, dml=True):
    """The wheels of the video cards beside the packages, for the Python of this PC: torch for NVIDIA (the CUDA build
    install.py installs; on Windows its wheel carries the CUDA libraries, and its Python packages are those of the lock,
    the same as of the CPU build: --no-deps) in wheels_gpu, onnxruntime-directml for AMD and Intel cards in wheels_dml.
    Returns the names of the packages added, for THIRD_PARTY_LICENSES."""
    from assistant_x.setup import install

    added = []
    if cuda:
        gpu = os.path.join(packs, ML.WHEELS_GPU)
        os.makedirs(gpu, exist_ok=True)
        pip("download", "--no-deps", "--only-binary=:all:", "-d", gpu, install.GPU_TORCH, "--index-url", torch_cuda_index())
        added.append(install.GPU_TORCH)
    if dml:
        d = os.path.join(packs, ML.WHEELS_DML)
        os.makedirs(d, exist_ok=True)
        pip("download", "--no-deps", "--only-binary=:all:", "-d", d, install.DML_ORT)
        added.append(install.DML_ORT)
    return added


REPOSITORY = "https://github.com/AlexandrYalovoy/Assistant_X"


def readme(out, cuda, dml):
    """README.txt of the medium: what is on it, and which build of the search Setup.bat chooses."""
    from assistant_x.setup import install

    lines = [
        "Assistant X — installation medium",
        "",
        "Setup.bat (a double click) installs the program into %LOCALAPPDATA%\\AssistantX and connects it to Claude.",
        "Setup.bat --base base\\<package>.axbase also installs a base package.",
        "",
        "The search runs on:",
        f"  - an NVIDIA video card with driver {install.MIN_DRIVER} or newer: torch for CUDA "
        f"({install.GPU_TORCH}, packages\\wheels_gpu)" + ("" if cuda else " — NOT on this medium"),
        f"  - an AMD or Intel card with its own memory: ONNX through DirectML ({install.DML_ORT}, packages\\wheels_dml)"
        + ("" if dml else " — NOT on this medium"),
        "  - else the processor (torch for the CPU, packages\\wheels): slower, without reranking.",
        "Setup.bat looks at the cards of the PC and says what it chose; --cpu forces the processor.",
        "",
        "packages\\THIRD_PARTY_LICENSES.txt: the licenses of every package; programs\\VERSIONS.txt: the programs.",
        "",
        "Assistant X is free software under the GNU AGPL-3.0-or-later (app\\LICENSE, app\\NOTICE).",
        "app\\ is its complete source code; the repository: " + REPOSITORY,
    ]
    with open(os.path.join(out, "README.txt"), "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")


def fetch(url, sha, path):
    """url -> path through path.part, refused (and removed) unless its sha256 is the one given."""
    downloads.fetch(url, sha, path)


def hashed_lock(lock, wheels, folders=()):
    """The lock file rewritten with the sha256 of every wheel of its versions (pip install --require-hashes): a wheel
    changed on the medium after it was made is refused at the install. folders: more wheel folders (wheels_gpu,
    wheels_dml), each with its own requirements file of the same kind."""

    def hashes(folder, name, ver):
        files = [
            w
            for w in os.listdir(folder)
            if w.endswith(".whl")
            and norm(w.split("-")[0]) == norm(name)
            and w.split("-")[1].split("+")[0] == ver.split("+")[0]
        ]
        return [f"--hash=sha256:{downloads.sha256(os.path.join(folder, w))}" for w in sorted(files)]

    lines = []
    for line in open(lock, encoding="utf-8").read().split("\n"):
        if "==" not in line:
            continue
        name, ver = line.split("==", 1)
        got = hashes(wheels, name, ver)
        if not got:
            raise SystemExit(f"No wheel of {line} in {wheels}: the medium is not whole")
        lines.append(f"{line} " + " ".join(got))
    with open(lock, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    for folder, req in folders:
        name, ver = req.split("==", 1)
        got = hashes(folder, name, ver) if os.path.isdir(folder) else []
        if got:
            with open(os.path.join(folder, ML.HASHED_REQ), "w", encoding="utf-8", newline="\n") as f:
                f.write(f"{req} " + " ".join(got) + "\n")


def program_sources(programs):
    """The source archives of the copyleft programs in the programs folder of a medium (DjVuLibre, 7-Zip) into its
    sources folder, each checked by its sha256; a version without a pinned archive stops (the medium would carry a
    GPL or LGPL binary without its source)."""
    from assistant_x.setup import medium as M

    folder = os.path.join(programs, M.SOURCES_DIR)
    os.makedirs(folder, exist_ok=True)
    found = M.bundled(programs)
    for name, version in found.items():
        src = M.source_of(name, version)
        if not src:
            raise SystemExit(
                f"No pinned source archive of {name} {version} (assistant_x/setup/medium.py SOURCES): add "
                "it, or make the medium with --no-sources and give the source code another way."
            )
        path = os.path.join(folder, src["file"])
        if os.path.exists(path):
            print(f"  {src['file']}: there already")
            continue
        fetch(src["url"], src["sha256"], path)
    with open(os.path.join(folder, "SOURCES.txt"), "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(
            "The source code of the copyleft programs of the intake on this medium:\n\n"
            + "".join(
                f"{name} {version} ({M.LICENSES[name]}): {M.source_of(name, version)['file']}, from "
                f"{M.source_of(name, version)['url']}, sha256 {M.source_of(name, version)['sha256']}\n"
                for name, version in found.items()
            )
        )
    return found


def medium(out, models=None, download=False, no_models=False, programs=False, base=None, sources=True):
    """The rest of a medium beside its packages: the wheel of the program, app, Setup.bat, the models with
    MODELS.json, the programs, a base package."""
    from assistant_x.core.txn import copy_tree
    from assistant_x.setup import download_models as D

    print("\n5. The program")
    for old in os.listdir(WHEELS) if os.path.isdir(WHEELS) else ():
        if old.startswith(PROGRAM_WHEEL):  # a wheel of an earlier build of the program never stays on the medium
            os.remove(os.path.join(WHEELS, old))
    # built in isolation with the build tools of the medium (step 2): no internet, nothing of this environment, and
    # from a clean copy of the files of the program (a build/ folder left in the code would go into the wheel)
    import tempfile

    with tempfile.TemporaryDirectory(prefix="ax_wheel_") as tmp:
        for f in app_files(CODE):
            dst = os.path.join(tmp, *f.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(CODE, *f.split("/")), dst)
        pip("wheel", "--no-deps", "--no-index", "--find-links", WHEELS, "-w", WHEELS, tmp, python=build_python())
    app = os.path.join(out, ML.APP_DIR)
    if os.path.isdir(app):  # the program of this build only: a file removed from the code goes from the medium too
        shutil.rmtree(app)
    for f in app_files(CODE):
        dst = os.path.join(app, *f.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(CODE, *f.split("/")), dst)
    shutil.copy2(os.path.join(CODE, "Setup.bat"), os.path.join(out, "Setup.bat"))
    print(f"  {app}, {os.path.join(out, 'Setup.bat')}")
    dst = os.path.join(out, ML.MODELS_DIR)
    if download:
        print("\n6. The models (downloading)")
        D.main(["--dst", dst])
    elif not no_models:
        src = models or str(workspace.current().models)
        print(f"\n6. The models from {src}")
        for name in sorted(os.listdir(src)) if os.path.isdir(src) else []:
            if os.path.isdir(os.path.join(src, name)) and copy_tree(os.path.join(src, name), os.path.join(dst, name)):
                print(f"  {name}")
    if os.path.isdir(dst):
        if not os.path.exists(os.path.join(dst, *ML.ONNX_EMBEDDER)):
            print(
                f"  no {os.path.join(ML.MODELS_DIR, *ML.ONNX_EMBEDDER)}: a PC with an AMD or Intel card searches on the "
                "processor (assistant-x download-models exports it, or python -m assistant_x.search.onnx_models --export)"
            )
        print(f"  {D.write_manifest(dst)}")
    if programs:
        print("\n7. The programs of the intake")
        dst = os.path.join(out, ML.PROGRAMS_DIR)
        if os.path.isdir(dst):  # collect_programs never writes over a folder: a medium made again keeps its programs
            print(f"  {dst}: there already, left as it is (delete it to collect the programs again)")
            proc.run([sys.executable, "-m", "assistant_x.setup.collect_programs", "--dst", dst, "--versions"], check=True)
        else:
            proc.run([sys.executable, "-m", "assistant_x.setup.collect_programs", "--dst", dst], check=True)
        if sources:
            print("\n7a. The source code of DjVuLibre and 7-Zip (GPL, LGPL)")
            program_sources(dst)
        else:
            print(
                "  --no-sources: the source archives of DjVuLibre and 7-Zip are NOT on the medium; whoever passes the "
                "medium on must give their source code (or a written offer) with it"
            )
    if base:
        os.makedirs(os.path.join(out, ML.BASE_DIR), exist_ok=True)
        if os.path.isdir(base):
            copy_tree(base, os.path.join(out, ML.BASE_DIR, os.path.basename(base.rstrip("\\/"))))
        else:
            shutil.copy2(base, os.path.join(out, ML.BASE_DIR, os.path.basename(base)))
        print(f"\n8. The base package {base}")


def _same(a, b):
    with open(a, "rb") as f, open(b, "rb") as g:
        return f.read() == g.read()


def check(out):
    """[problems] of the medium at out against this code (prepare-media --check): the program (app, Setup.bat, the
    wheel of this version with the files of this code), the packages (the lock = constraints.txt, the sha256 of every
    wheel, SHA256SUMS.txt, the hashed requirements of the video card wheels), the models against MODELS.json, the
    programs against their SHA256SUMS.txt and the source archives of the copyleft ones."""
    import zipfile

    from assistant_x import __version__
    from assistant_x.setup import download_models as D, install

    out, problems = os.path.abspath(out), []
    app, packs = os.path.join(out, ML.APP_DIR), os.path.join(out, ML.PACKAGES_DIR)
    wheels, lock = os.path.join(packs, ML.WHEELS), os.path.join(packs, ML.LOCK_FILE)
    files = app_files(CODE)
    for f in files:
        p = os.path.join(app, *f.split("/"))
        if not os.path.isfile(p):
            problems.append(f"app/{f}: missing")
        elif not _same(p, os.path.join(CODE, *f.split("/"))):
            problems.append(f"app/{f}: not the file of this code")
    want = {f.replace("/", os.sep) for f in files}
    for dp, _, fns in os.walk(app):
        for n in fns:
            rel = os.path.relpath(os.path.join(dp, n), app)
            if rel not in want and "__pycache__" not in rel:
                problems.append(f"app/{rel.replace(os.sep, '/')}: not a file of this code")
    if not os.path.isfile(os.path.join(out, "Setup.bat")) or not _same(
        os.path.join(out, "Setup.bat"), os.path.join(CODE, "Setup.bat")
    ):
        problems.append("Setup.bat: missing or not the one of this code")
    own = [n for n in os.listdir(wheels) if n.startswith(PROGRAM_WHEEL)] if os.path.isdir(wheels) else []
    mine = [n for n in own if n.startswith(f"{PROGRAM_WHEEL}{__version__}-")]
    if len(own) != 1 or len(mine) != 1:
        problems.append(f"packages/wheels: one wheel of the program {__version__} is wanted, found {own or 'none'}")
    else:
        with zipfile.ZipFile(os.path.join(wheels, mine[0])) as z:
            for name in z.namelist():
                if name.startswith("assistant_x/") and not name.endswith("/"):
                    src = os.path.join(CODE, *name.split("/"))
                    if not os.path.isfile(src) or z.read(name) != open(src, "rb").read():
                        problems.append(f"the wheel of the program: {name} is not the file of this code")
    try:
        lines = [x for x in open(lock, encoding="utf-8").read().splitlines() if x.strip()]
    except OSError:
        lines = []
        problems.append(f"packages/{ML.LOCK_FILE}: missing")
    pins, torch = lock_file()
    if lines and {x.split()[0] for x in lines} != set(pins) | {f"torch=={torch}"}:
        problems.append(f"packages/{ML.LOCK_FILE}: not the versions of constraints.txt")
    problems += [f"packages/{ML.LOCK_FILE}: no sha256 for {x.split()[0]}" for x in lines if "--hash=sha256:" not in x]
    for x in lines:  # every hash names a wheel of the medium
        name, ver = x.split()[0].split("==", 1)
        have = {
            downloads.sha256(os.path.join(wheels, w))
            for w in os.listdir(wheels)
            if w.endswith(".whl") and norm(w.split("-")[0]) == norm(name) and w.split("-")[1].split("+")[0] == ver
        }
        if not have & {h.split(":", 1)[1] for h in x.split()[1:] if h.startswith("--hash=sha256:")}:
            problems.append(f"packages/wheels: no wheel of {name}=={ver} with the sha256 of the lock")
    for sub, pattern in ((ML.WHEELS_GPU, ML.TORCH_GPU_GLOB), (ML.WHEELS_DML, ML.DML_GLOB)):
        folder = os.path.join(packs, sub)
        wheel = os.path.isdir(folder) and any(fnmatch.fnmatch(w, pattern) for w in os.listdir(folder))
        if wheel and not install.has_hashes(os.path.join(folder, ML.HASHED_REQ)):
            problems.append(f"packages/{sub}: no {ML.HASHED_REQ} with the sha256 of its wheel")
    sums = downloads.check_sums(packs)
    problems += [f"packages: {p}" for p in sums]
    if not sums:
        named = open(os.path.join(packs, downloads.SUMS), encoding="utf-8").read()
        if os.name == "nt" and not any(n.startswith("python-") and n.endswith(".exe") for n in os.listdir(packs)):
            problems.append("packages: no Python installer")
        if mine and f"*{ML.WHEELS}/{mine[0]}" not in named:
            problems.append(f"packages/{downloads.SUMS}: the wheel of the program is not named")
    models = os.path.join(out, ML.MODELS_DIR)
    if os.path.isdir(models):
        try:
            data = json.load(open(os.path.join(models, D.MANIFEST), encoding="utf-8"))
            problems += [f"models/{p}" for p in D.check(models, data)]
        except (OSError, ValueError):
            problems.append(f"models/{D.MANIFEST}: missing or not readable")
    programs = os.path.join(out, ML.PROGRAMS_DIR)
    if os.path.isdir(programs):
        problems += [f"programs: {p}" for p in downloads.check_sums(programs)]
        for name, version in ML.bundled(programs).items():
            src = ML.source_of(name, version)
            p = os.path.join(programs, ML.SOURCES_DIR, src["file"]) if src else ""
            if not src or not os.path.isfile(p) or downloads.sha256(p) != src["sha256"]:
                problems.append(f"programs/{ML.SOURCES_DIR}: no source archive of {name} {version} with its sha256")
    return problems


def main(argv=None):
    global PACKS, WHEELS, LOCK
    ap = argparse.ArgumentParser(prog="assistant-x prepare-media")
    ap.add_argument("--check", metavar="MEDIUM", help="check a medium against this code (changes nothing)")
    ap.add_argument("--out", help="the folder of the medium (a flash drive, or a folder to copy onto one)")
    ap.add_argument("--models", help="the folder of the models to put on the medium (default: the models of this PC)")
    ap.add_argument("--download-models", action="store_true")
    ap.add_argument("--no-models", action="store_true")
    ap.add_argument("--programs", action="store_true")
    ap.add_argument("--base")
    ap.add_argument("--gpu", action="store_true", help="torch for NVIDIA cards (CUDA) in packages/wheels_gpu")
    ap.add_argument("--dml", action="store_true", help="onnxruntime-directml for AMD and Intel cards in packages/wheels_dml")
    ap.add_argument("--all", action="store_true", help="--programs, --gpu and --dml")
    ap.add_argument(
        "--no-sources",
        action="store_true",
        help="leave the source archives of DjVuLibre and 7-Zip off the medium (then give them another way)",
    )
    a = ap.parse_args(argv)
    if a.check:
        from assistant_x import __version__

        problems = check(a.check)
        print(f"Medium {os.path.abspath(a.check)} against this code (Assistant X {__version__}):")
        for p in problems[:200]:
            print(f"  - {p}")
        print("in order" if not problems else f"{len(problems)} problems: make the medium again (prepare-media --out)")
        return 1 if problems else 0
    PACKS = os.path.join(os.path.abspath(a.out), ML.PACKAGES_DIR) if a.out else (PACKS or str(workspace.current().packages))
    WHEELS, LOCK = os.path.join(PACKS, ML.WHEELS), os.path.join(PACKS, ML.LOCK_FILE)
    if sys.prefix == sys.base_prefix:
        raise SystemExit("Run it from the search environment: scripts\\prepare_media.bat (or .venv\\Scripts\\python.exe).")
    os.makedirs(WHEELS, exist_ok=True)
    print(f"Python {platform.python_version()}, folder: {PACKS}\n\n1. Package versions of the release (constraints.txt)")
    pins, torch = lock_file()
    with open(LOCK, "w", encoding="utf-8") as f:
        f.write("\n".join(pins + [f"torch=={torch}"]) + "\n")
    print(f"  {len(pins) + 1} packages, torch {torch} (CPU version)\n\n2. Downloading the packages")
    rest = LOCK + ".rest"
    with open(rest, "w", encoding="utf-8") as f:
        f.write("\n".join(pins) + "\n")
    try:  # the freeze already lists every dependency, so no resolving: exactly these files
        pip("download", "--no-deps", "--only-binary=:all:", "-d", WHEELS, "-r", rest)
        pip("download", "--no-deps", "--only-binary=:all:", "-d", WHEELS, f"torch=={torch}", "--index-url", TORCH_CPU)
        # the build tools of the editable install of the package itself (pip freeze leaves them out)
        pip("download", "--no-deps", "--only-binary=:all:", "-d", WHEELS, *BUILD_TOOLS)
        extra = gpu_wheels(PACKS, cuda=a.gpu or a.all, dml=a.dml or a.all) if a.out else []
    finally:
        os.remove(rest)
    # wheels of versions no longer used; a package whose file name does not match its pin exactly is left alone
    keep = {(norm(p.split("==")[0]), p.split("==")[1]) for p in pins} | {("torch", torch)}
    files = [(w, norm(w.split("-")[0]), w.split("-")[1].split("+")[0]) for w in os.listdir(WHEELS) if w.endswith(".whl")]
    exact = {n for _, n, v in files if (n, v) in keep}
    for w, n, v in files:
        if n in BUILD_TOOLS:
            continue
        if (n, v) not in keep and (n in exact or n not in {k[0] for k in keep}):
            os.remove(os.path.join(WHEELS, w))
            print(f"  removed the old {w}")
    from assistant_x.setup import install

    hashed_lock(
        LOCK,
        WHEELS,
        [(os.path.join(PACKS, ML.WHEELS_GPU), install.GPU_TORCH), (os.path.join(PACKS, ML.WHEELS_DML), install.DML_ORT)],
    )
    print("\n3. Licenses of the packages")
    third_party(pins, torch, extra)
    print("\n4. Python installer")
    python_installer()
    with open(os.path.join(PACKS, ML.PYVER_FILE), "w", encoding="utf-8") as f:
        f.write(".".join(platform.python_version().split(".")[:2]))
    if a.out:
        cuda, dml = a.gpu or a.all, a.dml or a.all
        medium(
            os.path.abspath(a.out),
            a.models,
            a.download_models,
            a.no_models,
            a.programs or a.all,
            a.base,
            sources=not a.no_sources,
        )
        readme(os.path.abspath(a.out), cuda, dml)
    # the sha256 of the Python installer (Setup.bat checks it) and of the wheel of the program (setup/install.py)
    named = [n for n in os.listdir(PACKS) if n.startswith("python-") and n.endswith(".exe")]
    named += [f"{ML.WHEELS}/{n}" for n in os.listdir(WHEELS) if n.startswith(PROGRAM_WHEEL)]
    downloads.sums(PACKS, named)
    total = sum(os.path.getsize(os.path.join(dp, n)) for dp, _, fs in os.walk(PACKS) for n in fs)
    if a.out:
        problems = check(os.path.abspath(a.out))
        print("\nThe medium checked against this code: " + ("in order" if not problems else "PROBLEMS"))
        for p in problems:
            print(f"  - {p}")
    print(
        f"\nDone: {len(os.listdir(WHEELS))} package files, {total / 2**20:.0f} MB in all in {PACKS}.\n"
        f"Check the installation without internet: python -m assistant_x.setup.install --venv <temporary folder> --no-register"
    )


if __name__ == "__main__":
    from assistant_x.core import debuglog

    debuglog.run(main, "prepare_media")
