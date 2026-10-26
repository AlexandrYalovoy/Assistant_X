# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The pieces of a change of the workspace that may be interrupted and continued: long paths, moves, files written at
once and the journal of the steps done. The apply of an intake (intake/apply.py) and the install of a base package use
them alike.

    lp(path)               a path that works past 260 characters on Windows
    move(src, dst)         a file to its place (another disk: copied, then removed)
    write_whole(path, t)   a text file written at once: a reader sees the old text or the new one, never half
    Journal(path)          {date, started, steps, moved}: start(), mark(step), done(step), moved(i)
    is_link(path)          a symbolic link or a junction (a folder of models or packages linked from elsewhere)
    links_inside(path)     the links under a folder: a tree with one is never removed or cleared
    copy_tree(src, dst)    a folder copied file by file, never into a link and never over what is there
    bad_path(name)         why a relative path ('/' between folders) of a package, an archive or a card is refused
    inside(path, root)     path (resolved) is root or under it: the last guard before a move or a removal
"""

import datetime, json, os, re, shutil, unicodedata
from pathlib import Path


def lp(path):
    """Path string that works past 260 characters on Windows (deep folders of multi-file documents)."""
    s = os.path.abspath(str(path))
    if os.name == "nt" and not s.startswith("\\\\?\\") and len(s) > 240:
        return "\\\\?\\" + s
    return s


def exists(p):
    return os.path.exists(lp(p))


def move(src, dst):
    os.makedirs(lp(Path(dst).parent), exist_ok=True)
    try:
        os.replace(lp(src), lp(dst))
    except OSError:  # another disk
        shutil.move(lp(src), lp(dst))


def write_whole(path, text):
    """A file written at once: a reader (or a switched-off PC) sees the old text or the new one, never half."""
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


class Journal:
    """A JSON journal of a change: the date of the change, the steps done, the indexes of the moves made."""

    def __init__(self, path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else None

    def start(self, date, **extra):
        self.data = {
            "date": date,
            "started": datetime.datetime.now().isoformat(timespec="seconds"),
            "steps": [],
            "moved": [],
            **extra,
        }
        self.save()

    def save(self):
        write_whole(self.path, json.dumps(self.data, ensure_ascii=False, indent=0))

    def done(self, step):
        return step in self.data["steps"]

    def mark(self, step):
        self.data["steps"].append(step)
        self.save()

    def moved(self, i):
        self.data["moved"].append(i)
        self.save()


def is_link(path):
    """A symbolic link or a junction (a reparse point on Windows; os.path.islink misses a junction before 3.12)."""
    if os.path.islink(path):
        return True
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return bool(getattr(st, "st_file_attributes", 0) & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT


def links_inside(path):
    """The links under path (path itself included), not followed: a tree with one is never removed or cleared, since
    removing it would remove what the link points at (a frozen environment, linked models)."""
    out = [str(path)] if is_link(path) else []
    if out or not os.path.isdir(path):
        return out
    for dp, dns, fns in os.walk(path):
        linked = [d for d in dns if is_link(os.path.join(dp, d))]
        out += [os.path.join(dp, d) for d in linked]
        dns[:] = [d for d in dns if d not in linked]  # never walked into
        out += [os.path.join(dp, f) for f in fns if is_link(os.path.join(dp, f))]
    return out


def copy_tree(src, dst):
    """Copy the folder src to dst file by file; dst that exists already (a link above all) is left as it is.
    Returns (files copied, bytes), or None when dst was there."""
    if os.path.exists(dst) or is_link(dst):
        return None
    n = size = 0
    for dp, dns, fns in os.walk(src):
        rel = os.path.relpath(dp, src)
        os.makedirs(lp(os.path.join(dst, rel)), exist_ok=True)
        for f in fns:
            shutil.copy2(lp(os.path.join(dp, f)), lp(os.path.join(dst, rel, f)))
            n += 1
            size += os.path.getsize(lp(os.path.join(dp, f)))
    return n, size


RESERVED_RX = r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$"


def bad_path(name, nfc=True):
    """Why a relative path with '/' (a name in a package or an archive, a path of a card) is refused, or '': an
    absolute path, a drive, a backslash or a colon (an NTFS stream), an empty part, '.' or '..', a device name of
    Windows, a part ending in a dot or a space; not in the NFC form (nfc=False: the caller normalizes it, as the
    intake does with the names of a macOS archive)."""
    if not name or "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ":" in name:
        return "an absolute path, a backslash or a colon"
    parts = name.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return "an empty part, '.' or '..'"
    if any(re.match(RESERVED_RX, p, re.I) for p in parts):
        return "a device name of Windows"
    if any(p != p.rstrip(". ") for p in parts):
        return "a part ending in a dot or a space"
    if nfc and unicodedata.normalize("NFC", name) != name:
        return "not in the NFC form"
    return ""


def inside(path, root):
    """Is path (resolved) root or under it? The last guard before a file is moved or removed."""
    try:
        p, r = os.path.realpath(path), os.path.realpath(root)
        return os.path.normcase(os.path.commonpath([p, r])) == os.path.normcase(r)
    except ValueError:  # another drive
        return False
