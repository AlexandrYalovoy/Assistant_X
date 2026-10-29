# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""File formats of a project in one place: page markers of texts, intake event statuses, headers of the index tables.
Everything is written with the English names below, whatever the language of the documents. The cards are JSON
(core/card.py, schemas/card-1.json), the catalog and the sources to update are made from them (search/catalog.py);
the shelves of the library (the letters of the codes) are data, the same in every profile (schemas/shelves.json)."""

import json, os, re


# ---------- places: the paths a card names ("library\01_Standards\N-00001_GOST.pdf"), relative to the workspace ----------
# A card writes them with backslashes on every system; on disk they are joined with the separator of the OS.
def place_of(rel):
    """A relative path of this system ("01_Standards/N-00001_GOST.pdf" on Linux) in the form of the cards."""
    return rel.replace("/", "\\")


def place_path(root, place):
    """The path on disk of a place of a card under root, with the separator of this system (either separator is
    accepted in place)."""
    return os.path.join(root, *place.replace("\\", "/").split("/"))


# ---------- texts: index/texts/<code>.md, pages marked '=== page N ===' (N = page of the PDF) ----------
# The text format "AX text 1" (docs/INTAKE.md): UTF-8, LF, NFC; a line of the body that would read as a marker is
# written with a backslash before it ('\=== page 3 ==='), so the markers below match the real ones only.
TEXT_FORMAT = "1"
PAGE_WORDS = "page"  # the word of a page marker
PAGE_RX = re.compile(r"^=== page (\d+) ===\s*$", re.M)
PAGE_SPLIT_RX = re.compile(r"(?:^|\n)=== page (\d+) ===\n")
_ESCAPED_RX = re.compile(r"^(\\*)(=== page \d+ ===\s*)$", re.M)  # a marker line with any number of backslashes
# beside <code>.md: <code>.pages.json, what is known of every page (its source, recognition score, printed label, flags)
PAGES_SUFFIX = ".pages.json"
PAGE_SOURCES = ("layer", "markdown", "ocr", "fallback")
PAGE_FLAGS = ("complex_table", "formula", "dpi_reduced", "garbled", "doubled")


def page_marker(n):
    return f"=== page {n} ==="


def escape_marker(text):
    """A line (or every line of a body) as it is written: one backslash more before a line that reads as a marker
    (with or without backslashes already), so unescape_text gives it back exactly."""
    return _ESCAPED_RX.sub(r"\\\1\2", text)


def unescape_text(text):
    """The body as it is: one backslash less before every escaped marker line."""
    return re.sub(r"^\\(\\*=== page \d+ ===\s*)$", r"\1", text, flags=re.M)


def pages_path(text_path):
    """<code>.pages.json beside <code>.md (or .txt)."""
    return re.sub(r"\.(md|txt)$", "", str(text_path)) + PAGES_SUFFIX


def read_pages_info(path):
    """{page: {source, ocr_score, label, flags}} of a .pages.json, or None when there is none or it does not read."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {int(k): v for k, v in data["pages"].items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def read_outline(path):
    """[[level, title, page or None]] of the outline the file gave itself (the "outline" of a .pages.json: PDF
    bookmarks, DOCX heading styles); [] when there is none."""
    try:
        with open(path, encoding="utf-8") as f:
            given = json.load(f).get("outline") or []
        return [[int(x[0]), str(x[1]), int(x[2]) if x[2] is not None else None] for x in given]
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
        return []


def write_pages_info(path, pages, outline=None):
    """Write {page: info} as a .pages.json of the text format (keys in page order), with the outline of the file when
    it has one."""
    data = {"format": int(TEXT_FORMAT), "pages": {str(k): pages[k] for k in sorted(pages)}}
    if outline:
        data["outline"] = [list(x) for x in outline]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


