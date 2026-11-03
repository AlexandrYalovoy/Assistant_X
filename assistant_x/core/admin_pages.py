# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Administrative pages kept out of the library (the author, 2026-11-03): a file that holds only such pages — a title
page, an approval or familiarization sheet, an implementation plan, an order putting a document into force, a cover
letter, a service memo, the minutes of a meeting, the explanatory note to a draft norm, a transfer act, in any
combination — is not taken in, whether a document of its own or a part of a set; the same pages bound with real
content in one file go in as usual. Page by page: a page whose head names an administrative page starts an
administrative section, the pages after it stay in it until one starts real content (a clause "Scope", "General",
a table of contents, or much engineering text). The words are those of the language packs (admin_* of intake.json).

Never rejected: a file with too little text to judge (a scan without its text), anything the packs name substantive
(admin_keep: catalogs, reviews, the results or acts of pilot tests, methods, commercial proposals, notices of change,
amendments, orders that approve rules), and a file whose text holds much engineering content unless all of it is an
implementation plan. A doubt is a warning of the intake report, never a rejection.

    classify(name, text) → reject | warn | None; scan_library(index) → the documents of the library to warn of
    the intake sets such files aside: intake/admin_filter.py
"""

import json, re

from assistant_x.core import lang

PAGE_RX = re.compile(r"^=== page \d+ ===\s*$", re.M)
JUNK_RX = re.compile(r"<!--.*?-->|<br>|[*#|_`]+", re.S)
WORD_RX = re.compile(r"\w+")
HEAD = 400  # characters of a page where its kind is named
TITLE_WORDS = 150  # a title page is short
BLANK_WORDS = 15  # a page with less text neither starts nor ends a section
MIN_WORDS = 20  # a file with less text is not judged (a scan without its text)
TECH_KEEP = 25.0  # engineering terms and quantities per 1000 words: past it a file is no administrative paper
TECH_PAGE = 40.0  # ... and a page past it is real content even inside an administrative section
WHOLE_PAGES = 12  # a letter or an order judged by its subject is short
# the kinds whose next pages go on with them (a plan, a letter, the minutes over several pages)
SECTIONS = {"implementation_plan", "order_in_force", "cover_letter", "service_memo", "meeting_minutes", "explanatory_note"}


def _rx(value):
    if isinstance(value, list):
        return [re.compile(v, re.I | re.M) for v in value if v]
    return re.compile(value, re.I | re.M) if value else None


def rules():
    """The rules of the active packs: page kinds, whole-file kinds, substantive words, the start of real content,
    the engineering words and the labels."""
    pages = {k: _rx(v) for k, v in lang.table("admin_pages").items() if v}
    whole = {k: _rx(v) for k, v in lang.table("admin_whole").items() if v}
    keep = {k: _rx(v) for k, v in lang.table("admin_keep").items() if v}
    restart = _rx(lang.alt("admin_restart"))
    tech = _rx(lang.alt("admin_tech"))
    return {"pages": pages, "whole": whole, "keep": keep, "restart": restart, "tech": tech,
            "labels": lang.table("admin_labels")}  # fmt: skip


_RULES = None


def _rules():
    global _RULES
    if _RULES is None:
        _RULES = rules()
    return _RULES


def pages_of(text):
    """The pages of a stored text (=== page N === marks) as plain text."""
    parts = PAGE_RX.split(text or "")
    return [re.sub(r"\s+", " ", JUNK_RX.sub(" ", p)).strip() for p in (parts[1:] if len(parts) > 1 else parts)]


def density(text, tech):
    """Engineering terms and quantities per 1000 words."""
    n = len(WORD_RX.findall(text))
    return 1000 * len(tech.findall(text)) / n if n and tech else 0.0


def page_kind(page, R):
    """The administrative kind its head names, or None."""
    head = page[:HEAD]
    # a plan under the template "approved by" is a plan: the kinds that open a section are looked for first
    for kind, rx in sorted(R["pages"].items(), key=lambda kv: kv[0] not in SECTIONS):
        if rx.search(head) and (kind != "title_page" or len(WORD_RX.findall(page)) <= TITLE_WORDS):
            return kind
    return None


def classify(name, text, R=None):
    """{"verdict": "reject" | "warn" | None, "kinds": [...], "rule": ..., "reason": ...} for a file by its name and
    its stored text; None: an ordinary document."""
    R = R or _rules()
    pages = pages_of(text)
    full = " ".join(pages)
    out = {"verdict": None, "kinds": [], "rule": "", "reason": ""}
    if len(WORD_RX.findall(full)) < MIN_WORDS:
        return out  # unreadable or empty: never rejected on a guess
    head = (name or "") + " " + " ".join(pages[:2])[:3000]
    for k, rx in R["keep"].items():
        if rx.search(head):
            return dict(out, rule="keep:" + k)
    dens = density(full, R["tech"])
    first = pages[0][:2000] if pages else ""
    if len(pages) <= WHOLE_PAGES and dens < TECH_KEEP:
        for k, rxs in R["whole"].items():
            if rxs and all(rx.search(first) for rx in rxs):
                return dict(out, verdict="reject", kinds=[k], rule=k, reason=R["labels"].get(k, k))
    kinds, section = [], False
    for p in pages:
        words = len(WORD_RX.findall(p))
        if words < BLANK_WORDS:
            continue
        kind = page_kind(p, R)
        if kind:
            section = kind in SECTIONS  # a title page or a sheet is one page: what follows it is judged by itself
            if kind not in kinds:
                kinds.append(kind)
            continue
        if section and not (R["restart"] and R["restart"].search(p)) and density(p, R["tech"]) < TECH_PAGE:
            continue  # the next page of the plan, of the letter, of the minutes
        return out  # real content: the file goes in as usual (its administrative pages with it)
    if not kinds:
        return out
    reason = " + ".join(R["labels"].get(k, k) for k in kinds)
    # the minutes of a meeting alone often hold the technical decisions: a doubt, taken in with a warning
    if dens >= TECH_KEEP and set(kinds) != {"implementation_plan"} or set(kinds) == {"meeting_minutes"}:
        return dict(out, verdict="warn", kinds=kinds, rule="tech", reason=reason)
    return dict(out, verdict="reject", kinds=kinds, rule=kinds[0], reason=reason)


def scan_library(index, max_pages=20):
    """The documents and parts of the library whose text is administrative pages only: [(code, reason)];
    read only (the base check warns of them). Texts of more than max_pages pages are not read."""
    R, out = _rules(), []
    texts = index / "texts"
    names = {}
    for card in (index / "cards").glob("*.json"):
        try:
            f = json.loads(card.read_text(encoding="utf-8")).get("file") or {}
        except (OSError, ValueError):
            continue
        names[card.stem] = f.get("source_name") or ""
        for p in f.get("parts") or []:
            if isinstance(p, dict) and p.get("code"):
                names[p["code"]] = p.get("source_name") or ""
    for code in sorted(names):
        pj, md = texts / f"{code}.pages.json", texts / f"{code}.md"
        if not md.is_file():
            continue
        try:
            n = len((json.loads(pj.read_text(encoding="utf-8")).get("pages") or {})) if pj.is_file() else 0
        except (OSError, ValueError):
            n = 0
        if n > max_pages:
            continue
        v = classify(names[code], md.read_text(encoding="utf-8", errors="replace"), R)
        if v["verdict"] == "reject":
            out.append((code, v["reason"]))
    return out
