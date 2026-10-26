# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The outline a file gives itself: the bookmarks of a PDF (with their pages) and the heading styles of a DOCX
(Heading 1…9, or an outline level; the pages are found by the text, core/textmap.given_heads). It is the first
source of the outline of a document; the headings guessed from the text are the fallback.
Usage: python -m assistant_x.intake.tools.outline <file.pdf | file.docx>      (prints [[level, title, page or null]])"""

import json, re, sys, zipfile
import xml.etree.ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
HEADING_RX = re.compile(r"(?i)^heading\s*([1-9])$")  # the built-in names stay English in styles.xml, whatever the UI


def pdf_outline(doc):
    """[[level, title, page]] of the bookmarks of an open PDF (a bookmark without a page left out)."""
    try:
        toc = doc.get_toc(simple=True)
    except Exception:  # noqa: BLE001 — a broken outline is no outline
        return []
    return [
        [int(lvl), re.sub(r"\s+", " ", str(title)).strip(), int(page)]
        for lvl, title, page in toc
        if page and page >= 1 and str(title).strip()
    ]


def _level(ppr, styles):
    if ppr is None:
        return None
    lvl = ppr.find(f"{W}outlineLvl")
    if lvl is not None and (lvl.get(f"{W}val") or "").isdigit() and int(lvl.get(f"{W}val")) < 9:
        return int(lvl.get(f"{W}val")) + 1
    st = ppr.find(f"{W}pStyle")
    return styles.get(st.get(f"{W}val")) if st is not None else None


def docx_headings(path):
    """[[level, title, None]] of the paragraphs of a DOCX in a heading style (or with an outline level)."""
    try:
        with zipfile.ZipFile(path) as z:
            styles = {}
            if "word/styles.xml" in z.namelist():
                for s in ET.fromstring(z.read("word/styles.xml")).iter(f"{W}style"):
                    name = s.find(f"{W}name")
                    m = HEADING_RX.match(name.get(f"{W}val", "")) if name is not None else None
                    lvl = _level(s.find(f"{W}pPr"), {})
                    if m or lvl:
                        styles[s.get(f"{W}styleId")] = int(m.group(1)) if m else lvl
            body = ET.fromstring(z.read("word/document.xml"))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        return []
    out = []
    for p in body.iter(f"{W}p"):
        lvl = _level(p.find(f"{W}pPr"), styles)
        if not lvl:
            continue
        title = re.sub(r"\s+", " ", "".join(t.text or "" for t in p.iter(f"{W}t"))).strip()
        if title:
            out.append([lvl, title, None])
    return out


def of_file(pdf, original=None):
    """The outline of a document: the bookmarks of its PDF, else the heading styles of its DOCX original."""
    import pymupdf

    try:
        with pymupdf.open(pdf) as doc:
            given = pdf_outline(doc)
    except Exception:  # noqa: BLE001
        given = []
    if not given and original and str(original).lower().endswith((".docx", ".docm")):
        given = docx_headings(original)
    return given


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.stdout.reconfigure(encoding="utf-8")
    p = sys.argv[1]
    print(json.dumps(docx_headings(p) if p.lower().endswith((".docx", ".docm")) else of_file(p), ensure_ascii=False))
