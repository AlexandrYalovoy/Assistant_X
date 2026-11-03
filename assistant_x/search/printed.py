# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The printed page of a PDF page found in its own text, for a PDF without page labels: a standard prints its page
number in the header or the footer. A candidate is a top or bottom line that is the number alone ("15", "- 15 -",
"iv") or the number with the word of a page ("Page 15 of 191"; the words of the language packs, references.json
"page_words" and "page_of"); never a number inside a text ("Example No. 4"). It counts only when the neighbouring
pages have one with the same offset to the PDF page: a run of RUN pages in a row. One offset only: when two fit, or
none, the page has no printed number here — never a guess. An offset of 0 (the printed page is the PDF page) adds
nothing to a reference and is left out."""

import re
from functools import lru_cache

EDGE = 3  # lines at the top and at the bottom of a page
RUN = 3  # pages in a row with the same offset
DASH = r"[\s\-–—]*"
ROMAN = re.compile(r"^(?=[ivxlc]+$)(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$", re.I)
VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}


@lru_cache(maxsize=1)
def line_rx():
    from assistant_x.core import lang

    return re.compile(
        rf"^{DASH}(?:(?:{lang.alt('page_words')})\s*)?(\d{{1,4}}|[ivxlcIVXLC]{{1,9}})"
        rf"(?:\s+(?:{lang.alt('page_of')})\s+\d{{1,4}})?{DASH}$"
    )


def roman(word):
    """The value of a roman numeral (up to 399), or None."""
    if not word or not ROMAN.match(word):
        return None
    w, total = word.lower(), 0
    for i, ch in enumerate(w):
        v = VALUES[ch]
        total += -v if i + 1 < len(w) and VALUES[w[i + 1]] > v else v
    return total


def candidates(text):
    """{(kind, value): as printed} of the page numbers of the top and bottom lines of a page; kind "n" or "r"."""
    lines = [s for s in (text or "").splitlines() if s.strip() and not s.lstrip().startswith(("|", "<!--"))]
    out = {}
    for s in lines[:EDGE] + lines[-EDGE:]:
        m = line_rx().match(re.sub(r"[*_#`]", " ", s).strip())
        if not m:
            continue
        got = m.group(1)
        if got.isdigit():
            out.setdefault(("n", int(got)), got)
        elif (v := roman(got)) is not None:
            out.setdefault(("r", v), got)
    return out


def detect(texts):
    """{PDF page: printed page} of a document from {PDF page: text}."""
    offsets = {p: {(k, v - p): shown for (k, v), shown in candidates(t).items()} for p, t in texts.items()}
    out = {}
    for p in offsets:
        fits = set()
        for key in offsets[p]:
            for start in range(p - RUN + 1, p + 1):  # a run of RUN pages in a row with p in it
                if all(key in offsets.get(q, {}) for q in range(start, start + RUN)):
                    fits.add(key)
                    break
        if len(fits) == 1:
            key = fits.pop()
            if key[1] != 0:
                out[p] = offsets[p][key]
    return out
