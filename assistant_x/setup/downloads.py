# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Downloads of the installation that run or install something: never trusted on TLS alone.

    fetch(url, sha256, path)       to path.part, checked against the sha256 pinned here, then renamed: a broken or
                                   changed file never takes the final name (it is removed)
    sha256(path)
    signed_by(path, publisher)     Windows: the Authenticode signature of an installer is valid and of publisher
    TESSDATA                       the languages of Tesseract the program installs, pinned
    sums(folder, names), check_sums(folder)   SHA256SUMS.txt of a folder of a medium (the Python installer: Setup.bat
                                   checks it before running it)

Standard library only (setup_intake and the installer use it)."""

import hashlib, os, subprocess, urllib.request

# languages: rus from tessdata (LSTM + legacy), eng and osd from tessdata_fast; unchanged since Tesseract 5.4
TESSDATA = {
    "rus": (
        "https://github.com/tesseract-ocr/tessdata/raw/main/rus.traineddata",
        "681be2c2bead1bc7bd235df88c44e8e60ae73ae866840c0ad4e3b4c247bd37c2",
    ),
    "eng": (
        "https://github.com/tesseract-ocr/tessdata_fast/raw/main/eng.traineddata",
        "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
    ),
    "osd": (
        "https://github.com/tesseract-ocr/tessdata_fast/raw/main/osd.traineddata",
        "9cf5d576fcc47564f11265841e5ca839001e7e6f38ff7f7aacf46d15a96b00ff",
    ),
}
SUMS = "SHA256SUMS.txt"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(url, sha, path, say=print):
    """url -> path through path.part; SystemExit (the part removed) unless its sha256 is sha. sha None: no pin (a
    language of a pack of the user's own): the file is only made whole (.part, then renamed) and the caller says so."""
    path = str(path)
    part = path + ".part"
    say(f"  downloading {url}")
    try:
        urllib.request.urlretrieve(url, part)
        got = sha256(part)
        if sha and got != sha:
            raise SystemExit(f"sha256 of {url} is {got}, expected {sha}: not used")
        os.replace(part, path)
    finally:
        if os.path.exists(part):
            os.remove(part)
    return path


def signed_by(path, publisher):
    """'' when the Authenticode signature of path is valid and its signer names publisher (Windows), else why not."""
    if os.name != "nt":
        return "not Windows: the signature cannot be checked"
    cmd = (
        "$s = Get-AuthenticodeSignature -LiteralPath $env:AX_SIGNED_FILE; "
        "Write-Output ($s.Status.ToString() + '|' + $s.SignerCertificate.Subject)"
    )
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=120,
            env=dict(os.environ, AX_SIGNED_FILE=str(path)),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"the signature could not be checked ({e})"
    status, _, subject = (p.stdout or "").strip().partition("|")
    if status != "Valid" or publisher not in subject:
        return f"signature {status or '?'} of {subject or 'nobody'}"
    return ""


def sums(folder, names):
    """SHA256SUMS.txt of these files of folder ("<sha256> *<name>", the format of sha256sum)."""
    with open(os.path.join(folder, SUMS), "w", encoding="utf-8", newline="\n") as f:
        for n in sorted(names):
            f.write(f"{sha256(os.path.join(folder, n))} *{n}\n")


def check_sums(folder):
    """[problems] of the files of SHA256SUMS.txt of folder."""
    out = []
    try:
        lines = open(os.path.join(folder, SUMS), encoding="utf-8").read().splitlines()
    except OSError:
        return [f"no {SUMS} in {folder}"]
    for line in lines:
        want, _, name = line.partition(" *")
        p = os.path.join(folder, name)
        if not name:
            continue
        if not os.path.isfile(p):
            out.append(f"{name}: missing")
        elif sha256(p) != want:
            out.append(f"{name}: another sha256")
    return out
