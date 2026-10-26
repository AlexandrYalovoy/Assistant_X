# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""The format of a base package "axbase/1": one zip file (stored, zip64 when big) or the same layout as a folder (for
a FAT32 flash drive, which takes no file over 4 GB).

    axbase.json        what the package is (manifest() below)
    README.txt         how to install it (English and Russian)
    cards/<code>.json  the cards (intake.package = {id, version, code})
    texts/<code>.md    the texts and their <code>.pages.json
    library/...        the originals and their PDF copies, by shelf
    vectors/           meta.json {dim, fingerprint, table_rows}, keys.bin, vectors.f16: the vector cache of its fragments
    events.tsv         date, code and status of the intake events of its documents (no file names, no folders)
    ocr_quality.tsv    the recognition scores of its texts
    CHECKSUMS.sha256   "sha256  path" of every other file

Package(path) reads either form: names(), read(name), open(name), size(name), manifest, verify()."""

import hashlib, json, os, re, zipfile, zlib

from assistant_x.core.txn import bad_path, inside  # noqa: F401 — the name rules (P.bad_path), shared with the intake

FORMAT = "axbase/1"
MANIFEST, CHECKSUMS, README = "axbase.json", "CHECKSUMS.sha256", "README.txt"
ID_RX = r"^[a-z0-9][a-z0-9._-]{0,63}$"
VERSION_RX = r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,39}$"
SUFFIX = ".axbase"
CODES = ("default", "reference")
LANG_RX = r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$"
TOPIC_RX = r"^[a-z][a-z0-9_]*$"
CODE_RX = r"^[A-Z]-[0-9]{5}$"
FINGERPRINT_RX = r"^[0-9A-Za-z._:+-]{1,128}$"


class PackageError(ValueError):
    pass


def _short(v, n=200):
    return isinstance(v, str) and len(v) <= n


def manifest_problems(man):
    """[problems] of the manifest of a package: a package is data from someone else, so every string that may reach a
    path, the settings or a report is checked before anything uses it (an empty list: it is fine)."""
    from assistant_x.core import config as settings, lang

    out = []
    if not isinstance(man, dict):
        return ["the manifest is not a JSON object"]
    if not (isinstance(man.get("id"), str) and re.fullmatch(ID_RX, man["id"])):
        out.append(f"id {man.get('id')!r}: lower-case letters, digits, '.', '_' and '-' (up to 64) are needed")
    if not (isinstance(man.get("version"), str) and re.fullmatch(VERSION_RX, man["version"])):
        out.append(f"version {man.get('version')!r}: letters, digits, '.', '_', '+' and '-' (up to 40) are needed")
    if man.get("codes") not in (None, *CODES):
        out.append(f"codes {man.get('codes')!r}: one of {', '.join(CODES)}")
    profile = man.get("profile")
    if profile is not None and (not isinstance(profile, str) or profile not in settings.profiles()):
        out.append(f"profile {profile!r}: not a profile of this program ({', '.join(settings.profiles())})")
    langs = man.get("card_languages")
    if langs is not None:
        known = lang.available()
        if not isinstance(langs, list) or not langs or not all(isinstance(x, str) for x in langs):
            out.append("card_languages: a list of language codes is needed")
        else:
            out += [
                f"card_languages: {x!r} is not a language pack of this program ({', '.join(known)})"
                for x in langs
                if x != "en" and x not in known
            ]
    for key, rx in (("languages", LANG_RX), ("topics", TOPIC_RX)):
        v = man.get(key)
        if v is not None and not (isinstance(v, list) and all(isinstance(x, str) and re.fullmatch(rx, x) for x in v)):
            out.append(f"{key}: a list of {key[:-1]} ids is needed")
    for key in ("name", "about"):
        v = man.get(key)
        if v is not None and not (
            isinstance(v, dict)
            and all(isinstance(k, str) and re.fullmatch(LANG_RX, k) and _short(x, 2000) for k, x in v.items())
        ):
            out.append(f"{key}: a map {{language: text}} is needed")
    if man.get("created") is not None and not _short(man["created"], 40):
        out.append("created: a date is needed")
    docs = man.get("docs")
    if docs is not None:
        if not isinstance(docs, list) or not all(
            isinstance(d, dict) and isinstance(d.get("code"), str) and re.fullmatch(CODE_RX, d["code"]) for d in docs
        ):
            out.append("docs: a list of {code, …} with document codes is needed")
    shelves = man.get("shelves")
    if shelves is not None and not (
        isinstance(shelves, dict) and all(re.fullmatch(r"[A-Z]", str(k)) and isinstance(v, int) for k, v in shelves.items())
    ):
        out.append("shelves: a map {letter: count} is needed")
    emb = man.get("embed")
    if emb is not None:
        if not isinstance(emb, dict):
            out.append("embed: an object is needed")
        else:
            if not (isinstance(emb.get("fingerprint"), str) and re.fullmatch(FINGERPRINT_RX, emb["fingerprint"])):
                out.append(f"embed: fingerprint {emb.get('fingerprint')!r} is not a fingerprint")
            for k in ("dim", "rows"):
                if not (isinstance(emb.get(k), int) and not isinstance(emb.get(k), bool) and emb[k] >= 0):
                    out.append(f"embed: {k} is not a number")
            if emb.get("model") is not None and not _short(emb["model"]):
                out.append("embed: model is not a name")
    req = man.get("requires")
    if req is not None and not isinstance(req, dict):
        out.append("requires: an object is needed")
    return out


def sha_stream(f):
    h = hashlib.sha256()
    for block in iter(lambda: f.read(1 << 20), b""):
        h.update(block)
    return h.hexdigest()


class Package:
    """A package to read, a zip file or a folder."""

    def __init__(self, path):
        self.path = os.path.abspath(str(path))
        self.folder = os.path.isdir(self.path)
        if not self.folder and not os.path.isfile(self.path):
            raise PackageError(f"No package {self.path}")
        if self.folder:
            self.zip = None
        else:
            try:
                self.zip = zipfile.ZipFile(self.path)
            except (zipfile.BadZipFile, OSError) as e:
                raise PackageError(f"{os.path.basename(self.path)}: not a zip file ({e})") from e
        try:
            self.manifest = self._manifest()
        except BaseException:  # every refusal lets the zip go: Windows keeps an open file from being moved or deleted
            self.close()
            raise

    def _manifest(self):
        """The manifest of the package, validated; PackageError when it does not read or is not valid."""
        name = os.path.basename(self.path)
        try:
            man = json.loads(self.read(MANIFEST).decode("utf-8"))
        except (KeyError, FileNotFoundError, ValueError) as e:
            raise PackageError(f"{name}: no readable {MANIFEST} ({e})") from e
        if not isinstance(man, dict):
            raise PackageError(f"{name}: {MANIFEST} is not a JSON object")
        if man.get("format") != FORMAT:
            raise PackageError(f"{name}: format {man.get('format')!r}, this program reads {FORMAT}")
        bad = manifest_problems(man)
        if bad:
            raise PackageError(f"{name}: the package is refused, its {MANIFEST} is not valid: " + "; ".join(bad[:10]))
        return man

    def close(self):
        if self.zip:
            self.zip.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def names(self):
        """Every file of the package, with '/' between folders."""
        if self.zip:
            return [i.filename for i in self.zip.infolist() if not i.is_dir()]
        out = []
        for dp, _, fns in os.walk(self.path):
            for f in fns:
                out.append(os.path.relpath(os.path.join(dp, f), self.path).replace(os.sep, "/"))
        return sorted(out)

    def _file(self, name):
        from assistant_x.core.txn import lp

        return lp(os.path.join(self.path, *name.split("/")))

    def open(self, name):
        return self.zip.open(name) if self.zip else open(self._file(name), "rb")

    def read(self, name):
        try:
            with self.open(name) as f:
                return f.read()
        except (zipfile.BadZipFile, zlib.error, EOFError) as e:
            raise PackageError(f"{os.path.basename(self.path)}: the package is damaged, {name} does not read ({e})") from e

    def size(self, name):
        return self.zip.getinfo(name).file_size if self.zip else os.path.getsize(self._file(name))

    def checksums(self):
        """{path: sha256} of CHECKSUMS.sha256."""
        out = {}
        for line in self.read(CHECKSUMS).decode("utf-8").splitlines():
            sha, _, name = line.partition("  ")
            if sha and name:
                out[name] = sha
        return out

    def identity(self):
        """sha256 of the manifest and the checksums together: what names this very package (another file of the same id
        and version, or the same one changed, has another)."""
        h = hashlib.sha256(self.read(MANIFEST))
        h.update(b"\0")
        h.update(self.read(CHECKSUMS) if CHECKSUMS in self.names() else b"")
        return h.hexdigest()

    def verify(self, progress=None):
        """[problems] of the files against CHECKSUMS.sha256 (an empty list: every file is whole); a file the zip
        cannot give back whole (a bad CRC, a cut download) is "damaged" too."""
        want, have = self.checksums(), set(self.names()) - {CHECKSUMS}
        problems = [f"missing: {n}" for n in sorted(set(want) - have)]
        problems += [f"not in {CHECKSUMS}: {n}" for n in sorted(have - set(want))]
        for i, name in enumerate(sorted(set(want) & have)):
            try:
                with self.open(name) as f:
                    if sha_stream(f) != want[name]:
                        problems.append(f"damaged: {name}")
            except DAMAGED as e:
                problems.append(f"damaged: {name} ({e})")
            if progress and i % 500 == 499:
                progress(i + 1, len(want))
        return problems


DAMAGED = (zipfile.BadZipFile, zlib.error, EOFError, OSError)  # what reading a damaged entry of a zip raises
TOP = ("cards/", "texts/", "library/", "vectors/")
TOP_FILES = (MANIFEST, CHECKSUMS, README, "events.tsv", "ocr_quality.tsv")


def bad_name(name):
    """Why a name of a package entry is refused, or ''."""
    why = bad_path(name)
    if why:
        return why
    if not (name in TOP_FILES or name.startswith(TOP)):
        return "not a file of a package"
    return ""


def check_entries(pkg):
    """[problems] of the entries of a package, before anything is extracted (inspect, install and update check them)."""
    problems, seen = [], {}
    if pkg.zip:
        entries = [(i.filename, i) for i in pkg.zip.infolist() if not i.is_dir()]
    else:
        entries = [(n, None) for n in pkg.names()]
    for name, info in entries:
        why = bad_name(name)
        if why:
            problems.append(f"{name}: {why}")
            continue
        low = name.lower()
        if low in seen:
            problems.append(f"{name}: the same name as {seen[low]} but for the case")
        seen[low] = name
        if info is not None:
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                problems.append(f"{name}: a link")
            if info.compress_type != zipfile.ZIP_STORED:
                problems.append(f"{name}: compressed (a package stores its files as they are)")
        else:
            p = pkg._file(name)
            if os.path.islink(p) or getattr(os.lstat(p), "st_file_attributes", 0) & 0x400:  # a reparse point
                problems.append(f"{name}: a link")
    return problems
