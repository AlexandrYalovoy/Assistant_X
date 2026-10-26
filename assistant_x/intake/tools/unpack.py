# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Safe unpacking of an archive into a folder beside it (Documents.zip -> Documents\\, taken: Documents_2\\).
Refuses the whole archive, before writing anything, if a name is absolute or goes up with ..,
or if the files add up to more than the limit; nested archives are unpacked the same way down to a depth limit
(an unpacked nested archive is removed: the outer one keeps it).
zip and tar: Python; 7z and rar: 7-Zip (7z.exe), else py7zr for 7z if installed.
Usage: python -m assistant_x.intake.tools.unpack <archive> [--dest DIR] [--max-gb 5] [--max-depth 3] [--sevenzip 7z.exe]
Prints a JSON report: dest, files, bytes, nested, left (archives not unpacked: too deep, broken), error."""

import json, os, re, shutil, sys, tarfile, unicodedata, zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from assistant_x.core import proc

from assistant_x.core.config import INTAKE
from assistant_x.core.formats import extensions

LIMITS, TIMEOUT = INTAKE["unpack"], INTAKE["timeouts"]["unpack"]  # the defaults of [intake] (the intake passes its own)
ARCHIVES = tuple("." + e for e in extensions("archive"))  # core/formats.EXTENSIONS
GB = 1024**3


class Refused(Exception):
    """Unsafe or too big: nothing was unpacked. kind says why for the code ("password": nobody can open it here,
    "unsafe", "size", "damaged", "tool"); the message says it for the user."""

    def __init__(self, message, kind="damaged"):
        super().__init__(message)
        self.kind = kind


PASSWORD = "password"  # Refused.kind of an archive protected by a password


def archive_ext(name):
    n = str(name).lower()
    for e in sorted(ARCHIVES, key=len, reverse=True):
        if n.endswith(e):
            return e
    return ""


def is_archive(name):
    return bool(archive_ext(name))


def safe_name(name):
    """Relative path parts of a member (in the NFC form), or Refused for an absolute path, .., a colon (an NTFS
    stream), a device name of Windows or a part ending in a dot or a space: the rules of a base package
    (txn.bad_path), a backslash taken for a folder separator and "." parts dropped."""
    from assistant_x.core.txn import bad_path

    n = unicodedata.normalize("NFC", name.replace("\\", "/"))
    if n.startswith("/") or PureWindowsPath(name).drive or re.match(r"^[A-Za-z]:", n):
        raise Refused(f"an absolute path in the archive: {name}", "unsafe")
    parts = [p for p in PurePosixPath(n).parts if p not in ("", ".")]
    if ".." in parts:
        raise Refused(f"a path with .. in the archive: {name}", "unsafe")
    why = bad_path("/".join(parts), nfc=False) if parts else ""
    if why:
        raise Refused(f"a name Windows does not take in the archive ({why}): {name}", "unsafe")
    return parts


def target_dir(archive):
    a = Path(archive)
    stem = a.name[: -len(archive_ext(a.name))] or a.stem
    d, k = a.parent / stem.rstrip(" ."), 2
    while d.exists():
        d, k = a.parent / f"{stem.rstrip(' .')}_{k}", k + 1
    return d


def zip_name(info):
    """Russian names without the UTF-8 flag are cp866 read as cp437: decode them back."""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp866")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def _copy(src, dst, budget):
    """Copy a stream, counting bytes: a member that lies about its size still stops at the limit."""
    n = 0
    while True:
        block = src.read(1 << 20)
        if not block:
            return n
        n += len(block)
        if n > budget:
            raise Refused("the unpacked size exceeded the limit", "size")
        dst.write(block)


def _zip(archive, dest, budget):
    with zipfile.ZipFile(archive) as z:
        items = [(i, safe_name(zip_name(i))) for i in z.infolist()]
        total = sum(i.file_size for i, _ in items)
        if total > budget:
            raise Refused(f"the archive holds {total / GB:.1f} GB, the limit is {budget / GB:.1f} GB", "size")
        if any(i.flag_bits & 0x1 for i, _ in items):
            raise Refused("the archive is protected by a password", PASSWORD)
        written = 0
        for i, parts in items:
            if not parts:
                continue
            out = dest.joinpath(*parts)
            if i.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as src, open(out, "wb") as dst:
                written += _copy(src, dst, budget - written)
        return written


def _tar(archive, dest, budget):
    with tarfile.open(archive) as t:
        items = t.getmembers()
        for m in items:
            safe_name(m.name)
            if not (m.isfile() or m.isdir()):
                raise Refused(f"a link or a device in the archive: {m.name}", "unsafe")
        total = sum(m.size for m in items if m.isfile())
        if total > budget:
            raise Refused(f"the archive holds {total / GB:.1f} GB, the limit is {budget / GB:.1f} GB", "size")
        written = 0
        for m in items:
            out = dest.joinpath(*safe_name(m.name))
            if m.isdir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with t.extractfile(m) as src, open(out, "wb") as dst:
                written += _copy(src, dst, budget - written)
        return written


def _gz(archive, dest, budget):
    import gzip

    name = Path(archive).name[:-3] or "file"
    dest.mkdir(parents=True, exist_ok=True)
    with gzip.open(archive) as src, open(dest / name, "wb") as dst:
        return _copy(src, dst, budget)


def _7z_list(sevenzip, archive):
    p = proc.run(
        [sevenzip, "l", "-slt", "-ba", "-p-", "-sccUTF-8", str(archive)],
        capture_output=True,
        timeout=600,
        encoding="utf-8",
        errors="replace",
    )
    if p.returncode != 0:
        msg = (p.stdout + p.stderr).strip().splitlines()
        raise Refused("the archive cannot be read: " + (msg[-1] if msg else f"code {p.returncode}"))
    items, cur = [], {}
    for line in p.stdout.splitlines() + [""]:
        if not line.strip():
            if "Path" in cur:
                items.append(cur)
            cur = {}
        elif " = " in line:
            k, v = line.split(" = ", 1)
            cur[k.strip()] = v
    return items


def _7z(archive, dest, budget, sevenzip, timeout):
    if not sevenzip:
        if archive_ext(archive) == ".7z":
            try:
                import py7zr
            except ImportError:
                raise Refused("no 7-Zip and no py7zr: a .7z archive cannot be unpacked", "tool")
            with py7zr.SevenZipFile(archive) as z:
                if z.needs_password():
                    raise Refused("the archive is protected by a password", PASSWORD)
                infos = z.list()
                for i in infos:
                    safe_name(i.filename)
                total = sum(i.uncompressed or 0 for i in infos)
                if total > budget:
                    raise Refused(f"the archive holds {total / GB:.1f} GB, the limit is {budget / GB:.1f} GB", "size")
                z.extractall(dest)
                return total
        raise Refused("no 7-Zip: a .rar archive cannot be unpacked", "tool")
    items = _7z_list(sevenzip, archive)
    for i in items:
        safe_name(i["Path"])
        if i.get("Encrypted") == "+":
            raise Refused("the archive is protected by a password", PASSWORD)
    total = sum(int(i.get("Size") or 0) for i in items)
    if total > budget:
        raise Refused(f"the archive holds {total / GB:.1f} GB, the limit is {budget / GB:.1f} GB", "size")
    dest.mkdir(parents=True, exist_ok=True)
    p = proc.run(
        [sevenzip, "x", "-y", "-p-", "-snl-", f"-o{dest}", str(archive)],
        capture_output=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    if p.returncode != 0:
        msg = (p.stdout + p.stderr).strip().splitlines()
        raise Refused("7-Zip did not unpack it: " + (msg[-1] if msg else f"code {p.returncode}"))
    return total


def _inside(dest):
    """Every unpacked file is inside dest (a second guard after the name check)."""
    root = os.path.realpath(dest)
    for dp, _, fns in os.walk(dest):
        for f in fns:
            if not os.path.realpath(os.path.join(dp, f)).startswith(root + os.sep):
                raise Refused(f"a file outside the unpack folder: {f}", "unsafe")


def _remove_tree(d):
    """Undo a failed unpacking: files we wrote, then the empty folders (no shutil.rmtree)."""
    for dp, dns, fns in os.walk(d, topdown=False):
        for f in fns:
            os.remove(os.path.join(dp, f))
        os.rmdir(dp)


def unpack_one(archive, dest, budget, sevenzip=None, timeout=TIMEOUT):
    """Bytes written into dest; Refused leaves nothing behind."""
    ext = archive_ext(archive)
    dest = Path(dest)
    fresh = not dest.exists()  # a folder that was there before is never cleaned up
    try:
        if ext == ".zip" and zipfile.is_zipfile(archive):
            n = _zip(archive, dest, budget)
        elif ext in (".tar", ".tgz", ".tar.gz", ".tar.bz2", ".tar.xz"):
            n = _tar(archive, dest, budget)
        elif ext == ".gz":
            n = _gz(archive, dest, budget)
        else:  # .7z, .rar, a .zip Python cannot read
            n = _7z(archive, dest, budget, sevenzip, timeout)
        if dest.exists():
            _inside(dest)
        return n
    except (Refused, zipfile.BadZipFile, tarfile.TarError, OSError, EOFError, proc.TimeoutExpired) as e:
        if fresh and dest.exists():
            _remove_tree(dest)
        raise e if isinstance(e, Refused) else Refused(f"the archive is damaged: {e}")


def unpack(
    archive, dest=None, max_total=LIMITS["max_total_gb"] * GB, max_depth=LIMITS["max_depth"], sevenzip=None, timeout=TIMEOUT
):
    """Unpack an archive and the archives in it. Report dict; error is set when the archive itself was refused."""
    archive = Path(archive)
    dest = Path(dest) if dest else target_dir(archive)
    rep = {
        "archive": str(archive),
        "dest": str(dest),
        "files": 0,
        "bytes": 0,
        "nested": [],
        "left": [],
        "error": None,
        "kind": None,
    }
    try:
        rep["bytes"] = unpack_one(archive, dest, max_total, sevenzip, timeout)
    except Refused as e:
        rep["error"], rep["kind"] = str(e), e.kind
        return rep
    queue = [(dest, 1)]
    while queue:
        folder, depth = queue.pop()
        for dp, _, fns in os.walk(folder):
            for f in sorted(fns):
                p = Path(dp) / f
                if not is_archive(f):
                    continue
                if depth >= max_depth:
                    rep["left"].append({"path": str(p), "why": f"nesting deeper than {max_depth}", "kind": "depth"})
                    continue
                d = target_dir(p)
                try:
                    rep["bytes"] += unpack_one(p, d, max_total - rep["bytes"], sevenzip, timeout)
                except Refused as e:
                    rep["left"].append({"path": str(p), "why": str(e), "kind": e.kind})
                    continue
                os.remove(p)  # the outer archive keeps it
                rep["nested"].append(str(p))
                queue.append((d, depth + 1))
    rep["files"] = sum(len(fns) for _, _, fns in os.walk(dest))
    return rep


def main(argv):
    if not argv or argv[0].startswith("-"):
        sys.exit(__doc__)
    opt = lambda k, d: argv[argv.index(k) + 1] if k in argv else d
    rep = unpack(
        argv[0],
        opt("--dest", None),
        float(opt("--max-gb", LIMITS["max_total_gb"])) * GB,
        int(opt("--max-depth", LIMITS["max_depth"])),
        opt("--sevenzip", None) or shutil.which("7z"),
    )
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    sys.exit(1 if rep["error"] else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
