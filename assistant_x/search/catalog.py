# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""index/CATALOG.md and index/sources_to_update.md made from the cards (index/cards/<code>.json): the cards are the
one source of truth, these two files are views of them for people and are never edited by hand. The apply of an
intake and `assistant-x build` write them again; a file is rewritten only when its content changed.

    CATALOG.md            a row per document: code, title, type, shelf, year, format, topics
    sources_to_update.md  the issues of the cards (file.issues): "Open" by priority, "Closed" with their date
Usage: python -m assistant_x.search.catalog [--config assistant_x.toml]"""

import argparse, datetime, os, re
from pathlib import Path

from assistant_x.core import card as C
from assistant_x.core import config as settings

CATALOG, UPDATES = "CATALOG.md", "sources_to_update.md"
CATALOG_COLUMNS = ("Code", "Document", "Type", "Section", "Year", "Format", "Key topics")
CATALOG_STAMP_RX = re.compile(r"(?m)^Updated: [^.]*\. Documents: \d+\.")
UPDATES_OPEN, UPDATES_CLOSED = "Open", "Closed"
UPDATES_STAMP_RX = re.compile(r"(?m)^Updated: [^.]*\. Open items: \d+\.")
UPDATES_COLUMNS = ("Code", "Document", "What is wrong", "What is needed", "Priority", "Noted")
PRIORITIES = ("high", "medium", "low")
NOTE = "Made from the cards (index/cards/*.json) by the intake and by assistant-x build: do not edit, change the cards."


def priority_rank(p):
    p = (p or "").strip().lower()
    return PRIORITIES.index(p) if p in PRIORITIES else len(PRIORITIES)


def catalog_stamp(date, n):
    return f"Updated: {date}. Documents: {n}."


def updates_stamp(date, n):
    return f"Updated: {date}. Open items: {n}."


def _cell(x):
    return re.sub(r"\s+", " ", str(x if x is not None else "")).replace("|", "/").strip()


def _header(cols):
    return "| " + " | ".join(cols) + " |\n|" + "|".join("---" for _ in cols) + "|"


def title_of(card, n=110):
    """The title of a card as the catalog shows it: in the first language of the document (else English), after its
    designation, cut to n characters."""
    doc = card.get("doc") or {}
    lang = (doc.get("lang") or ["en"])[0]
    title = C.text(doc.get("title"), lang)
    desig = C.text(doc.get("designation"), lang)
    full = f"{desig} {title}".strip() if desig and desig not in title else title
    return full if len(full) <= n else full[: n - 1] + "…"


def load_cards(cards_dir):
    """({code: card}, [errors of the files that are no cards]): broken files are left out, not fatal here
    (assistant-x check reports them)."""
    cards, errors = {}, []
    for code, p in C.paths(cards_dir).items():
        try:
            cards[code] = C.load(p)
        except C.CardError as e:
            errors.append(str(e))
    return cards, errors


def catalog_text(cards, date, profile=None):
    rows = []
    for code in sorted(cards):
        c = cards[code]
        doc, file = c.get("doc") or {}, c.get("file") or {}
        fmt = C.format_line(file.get("format")).rsplit(", ", 1)[0]
        rows.append(
            "| "
            + " | ".join(
                _cell(x)
                for x in (
                    code,
                    title_of(c),
                    c.get("doc_type"),
                    settings.section_name(c.get("section"), profile),
                    doc.get("year") or "",
                    fmt,
                    ", ".join(doc.get("topics") or []),
                )
            )
            + " |"
        )
    return (
        "\n".join(["# Library catalog", "", catalog_stamp(date, len(rows)), "", NOTE, "", _header(CATALOG_COLUMNS), *rows])
        + "\n"
    )


def issues(cards):
    """[(code, card, issue)] of every issue of every card, the open ones by priority first."""
    out = [(i.get("code") or code, c, i) for code, c in cards.items() for i in (c.get("file") or {}).get("issues") or []]
    return sorted(
        out, key=lambda x: (bool(x[2].get("closed")), priority_rank(x[2].get("priority")), x[0], x[2].get("noted", ""))
    )


def updates_text(cards, date):
    found = issues(cards)
    open_, closed = [x for x in found if not x[2].get("closed")], [x for x in found if x[2].get("closed")]

    def row(code, c, i, extra=()):
        return (
            "| "
            + " | ".join(
                _cell(x)
                for x in (code, title_of(c, 80), i.get("what"), i.get("need"), i.get("priority"), i.get("noted"), *extra)
            )
            + " |"
        )

    lines = [
        "# Sources to update",
        "",
        updates_stamp(date, len(open_)),
        "",
        NOTE,
        "",
        f"## {UPDATES_OPEN}",
        "",
        _header(UPDATES_COLUMNS),
        *[row(*x) for x in open_],
        "",
        f"## {UPDATES_CLOSED}",
        "",
    ]
    if closed:
        lines += [_header(UPDATES_COLUMNS + ("Closed",)), *[row(*x, extra=(x[2]["closed"],)) for x in closed]]
    return "\n".join(lines).rstrip("\n") + "\n"


def _same(old, new, stamp_rx):
    """The two texts differ only in their stamp date (or not at all)."""
    return stamp_rx.sub("", old) == stamp_rx.sub("", new)


def _write(path, text, stamp_rx):
    """Write a view when its content changed (the date of the stamp alone is no change); True when written."""
    path = Path(path)
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if old == text or (_same(old, text, stamp_rx) and stamp_rx.search(old)):
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return True


def write(index, date=None, profile=None, cards=None):
    """CATALOG.md and sources_to_update.md of index from its cards; returns (documents, open issues)."""
    index = Path(index)
    date = date or datetime.date.today().isoformat()
    if cards is None:
        cards, _ = load_cards(index / "cards")
    _write(index / CATALOG, catalog_text(cards, date, profile), CATALOG_STAMP_RX)
    _write(index / UPDATES, updates_text(cards, date), UPDATES_STAMP_RX)
    return len(cards), sum(1 for *_, i in issues(cards) if not i.get("closed"))


def main():
    from assistant_x.core.common import load_config

    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    a = ap.parse_args()
    cfg = load_config(a.config)
    n, k = write(Path(cfg["catalog"]).parent, profile=cfg)
    print(f"Catalog: {n} documents; sources to update: {k} open items.")


if __name__ == "__main__":
    main()
