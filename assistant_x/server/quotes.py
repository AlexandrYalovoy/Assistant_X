# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The reference mode of a small local model (LM Studio, the compact bridge): every search hit as one line ready to
copy, «quote» — [code, PDF N], short title. The quote is the sentence or the table row of the fragment that holds the
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


def window(query, text, n=WINDOW):
    """The lines of a fragment around the one with the most words of the question (a value counts a little more),
    n characters at most, a table row with the header row of its table; the fragment itself when it is short.
    read_pages gives the whole page."""
    text = text or ""
    if len(text) <= n:
        return text
    lines = text.splitlines()
    want = stems(query)
    header, heads = "", []
    for x in lines:  # the header row of the table of each line ("" outside a table)
        row = x.lstrip().startswith("|")
        header = (header or clean(x)) if row else ""
        heads.append(header if row else "")
    best = max(
        range(len(lines)),
        key=lambda i: (worth(want, clean(lines[i]), heads[i], lines[i].lstrip().startswith("|")), -i),
    )
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


def line(query, r):
    """«quote» — [code, PDF N], short title of a page hit (None for the card of a document: it has no page)."""
    if r.get("kind") in ("card", "card_q") or not r.get("page"):
        return None
    if r.get("quote"):  # a key norm: its verified quote, "header: row" for a table row of an older list
        quote, header = r["quote"], r.get("header") or ""
        if not header and ": " in quote and " | " in quote.split(": ", 1)[0]:
            header, quote = quote.split(": ", 1)
    else:
        quote, header = pick_parts(query, r.get("text") or "")
    quote = quote.replace("«", '"').replace("»", '"')
    if not quote:
        return None
    at = f"p. {r['label']}, PDF {r['page']}" if r.get("label") else f"PDF {r['page']}"
    table = f" (table: {header})" if header else ""  # the columns of a row, outside the quote: it stays verifiable
    mark = f" [{r['supplement']}]" if r.get("supplement") else ""  # a foreign national norm, after the answer
    title = cut(" ".join((r.get("title") or "").split()), TITLE_CHARS)
    return f"«{quote}»{table} — [{r['code']}, {at}], {title}{mark}"


def lines(query, res):
    """The lines of the page hits, one per hit, the highest level of the hierarchy of documents first (the order of
    the search within a level); [] when no hit has a page."""
    ranked = sorted(res, key=lambda r: (bool(r.get("supplement")), r.get("level") if r.get("level") is not None else 99))
    return [x for x in (line(query, r) for r in ranked) if x]
