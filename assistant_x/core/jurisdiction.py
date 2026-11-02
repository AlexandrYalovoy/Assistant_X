# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The jurisdiction of a document: the state or the union whose norm it is, doc.jurisdiction of a card.

    KZ, RU, US, DE, GB …   a country, ISO 3166-1 alpha-2
    EAEU                   the Eurasian Economic Union and the Customs Union before it (TR CU, TR EAEU)
    CIS                    the interstate standards of the CIS countries (GOST without R, interstate building norms)
    EU                     European standards (EN)
    INT                    international bodies (ISO, IEC, ITU, IMO, register rules)

The patterns are data, the [value, pattern] pairs of the language packs (lang/<code>/jurisdiction.json, the keys
jurisdiction_designations and jurisdiction_words), then of the profile: the first match wins. A designation decides
(each of "A / B"; else the start of the title); without one, the names of a state or a union in the title, the
publisher and the source name of a normative document, then in the start of its text: one value is the answer, two
are a doubt (left empty: unsure). A book, a drawing, a datasheet get a value only by a designation.

Usage: python -m assistant_x.core.jurisdiction <cards folder> [--texts <texts folder>] [--write --backup <folder>]
       counts the values a backfill gives the cards without one (and lists the unsure ones); --write sets them."""

import argparse, functools, json, re, shutil, sys
from collections import Counter
from pathlib import Path

from assistant_x.core import lang

VALUES_RX = re.compile(r"^(?:[A-Z]{2}|EAEU|CIS|EU|INT)$")
# the genres whose jurisdiction the words of their title or text may tell; any other only by its designation
NORMATIVE = ("standard", "regulation", "law", "guideline")
TEXT_HEAD = 3000  # the characters of the start of a text read for the names of a state


@functools.lru_cache(maxsize=None)
def _rules(key):
    out = []
    for value, pattern in lang.words(key):
        if not VALUES_RX.match(value):
            raise ValueError(f"{key}: {value!r} is no jurisdiction (KZ, RU, US, EAEU, CIS, EU, INT …)")
        out.append((value, re.compile(pattern)))
    return tuple(out)


def _texts(m):
    """The texts of a map {language: text} (or a plain string), each of "A / B" apart."""
    vals = m.values() if isinstance(m, dict) else [m] if m else []
    return [x.strip() for v in vals if isinstance(v, str) for x in v.split(" / ") if x.strip()]


@functools.lru_cache(maxsize=None)
def _amendment():
    """The head of an amendment ("Amendment No. 1 to"): the designation of the amended standard follows it."""
    return re.compile(rf"(?i)^(?:{lang.alt('amendment')})\s*(?:\w{{1,3}}\s+)?")


def by_designation(*names):
    """The jurisdiction the first designation that a pattern knows gives (an amendment: that of the standard it
    amends), else ''."""
    for n in names:
        n = _amendment().sub("", n)
        for value, rx in _rules("jurisdiction_designations"):
            if rx.search(n):
                return value
    return ""


def by_words(*texts):
    """{values} the names of states and unions in the texts give."""
    found = set()
    for t in texts:
        for value, rx in _rules("jurisdiction_words"):
            if t and rx.search(t):
                found.add(value)
    return found


def detect(doc, doc_type="", source="", text=""):
    """(value, how) of a document: how is 'designation', 'words', 'text', or 'unsure' / '' with the value ''
    ('unsure': a normative document no rule places or two rules place apart; '': a document of another genre)."""
    doc = doc or {}
    names = _texts(doc.get("designation")) + ([doc["amends"]] if doc.get("amends") else [])
    v = by_designation(*names) or (by_designation(*_texts(doc.get("title"))) if not names else "")
    if v:
        return v, "designation"
    if doc_type not in NORMATIVE:
        return "", ""
    how = "words"
    found = by_words(*_texts(doc.get("title")), doc.get("publisher") or "", source or "")
    if not found and text:
        how, found = "text", by_words(text[:TEXT_HEAD])
    if found == {"KZ", "EAEU"}:  # an act of the union as Kazakhstan publishes it: the union's
        found = {"EAEU"}
    if len(found) == 1:
        return found.pop(), how
    return "", "unsure"


def of_card(card, text=""):
    """detect() of a card (its doc, genre and source name)."""
    return detect(card.get("doc") or {}, card.get("doc_type") or "", (card.get("file") or {}).get("source_name") or "", text)


def backfill(cards_dir, texts_dir=None, write=False, backup=None):
    """{'counts': {value: n}, 'unsure': [code], 'set': [(code, value, how)], 'kept': n} for the cards without a
    jurisdiction; write=True writes the value into each card, the card as it was copied to backup first."""
    from assistant_x.core import card as C

    counts, unsure, done, kept = Counter(), [], [], 0
    for p in C.paths(cards_dir).values():
        c = C.load(p)
        if (c.get("doc") or {}).get("jurisdiction"):
            kept += 1
            counts[c["doc"]["jurisdiction"]] += 1
            continue
        text = ""
        if texts_dir:
            t = Path(texts_dir) / f"{c.get('code')}.md"
            text = t.read_text(encoding="utf-8", errors="replace")[:TEXT_HEAD] if t.is_file() else ""
        value, how = of_card(c, text)
        if not value:
            if how == "unsure":
                unsure.append(c.get("code"))
            counts["(none)"] += 1
            continue
        counts[value] += 1
        done.append((c.get("code"), value, how))
        if write:
            if backup:
                Path(backup).mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, Path(backup) / Path(p).name)
            c["doc"]["jurisdiction"] = value
            C.dump(c, p)
    return {"counts": dict(counts), "unsure": unsure, "set": done, "kept": kept}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m assistant_x.core.jurisdiction", description=__doc__.split("\n\n")[0])
    ap.add_argument("cards")
    ap.add_argument("--texts", help="the texts folder (index/texts): the start of a text names a state as well")
    ap.add_argument("--write", action="store_true", help="write the values into the cards")
    ap.add_argument("--backup", help="the folder the changed cards are copied to first (with --write)")
    ap.add_argument("--json", help="write the whole result to this JSON file")
    a = ap.parse_args(argv)
    if a.write and not a.backup:
        ap.error("--write needs --backup")
    res = backfill(a.cards, a.texts, a.write, a.backup)
    print(json.dumps({"counts": res["counts"], "kept": res["kept"], "set": len(res["set"]), "unsure": len(res["unsure"])}, ensure_ascii=False))
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
