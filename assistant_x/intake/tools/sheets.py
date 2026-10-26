# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The cells of a spreadsheet as Markdown tables, one per sheet, so the search finds them (the PDF LibreOffice makes
of the workbook keeps the pages to cite). XLSX and XLSM are read here (the standard library); XLS, XLSB and ODS are
made XLSX by LibreOffice first (work.prep).
Usage: python -m assistant_x.intake.tools.sheets <book.xlsx>"""

import re, sys, zipfile
import xml.etree.ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"
MAX_ROWS, MAX_COLS = 2000, 60  # a bigger sheet keeps its first rows and columns, with a note
CELL_RX = re.compile(r"([A-Z]+)(\d+)")


def _col(ref):
    m = CELL_RX.match(ref or "")
    if not m:
        return None
    n = 0
    for ch in m.group(1):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _text(el):
    return "".join(t.text or "" for t in el.iter(f"{NS}t"))


def read_xlsx(path, max_rows=MAX_ROWS, max_cols=MAX_COLS):
    """[(sheet name, rows as lists of strings, cut)] of a workbook, in the order of its sheets; cut: rows or columns
    were left out."""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            shared = [_text(si) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{NS}si")]
        rels = {}
        if "xl/_rels/workbook.xml.rels" in names:
            for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(f"{PKG}Relationship"):
                t = r.get("Target", "").lstrip("/")
                rels[r.get("Id")] = t if t.startswith("xl/") else "xl/" + t
        out = []
        for sh in ET.fromstring(z.read("xl/workbook.xml")).iter(f"{NS}sheet"):
            part = rels.get(sh.get(f"{REL}id"))
            if not part or part not in names:
                continue
            rows, cut = [], False
            with z.open(part) as f:
                for _, el in ET.iterparse(f):
                    if el.tag != f"{NS}row":
                        continue
                    if len(rows) >= max_rows:
                        cut = True
                        break
                    row = {}
                    for i, c in enumerate(el.iter(f"{NS}c")):
                        col = _col(c.get("r"))
                        col = i if col is None else col
                        if col >= max_cols:
                            cut = True
                            continue
                        t, v = c.get("t"), c.find(f"{NS}v")
                        if t == "s" and v is not None and v.text and v.text.isdigit() and int(v.text) < len(shared):
                            val = shared[int(v.text)]
                        elif t == "inlineStr":
                            val = _text(c)
                        elif t == "b" and v is not None:
                            val = "TRUE" if v.text == "1" else "FALSE"
                        else:
                            val = v.text if v is not None and v.text else ""
                        if val.strip():
                            row[col] = val
                    el.clear()
                    if row:
                        rows.append([row.get(k, "") for k in range(max(row) + 1)])
            out.append((sh.get("name") or f"Sheet{len(out) + 1}", rows, cut))
    return out


def cell(s):
    return re.sub(r"\s+", " ", s).replace("|", "\\|").strip()


def markdown(rows):
    """A GFM table of the rows: the first row is the header, every row as wide as the widest."""
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [[cell(c) for c in r] + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def sheets_markdown(path):
    """[(sheet name, Markdown of the sheet, a few of its cell values to find its page)] of the sheets with cells."""
    out = []
    for name, rows, cut in read_xlsx(path):
        if not rows:
            continue
        md = markdown(rows) + ("\n\n(the sheet is longer: its first rows and columns only)" if cut else "")
        probe = [c for r in rows[:20] for c in r if len(c.strip()) >= 4 and not re.fullmatch(r"[\d.,\s-]+", c)][:5]
        out.append((name, md, probe))
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.stdout.reconfigure(encoding="utf-8")
    for name, md, _ in sheets_markdown(sys.argv[1]):
        print(f"## Sheet: {name}\n\n{md}\n")
