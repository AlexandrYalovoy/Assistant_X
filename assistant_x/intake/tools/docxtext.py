# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The text of a Word document (.docx, .docm) read straight from its XML: its paragraphs in order, its tables as
Markdown tables, its headings marked. The intake lays it out on pages when LibreOffice cannot draw the document (a
report holding dozens of embedded objects went past 6 GB in a trial batch); no layout, no pictures.

Usage: python -m assistant_x.intake.tools.docxtext <file.docx>"""

import re, sys, zipfile
import xml.etree.ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
HEADING = re.compile(r"^(?:heading\s*)?(\d)$", re.I)  # "Heading1"; a Russian Word names its heading styles "1", "2"
MAX_XML = 200_000_000  # bytes of document.xml at most (a zip bomb is no document)


def _text(el):
    out = []
    for node in el.iter():
        if node.tag == W + "t" and node.text:
            out.append(node.text)
        elif node.tag == W + "tab":
            out.append("\t")
        elif node.tag in (W + "br", W + "cr"):
            out.append("\n")
    return "".join(out).strip()


def _cell(text):
    return text.replace("|", "/").replace("\n", " ")


def markdown(path):
    """The text of the document as Markdown, "" when it has none."""
    with zipfile.ZipFile(path) as z:
        info = z.getinfo("word/document.xml")
        if info.file_size > MAX_XML:
            raise ValueError(f"word/document.xml of {info.file_size} bytes")
        root = ET.fromstring(z.read(info))
    body = root.find(W + "body")
    if body is None:
        return ""
    lines = []
    for el in body:
        if el.tag == W + "p":
            text = _text(el)
            if not text:
                continue
            style = el.find(f"{W}pPr/{W}pStyle")
            m = HEADING.match(style.get(W + "val", "")) if style is not None else None
            lines.append(("#" * min(int(m.group(1)), 6) + " " if m else "") + text)
        elif el.tag == W + "tbl":
            rows = [[_cell(_text(c)) for c in r.findall(W + "tc")] for r in el.findall(W + "tr")]
            rows = [r for r in rows if any(r)]
            if not rows:
                continue
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            lines.append("| " + " | ".join(rows[0]) + " |")
            lines.append("|" + " --- |" * width)
            lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n\n".join(lines).strip()


def _number(name):
    m = re.search(r"(\d+)", name.rsplit("/", 1)[-1])
    return int(m.group(1)) if m else 0


def embedded_pdfs(path):
    """[(name, bytes)] of the PDF documents embedded in a Word document, in the order of their numbers: an OLE object
    of Acrobat (its CONTENTS stream) or a PDF part (a report of 87 embedded PDFs in a trial batch)."""
    from assistant_x.intake.tools.letters import CompoundFile

    out = []
    with zipfile.ZipFile(path) as z:
        names = sorted((n for n in z.namelist() if n.startswith("word/embeddings/")), key=_number)
        for name in names:
            data = z.read(name)
            if data[:5] == b"%PDF-":
                out.append((name, data))
                continue
            if not name.lower().endswith(".bin"):
                continue
            try:
                cf = CompoundFile(data)
                stream = next((cf.stream(i) for n, i in cf.children().items() if n.upper() == "CONTENTS"), b"")
            except Exception:  # noqa: BLE001 — an embedded object that does not read is left out
                continue
            if stream[:5] == b"%PDF-":
                out.append((name, stream))
    return out


def to_pdf(path, out, page_md):
    """A PDF of a Word document LibreOffice could not draw: its text (as Markdown, laid out on pages) and the PDFs
    embedded in it after it. None, or the error dict."""
    import pymupdf

    from assistant_x.intake.work import reflow_to_pdf

    text = markdown(path)
    pdfs = embedded_pdfs(path)
    if not text and not pdfs:
        return {"status": "error", "why": "the document has no text and no embedded PDF to read"}
    doc = pymupdf.open()
    if text:
        with open(page_md, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        err = reflow_to_pdf(page_md, str(page_md) + ".pdf", "md")
        if err:
            return err
        doc.insert_pdf(pymupdf.open(str(page_md) + ".pdf"))
    for _, data in pdfs:
        try:
            doc.insert_pdf(pymupdf.open(stream=data, filetype="pdf"))
        except Exception:  # noqa: BLE001 — a broken embedded PDF is left out
            continue
    if not doc.page_count:
        return {"status": "error", "why": "nothing of the document could be laid out"}
    doc.save(out, garbage=3, deflate=True)
    return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.stdout.reconfigure(encoding="utf-8")
    print(markdown(sys.argv[1]))
