# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""programs for the archive: copies of the Tesseract, LibreOffice and 7-Zip installed on this PC (setup_intake puts
them in %LOCALAPPDATA%\Programs), trimmed to what the intake needs; they run from the folder, no installation.
intake_cfg.find_* look there first. programs is not in Git; it is for an offline media (with assistant_x.setup.prepare_media).
Tesseract can instead come from its official installer (--tesseract-setup), checked by sha256 and unpacked with 7-Zip,
nothing installed; the languages are the files below, checked by sha256 too.
Usage: python -m assistant_x.setup.collect_programs [--dst DIR]      (the folder must not exist yet: delete the old one yourself)
       python -m assistant_x.setup.collect_programs --only tesseract --tesseract-setup [EXE]   one program into an existing DST
                                                          (DST/Tesseract-OCR must not exist; no EXE: TESS_URL is downloaded)
       python -m assistant_x.setup.collect_programs --versions     only rewrite programs/VERSIONS.txt (and SHA256SUMS.txt)
VERSIONS.txt says what each program is, its license and where its source is; SHA256SUMS.txt gives the sha256 of every
file of the folder, so a medium can be checked later (also of the programs copied from this PC, which no download
pins)."""

import argparse, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

from assistant_x.intake import config as intake_cfg
from assistant_x.setup import downloads, medium as M

L = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Programs"
SZ = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "7-Zip"
# the Tesseract of the archive: UB-Mannheim build from the releases of github.com/tesseract-ocr/tesseract
TESS_VERSION = "5.5.3.20260724"
TESS_URL = "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/tesseract-ocr-w64-setup-5.5.3.20260724.exe"
TESS_SHA256 = "bee9e3434bd94fd65387d9be28cd467a41f61b1275383b55b0f59a1331270ae4"
TESSDATA = downloads.TESSDATA  # the languages, pinned by sha256 (setup/downloads.py)
# DjVuLibre (ddjvu: DjVu -> PDF): the official Windows installer of sourceforge.net/projects/djvu (the hash of the
# winget manifest DjVuLibre.DjView, checked on the download of 2026-10-25), unpacked by 7-Zip, nothing run
DJVU_VERSION = "3.5.29 (DjView 4.12)"
DJVU_URL = (
    "https://sourceforge.net/projects/djvu/files/DjVuLibre_Windows/3.5.29+4.12/"
    "DjVuLibre-3.5.29_DjView-4.12_Setup.exe/download"
)
DJVU_SHA256 = "92233fbf891c63f3fb7a0b5e1ce108baa4c29a40c89a442d1313f883aae84670"
PART = {"tesseract": "Tesseract-OCR", "libreoffice": "LibreOffice", "7zip": "7-Zip", "djvulibre": "DjVuLibre"}
SUMS = downloads.SUMS  # SHA256SUMS.txt of the programs folder


def versions(dst):
    """VERSIONS.txt: what is inside, the version each program reports, the licence (THIRD_PARTY_LICENSES of the archive)."""

    def out(cmd):
        try:
            p = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return ((p.stdout or "") + (p.stderr or "")).strip().splitlines()[0]
        except (OSError, IndexError, subprocess.TimeoutExpired) as e:
            return f"did not start: {e}"

    tess, lo, sz = (
        out([dst / "Tesseract-OCR" / "tesseract.exe", "--version"]),
        out([dst / "LibreOffice" / "program" / "soffice.com", "--version"]),
        out([dst / "7-Zip" / "7z.exe"]),
    )

    def version(text, rx):
        m = re.search(rx, text)
        return m[1] if m else ""

    lines = [
        "Programs of the document intake: they run from this folder, no installation needed. Each is distributed",
        "under its own license; where its source code is, is said on its line.",
        "",
        f"Tesseract-OCR   {tess}; languages rus, eng, osd. License {M.LICENSES['Tesseract-OCR']} "
        "(github.com/tesseract-ocr/tesseract), UB-Mannheim build; "
        + M.source_line("Tesseract-OCR", version(tess, r"tesseract v?(\d+\.\d+\.\d+)"))
        + ".",
        f"LibreOffice     {lo}; without help, dictionaries ru and en. License {M.LICENSES['LibreOffice']} "
        "(LibreOffice/LICENSE.html); " + M.source_line("LibreOffice", version(lo, r"(\d+\.\d+\.\d+)")) + ".",
        f"7-Zip           {sz}. License {M.LICENSES['7-Zip']} (7-Zip/License.txt); "
        + M.source_line("7-Zip", version(sz, r"7-Zip (\d+\.\d+)"))
        + ".",
        f"DjVuLibre       {DJVU_VERSION}: ddjvu and the command-line tools, without the DjView viewer. License "
        f"{M.LICENSES['DjVuLibre']} (DjVuLibre/COPYING.txt); " + M.source_line("DjVuLibre", M.DJVU) + ".",
        "",
        M.VC_RUNTIME,
        "",
        f"The source archives of DjVuLibre (GPL) and 7-Zip (LGPL) are in {M.SOURCES_DIR}/ beside this file when the",
        "medium was made with them (prepare-media without --no-sources). Whoever passes on a medium without them",
        "must give the source code of these two programs with it, or a written offer to give it, as their",
        "licenses require.",
        "",
    ]
    lines += [f"The sha256 of every file of this folder: {SUMS}.", ""]
    (dst / "VERSIONS.txt").write_text("\n".join(lines), encoding="utf-8-sig")
    print("\n".join(lines))
    write_sums(dst)


def write_sums(dst):
    """SHA256SUMS.txt of every file of the programs folder ("<sha256> *<path with />"), the source archives aside (they
    are pinned in medium.SOURCES) and the two files of the description."""
    lines = []
    for dp, dns, fns in os.walk(dst):
        dns[:] = sorted(d for d in dns if not (Path(dp) == Path(dst) and d == M.SOURCES_DIR))
        for f in sorted(fns):
            rel = os.path.relpath(os.path.join(dp, f), dst).replace(os.sep, "/")
            if rel not in (SUMS, "VERSIONS.txt"):
                lines.append(f"{downloads.sha256(os.path.join(dp, f))} *{rel}")
    (Path(dst) / SUMS).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return len(lines)


def sha256(path):
    return downloads.sha256(path)


def fetch(url, sha, path):
    """url -> path (through path.part), refused unless its sha256 is the expected one."""
    downloads.fetch(url, sha, path)


def tesseract_setup(tmp, given, dst):
    """The official installer (given: its path, or "download"), checked by sha256, unpacked by 7-Zip (nothing
    installed); its folder with our languages."""
    exe = Path(given) if given != "download" else tmp / TESS_URL.rsplit("/", 1)[1]
    if given == "download":
        fetch(TESS_URL, TESS_SHA256, exe)
    elif sha256(exe) != TESS_SHA256:
        sys.exit(f"{exe}: sha256 is not {TESS_SHA256} (TESS_SHA256 — the installer of {TESS_VERSION})")
    out = tmp / "Tesseract-OCR"
    sz = next((p for p in (SZ / "7z.exe", dst / "7-Zip" / "7z.exe") if p.is_file()), SZ / "7z.exe")
    p = subprocess.run(
        [str(sz), "x", "-y", f"-o{out}", str(exe)],
        capture_output=True,
        text=True,
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if p.returncode:
        sys.exit(f"7-Zip did not unpack {exe}:\n{p.stdout}{p.stderr}")
    for lang, (url, sha) in TESSDATA.items():
        have = L / "Tesseract-OCR" / "tessdata" / f"{lang}.traineddata"
        if have.is_file() and sha256(have) == sha:
            shutil.copy2(have, out / "tessdata" / have.name)
        else:
            fetch(url, sha, out / "tessdata" / have.name)
    return out


def copy(src, dst, keep):
    n = b = 0
    for dp, dns, fns in os.walk(src):
        rel = Path(dp).relative_to(src)
        dns[:] = [d for d in dns if keep(rel / d, True)]
        for f in fns:
            if keep(rel / f, False):
                (dst / rel).mkdir(parents=True, exist_ok=True)
                shutil.copy2(Path(dp) / f, dst / rel / f)
                n += 1
                b += (dst / rel / f).stat().st_size
    print(f"{dst.name}: {n} files, {b / 2**20:.0f} MB")


# Tesseract: the program, its DLLs, rus/eng/osd, configs; no training tools, docs or Java viewer
TRAIN = {
    "ambiguous_words",
    "classifier_tester",
    "cntraining",
    "combine_lang_model",
    "combine_tessdata",
    "dawg2wordlist",
    "lstmeval",
    "lstmtraining",
    "merge_unicharsets",
    "mftraining",
    "set_unicharset_properties",
    "shapeclustering",
    "text2image",
    "unicharset_extractor",
    "wordlist2dawg",
    "uninstall",
    "winpath",
}


def tess(rel, isdir):
    p = rel.parts
    if isdir:
        return p[0] in ("tessdata",) and (len(p) == 1 or p[1] in ("configs", "tessconfigs"))
    if len(p) == 1:
        stem, ext = rel.stem.lower(), rel.suffix.lower()
        return ext == ".dll" or (ext == ".exe" and stem not in TRAIN) or rel.name.lower() in ("license", "license.txt")
    if p[0] == "tessdata" and len(p) == 2:
        return rel.name in ("rus.traineddata", "eng.traineddata", "osd.traineddata", "pdf.ttf")
    return True


# LibreOffice: no help, no installer copy, dictionaries only ru and en, icon themes only colibre (the default)
def lo(rel, isdir):
    p, name = rel.parts, rel.name.lower()
    if isdir:
        if p[0] in ("help", "System"):
            return False
        if len(p) == 3 and p[:2] == ("share", "extensions") and name.startswith("dict-"):
            return name in ("dict-ru", "dict-en")
        return True
    if name.endswith(".msi"):
        return False
    if len(p) == 3 and p[:2] == ("share", "config") and name.startswith("images_"):
        return name.startswith("images_colibre")
    return True


# DjVuLibre: the command-line tools and their DLLs (no viewer, no Qt, no installer leftovers)
def djvu(rel, isdir):
    name = rel.name.lower()
    if isdir:
        return False
    if name.endswith(".exe"):
        return name not in ("djview.exe", "uninst.exe", "vcredist_x86.exe")
    return (name.endswith(".dll") and not name.startswith(("qt5", "libssl", "libcrypto"))) or name == "copying.txt"


def djvu_setup(tmp, dst):
    """The installer, checked by sha256, unpacked by 7-Zip."""
    exe = tmp / "djvulibre_setup.exe"
    fetch(DJVU_URL, DJVU_SHA256, exe)
    out = tmp / "DjVuLibre"
    sz = next((p for p in (SZ / "7z.exe", dst / "7-Zip" / "7z.exe") if p.is_file()), SZ / "7z.exe")
    p = subprocess.run(
        [str(sz), "x", "-y", f"-o{out}", str(exe)],
        capture_output=True,
        text=True,
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if p.returncode:
        sys.exit(f"7-Zip did not unpack {exe}:\n{p.stdout}{p.stderr}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m assistant_x.setup.collect_programs")
    ap.add_argument("--dst", default=str(intake_cfg.programs_dir()))
    ap.add_argument("--versions", action="store_true")
    ap.add_argument("--only", choices=tuple(PART))
    ap.add_argument("--tesseract-setup", nargs="?", const="download", metavar="EXE")
    a = ap.parse_args(argv)
    dst = Path(a.dst)
    if a.versions:
        versions(dst)
        return 0
    if a.only and (dst / PART[a.only]).exists():
        sys.exit(f"{dst / PART[a.only]} exists already: rename or delete the folder yourself")
    if not a.only and dst.exists():
        sys.exit(f"{dst} exists already: delete the folder yourself or give another one (--dst)")
    if a.only in (None, "tesseract"):
        if a.tesseract_setup:
            with tempfile.TemporaryDirectory() as tmp:  # only the unpacked installer: removed with the temp folder
                copy(tesseract_setup(Path(tmp), a.tesseract_setup, dst), dst / "Tesseract-OCR", tess)
        else:
            copy(L / "Tesseract-OCR", dst / "Tesseract-OCR", tess)
    if a.only in (None, "libreoffice"):
        copy(L / "LibreOffice", dst / "LibreOffice", lo)
        # the Visual C++ runtime of the administrative install (System64) beside soffice: a PC without it still starts it
        for f in (L / "LibreOffice" / "System64").iterdir():
            t = dst / "LibreOffice" / "program" / f.name
            if not t.exists():
                shutil.copy2(f, t)
        shutil.rmtree(dst / "LibreOffice" / "System64")  # only in the copy just made: the runtime now lives in program
        print("VC++ runtime -> LibreOffice/program")
    if a.only in (None, "7zip"):  # the console program, its DLL, the license
        (dst / "7-Zip").mkdir(parents=True)
        for f in ("7z.exe", "7z.dll", "License.txt", "readme.txt"):
            shutil.copy2(SZ / f, dst / "7-Zip" / f)
        print("7-Zip: 4 files")
    if a.only in (None, "djvulibre"):
        if (L / "DjVuLibre" / "ddjvu.exe").is_file():
            copy(L / "DjVuLibre", dst / "DjVuLibre", djvu)
        else:
            with tempfile.TemporaryDirectory() as tmp:
                copy(djvu_setup(Path(tmp), dst), dst / "DjVuLibre", djvu)
        wow = Path(os.environ.get("WINDIR", r"C:\Windows")) / "SysWOW64"  # the x86 runtime the tools are built with
        for f in ("vcruntime140.dll", "msvcp140.dll"):
            if (wow / f).is_file() and not (dst / "DjVuLibre" / f).exists():
                shutil.copy2(wow / f, dst / "DjVuLibre" / f)
    versions(dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
