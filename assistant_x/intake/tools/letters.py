# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The attachments of a letter: .eml (MIME, the standard library) and .msg / .oft (Outlook: a compound file read
here, no extra package). The attachments are documents of the intake; the letter itself goes aside.
Usage: python -m assistant_x.intake.tools.letters <letter> <folder>      (writes the attachments, prints a JSON report)"""

import email, json, os, struct, sys
from email import policy
from pathlib import Path

FREE, END = 0xFFFFFFFF, 0xFFFFFFFE  # the special sector numbers of a compound file
SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")


class CompoundFile:
    """A minimal reader of a Microsoft compound file (the container of .msg, .oft, .doc, .xls): its storages and
    streams by name."""

    def __init__(self, data):
        if data[:8] != SIGNATURE:
            raise ValueError("not a compound file")
        self.data = data
        self.sector = 1 << struct.unpack_from("<H", data, 0x1E)[0]
        self.mini = 1 << struct.unpack_from("<H", data, 0x20)[0]
        n_fat, first_dir = struct.unpack_from("<II", data, 0x2C)
        self.cutoff, first_minifat, n_minifat, first_difat, n_difat = struct.unpack_from("<IIIII", data, 0x38)
        difat = list(struct.unpack_from("<109I", data, 0x4C))
        s = first_difat
        for _ in range(n_difat):
            if s >= END:
                break
            vals = struct.unpack_from(f"<{self.sector // 4}I", data, self._at(s))
            difat += vals[:-1]
            s = vals[-1]
        self.fat = []
        for s in difat[:n_fat]:
            if s < END:
                self.fat += struct.unpack_from(f"<{self.sector // 4}I", data, self._at(s))
        self.minifat = []
        for s in self._chain(first_minifat):
            self.minifat += struct.unpack_from(f"<{self.sector // 4}I", data, self._at(s))
        raw = b"".join(self.data[self._at(s) : self._at(s) + self.sector] for s in self._chain(first_dir))
        self.entries = []
        for off in range(0, len(raw) - 127, 128):
            nlen = struct.unpack_from("<H", raw, off + 64)[0]
            kind = raw[off + 66]
            left, right, child = struct.unpack_from("<III", raw, off + 68)
            start, size = struct.unpack_from("<IQ", raw, off + 116)
            name = raw[off : off + max(nlen - 2, 0)].decode("utf-16-le", "replace")
            self.entries.append(
                {
                    "name": name,
                    "kind": kind,
                    "left": left,
                    "right": right,
                    "child": child,
                    "start": start,
                    "size": size & 0xFFFFFFFF if self.sector == 512 else size,
                }
            )
        root = self.entries[0]
        self.ministream = self._read(root["start"], root["size"], small=False)

    def _at(self, sector):
        return (sector + 1) * self.sector

    def _chain(self, start, table=None):
        table = self.fat if table is None else table
        out, seen = [], set()
        while start < len(table) and start not in seen and start < 0xFFFFFFFA:
            seen.add(start)
            out.append(start)
            start = table[start]
        return out

    def _read(self, start, size, small):
        if small:
            data = b"".join(self.ministream[s * self.mini : (s + 1) * self.mini] for s in self._chain(start, self.minifat))
        else:
            data = b"".join(self.data[self._at(s) : self._at(s) + self.sector] for s in self._chain(start))
        return data[:size]

    def children(self, index=0):
        """{name: entry index} of the entries of a storage (the root: 0)."""
        out, stack = {}, [self.entries[index]["child"]]
        while stack:
            i = stack.pop()
            if i >= len(self.entries):
                continue
            e = self.entries[i]
            out[e["name"]] = i
            stack += [e["left"], e["right"]]
        return out

    def stream(self, index):
        e = self.entries[index]
        return self._read(e["start"], e["size"], small=e["size"] < self.cutoff)


def _msg_text(cf, items, tag):
    """A string property of an Outlook item: the Unicode one (001F), else the 8-bit one (001E)."""
    for suffix, enc in (("001F", "utf-16-le"), ("001E", "latin-1")):
        i = items.get(f"__substg1.0_{tag}{suffix}")
        if i is not None:
            return cf.stream(i).decode(enc, "replace").rstrip("\x00")
    return ""


# a picture of the body of a letter (a logo, a signature, an icon): referred to by a Content-ID, small; a bigger one
# (a screenshot pasted into the letter) is taken out like any attachment
INLINE_MAX = 100_000  # bytes
PICTURES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".emf", ".wmf")


def body_picture(name, data, cid):
    return bool(cid) and data is not None and len(data) < INLINE_MAX and name.lower().endswith(PICTURES)


def msg_attachments(data, inline=None):
    """[(file name, bytes)] of the attachments of an Outlook .msg / .oft; [(name, None)] of an attachment that is an
    embedded message or an OLE object (not taken out). The small pictures of the body (body_picture) are left out,
    their names added to the list inline when one is given."""
    cf = CompoundFile(data)
    out = []
    for name, i in sorted(cf.children().items()):
        if not name.startswith("__attach_version1.0_"):
            continue
        items = cf.children(i)
        fname = _msg_text(cf, items, "3707") or _msg_text(cf, items, "3704") or f"attachment_{len(out) + 1}"
        data_i = items.get("__substg1.0_37010102")
        blob = cf.stream(data_i) if data_i is not None else None
        if body_picture(fname, blob, _msg_text(cf, items, "3712")):  # PR_ATTACH_CONTENT_ID
            if inline is not None:
                inline.append(fname)
            continue
        out.append((fname, blob))
    return out


def eml_attachments(data, inline=None):
    """[(file name, bytes)] of the attachments of a MIME letter; a forwarded letter comes as an .eml of its own. The
    small pictures of the body (body_picture) are left out, their names added to the list inline when one is given."""
    msg = email.message_from_bytes(data, policy=policy.default)
    out = []
    for part in msg.iter_attachments():
        name = part.get_filename() or ""
        if part.get_content_type() == "message/rfc822":
            inner = part.get_payload()
            inner = inner[0] if isinstance(inner, list) else inner
            subject = str(inner.get("subject") or "") if hasattr(inner, "get") else ""
            out.append(
                (
                    (name or subject or f"letter_{len(out) + 1}") + ("" if name.lower().endswith(".eml") else ".eml"),
                    inner.as_bytes() if hasattr(inner, "as_bytes") else bytes(inner),
                )
            )
            continue
        payload = part.get_payload(decode=True)
        name = name or f"attachment_{len(out) + 1}"
        if body_picture(name, payload, part.get("Content-ID")):
            if inline is not None:
                inline.append(name)
            continue
        out.append((name, payload))
    return out


def attachments(path, inline=None):
    """[(file name, bytes or None)] of the attachments of a letter by its extension (the pictures of its body left out,
    named in the list inline)."""
    data = Path(path).read_bytes()
    if str(path).lower().endswith(".eml"):
        return eml_attachments(data, inline)
    return msg_attachments(data, inline)


def extract(path, folder, safe_name=lambda s: s):
    """Write the attachments of a letter into folder (made only when there is one); returns {"files": [paths],
    "skipped": [names of embedded items not taken out], "inline": [names of the pictures of the body left out],
    "error": text or ""}."""
    rep = {"files": [], "skipped": [], "inline": [], "error": ""}
    try:
        items = attachments(path, rep["inline"])
    except Exception as e:  # noqa: BLE001 — a letter that does not read loses nothing: it still goes aside whole
        rep["error"] = f"the attachments were not read: {e!r}"[:300]
        return rep
    for name, data in items:
        if data is None:
            rep["skipped"].append(name)
            continue
        os.makedirs(folder, exist_ok=True)
        base = safe_name(os.path.basename(name.replace("\\", "/"))) or "attachment"
        target, k = os.path.join(folder, base), 2
        while os.path.exists(target):
            stem, ext = os.path.splitext(base)
            target, k = os.path.join(folder, f"{stem}_{k}{ext}"), k + 1
        with open(target, "wb") as f:
            f.write(data)
        rep["files"].append(target)
    return rep


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    print(json.dumps(extract(sys.argv[1], sys.argv[2]), ensure_ascii=False, indent=1))
