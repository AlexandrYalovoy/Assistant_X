# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""Settings of the intake on this PC: the [intake] table of assistant_x.toml (core/config.py), the folders of the
workspace (core/workspace.py), overridden by AX_* environment variables. Every intake module takes its paths only
from here.

  AX_CONFIG         another assistant_x.toml
  AX_INBOX, AX_LIBRARY, AX_INDEX, AX_WORK, AX_REPORTS               folders
  AX_SOFFICE, AX_TESSERACT, AX_TESSDATA, AX_SEVENZIP, AX_DDJVU      programs ("-" = do not use)
  AX_WORKERS, AX_OCR_THREADS, AX_WORKER_MEMORY_MB                   numbers
  AX_STAGE_MODE     "inproc" (persistent workers, pool.py) | "subprocess" (a python process per tool, the old way)
  AX_PRIORITY       "below_normal" | "idle" | "normal"; AX_AFFINITY "auto" | "ecores" | "all" | "8,9,10" (balance.py)
  AX_PROFILE        "auto" | "weak" | "night" (balance.py)
  AX_PROGRAMS       the folder of the bundled programs (default: %USERPROFILE%\.assistant_x\programs)

Programs are looked for in this order: the bundled programs folder (portable copies of an offline media), the path in
the settings, the usual install folders, PATH. Paths of programs on this PC go to assistant_x.local.toml (not in Git).
"""

import os, re, shutil, sys, unicodedata
from pathlib import Path

from assistant_x.core import config as settings, env, lang, workspace
from assistant_x.core.txn import lp  # noqa: F401 — intake_cfg.lp for the intake modules

FOLDERS = ("inbox", "library", "index", "work", "reports")
PROGRAMS = settings.LOCAL_KEYS
STAGE_MODES = ("inproc", "subprocess")
# service folders of inbox: never scanned, never removed
SERVICE = ("_duplicates", "_to_delete", "_rejected")
# files of programs, not documents: build sends them to _rejected\programs when meta.jsonl has no line for them; a
# domain profile adds the files of the programs of its field (program_ext of profiles/<name>/documents.json),
# [intake] program_ext replaces the whole list
PROGRAM_EXT = ("exe", "dll", "msi")
LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
BUNDLED = {
    "soffice": Path("LibreOffice") / "program",
    "tesseract": Path("Tesseract-OCR"),
    "sevenzip": Path("7-Zip"),
    "ddjvu": Path("DjVuLibre"),
}
PF = [Path(os.environ.get(k)) for k in ("ProgramFiles", "ProgramFiles(x86)") if os.environ.get(k)]


class Config(dict):
    __getattr__ = dict.__getitem__


def config_path():
    """The settings file in use: assistant_x.toml of the workspace, or the file of AX_CONFIG."""
    return settings.config_path()


def local_path(path=None):
    """The settings of this PC only (paths of programs), not in Git: assistant_x.local.toml."""
    return settings.local_of(Path(path or config_path()))


def programs_dir():
    """The programs that come with an offline media (Tesseract, LibreOffice, 7-Zip): one folder per PC."""
    return Path(env.get("PROGRAMS") or workspace.machine_dir() / "programs")


def load(path=None):
    path = Path(path or config_path())
    w, all_raw = settings.load(path)
    raw, root = dict(all_raw["intake"]), w.root
    folders = {k: getattr(w, k) for k in FOLDERS}
    raw["domain_profile"] = all_raw["profile"]
    for k in FOLDERS + PROGRAMS + settings.INTAKE_INTS + ("stage_mode", "priority", "affinity"):
        v = env.get(k.upper())
        if v:
            if k in FOLDERS:
                folders[k] = (root / v).resolve()
            else:
                raw[k] = v
    cfg = Config(raw, path=path, root=root)
    cfg.update(folders)
    # the defaults are core/config.INTAKE, merged under the file by settings.load: none are repeated here
    default = settings.INTAKE
    for k in settings.INTAKE_INTS:
        cfg[k] = int(raw.get(k) or 0)
    cfg["stage_mode"] = raw.get("stage_mode") or default["stage_mode"]
    if cfg["stage_mode"] not in STAGE_MODES:
        sys.exit(f"{path}: stage_mode {cfg['stage_mode']!r}, one of these is needed: {', '.join(STAGE_MODES)}")
    from assistant_x.intake import balance

    if env.get("PROFILE"):
        raw["profile"] = env.get("PROFILE")
    cfg["priority"] = raw.get("priority") or default["priority"]
    cfg["affinity"] = raw.get("affinity", default["affinity"])
    try:
        balance.priority_class(cfg["priority"])
        balance.cpus(cfg["affinity"])
        cfg["balance"] = balance.options(raw)
    except ValueError as e:
        sys.exit(f"{path}: {e}")
    cfg["heavy_mb"] = float(raw.get("heavy_mb", default["heavy_mb"]))
    from assistant_x.intake import schedule

    cfg["ocr_shards"] = str(raw.get("ocr_shards") or default["ocr_shards"])
    if cfg["ocr_shards"] not in schedule.SHARD_MODES:
        sys.exit(f"{path}: ocr_shards {cfg['ocr_shards']!r}, one of these is needed: {', '.join(schedule.SHARD_MODES)}")
    cfg["timeouts"] = settings.merge(default["timeouts"], raw.get("timeouts"))
    cfg["unpack"] = settings.merge(default["unpack"], raw.get("unpack"))
    # free space before run: factor x the files of inbox and at least min_free_gb (core/common.free_space_problem)
    cfg["disk"] = settings.merge(default["disk"], raw.get("disk"))
    # [intake] personal = true: every batch is marked personal (intake.personal of its cards); by default false: the user's
    # documents go onto the same shelves as an installed base package (build --personal marks one batch on request)
    cfg["personal"] = bool(raw.get("personal", False))
    # [intake] to_delete_ext: the files of these extensions the user sends away, loose or out of an archive (prepare
    # moves them to _to_delete\<folder>\ keeping their folders, a line of the journal each): a list (the folder is the
    # extension: ["gsfx"]) or a table of extension = folder ({dwg = "dwg", cdw = "dwg", bak = "dwg"})
    given = raw.get("to_delete_ext") or {}
    pairs = given.items() if isinstance(given, dict) else ((e, str(e).lower().lstrip(".")) for e in given)
    cfg["to_delete_ext"] = {str(e).lower().lstrip("."): str(f).strip("\\/ ") or "other" for e, f in pairs}
    cfg["fingerprints"] = w.fingerprints  # the one cache of the duplicate check (tools/dupcheck.py), of the workspace
    cfg["ocr_vocab"] = root / ".assistant_x" / "ocr_vocab.txt"
    cfg["soffice"] = find_soffice(raw.get("soffice"))
    cfg["tesseract"] = find_tesseract(raw.get("tesseract"))
    cfg["tessdata"] = find_tessdata(raw.get("tessdata"), cfg["tesseract"])
    cfg["sevenzip"] = find_sevenzip(raw.get("sevenzip"))
    cfg["ddjvu"] = find_ddjvu(raw.get("ddjvu"))
    return cfg


def _first(given, names, places, bundled=()):
    """Path of a program: "-" = none; else the bundled copy (programs), the one given, the usual install folders,
    PATH. A given path that is not there (settings of another PC) does not stop the search."""
    if given == "-":
        return None
    for p in [*bundled, *([Path(given)] if given else []), *places]:
        if p.is_file():
            return str(p)
    for n in names:
        w = shutil.which(n)
        if w:
            return w
    return None


def find_soffice(given=None):
    # soffice.com waits for the conversion; soffice.exe returns at once
    exe = ("soffice.com", "soffice.exe") if os.name == "nt" else ("soffice", "libreoffice")
    dirs = [LOCAL / "Programs" / "LibreOffice" / "program"] + [p / "LibreOffice" / "program" for p in PF]
    found = _first(given, exe, [d / e for d in dirs for e in exe], [programs_dir() / BUNDLED["soffice"] / e for e in exe])
    if found and found.lower().endswith("soffice.exe") and Path(found).with_suffix(".com").is_file():
        found = str(Path(found).with_suffix(".com"))
    return found


def find_tesseract(given=None):
    exe = "tesseract.exe" if os.name == "nt" else "tesseract"
    dirs = [LOCAL / "Programs" / "Tesseract-OCR"] + [p / "Tesseract-OCR" for p in PF]
    return _first(given, ["tesseract"], [d / exe for d in dirs], [programs_dir() / BUNDLED["tesseract"] / exe])


def find_tessdata(given, tesseract):
    if given == "-":
        return None
    beside = [Path(tesseract).parent / "tessdata"] if tesseract else []
    first = beside if beside and programs_dir() in beside[0].parents else []  # the bundled Tesseract: its own languages
    for d in (
        first
        + ([Path(given)] if given else [])
        + ([Path(os.environ["TESSDATA_PREFIX"])] if os.environ.get("TESSDATA_PREFIX") else [])
        + beside
        + [Path("/usr/share/tesseract-ocr/5/tessdata"), Path("/usr/share/tesseract-ocr/4.00/tessdata")]
    ):
        if (d / "eng.traineddata").is_file():
            return str(d)
    return None


def find_sevenzip(given=None):
    exe = "7z.exe" if os.name == "nt" else "7z"
    return _first(
        given,
        ["7z", "7za"],
        [p / "7-Zip" / exe for p in PF] + [LOCAL / "Programs" / "7-Zip" / exe],
        [programs_dir() / BUNDLED["sevenzip"] / exe],
    )


def find_ddjvu(given=None):
    """ddjvu of DjVuLibre (DjVu -> PDF); None when it is not on this PC (a .djvu is then skipped with a note)."""
    exe = "ddjvu.exe" if os.name == "nt" else "ddjvu"
    dirs = [LOCAL / "Programs" / "DjVuLibre", LOCAL / "DjVuLibre"] + [p / "DjVuLibre" for p in PF]
    return _first(given, ["ddjvu"], [d / exe for d in dirs], [programs_dir() / BUNDLED["ddjvu"] / exe])


def ocr_languages(cfg):
    """Languages in tessdata: OCR needs those of the document languages (core/lang.tesseract())."""
    d = cfg.get("tessdata")
    return sorted(p.name[:-12] for p in Path(d).glob("*.traineddata")) if d else []


def can_ocr(cfg):
    return bool(cfg.get("tesseract") and set(lang.tesseract().split("+")) <= set(ocr_languages(cfg)))


def tool_env(cfg):
    """Environment of the tool processes: Tesseract found by PyMuPDF and by tools that call it, one thread per math
    library and per OCR, the priority and CPUs of the settings (balance.py)."""
    from assistant_x.intake import balance

    env = dict(
        os.environ,
        **balance.env(cfg.get("priority"), cfg.get("affinity", balance.DEFAULT_AFFINITY)),
        PYTHONUTF8="1",
        PYTHONIOENCODING="utf-8",
    )
    if cfg.get("tesseract"):
        env["PATH"] = str(Path(cfg["tesseract"]).parent) + os.pathsep + env.get("PATH", "")
        env["TESSERACT"] = cfg["tesseract"]
    if cfg.get("tessdata"):
        env["TESSDATA_PREFIX"] = cfg["tessdata"]
    return env


BAD_NAME_CHARS = re.compile(r'[<>:"/\\|?*]')


def safe_name(name):
    """A file or folder name robocopy, the backup and Windows tools all take: NFC (a decomposed letter from macOS or a
    web page, a base letter + U+0306, breaks robocopy), no invisible format or control characters (zero-width space),
    no spaces or dots at the ends, no leading hyphen, no characters Windows forbids."""
    n = unicodedata.normalize("NFC", name)
    n = "".join(c for c in n if unicodedata.category(c) not in ("Cf", "Cc"))
    n = BAD_NAME_CHARS.sub("_", n).strip(" ").lstrip("-").rstrip(". ")  # «-x.png»: robocopy took it for a switch
    return n or "_"


def safe_place(place):
    """'inbox\\a\\b.pdf' with every part made safe_name (the head folder stays as it is)."""
    head, sep, rest = place.partition("\\")
    return head + sep + "\\".join(safe_name(p) if p else p for p in rest.split("\\")) if sep else place


def save(updates, path=None):
    """Write values of [intake], keeping the rest; paths of programs go to the local file of this PC."""
    settings.save(updates, "intake", Path(path or config_path()))
