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
    words = text.split()
    if len(words) <= WORDS:
        return [text]
    return [" ".join(words[i : i + WORDS]) for i in range(0, len(words) - WORDS // 2, WORDS)]


def squash(text):
    """The letters and digits of a text in lower case, yo as ye: what is compared when the spaces differ."""
    return re.sub(r"[\W_]+", "", (text or "").lower().replace("\u0451", "\u0435"))


def by_words(words, text):
    """The boxes of the words of a page (page.get_text("words")) that hold text once the spaces and the marks are
    left out on both sides: a word run together in a recognized text is two words on the page."""
    want = squash(text)
    if len(want) < 2:
        return []
    joined, owner = "", []
    for i, w in enumerate(words):
        s = squash(w[4])
        joined += s
        owner += [i] * len(s)
    import pymupdf

    out, at = [], joined.find(want)
    while at >= 0:
        idx = sorted(set(owner[at : at + len(want)]))
        out += [pymupdf.Rect(words[i][:4]) for i in idx]
        at = joined.find(want, at + len(want))
    return out


def look(page, words, text):
    return page.search_for(text) or by_words(words, text)


def find(page, quote):
    """(rects, status) of a quote on a PyMuPDF page: status "marked" (every part found), "partial" or "none"."""
    pieces = parts(quote)
    if not pieces or not page.get_text("text").strip():
        return [], "none"
    words = page.get_text("words")
    found, total, hit = {}, 0, 0
    for p in pieces:
        got = look(page, words, p)
        if got:
            found[p] = got
            total, hit = total + 1, hit + 1
            continue
        for r in runs(p):  # a long sentence broken by a footnote or a recognition slip: its runs
            total += 1
            if got := look(page, words, r):
                found[r], hit = got, hit + 1
    if not found:
        return [], "none"
    anchor = found[max(found, key=len)]
    top, bottom = min(r.y0 for r in anchor) - NEAR, max(r.y1 for r in anchor) + NEAR
    rects = [r for got in found.values() for r in got if r.y1 >= top and r.y0 <= bottom]
    return rects, "marked" if hit == total else "partial"


def mark(page, rects):
    for r in rects:
        page.draw_rect(r, color=None, fill=MARK, fill_opacity=OPACITY, overlay=True)


def marked_page(src, page_no, quote):
    """(a one-page PDF with the quote marked, status) from page page_no (1-based) of the open PDF src."""
    import pymupdf

    one = pymupdf.open()
    one.insert_pdf(src, from_page=page_no - 1, to_page=page_no - 1)
    if not quote:
        return one, None
    if one[0].rotation:  # the places of the text layer and of the drawing differ on a turned page: no mark
        return one, "none"
    rects, status = find(one[0], quote)
    mark(one[0], rects)
    return one, status


def references(texts):
    """[(code, PDF page, quote or "")] of every reference in the lines of texts (an answer, or reference lines), in
    their order, each once."""
    out, seen = [], set()
    for text in texts:
        for line in str(text).splitlines():
            q = QUOTE.search(line)
            for m in REF.finditer(line):
                key = (m[1], int(m[2]), q[1] if q else "")
                if key not in seen:
                    seen.add(key)
                    out.append(key)
    return out


def safe_folder(folder, forbidden):
    """The absolute folder to write into, or ValueError: a full path, not inside the library (forbidden)."""
    if not folder or not os.path.isabs(folder):
        raise ValueError(f"Give the full path of a folder, e.g. D:\\References, not {folder!r}.")
    path = os.path.normpath(os.path.abspath(folder))
    for f in forbidden:
        if f and os.path.normcase(path + os.sep).startswith(os.path.normcase(os.path.normpath(f) + os.sep)):
            raise ValueError(f"{path} is inside the library: choose a folder of your own.")
    if os.path.exists(path) and not os.path.isdir(path):
        raise ValueError(f"{path} is a file, not a folder.")
    return path


def export(folder, refs, originals, head, file_name, unmarked, highlight=True, overwrite=False):
    """Copy the files of the documents of refs [(code, page, quote)] into folder and make file_name there, one page a
    sheet. originals(code) -> (path, why); head(code, page, quote) -> the line above a page (HTML); unmarked:
    {"none" | "partial": the note under it when a quote is not marked or only in part}. Without overwrite nothing is written when a file is there already: the answer names them.
    -> dict(folder, files, pdf, marked, partial, none, missing, exists)."""
    import pymupdf

    paths, missing = {}, []
    for code, _, _ in refs:
        if code not in paths and code not in missing:
            path, why = originals(code)
            if path:
                paths[code] = path
            else:
                missing.append(f"{code}: {why}")
    pdf = os.path.join(folder, f"{file_name} — {time.strftime('%Y-%m-%d')}.pdf")
    targets = {code: os.path.join(folder, os.path.basename(p)) for code, p in paths.items()}
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
            out[status] += 1
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
