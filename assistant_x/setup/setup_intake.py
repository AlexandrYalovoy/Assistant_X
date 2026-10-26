# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Installation of the intake on this PC (assistant-x setup-intake): the Python packages into the project environment,
LibreOffice and Tesseract with the languages of the packs, 7-Zip and DjVuLibre (when possible); the paths found go to
assistant_x.local.toml of the workspace (this PC, not in Git). Installs without administrator rights, into the user folder: winget in
user mode, otherwise the winget installer is unpacked (LibreOffice: msiexec /a, Tesseract and DjVuLibre: 7-Zip; winget
checks the hash of what it downloads), the Tesseract languages are downloaded from github.com/tesseract-ocr. What fails
to install, the intake works without: DOC/DOCX are skipped with a note, scans without OCR are marked, DjVu is skipped
with a note.
Usage: python -m assistant_x.setup.setup_intake [--dry-run] [--no-install]"""

import argparse, os, shutil, subprocess, sys, tempfile
from pathlib import Path

from assistant_x.core import lang, workspace
from assistant_x.intake import config as intake_cfg

CODE = Path(__file__).resolve().parents[2]  # the folder with pyproject.toml: the extra "intake" lists the packages
IMPORTS = "import pymupdf, pymupdf4llm, psutil; print(pymupdf.__version__)"
PROGRAMS = intake_cfg.LOCAL / "Programs"
TESSDATA_URL = "https://github.com/tesseract-ocr/tessdata/raw/main/{}.traineddata"


def say(msg=""):
    print(msg, flush=True)


def sh(cmd, timeout=1800):
    try:
        p = subprocess.run(
            [str(c) for c in cmd], capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace"
        )
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def python_packages(dry, install):
    rc, out = sh([sys.executable, "-c", IMPORTS], 300)
    if rc == 0:
        say(f"Python packages of the intake: present (PyMuPDF {out.splitlines()[-1]}), environment {sys.prefix}")
        return True
    say(f"Python packages of the intake: missing ({out.splitlines()[-1] if out else 'import error'})")
    if dry or not install:
        say(f'  to install: {sys.executable} -m pip install -e "{CODE}[intake]"')
        return False
    rc, out = sh([sys.executable, "-m", "pip", "install", "-e", f"{CODE}[intake]"], 3600)
    say("  installed" if rc == 0 else f"  pip failed: {out[-400:]}")
    return rc == 0


def winget(*args):
    if not shutil.which("winget"):
        return 1, "no winget"
    return sh(
        ["winget", *args, "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"], 3600
    )


def winget_download(pkg, folder, ext):
    rc, out = winget("download", "--id", pkg, "-d", folder)
    found = sorted(Path(folder).glob(f"*{ext}"))
    return found[0] if found else None


def install_libreoffice(tmp):
    rc, out = winget("install", "--id", "TheDocumentFoundation.LibreOffice", "--scope", "user", "--silent")
    if intake_cfg.find_soffice():
        return "winget (user)"
    msi = winget_download("TheDocumentFoundation.LibreOffice", tmp / "lo", ".msi")
    if not msi:
        return None
    # administrative install: unpacks the program into a folder, no administrator rights needed
    rc, out = sh(["msiexec", "/a", msi, "/qn", f"TARGETDIR={PROGRAMS / 'LibreOffice'}"], 3600)
    return "msiexec /a into " + str(PROGRAMS / "LibreOffice") if intake_cfg.find_soffice() else None


def install_tesseract(tmp, sevenzip):
    rc, out = winget("install", "--id", "UB-Mannheim.TesseractOCR", "--scope", "user", "--silent")
    if intake_cfg.find_tesseract():
        return "winget (user)"
    exe = winget_download("UB-Mannheim.TesseractOCR", tmp / "tess", ".exe")
    if not exe:
        return None
    dst = PROGRAMS / "Tesseract-OCR"
    if sevenzip:  # the NSIS installer is an archive: unpacked, no administrator rights needed
        sh([sevenzip, "x", "-y", f"-o{dst}", exe], 1800)
    else:
        sh([exe, "/S", f"/D={dst}"], 1800)  # may ask for administrator rights
    return f"unpacked into {dst}" if intake_cfg.find_tesseract() else None


PACKAGES = {  # Linux and macOS: the package of each program by package manager (nothing is installed by the setup)
    "apt-get": {
        "soffice": ["libreoffice"],
        "tesseract": ["tesseract-ocr"],
        "sevenzip": ["p7zip-full"],
        "ddjvu": ["djvulibre-bin"],
        "lang": "tesseract-ocr-{}",
    },
    "dnf": {
        "soffice": ["libreoffice"],
        "tesseract": ["tesseract"],
        "sevenzip": ["p7zip", "p7zip-plugins"],
        "ddjvu": ["djvulibre"],
        "lang": "tesseract-langpack-{}",
    },
    "brew": {
        "soffice": ["--cask libreoffice"],
        "tesseract": ["tesseract", "tesseract-lang"],
        "sevenzip": ["p7zip"],
        "ddjvu": ["djvulibre"],
        "lang": None,
    },
}
SUDO = {"apt-get": "sudo apt-get install", "dnf": "sudo dnf install", "brew": "brew install"}


def install_hint(missing, langs=(), which=shutil.which):
    """The command of the package manager of this system that installs the missing programs ("soffice", "tesseract",
    "sevenzip", "ddjvu") and the OCR languages; "" when nothing is missing or no package manager is known."""
    pm = next((m for m in PACKAGES if which(m)), None)
    if not pm or not (missing or langs):
        return ""
    p = PACKAGES[pm]
    pkgs = [x for k in missing for x in p[k]] + ([p["lang"].format(code) for code in langs] if p["lang"] else [])
    casks = [x for x in pkgs if x.startswith("--cask")]
    lines = (
        [f"{SUDO[pm]} {' '.join(dict.fromkeys(x for x in pkgs if not x.startswith('--cask')))}"]
        if len(casks) < len(pkgs)
        else []
    )
    return "\n".join(lines + [f"{SUDO[pm]} {c}" for c in casks])


def install_djvulibre(tmp, sevenzip):
    """DjVuLibre (ddjvu: DjVu -> PDF): winget in user mode, else its NSIS installer unpacked by 7-Zip into
    %LOCALAPPDATA%\\Programs\\DjVuLibre (nothing is run, no administrator rights)."""
    rc, out = winget("install", "--id", "DjVuLibre.DjView", "--scope", "user", "--silent")
    if intake_cfg.find_ddjvu():
        return "winget (user)"
    exe = winget_download("DjVuLibre.DjView", tmp / "djvu", ".exe")
    if not exe or not sevenzip:
        return None
    dst = PROGRAMS / "DjVuLibre"
    rc, out = sh([sevenzip, "x", "-y", f"-o{dst}", exe], 1800)
    return f"unpacked into {dst}" if intake_cfg.find_ddjvu() else None


def languages(tessdata, dry, install):
    have = {p.name[:-12] for p in Path(tessdata).glob("*.traineddata")}
    for code in lang.tesseract().split("+"):  # the "tesseract" codes of the language packs in use
        if code in have:
            continue
        say(f"  no language {code} in {tessdata}")
        if dry or not install:
            continue
        from assistant_x.setup import downloads

        url, sha = downloads.TESSDATA.get(code) or (TESSDATA_URL.format(code), None)
        try:
            downloads.fetch(url, sha, Path(tessdata) / f"{code}.traineddata", say=say)
            say(f"  language {code} downloaded" + ("" if sha else " (no sha256 pinned for it: only made whole)"))
        except (OSError, SystemExit) as e:
            say(f"  language {code} not downloaded: {e}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="assistant-x setup-intake", description="Installation of the intake on the PC")
    ap.add_argument("--dry-run", action="store_true", help="only check and show what would be done")
    ap.add_argument("--no-install", action="store_true", help="install nothing, only find and write down the paths")
    a = ap.parse_args(argv)
    install = not a.no_install and os.name == "nt"
    say(f"Workspace: {workspace.current().root}")
    ok_py = python_packages(a.dry_run, not a.no_install)
    tmp = Path(tempfile.mkdtemp(prefix="ax_setup_"))
    sevenzip = intake_cfg.find_sevenzip()
    if not sevenzip and install and not a.dry_run:
        winget("install", "--id", "7zip.7zip", "--scope", "user", "--silent")
        sevenzip = intake_cfg.find_sevenzip()
    say(f"7-Zip: {sevenzip or 'none (zip is unpacked without it, 7z and rar are not)'}")
    soffice = intake_cfg.find_soffice()
    if not soffice and install and not a.dry_run:
        say("LibreOffice: installing (this takes a few minutes)…")
        how = install_libreoffice(tmp)
        soffice = intake_cfg.find_soffice()
        say(f"  {how}" if how else "  installation failed")
    say(f"LibreOffice: {soffice or 'MISSING — DOC/DOCX/PPTX will be skipped with a note'}")
    tess = intake_cfg.find_tesseract()
    if not tess and install and not a.dry_run:
        say("Tesseract: installing…")
        how = install_tesseract(tmp, sevenzip)
        tess = intake_cfg.find_tesseract()
        say(f"  {how}" if how else "  installation failed")
    tessdata = intake_cfg.find_tessdata(None, tess)
    if tessdata:
        languages(tessdata, a.dry_run, install or not a.no_install)
    cfg_like = {"tesseract": tess, "tessdata": tessdata}
    langs = intake_cfg.ocr_languages(cfg_like)
    say(
        f"Tesseract: {tess or 'MISSING'}; languages: {', '.join(langs) or '—'}"
        + ("" if intake_cfg.can_ocr(cfg_like) else " — scans will have no OCR and are marked")
    )
    ddjvu = intake_cfg.find_ddjvu()
    if not ddjvu and install and not a.dry_run:
        say("DjVuLibre: installing…")
        how = install_djvulibre(tmp, sevenzip)
        ddjvu = intake_cfg.find_ddjvu()
        say(f"  {how}" if how else "  installation failed")
    say(f"DjVuLibre: {ddjvu or 'MISSING — DjVu files will be skipped with a note'}")
    if not a.dry_run:
        intake_cfg.save(
            {
                "soffice": soffice or "",
                "tesseract": tess or "",
                "tessdata": tessdata or "",
                "sevenzip": sevenzip or "",
                "ddjvu": ddjvu or "",
            }
        )
        say(f"The paths are written to {intake_cfg.local_path()}")
    try:
        os.rmdir(tmp)
    except OSError:
        pass  # downloaded installers stay in TEMP; Windows cleans it
    if os.name != "nt":  # Linux, macOS: the setup installs nothing; it says what to install
        missing = [
            k for k, v in (("soffice", soffice), ("tesseract", tess), ("sevenzip", sevenzip), ("ddjvu", ddjvu)) if not v
        ]
        need = [x for x in lang.tesseract().split("+") if x not in langs] if tess else []
        hint = install_hint(missing, need)
        if hint:
            say("To install what is missing (then run assistant-x setup-intake again):\n" + hint)
        elif missing:
            say(f"Missing: {', '.join(missing)}; install them with the package manager of this system.")
    ready = ok_py and soffice and intake_cfg.can_ocr(cfg_like)
    say(
        "The intake is ready: intake.bat (or assistant-x intake run)."
        if ready
        else "The intake will work with limits (see above)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
