# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The quote of a reference marked on its page, and the references of an answer gathered into a folder.

find(page, quote): the places of a quote in the text layer of a PDF page (PyMuPDF search): the whole quote, else its
parts (the cells of a table row, the pieces around "…", runs of a few words), the parts kept near the longest one.
Only what the text layer of the page has is marked: a scan without one, or a quote the page does not have, stays
unmarked and says so — never a mark at a guessed place. The originals are never changed: a page is marked on a copy.

export(folder, refs, ...): the files of the documents cited, copied, and one PDF of the pages cited, one page a sheet
with a line on top (the reference, the title, whether the quote is marked)."""

import os
import re
import shutil
import time

MARK = (1.0, 0.85, 0.0)  # the colour of a mark: yellow, under the text
OPACITY = 0.35
HEAD = 46  # points above a page in the PDF of the references: its line
WORDS = 6  # a part of a quote not found whole is looked for in runs of this many words
NEAR = 60  # points: a part of a quote counts only this near (up or down) to its longest part
SHORT = 5  # letters and digits: a shorter part of a quote is marked only as whole words
MAX_REFS = 200  # references of one export at most
REF = re.compile(r"\[([A-Z]-\d{5}(?:-\d{2})?)(?:, [^\]\n]*?)?, PDF (\d+)\]")
QUOTE = re.compile(r"«([^»\n]+)»")


def clean(quote):
    """The words of a quote as the page shows them: no Markdown marks, no line breaks of a table cell."""
    q = re.sub(r"<br\s*/?>", " ", quote or "")
    q = re.sub(r"[*_`#]+", " ", q)
    return " ".join(q.split())


def parts(quote):
    """The pieces of a quote to look for: the cells of a table row, the pieces around "…"."""
    out = [p.strip(" .,;:") for p in re.split(r"\s*\|\s*|\s*…\s*|\s*\.\.\.\s*", clean(quote))]
    return [p for p in out if len(p) >= 2]


def runs(text):
    """Runs of WORDS words that cover a text to its last word."""
    words = text.split()
    if len(words) <= WORDS:
        return [text]
    starts = list(range(0, len(words) - WORDS, WORDS)) + [len(words) - WORDS]
    return [" ".join(words[i : i + WORDS]) for i in starts]


def squash(text):
    """The letters and digits of a text in lower case, yo as ye: what is compared when the spaces differ."""
    return re.sub(r"[\W_]+", "", (text or "").lower().replace("\u0451", "\u0435"))


def by_words(words, text, whole=False):
    """The boxes of the words of a page (page.get_text("words")) that hold text once the spaces and the marks are
    left out on both sides: a word run together in a recognized text is two words on the page. whole: the text must
    start and end at the edges of words (a short part, "10", never matches inside "2010")."""
    want = squash(text)
    if len(want) < 2:
        return []
    joined, owner, starts, ends = "", [], set(), set()
    for i, w in enumerate(words):
        s = squash(w[4])
        if s:
            starts.add(len(joined))
            joined += s
            owner += [i] * len(s)
            ends.add(len(joined))
    import pymupdf

    out, at = [], joined.find(want)
    while at >= 0:
        if not whole or (at in starts and at + len(want) in ends):
            out += [pymupdf.Rect(words[i][:4]) for i in sorted(set(owner[at : at + len(want)]))]
        at = joined.find(want, at + 1)
    return out


def look(page, words, text):
    """The places of a part of a quote: a short one (a number, a word of a table cell) only as whole words."""
    if len(squash(text)) < SHORT:
        return by_words(words, text, whole=True)
    return page.search_for(text) or by_words(words, text)


def find(page, quote):
    """(rects, status) of a quote on a PyMuPDF page: status "marked" (every part found near the others), "partial"
    or "none"."""
    pieces = parts(quote)
    if not pieces or not page.get_text("text").strip():
        return [], "none"
    words = page.get_text("words")
    found, wanted = {}, 0
    for p in pieces:
        got = look(page, words, p)
        if got:
            found[p], wanted = got, wanted + 1
            continue
        for r in runs(p):  # a long sentence broken by a footnote or a recognition slip: its runs
            wanted += 1
            if got := look(page, words, r):
                found[r] = got
    if not found:
        return [], "none"
    anchor = found[max(found, key=len)]
    top, bottom = min(r.y0 for r in anchor) - NEAR, max(r.y1 for r in anchor) + NEAR
    near = {k: [r for r in got if r.y1 >= top and r.y0 <= bottom] for k, got in found.items()}
    near = {k: v for k, v in near.items() if v}
    rects = [r for v in near.values() for r in v]
    return rects, "marked" if len(near) == wanted else "partial"


def mark(page, rects):
    for r in rects:
        page.draw_rect(r, color=None, fill=MARK, fill_opacity=OPACITY, overlay=True)


def marked_page(src, page_no, quote):
    """(a one-page PDF with the quote marked, status) from page page_no (1-based) of the open PDF src; status None
    when no quote is given, "rotated" on a turned page (its text layer and its drawing do not share places)."""
    import pymupdf

    one = pymupdf.open()
    one.insert_pdf(src, from_page=page_no - 1, to_page=page_no - 1)
    if not quote:
        return one, None
    if one[0].rotation:
        return one, "rotated"
    rects, status = find(one[0], quote)
    mark(one[0], rects)
    return one, status


def references(texts):
    """[(code, PDF page, quote or "")] of every reference in the lines of texts (an answer, or reference lines), in
    their order, each once; the quote of a reference is the «…» before it on its line, after the reference before."""
    out, seen = [], set()
    for text in texts:
        for line in str(text).splitlines():
            quotes = [(q.end(), q[1]) for q in QUOTE.finditer(line)]
            since = 0
            for m in REF.finditer(line):
                own = [q for end, q in quotes if since <= end <= m.start()]
                since = m.end()
                key = (m[1], int(m[2]), own[-1] if own else "")
                if key not in seen:
                    seen.add(key)
                    out.append(key)
    return out


def safe_folder(folder, forbidden):
    """The absolute folder to write into, or ValueError: a full path of a drive of this PC (not a network share, not a
    device path), not inside the library (forbidden), with the links on the way resolved."""
    folder = (folder or "").strip()
    if folder.startswith(("\\\\", "//")):
        raise ValueError(f"{folder} is a network or device path: choose a folder on a drive of this PC.")
    if not os.path.isabs(folder) or (os.name == "nt" and not re.match(r"^[A-Za-z]:[\\/]", folder)):
        raise ValueError(f"Give the full path of a folder, e.g. D:\\References, not {folder!r}.")
    path = os.path.normpath(os.path.abspath(folder))
    real = os.path.normcase(os.path.realpath(path)) + os.sep
    for f in forbidden:
        if f and real.startswith(os.path.normcase(os.path.realpath(os.path.normpath(str(f)))) + os.sep):
            raise ValueError(f"{path} is inside the library: choose a folder of your own.")
    if os.path.exists(path) and not os.path.isdir(path):
        raise ValueError(f"{path} is a file, not a folder.")
    return path


def names(paths):
    """{code: file name in the folder}: the name of the original, with its code in front when two share a name."""
    base = {code: os.path.basename(p) for code, p in paths.items()}
    count = {}
    for n in base.values():
        count[n.lower()] = count.get(n.lower(), 0) + 1
    return {c: n if count[n.lower()] == 1 or n.startswith(c) else f"{c}_{n}" for c, n in base.items()}


def export(folder, refs, originals, head, file_name, unmarked, highlight=True, overwrite=False):
    """Copy the files of the documents of refs [(code, page, quote)] into folder and make file_name there, one page a
    sheet. originals(code) -> (path, why); head(code, page, quote) -> the line above a page (HTML); unmarked:
    {status: the note under it when a quote is not marked, or only in part}. Without overwrite nothing is written
    when a file is there already: the answer names them. A file that does not open as a PDF is left out before
    anything is written. -> dict(folder, files, pdf, marked, partial, none, missing, exists)."""
    import pymupdf

    paths, missing, failed = {}, [], set()
    for code, _, _ in refs:
        if code in paths or code in failed:
            continue
        path, why = originals(code)
        if path:
            try:  # an encrypted or damaged file: left out, nothing half-written
                with pymupdf.open(path) as d:
                    if d.needs_pass:
                        raise ValueError("the PDF is protected by a password")
                paths[code] = path
                continue
            except Exception as e:
                why = f"{path}: {e}"
        failed.add(code)
        missing.append(f"{code}: {why}")
    pdf = os.path.join(folder, f"{file_name} — {time.strftime('%Y-%m-%d')}.pdf")
    targets = {code: os.path.join(folder, n) for code, n in names(paths).items()}
    exists = sorted({t for t in [*targets.values(), pdf] if os.path.exists(t)})
    out = dict(folder=folder, files=[], pdf=None, marked=0, partial=0, none=0, missing=missing, exists=exists)
    if exists and not overwrite:
        return out
    os.makedirs(folder, exist_ok=True)
    for code, p in paths.items():
        if os.path.normcase(os.path.abspath(p)) != os.path.normcase(targets[code]):
            shutil.copy2(p, targets[code])
        out["files"].append(targets[code])
    book = pymupdf.open()
    for code, page, quote in refs:
        if code not in paths:
            continue
        with pymupdf.open(paths[code]) as src:
            if not 1 <= page <= src.page_count:
                out["missing"].append(f"{code}: no PDF page {page}")
                continue
            one, status = marked_page(src, page, quote if highlight else "")
        if status:
            out["none" if status == "rotated" else status] += 1
        r = one[0].rect
        sheet = book.new_page(width=r.width, height=r.height + HEAD)
        sheet.show_pdf_page(pymupdf.Rect(0, HEAD, r.width, r.height + HEAD), one, 0)
        line = head(code, page, quote) + (f"<br><i>{unmarked[status]}</i>" if status in unmarked else "")
        sheet.insert_htmlbox(pymupdf.Rect(18, 6, r.width - 18, HEAD - 2), line, css="* {font-size: 8.5pt;}")
        one.close()
    if book.page_count:
        book.save(pdf, garbage=3, deflate=True)
        out["pdf"] = pdf
    book.close()
    return out
