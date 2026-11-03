# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The reference mode of a small local model (LM Studio, the compact bridge): every search hit as one line ready to
copy, «quote» — [code, cl. N, table N, p. N, PDF N], short title. The quote is the sentence or the table row of the fragment that holds the
most words of the question (a table row with the header of its table), cut short to save the context of the model.
Standard library only: the server and the bridge both use it."""

import re

QUOTE_CHARS = 320  # the longest quote of a line
TITLE_CHARS = 90  # the short title after the reference
SHORT = 120  # a sentence shorter than this takes the next one with it
HEAD = (
    "Quotes for the answer (reference mode): copy the lines you use exactly as they are, each with its reference; "
    "read_pages(code, page, page) gives a whole page."
)

WORD = re.compile(r"\w+", re.UNICODE)
SENTENCE = re.compile(r"(?<=[.!?;])\s+")
TOC = re.compile(r"(\.{3,}|…{2,}|\s)\d{1,4}\s*$")  # a line of a table of contents: it ends in a page number
PICTURE = re.compile(r"<!-- Start of picture text -->.*?<!-- End of picture text -->", re.S)
MARKUP = re.compile(r"<br\s*/?>|\*\*|__|`|^#+\s*", re.M)


def stems(text):
    """The stems of the content words of a question: a word of four letters or more without its ending (its first
    five letters, a shorter word without its last letter: a crude stem that holds for the word forms of Russian and
    English alike), a number as it is."""
    out = set()
    for w in WORD.findall((text or "").lower()):
        if w.isdigit():
            out.add(w)
        elif len(w) >= 4:
            out.add(w[:5] if len(w) >= 6 else w[:-1])
    return out


def found(want, text):
    """The stems of want that start a word of text (a word glued by the recognition counts by its start too)."""
    words = WORD.findall((text or "").lower())
    return {s for s in want if any(w.startswith(s) for w in words)}


def clean(text):
    return " ".join(MARKUP.sub(" ", text).replace("_", " ").split())


def cells(row):
    return [clean(c) for c in row.strip().strip("|").split("|")]


def units(text):
    """(kind, text, the header row of its table or "") of a fragment: its table rows and its sentences in order."""
    out, header, in_table = [], "", False
    for line in PICTURE.sub("\n", text or "").splitlines():
        s = line.strip()
        if s.startswith("|"):
            if re.fullmatch(r"\|[\s|:-]*\|?", s):  # the separator row of a markdown table
                continue
            row = " | ".join(c for c in cells(s) if c)
            if not in_table:
                header, in_table = row, True
                out.append(("row", row, ""))
            else:
                out.append(("row", row, header))
            continue
        in_table = False
        for sent in SENTENCE.split(clean(s)):
            if sent:
                out.append(("text", sent, ""))
    return out


CLAUSE = re.compile(r"^\s*\d+(?:\.\d+)+\.?\s")  # the number of a clause at the start of a line: no value
# a clause that heads a line: its number, then a word with a capital or of 4 letters at least ("6.2.1.9 The speeds",
# "3.1 pipeline: a ..."), never a date ("01.07.2021 entered") or a value with its unit ("2.5 m is")
HEAD_CLAUSE = re.compile(r"^\s*(\d+(?:\.\d+)+)\.?\s+[\W\d_]*([^\W\d_]+)")
DATE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$")
_value = []


def value_rx():
    """A value of a norm: a range ("5-20", "2,0…5,0") or a number with a unit of measure of the language packs
    (lang/<code>/text.json "units"), or a percent or a degree."""
    if not _value:
        from assistant_x.core import lang

        units = sorted(set(lang.words("units")), key=len, reverse=True)
        unit = "|".join(re.escape(u) for u in units) or "(?!)"
        _value.append(re.compile(rf"\d+(?:[,.]\d+)?\s*(?:-|–|…|\.\.\.)\s*\d|\d\s*(?:%|°|(?:{unit})(?!\w))"))
    return _value[0]


def worth(want, unit, header="", row=False):
    """The score of a sentence or a table row for a question: the stems of the question in it, the ones only in the
    header of its table a half; a value (a range, a number with its unit; not the number of a clause) one more, a
    table row with a word of the question a quarter more, a line of a table of contents far less."""
    got = found(want, unit)
    sc = len(got) + 0.5 * len(found(want, header) - got)
    if (got or found(want, header)) and value_rx().search(CLAUSE.sub("", unit)):
        sc += 1.5
    if row and got:
        sc += 0.25
    if not row and len(unit.split()) <= 12 and (TOC.search(unit) or re.search(r"\d\s+\D+\s\d{1,4}$", unit)):
        sc -= 10
    return sc


def pick(query, text):
    """The quote of a fragment for a question with the header of its table in front of a table row (one string)."""
    quote, header = pick_parts(query, text)
    return f"{header}: {quote}" if header else quote


def pick_parts(query, text):
    """(quote, header of its table or "") of a fragment for a question: the unit with the most stems of the question (a
    value and a table row count a little more), a short sentence with the next one; the start of the fragment when no
    unit has a word of the question. The quote is the text of the page as it is (verify_quote finds it), the header of
    a table row apart."""
    want = stems(query)
    us = units(text)
    if not us:
        return "", ""
    best, score = 0, -1.0
    for i, (kind, u, header) in enumerate(us):
        sc = worth(want, u, header, kind == "row")
        if sc > score:
            best, score = i, sc
    kind, quote, header = us[best]
    if kind == "text" and len(quote) < SHORT and best + 1 < len(us) and us[best + 1][0] == "text":
        quote = f"{quote} {us[best + 1][1]}"
    return cut(quote, QUOTE_CHARS), (cut(header, TITLE_CHARS) if kind == "row" else "")


WINDOW = 900  # the characters of a search hit shown around its best line


ENGLISH = ("cl.", "table", "p.")  # the labels of a reference: clause, table, printed page


def labels(lang):
    """The labels of a reference in a language (lang/<code>/text.json "ref_labels"), English when it has none."""
    from assistant_x.core import lang as packs

    got = packs.get(lang, "ref_labels") if lang in packs.available() else None
    return tuple(got) if got and len(got) == 3 else ENGLISH


def cite(code, pdf, page=None, clause=None, table=None, lang="en"):
    """The one form of a reference: [code, cl. 6.2.1.9, table 1, p. 36, PDF 36], the labels in the language of the
    answer (lang/<code>/text.json "ref_labels"); a part that is not known is left out, never made up; the code and the
    PDF page always."""
    cl, tb, pg = labels(lang)
    parts = [code]
    parts += [f"{cl} {clause}"] if clause else []
    parts += [f"{tb} {table}"] if table else []
    parts += [f"{pg} {page}"] if page else []
    return "[" + ", ".join(parts + [f"PDF {pdf}"]) + "]"


_caption = []


def caption_rx():
    """A caption of a table (the words of the language packs, lang/<code>/references.json "caption_table") and its
    number."""
    if not _caption:
        from assistant_x.core import lang

        words = "|".join(lang.words("caption_table")) or "(?!)"
        _caption.append(re.compile(rf"^\W*(?:{words})\W*\s*([^\W_][\w.\-]*)", re.I))
    return _caption[0]


def place(text, at):
    """(clause, table) of the line at of a page text: the nearest number of a clause at the start of a line up to it,
    and, for a table row, the number of the nearest caption of a table above it; None for a part not found."""
    lines = (text or "").splitlines()
    if not lines:
        return None, None
    at = max(0, min(at, len(lines) - 1))
    clause = table = None
    for i in range(at, max(-1, at - 40), -1):
        m = HEAD_CLAUSE.match(clean(lines[i]))
        if m and (m.group(2)[0].isupper() or len(m.group(2)) >= 4) and not DATE.match(m.group(1)):
            clause = m.group(1)
            break
    if lines[at].lstrip().startswith("|"):
        for i in range(at, max(-1, at - 60), -1):
            m = caption_rx().match(clean(lines[i]))
            if m and any(ch.isdigit() for ch in m.group(1)):  # "Table 5.3", "Table A.1"; not "Table continued"
                table = m.group(1).rstrip(".")
                break
    return clause, table


def line_of(text, quote):
    """The index of the line of a page text that holds the start of a quote (-1 when none does)."""
    head = squash(quote.split(" | ")[0])[:30]
    if not head:
        return -1
    for i, x in enumerate((text or "").splitlines()):
        if head in squash(x):
            return i
    return -1


def squash(s):
    return re.sub(r"[\s|*_]+", "", s or "").lower()


def best_line(query, lines):
    """The index of the line of a fragment with the most words of the question (worth: a value counts more, a table
    row is read with the header of its table)."""
    if not lines:
        return 0
    want = stems(query)
    header, heads = "", []
    for x in lines:  # the header row of the table of each line ("" outside a table)
        row = x.lstrip().startswith("|")
        header = (header or clean(x)) if row else ""
        heads.append(header if row else "")
    return max(
        range(len(lines)),
        key=lambda i: (worth(want, clean(lines[i]), heads[i], lines[i].lstrip().startswith("|")), -i),
    )


def head_cite(query, r, lang="en"):
    """The reference of a search hit in the one form (cite): the clause and the table of its line the most about the
    question."""
    text = r.get("text") or ""
    clause, table = place(text, best_line(query, text.splitlines())) if text else (None, None)
    return cite(r["code"], r["page"], r.get("label"), clause, table, lang)


def window(query, text, n=WINDOW):
    """The lines of a fragment around the one with the most words of the question (a value counts a little more),
    n characters at most, a table row with the header row of its table; the fragment itself when it is short.
    read_pages gives the whole page."""
    text = text or ""
    if len(text) <= n:
        return text
    lines = text.splitlines()
    best = best_line(query, lines)
    lo = hi = best
    size = len(lines[best])
    while True:  # the neighbours, after it first, while they fit
        grown = False
        for j in (hi + 1, lo - 1):
            if 0 <= j < len(lines) and size + len(lines[j]) + 1 <= n and (j > hi or j < lo):
                size += len(lines[j]) + 1
                lo, hi = min(lo, j), max(hi, j)
                grown = True
        if not grown:
            break
    shown, before = lines[lo : hi + 1], lo > 0
    if lines[best].lstrip().startswith("|"):  # the header row of its table, when it is above the lines shown
        top = best
        while top > 0 and lines[top - 1].lstrip().startswith("|"):
            top -= 1
        if top < lo:
            shown, before = [lines[top], "…"] + shown, top > 0
    out = ("…\n" if before else "") + "\n".join(shown) + ("\n…" if hi < len(lines) - 1 else "")
    return out if len(out) <= 2 * n else cut(out, n)  # one long line of a recognized page


def cut(text, n):
    if len(text) <= n:
        return text
    sp = text.rfind(" ", int(n * 0.7), n)
    return text[: sp if sp > 0 else n].rstrip(" ,;:") + "…"


def on_page(text, quote):
    """Is every cell of a quote (a row "a | b", or a sentence) in the text of its page, spaces and marks aside?"""
    page = squash_all(text)
    return all(squash_all(x) in page for x in quote.split(" | ") if squash_all(x))


def squash_all(s):
    return re.sub(r"[\W_]+", "", re.sub(r"<br\s*/?>", " ", s or "")).lower()


def line(query, r, lang="en"):
    """«quote» — [code, cl. N, table N, p. N, PDF N], short title of a page hit (None for the card of a document: it has no page)."""
    if r.get("kind") in ("card", "card_q") or not r.get("page"):
        return None
    given = r.get("quote") or r.get("evidence") or ""  # a key norm: the quote that verified its topic on the page
    header = r.get("header") or ""
    if given and not header and ": " in given and " | " in given.split(": ", 1)[0]:  # "header: row" of a table
        header, given = given.split(": ", 1)
    if given and not on_page(r.get("text") or "", given):
        given = ""  # a quote of a key norm the page text does not hold (a recognition slip, a glued caption): never shown
    if (r.get("quote") and given) or (given and found(stems(query), given) and value_rx().search(CLAUSE.sub("", given))):
        quote = given  # the evidence answers the question: it has a word of it and a value
    else:
        quote, header = pick_parts(query, r.get("text") or "")
    quote = quote.replace("«", '"').replace("»", '"')
    if not quote:
        return None
    i = line_of(r.get("text") or "", quote)
    clause, tab = place(r.get("text") or "", i) if i >= 0 else (None, None)
    ref = cite(r["code"], r["page"], r.get("label"), clause, tab, lang)
    table = (
        f" ({labels(lang)[1]}: {header})" if header else ""
    )  # the columns of a row, outside the quote: it stays verifiable
    mark = f" [{r['supplement']}]" if r.get("supplement") else ""  # a foreign national norm, after the answer
    title = cut(" ".join((r.get("title") or "").split()), TITLE_CHARS)
    return f"«{quote}»{table} — {ref}, {title}{mark}"


PER_DOC = 2  # quote lines of one document in a search: the others get places too


def lines(query, res, n=None, lang="en"):
    """The lines of the page hits, one per hit, the highest level of the hierarchy of documents first (the order of
    the search within a level), PER_DOC of a document and n at most (all when None); [] when no hit has a page."""
    ranked = sorted(res, key=lambda r: (bool(r.get("supplement")), r.get("level") if r.get("level") is not None else 99))
    out, per = [], {}
    for r in ranked:
        if per.get(r["code"], 0) >= PER_DOC:
            continue
        x = line(query, r, lang)
        if x:
            per[r["code"]] = per.get(r["code"], 0) + 1
            out.append(x)
    return out[:n] if n else out