# ---------- the files the intake meets: extension (lower case, no dot) -> how it is handled ----------
# pdf: read as it is; office: to PDF by LibreOffice; image: to PDF by PyMuPDF, then OCR; archive: unpacked beside it;
# letter: its attachments taken out beside it (tools/letters.py), the letter to _to_delete; spreadsheet: to PDF by
# LibreOffice and every sheet a Markdown table of the text (tools/sheets.py); ebook (EPUB, FB2, MOBI, XPS) and text
# (TXT, Markdown, HTML): laid out on A4 pages by PyMuPDF; djvu: to PDF by DjVuLibre (ddjvu), then OCR; skip: a kind
# with no extension of its own yet. The PDF made of a file that is no PDF goes beside the original (pdf_copy of the
# card): the page numbers of a citation are its pages. Any other extension is left for the user to decide.
FILE_KINDS = ("pdf", "office", "image", "archive", "letter", "spreadsheet", "ebook", "text", "djvu", "skip")
EXTENSIONS = {
    "pdf": "pdf",
    # docm, pptm: the documents with macros; LibreOffice converts them to PDF without running a macro
    **dict.fromkeys(("doc", "docx", "docm", "rtf", "odt", "ppt", "pptx", "pptm", "pps", "ppsx", "odp"), "office"),
    **dict.fromkeys(("jpg", "jpeg", "png", "tif", "tiff", "bmp"), "image"),
    **dict.fromkeys(("zip", "7z", "rar", "tar", "tgz", "tar.gz", "tar.bz2", "tar.xz", "gz"), "archive"),
    # the first volume of an archive split in parts (7-Zip reads the next ones .002, .003 … beside it)
    **dict.fromkeys(("7z.001", "zip.001", "rar.001", "001"), "archive"),
    **dict.fromkeys(("msg", "eml", "oft"), "letter"),
    **dict.fromkeys(("xls", "xlsx", "xlsm", "xlsb", "ods"), "spreadsheet"),
    **dict.fromkeys(("epub", "fb2", "mobi", "xps", "oxps"), "ebook"),
    **dict.fromkeys(("txt", "md", "markdown", "html", "htm", "xhtml"), "text"),
    **dict.fromkeys(("djvu", "djv"), "djvu"),
}


def extensions(kind):
    """The extensions of a kind of file, in the order of the table."""
    if kind not in FILE_KINDS:
        raise ValueError(f"no kind of file {kind!r}: {', '.join(FILE_KINDS)}")
    return tuple(e for e, k in EXTENSIONS.items() if k == kind)


def file_ext(name):
    """The extension of a file name the table knows (the longest one: "a.tar.gz" -> "tar.gz"), else its last one."""
    n = str(name).lower()
    known = [e for e in EXTENSIONS if n.endswith("." + e)]
    return max(known, key=len) if known else (n.rsplit(".", 1)[-1] if "." in n else "")


def natural_key(name):
    """Sort key of a file or folder name with its numbers as numbers: "Chapter 2" before "Chapter 10"."""
    return [int(x) if x.isdigit() else x.casefold() for x in re.split(r"(\d+)", str(name))]


def file_kind(name):
    """The kind of a file by its name (FILE_KINDS), or "" for an extension the table does not know."""
    return EXTENSIONS.get(file_ext(name), "")


# ---------- intake events: index/intake_events.tsv and the table of index/journal.md ----------
EVENTS_HEADER = ["date", "source_file", "size", "sha256", "code", "destination", "status"]
# the status of an event starts with one of these words
EVENT_DONE, EVENT_DUP, EVENT_REJECTED, EVENT_DELETE, EVENT_ERROR = "done", "duplicate", "rejected", "to delete", "error"
EVENT_REMOVED = "removed"  # taken out of the library by the user (assistant-x remove): its file is no duplicate after
EVENT_KINDS = [
    ("done", "accepted"),
    ("duplicate", "duplicate"),
    ("rejected", "rejected"),
    ("to delete", "to delete"),
    ("error", "error"),
    ("removed", "removed"),
    ("to pdf", "to PDF"),
    ("estimate", "estimate"),
    ("archive", "archive"),
]


def event_kind(status):
    s = status.strip().lower()
    for prefix, k in EVENT_KINDS:
        if s.startswith(prefix):
            return k
    return "other"


# ---------- the other tables of index/ ----------
MANIFEST_HEADER = ["path", "size", "modified", "sha256", "code"]
# index/ocr_quality.tsv: the recognition score of every text (intake/tools/ocr_score.py)
OCR_HEADER = ["code", "score", "nonword", "words", "pages", "pages_below_threshold", "worst_pages", "source", "date"]


def column_keys(header):
    """The keys of the cells of a header row."""
    return [h.strip().lower() for h in header]
