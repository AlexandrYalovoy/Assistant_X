# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A compiled HTML help file (.chm: a book or a handbook of the nineties and two thousands) as one HTML document:
7-Zip takes its pages out into a folder of the work, the contents (.hhc) gives their order and titles (else the pages
in the natural order of their names), every page goes in under its title as a heading; scripts, styles, pictures and
objects are left out (nothing of the file runs). work.prep lays the HTML out on A4 pages like any HTML text.

Usage: python -m assistant_x.intake.tools.chm <file.chm> <out.html> <7z.exe>"""

import html, os, re, sys
from pathlib import Path

PAGE_EXT = (".htm", ".html")
MAX_PAGES = 5000  # pages of a help file at most (a bigger one is cut, the rest named in the log)
PARAM = re.compile(r'<param\s+name\s*=\s*"?(name|local)"?\s+value\s*=\s*"([^"]*)"', re.I)
OBJECT = re.compile(r"<object[^>]*>(.*?)</object>", re.I | re.S)
CHARSET = re.compile(rb'charset\s*=\s*["\']?([A-Za-z0-9_-]+)', re.I)
BODY = re.compile(r"<body[^>]*>(.*)</body>", re.I | re.S)
DROP = re.compile(
    r"<(script|style|object|iframe|applet|embed|noscript)\b.*?</\1\s*>|<(img|link|meta|base)\b[^>]*>", re.I | re.S
)


def page_text(data):
    """The HTML of a page as text: its declared charset, else UTF-8, else the legacy code page of the packs."""
    m = CHARSET.search(data[:2048])
    if m:
        try:
            return data.decode(m.group(1).decode("ascii"), "replace")
        except LookupError:
            pass
    from assistant_x.intake.work import decode_text

    return decode_text(data)


def contents(folder):
    """[(title, relative path)] of the .hhc of a help file in its order, [] without one."""
    hhc = next((p for p in sorted(Path(folder).rglob("*")) if p.suffix.lower() == ".hhc"), None)
    if hhc is None:
        return []
    out = []
    for obj in OBJECT.findall(page_text(hhc.read_bytes())):
        found = {k.lower(): html.unescape(v) for k, v in PARAM.findall(obj)}
        local = found.get("local", "").split("#")[0].replace("\\", "/")
        if local.lower().endswith(PAGE_EXT):
            out.append((found.get("name") or Path(local).stem, local))
    return out


def body_of(text):
    m = BODY.search(text)
    return DROP.sub(" ", m.group(1) if m else text)


def assemble(folder, title="", depth=None):
    """(one HTML document of the pages of a taken-out help file, or of a folder of HTML pages (depth=1: its own pages
    only), the number of pages, the pages left out)."""
    from assistant_x.core.formats import natural_key

    folder = Path(folder)
    found = folder.glob("*") if depth == 1 else folder.rglob("*")
    pages = {str(p.relative_to(folder)).replace("\\", "/").lower(): p for p in found if p.suffix.lower() in PAGE_EXT}
    order, seen = [], set()
    for name, local in contents(folder):
        key = local.lstrip("/").lower()
        if key in pages and key not in seen:
            order.append((name, pages[key]))
            seen.add(key)
    for key in sorted(set(pages) - seen, key=natural_key):  # the pages the contents does not name, after it
        order.append((Path(key).stem, pages[key]))
    left = max(0, len(order) - MAX_PAGES)
    parts = [f"<html><head><meta charset='utf-8'><title>{html.escape(title)}</title></head><body>"]
    for name, path in order[:MAX_PAGES]:
        parts.append(f"<h1>{html.escape(name)}</h1>\n{body_of(page_text(path.read_bytes()))}")
    parts.append("</body></html>")
    return "\n".join(parts), min(len(order), MAX_PAGES), left


def to_html(chm, out_html, sevenzip, folder, timeout=600):
    """Take the pages of a .chm out into folder by 7-Zip and write them as one HTML; None, or the error dict."""
    from assistant_x.core import proc

    if not sevenzip:
        return {"status": "skipped", "why": "no 7-Zip: a .chm help file is not taken apart (assistant-x setup-intake)"}
    os.makedirs(folder, exist_ok=True)
    p = proc.run([sevenzip, "x", "-y", "-p-", "-snl-", f"-o{folder}", str(chm)], capture_output=True, timeout=timeout)
    if p.returncode != 0:
        return {"status": "error", "why": f"7-Zip did not take the help file apart (code {p.returncode})"}
    text, n, left = assemble(folder, Path(chm).stem)
    if not n:
        return {"status": "error", "why": "the help file holds no HTML page"}
    Path(out_html).write_text(text, encoding="utf-8")
    return None


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    print(to_html(sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[2]).with_suffix("")) or "ok")
