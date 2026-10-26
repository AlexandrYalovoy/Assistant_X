# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check index before the base is built: every card passes the schema and the profile (core/card.validate), the cards,
their parts, the texts and the originals agree. Errors stop build_index.py; warnings are only listed.
A text is checked against the text format "AX text 1" (docs/INTAKE.md): its page markers in order and, when the
original PDF is at hand, one for every page of it (errors); line ends CRLF, invisible characters, a missing
<code>.pages.json or one with other pages than the text (warnings).
Usage: assistant-x check [--config assistant_x.toml] [--all] [--no-files]
  --all       show every case, not the first 10 of each kind
  --no-files  do not look for the originals in library (e.g. on a copy of the index without the library)"""

import argparse, collections, os
from assistant_x.core import card as C
from assistant_x.core import config as settings
from assistant_x.core.common import INVISIBLE_RX, load_config, split_pages, text_stats
from assistant_x.core.formats import PAGE_RX, pages_path, place_path, read_pages_info
from assistant_x.core.txn import exists, lp
from assistant_x.search.build_index import text_file

SHOW = 10


class Report:
    def __init__(self):
        self.items = collections.OrderedDict()  # (level, kind) -> [text]

    def add(self, level, kind, text):
        self.items.setdefault((level, kind), []).append(text)

    def count(self, level):
        return sum(len(v) for (lv, _), v in self.items.items() if lv == level)

    def lines(self, show_all=False, levels=("error", "warning")):
        out = []
        for (level, kind), texts in self.items.items():
            if level not in levels:
                continue
            out.append(f"{'ERROR' if level == 'error' else 'Warning'}: {kind} — {len(texts)}")
            for t in texts if show_all else texts[:SHOW]:
                out.append(f"    {t}")
            if not show_all and len(texts) > SHOW:
                out.append(f"    … and {len(texts) - SHOW} more (assistant-x check --all)")
        return out


def library_path(root, place):
    return place_path(root, place)


def pdf_pages(path):
    """Page count of a PDF, or None when it does not open."""
    try:
        import pymupdf

        with pymupdf.open(lp(path)) as d:
            return d.page_count
    except Exception:  # noqa: BLE001 — a broken original is another check's matter
        return None


def check_text(tf, sub, original, err, warn):
    """The text format of one text; original: the path of its PDF when it is at hand, else None."""
    raw = open(tf, "rb").read().decode("utf-8", errors="replace")
    name = os.path.basename(tf)
    if "\r\n" in raw:
        warn("a text with CRLF line ends (the text format has LF)", name)
    if INVISIBLE_RX.search(raw):
        warn("invisible characters in a text (zero width, text direction)", f"{name}: {len(INVISIBLE_RX.findall(raw))}")
    marks = [int(n) for n in PAGE_RX.findall(raw.replace("\r\n", "\n"))]
    if any(b <= a for a, b in zip(marks, marks[1:])):
        err("page markers out of order", f"{name}: " + ", ".join(map(str, marks[:12])) + (" …" if len(marks) > 12 else ""))
    if original and marks:
        n = pdf_pages(original)
        if n is not None and len(marks) != n:
            err("the page markers of a text and the pages of its PDF differ", f"{sub}: {len(marks)} markers, {n} PDF pages")
    info = read_pages_info(pages_path(tf))
    if info is None:
        warn("a text without its .pages.json (what is known of its pages)", name)
    elif marks and set(info) != set(marks):
        warn("a .pages.json with other pages than its text", f"{sub}: {len(info)} pages in it, {len(marks)} in the text")


def check(cfg, files=True):
    rep = Report()
    err = lambda kind, text: rep.add("error", kind, text)
    warn = lambda kind, text: rep.add("warning", kind, text)
    langs, topics = settings.card_languages(cfg), settings.topics(cfg)
    letters = [s["letter"] for s in settings.sections(cfg)]

    cards = {}
    for code, p in C.paths(cfg["cards_dir"]).items():
        try:
            c = C.load(p)
        except C.CardError as e:
            err("a card that cannot be read", str(e))
            continue
        problems = C.validate(c, langs, letters, topics)
        if problems:
            err(
                "a card that does not pass the schema or the profile",
                f"{code}: " + "; ".join(problems[:5]) + (f" (and {len(problems) - 5} more)" if len(problems) > 5 else ""),
            )
        if c.get("code") != code:
            err("the name of a card file is not its code", f"{p.name}: code {c.get('code')}")
        cards[code] = c

    root, have_lib = cfg["library_root"], os.path.isdir(os.path.join(cfg["library_root"], "library"))
    places, known_texts = collections.defaultdict(list), set()
    for code, c in sorted(cards.items()):
        file = c.get("file") or {}
        entries = [(code, file)] + [(p.get("code", "?"), p) for p in file.get("parts") or [] if isinstance(p, dict)]
        for sub, f in entries:
            tf = text_file(cfg["texts_dir"], sub)
            if f.get("text") and os.path.basename(f["text"]) not in (f"{sub}.md", f"{sub}.txt"):
                err("the text of a card is not <code>.md", f"{sub}: {f['text']}")
            if tf:
                known_texts.add(os.path.basename(tf))
                pages = split_pages(open(tf, encoding="utf-8").read())
                if not pages:
                    err('no "=== page N ===" markers in the text', os.path.basename(tf))
                else:
                    st = text_stats(pages)
                    if st["fffd_per_1000"] >= 1:
                        warn("many lost symbols in the text (U+FFFD)", f"{sub}: {st['fffd_per_1000']:g} per 1000 characters")
                    if st["empty_share"] >= 0.5:
                        warn("more than half of the pages have almost no text", f"{sub}: {st['empty_share']:.0%}")
                if not f.get("text"):
                    warn("a text the card does not name (file.text is empty)", f"{sub}: {os.path.basename(tf)}")
                pdf = next((p for p in (f.get("library") or "", f.get("pdf_copy") or "") if p.lower().endswith(".pdf")), "")
                pdf = library_path(root, pdf) if pdf and files and have_lib and pdf.startswith("library") else ""
                check_text(tf, sub, pdf if pdf and exists(pdf) else None, err, warn)
            elif sub == code:
                err("no text of the document", f"{code}: {os.path.basename(cfg['texts_dir'])}\\{code}.md")
            elif f.get("text"):
                err("no text of a part its card names", f"{sub}: {f['text']}")
            place = f.get("library") or ""
            if place:
                places[place.lower()].append(sub)
                if files and have_lib and place.startswith("library"):
                    if not exists(library_path(root, place)):
                        err("the original is not on disk at its place in the library", f"{sub}: {place}")
        for other in (c.get("doc") or {}).get("other_versions") or []:
            if other not in cards:
                warn("another version a card names is not in the library", f"{code}: {other}")
    for place, codes in places.items():
        if len(codes) > 1:
            err("one file belongs to several documents", f"{', '.join(codes)}: {place}")
    if os.path.isdir(cfg["texts_dir"]):
        for f in sorted(os.listdir(cfg["texts_dir"])):
            if f.endswith(".md") and not f.startswith("_") and f not in known_texts:
                warn("a text that belongs to no document (it is not searched)", f)
    if files and not have_lib:
        warn("originals not checked", f"no folder {os.path.join(root, 'library')}")
    from assistant_x.core.common import index_stale

    stale = index_stale(cfg)
    if stale:
        warn(
            "the search base is behind the library (an apply on that date): assistant-x build, then assistant-x embed", stale
        )
    # the journal is generated from the intake events and the manifest (core/journal.py)
    idx = os.path.dirname(cfg["catalog"])
    if os.path.exists(os.path.join(idx, "intake_events.tsv")):
        from assistant_x.core import journal

        ok, why = journal.is_current(idx)
        if not ok:
            warn("journal.md is out of date (update: python -m assistant_x.core.journal)", why)
    return rep, len(cards)


def run(cfg, quiet=False, show_all=False, files=True):
    """Number of errors; prints the report (only errors and a summary line when quiet)."""
    rep, n = check(cfg, files)
    e, w = rep.count("error"), rep.count("warning")
    for line in rep.lines(show_all, ("error",) if quiet else ("error", "warning")):
        print(line)
    print(
        f"Index check: cards {n}, errors {e}, warnings {w}" + (" (details: assistant-x check)" if quiet and w else "") + "."
    )
    return e


def main():
    ap = argparse.ArgumentParser(prog="assistant-x check")
    ap.add_argument("--config")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--no-files", action="store_true")
    a = ap.parse_args()
    raise SystemExit(1 if run(load_config(a.config), show_all=a.all, files=not a.no_files) else 0)


if __name__ == "__main__":
    from assistant_x.core import debuglog

    debuglog.run(main, "check_index")
