# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""The layout of a medium (prepare-media writes it, Setup.bat and setup/install.py read it, the tests check it) and
what it carries besides the program: the programs of the intake and where their source code is.

    MEDIUM\Setup.bat, README.txt
    MEDIUM\app\                         APP_DIR: the program
    MEDIUM\packages\                    PACKAGES_DIR: wheels\ (WHEELS), wheels_gpu\ (WHEELS_GPU), wheels_dml\
                                         (WHEELS_DML), requirements-lock.txt (LOCK_FILE), python_version.txt
                                         (PYVER_FILE), THIRD_PARTY_LICENSES.txt (THIRD_PARTY), python-<ver>-amd64.exe
    MEDIUM\models\                      MODELS_DIR: a folder per model, onnx\ (ONNX_DIR: the ONNX export for
                                         DirectML), MODELS.json
    MEDIUM\programs\                    PROGRAMS_DIR: the programs of the intake, VERSIONS.txt, sources\ (SOURCES_DIR)
    MEDIUM\base\                        BASE_DIR: a base package

The programs of the intake on a medium (collect_programs) are distributed under their own licenses. Two of them are
copyleft and need their source code with the binaries: DjVuLibre (GPL-2.0-or-later, section 3) and 7-Zip (LGPL-2.1,
section 6). prepare-media puts their source archives, pinned by sha256, into programs\sources\ of the medium
(program_sources); LibreOffice (MPL-2.0) and Tesseract (Apache-2.0) are listed with the place of their source.

    SOURCES          program -> {version: {url, file, sha256}} of the source archives shipped on a medium
    SOURCE_PAGES     program -> the page of the source of a version (only told, not shipped)
    VC_RUNTIME       the terms of the Microsoft Visual C++ runtime DLLs beside LibreOffice and DjVuLibre"""

import os

APP_DIR, PACKAGES_DIR, MODELS_DIR, PROGRAMS_DIR, BASE_DIR = "app", "packages", "models", "programs", "base"
WHEELS, WHEELS_GPU, WHEELS_DML = "wheels", "wheels_gpu", "wheels_dml"  # in packages
LOCK_FILE, PYVER_FILE, THIRD_PARTY = "requirements-lock.txt", "python_version.txt", "THIRD_PARTY_LICENSES.txt"
ONNX_DIR, SOURCES_DIR = "onnx", "sources"  # in models, in programs
HASHED_REQ = "requirements.txt"  # in wheels_gpu and wheels_dml: their wheel with its sha256 (pip --require-hashes)
TORCH_GPU_GLOB, DML_GLOB = "torch-*cu128*.whl", "onnxruntime_directml-*.whl"  # the wheels the installer looks for
ONNX_EMBEDDER = (ONNX_DIR, "bge-m3", "model.onnx")  # what DirectML needs, under a models folder

SOURCES = {
    # sourceforge.net/projects/djvu: the release whose Windows build collect_programs bundles (3.5.29 + DjView 4.12);
    # sha256 of the download of 2026-10-26
    "DjVuLibre": {
        "3.5.29": {
            "url": "https://sourceforge.net/projects/djvu/files/DjVuLibre/3.5.29/djvulibre-3.5.29.tar.gz/download",
            "file": "djvulibre-3.5.29.tar.gz",
            "sha256": "d3b4b03ae2bdca8516a36ef6eb27b777f0528c9eda26745d9962824a3fdfeccf",
        }
    },
    # github.com/ip7z/7zip (linked from 7-zip.org/download.html): the version of the 7-Zip of the build PC is copied,
    # so every version a medium may carry needs its row here (prepare-media stops on one it has not)
    "7-Zip": {
        "26.05": {
            "url": "https://github.com/ip7z/7zip/releases/download/26.05/7z2605-src.tar.xz",
            "file": "7z2605-src.tar.xz",
            "sha256": "0b6080b8c3e7a579161d2d495224c0e51c467576cb4c7048b0ab485ef44cc22e",
        }
    },
}
SOURCE_PAGES = {
    "Tesseract-OCR": "https://github.com/tesseract-ocr/tesseract/archive/refs/tags/{v}.tar.gz",
    "LibreOffice": "https://download.documentfoundation.org/libreoffice/src/{v}/",
}
LICENSES = {
    "Tesseract-OCR": "Apache-2.0",
    "LibreOffice": "MPL-2.0",
    "7-Zip": "LGPL-2.1-or-later with the unRAR restriction",
    "DjVuLibre": "GPL-2.0-or-later",
}
VC_RUNTIME = (
    "The Microsoft Visual C++ runtime DLLs beside LibreOffice and DjVuLibre (vcruntime140.dll, msvcp140.dll "
    "and the like) are Microsoft's redistributable files: distributed unmodified and only with the programs "
    "that use them, under the Microsoft Software License Terms of Visual Studio (Distributable Code)."
)


DJVU = "3.5.29"  # the DjVuLibre of collect_programs (its Windows build 3.5.29 + DjView 4.12)


def bundled(programs):
    """{program: version} of the copyleft programs in a programs folder: 7-Zip as its 7z.exe reports it, DjVuLibre
    as collect_programs bundles it."""
    import re, subprocess

    out = {}
    exe = os.path.join(programs, "7-Zip", "7z.exe")
    if os.path.isfile(exe):
        try:
            p = subprocess.run(
                [exe],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=60,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            m = re.search(r"7-Zip (?:\(a\) )?(\d+\.\d+)", p.stdout or "")
        except (OSError, subprocess.TimeoutExpired):
            m = None
        if not m:
            raise SystemExit(f"{exe} does not tell its version: its source archive cannot be chosen")
        out["7-Zip"] = m[1]
    if os.path.isfile(os.path.join(programs, "DjVuLibre", "ddjvu.exe")):
        out["DjVuLibre"] = DJVU
    return out


def source_of(program, version):
    """{url, file, sha256} of the source archive of a program version shipped on a medium, or None."""
    return (SOURCES.get(program) or {}).get(version)


def source_line(program, version):
    """Where the source code of a program version is, for VERSIONS.txt and THIRD_PARTY_LICENSES.txt."""
    s = source_of(program, version)
    if s:
        return f"source code: {SOURCES_DIR}/{s['file']} on this medium (from {s['url']})"
    page = SOURCE_PAGES.get(program)
    if page and version:
        return f"source code: {page.format(v=version)}"
    return "source code: the project page of the program"
