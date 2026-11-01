# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A new version of a document of the library: a file of the batch with the same designation (another year: "GOST R
51858-2002" in the library, "GOST R 51858-2020" in inbox) or a very similar title. The draft asks Claude to put the
question to the user, and meta.jsonl takes the answer:

    {"replaces": "N-00001"}       the new file takes the code N-00001, the old original goes to inbox\\_to_delete
    {"other_version": "N-00001"}  both stay; the cards name each other (doc.other_versions)

Whether a document is in force is the user's matter: the library keeps the versions the user chose. An amendment to a
standard (the "amends" of its draft) is no version of it: it is never paired with its base."""

import re
from pathlib import Path

from assistant_x.core.common import tokens

SIMILAR = 0.8  # a title with this share of the words of another one in common (and at least MIN_WORDS words)
MIN_WORDS = 3
YEAR_TAIL = re.compile(r"\s*[-–—:.]\s*\d{2,4}\s*$")


def key(designation):
    """The designation without its year and spaces: the same standard in every edition."""
    return re.sub(r"[–—]", "-", re.sub(r"\s+", "", YEAR_TAIL.sub("", designation or "")).upper())


def norm(designation):
    """The designation as written, spaces and dashes evened out: two editions differ here, not in key()."""
    return re.sub(r"[–—]", "-", re.sub(r"\s+", "", designation or "").upper())


def words(title):
    return {w for w in tokens(title or "", drop_stop=True) if not w[0].isdigit() and len(w) > 2}


def library(index):
    """[(code, title, designation)] of the documents of the library by their cards, one row per language of the
    designation (a Russian standard is found by its Russian and its Latin designation)."""
    from assistant_x.core import card as C

    out = []
    for code, p in C.paths(Path(index) / "cards").items():
        try:
            doc = C.load(p).get("doc") or {}
        except C.CardError:
            continue
        title = " ".join(C.all_texts(doc.get("title")))
        for d in C.all_texts(doc.get("designation")) or [None]:
            out.append((code, title, d))
    return out


def find(desig, title, docs):
    """(code, title, why) of the document of the library this one looks like a version of, or None."""
    k = key(desig)
    if k:
        for code, t, d in docs:
            if d and key(d) == k:
                same = norm(d) == norm(desig)  # spaces and dashes aside: the same year too
                return (
                    code,
                    t,
                    (f"{SAME}{d}" if same else f"the same designation: {d} in the library, {desig} here"),
                )
    w = words(title)
    if len(w) >= MIN_WORDS:
        best = None
        for code, t, _ in docs:
            o = words(t)
            share = len(w & o) / len(w | o) if o else 0
            if share >= SIMILAR and (best is None or share > best[0]):
                best = (share, code, t)
        if best:
            return best[1], best[2], f"a very similar title ({best[0]:.0%} of the words in common)"
    return None


SAME = "the same designation "  # the start of the why of find for a designation written alike, the year too


def question(code, title, why):
    if why.startswith(SAME):  # the same standard of the same year: a copy rather than a new version
        return (
            f"has {why} as {code} «{title[:80]}» of the library: most likely the same document — "
            f'{{"dupof": "{code}"}}; a better copy (a text layer instead of a scan) may take its place — '
            f'{{"replaces": "{code}"}} — after the user says so'
        )
    return (
        f"looks like a new version of {code} «{title[:80]}» ({why}): ask the user whether it replaces the old one — "
        f'{{"replaces": "{code}"}} (the old original goes to inbox\\_to_delete) — or both stay — '
        f'{{"other_version": "{code}"}}'
    )
