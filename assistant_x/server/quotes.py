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


def pick(query, text):
    """The quote of a fragment for a question: the unit with the most stems of the question (a value and a table row
    count a little more), a short sentence with the next one, a table row with its header; the start of the fragment
    when no unit has a word of the question."""
    want = stems(query)
    us = units(text)
    if not us:
        return ""
    best, score = 0, -1.0
    for i, (kind, u, header) in enumerate(us):
        got = found(want, u)
        sc = len(got) + 0.5 * len(found(want, header) - got)  # a row is read with the header of its table
        if got and any(ch.isdigit() for ch in u):
            sc += 0.5  # a value
        if kind == "row" and got:
            sc += 0.25  # the data of a table before the sentence that only names it
        if kind == "text" and len(u.split()) <= 12 and (TOC.search(u) or re.search(r"\d\s+\D+\s\d{1,4}$", u)):
            sc -= 10  # a line of a table of contents names a subject and a page, it answers nothing
        if sc > score:
            best, score = i, sc
    kind, quote, header = us[best]
    if kind == "row" and header:
        quote = f"{header}: {quote}"
    elif kind == "text" and len(quote) < SHORT and best + 1 < len(us) and us[best + 1][0] == "text":
        quote = f"{quote} {us[best + 1][1]}"
    return cut(quote, QUOTE_CHARS)


def cut(text, n):
    if len(text) <= n:
        return text
    sp = text.rfind(" ", int(n * 0.7), n)
    return text[: sp if sp > 0 else n].rstrip(" ,;:") + "…"


def line(query, r):
    """«quote» — [code, PDF N], short title of a page hit (None for the card of a document: it has no page)."""
    if r.get("kind") in ("card", "card_q") or not r.get("page"):
        return None
    quote = (r.get("quote") or pick(query, r.get("text") or "")).replace("«", '"').replace("»", '"')
    if not quote:
        return None
    at = f"p. {r['label']}, PDF {r['page']}" if r.get("label") else f"PDF {r['page']}"
    return f"«{quote}» — [{r['code']}, {at}], {cut(' '.join((r.get('title') or '').split()), TITLE_CHARS)}"


def lines(query, res):
    """The lines of the page hits, one per hit, the highest level of the hierarchy of documents first (the order of
    the search within a level); [] when no hit has a page."""
    ranked = sorted(res, key=lambda r: r.get("level") if r.get("level") is not None else 99)
    return [x for x in (line(query, r) for r in ranked) if x]
