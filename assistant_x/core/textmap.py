# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The structure of a text read from the text itself: its headings (Markdown, numbered, chapters), the section a line
belongs to, the table of contents with its printed pages, the captions of tables, figures, formulas and appendices,
and the outline made of all of them. Shared by the search (common.chunk_doc, search/bookmap.py stores the outline in
the base) and the intake (metadraft drafts the contents of a card, assemble_md flags a page with a formula). The words
come from the language packs (lang/<code>/headings.json, references.json)."""

import collections, re

from assistant_x.core import lang

MD_HEAD_RX = re.compile(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$")
NUM_HEAD_RX = re.compile(rf"^(\d{{1,2}}(?:\.\d{{1,3}}){{0,4}})\.?\s+(?=[{lang.chars('upper')}«\"])")
CHAPTER_RX = re.compile(rf"^({lang.alt('chapter_words')})\s+(\d+|[IVXLC]+)\b\.?", re.I)
# headings that name no section ("Solution", "Table 3", "Contents"), with a number or letter after them
GENERIC_RX = re.compile(
    rf"^({lang.alt('generic_headings')})"
    rf"(\s+[\d{lang.chars('upper_basic')}][\d.\-–{lang.chars('generic_suffix_letters')}]*)?\.?$",
    re.I,
)
TOC_HEADING_RX = re.compile(rf"(?im)^#.*({lang.alt('toc_heading_words')})")
WORD4_RX = re.compile(rf"[{lang.chars('letters')}]{{4,}}")


def heading_text(line):
    """Text of a Markdown heading line without emphasis and markup, or None."""
    m = MD_HEAD_RX.match(line)
    if not m:
        return None
    h = re.sub(r"<[^>]+>", " ", m.group(1))
    h = re.sub(r"[*_`]+", "", h)
    h = re.sub(r"\s+", " ", h).strip(" .:;,-–—")
    return h or None


def _usable(h):
    """Converters turn big-font lines into headings: '# or', '# ΔT= temperature difference'. Keep real titles only."""
    letters = sum(c.isalpha() for c in h)
    return (
        4 <= len(h) <= 160
        and (h[0].isupper() or h[0].isdigit() or h[0] in '«"')
        and "=" not in h
        and letters >= 0.6 * len(h.replace(" ", ""))
        and WORD4_RX.search(h)
        and not GENERIC_RX.match(h)
    )


class SectionTracker:
    """Follows the headings of one document and names the section a fragment belongs to: numbered headings
    as a chain ('11.9. Loss estimate / 11.9.2. Losses at outflow…') and the plain headings after them.
    Running headers repeated on many pages, generic ones ('Solution', 'Table 3') and tables of contents
    are ignored."""

    def __init__(self, pages):
        seen = collections.Counter()
        self.toc = set()
        for no, text in pages:
            hs = {heading_text(l) for l in text.splitlines()} - {None}
            seen.update(hs)
            if sum(bool(NUM_HEAD_RX.match(h)) for h in hs) >= 8 or TOC_HEADING_RX.search(text):
                self.toc.add(no)
        self.running = {h for h, c in seen.items() if c >= 4}
        self.levels, self.plain = {}, []

    def feed(self, page, line):
        h = heading_text(line)
        if not h or page in self.toc or h in self.running:
            return
        m, c = NUM_HEAD_RX.match(h), CHAPTER_RX.match(h)
        if c:
            self.levels, self.plain = {(c.group(2),): h[:100]}, []
        elif m and _usable(h[m.end() :]):
            num = tuple(m.group(1).split("."))
            # keep only the headings this one belongs to: '3.1.6' drops '2.4'; 'Chapter 3' stays, 'Chapter 2' goes
            self.levels = {
                k: t
                for k, t in self.levels.items()
                if len(k) < len(num) and (k == num[: len(k)] or (len(k) == 1 and not k[0].isdigit()))
            }
            self.levels[num] = h[:120]
            self.plain = []
        elif _usable(h):
            self.plain = (self.plain + [h[:120]])[-2:]

    def current(self):
        parts = [self.levels[k] for k in sorted(self.levels, key=len)] + self.plain
        out = " / ".join(parts)
        while len(out) > 240 and len(parts) > 1:  # keep the most specific end
            parts = parts[1:]
            out = " / ".join(parts)
        return out[:240]


NUM = rf"([{lang.chars('upper_basic')}]?\d{{1,3}}(?:[.\-–]\d{{1,3}}){{0,3}}[{lang.chars('ref_num_suffix')}]?)"
# captions and equation numbers: where a table, figure or formula is (the first such place, outside the contents)
DEF_RX = {
    "t": re.compile(rf"^[\W_]{{0,8}}(?:{lang.alt('caption_table')})\s*№?\s*" + NUM + r"(?![\d.]*\d)", re.M),
    "f": re.compile(r"\(\s*" + NUM + r"\s*\)\s*(?:<br>)?\s*$", re.M),
    "r": re.compile(rf"^[\W_]{{0,8}}(?:{lang.alt('caption_figure')})\s*" + NUM + r"[.\s]", re.M),
    "a": re.compile(rf"^[\W_]{{0,8}}(?:{lang.alt('caption_appendix')})\s+([{lang.chars('upper_basic')}]|\d{{1,2}})\b", re.M),
}


def formula_number(num):
    """A number in brackets at the end of a line that is an equation number: not a year, not a long run of digits."""
    return not (re.fullmatch(r"(19|20)\d\d", num) or len(num) > 9)


def has_formula(text):
    """True when a line of the text ends with an equation number ("(12)", "(4.3)"): a page with a formula."""
    return any(formula_number(norm(m.group(1))) for m in DEF_RX["f"].finditer(text))


def norm(num):
    return re.sub(r"[\-–]", ".", num.strip().rstrip(".")).upper()


MIN_HEADS = 3  # an outline of fewer entries is no outline: the next way of finding one is tried
MIN_PAGES = 3  # a sheet or two (a drawing, a certificate) gets no guessed outline
TOC_WORD_RX = re.compile(rf"^[\W_]*({lang.alt('toc_words')})[\W_]*$", re.I)
# a line of a table of contents: "5.3 Separators ........ 123", "Introduction … 7", "|5.3|Separators|123|"
TOC_LINE_RX = re.compile(
    rf"^(?:(\d{{1,2}}(?:\.\d{{1,3}}){{0,3}})\.?\s+)?([{lang.chars('upper')}«\"][^|]{{2,140}}?)"
    r"[\s.…_·|-]*?(?:\s|\.{2,}|…|\|)\s*(\d{1,4})$"
)
UPPER_RX = re.compile(rf"[{lang.chars('letters')}]")
CAPS4_RX = re.compile(rf"[{lang.chars('upper')}]{{4,}}")
KEY_RX = re.compile(rf"[^{lang.chars('lower_basic')}0-9]")
# OCR reads the dot leaders of a contents line as a run of e's
LEADER_RX = re.compile(rf"\.{{2,}}|…|„|\s[{lang.chars('dot_leader_letters')}]{{2,4}}(?:\s|$)")
TOC_SKIP_RX = re.compile(f"({lang.alt('toc_skip_words')})", re.I)


def _plain(line):
    """A line of the text without Markdown: table bars, emphasis, heading marks."""
    s = re.sub(r"<[^>]+>", " ", line)
    s = re.sub(r"[*_`#]+", "", s)
    return re.sub(r"\s+", " ", s).strip(" |:;,-–—")


def _flat_numbered(pages, tracker):
    """Numbered headings of a text without Markdown marks (OCR, plain text): "5.3.1 Gas separators" as a line of
    its own. List items ("1. Depth…"), clauses (a sentence going on in the next line or ending with a period),
    table rows and numbers out of order (a reference, a value "2.5 MPa") are not taken."""
    heads, last = [], None
    for no, text in pages:
        if no in tracker.toc:
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.lstrip().startswith(("|", "#")):
                continue
            h = _plain(line)
            m = NUM_HEAD_RX.match(h)
            if not m or len(h) > 110 or h.endswith((".", ";", ":", ",")) or h in tracker.running:
                continue
            num, title = m.group(1), h[m.end() :]
            words = title.split()
            if not _usable(title) or not words or (len(re.sub(r"\W", "", words[0])) < 4 and not title.isupper()):
                continue
            if "." not in num and not title.isupper():  # "1 Immersion depth" is a list item, "1 GENERAL" a chapter
                continue
            nxt = next((x.strip() for x in lines[i + 1 :] if x.strip()), "")
            if nxt[:1].islower():  # the sentence goes on: a clause, not a heading
                continue
            key = tuple(int(x) for x in num.split("."))
            if last is not None and not (last < key and key[0] - last[0] <= 2):
                continue
            last = key
            heads.append((num, h[:120], no, num.count(".") + 1))
    return heads


def _upper_lines(pages, tracker):
    """Headings set in capitals: "SEPARATION OF OIL AND GAS" as a line of its own, at most 3 on a page (more are a
    table or a drawing), not repeated on many pages (a running header)."""
    heads = []
    for no, text in pages[1:] if len(pages) > 5 else pages:  # the title page of a book is not a section
        if no in tracker.toc:
            continue
        found = []
        for line in text.splitlines():
            if line.lstrip().startswith("|"):
                continue
            h = _plain(line)
            letters = UPPER_RX.findall(h)
            if not (8 <= len(h) <= 90) or len(letters) < 0.7 * len(h.replace(" ", "")) or h.endswith("."):
                continue
            if sum(c.isupper() for c in letters) < 0.9 * len(letters) or len(h.split()) < 2 or h in tracker.running:
                continue
            if GENERIC_RX.match(h) or not CAPS4_RX.search(h) or len(set(h.split())) <= len(h.split()) // 2:
                continue  # "MANUAL MANUAL": a line read twice by OCR
            found.append(h)
        if len(found) <= 3:
            heads += [("", h[:120], no, 1) for h in found]
    return heads


def _plain_md(pages, tracker):
    """Markdown headings without a number ("# Absorption drying"): usable titles only, running headers skipped."""
    heads = []
    for no, text in pages:
        if no in tracker.toc:
            continue
        for line in text.splitlines():
            h = heading_text(line)
            if h and h not in tracker.running and not NUM_HEAD_RX.match(h) and not CHAPTER_RX.match(h) and _usable(h):
                heads.append(("", h[:120], no, 1))
    return heads


def _key(s):
    return KEY_RX.sub("", lang.fold(s.lower()))


def _toc_lines(text):
    """[(num, title, printed page)] of the lines of a page that look like a table of contents."""
    out = []
    for line in text.splitlines():
        if len(line) > 240:
            continue
        cells = [_plain(c) for c in line.split("|")] if line.lstrip().startswith("|") else [_plain(line)]
        m = TOC_LINE_RX.match(" ".join(c for c in cells if c))
        if not m:
            continue
        title = LEADER_RX.split(m.group(2))[0].strip(" .…_·-")
        if len(title) >= 4 and WORD4_RX.search(title) and not TOC_SKIP_RX.match(title):
            out.append((m.group(1) or "", title, int(m.group(3))))
    return out


def toc_pages(pages):
    """[(index of the first page, index after the last)] of the tables of contents: a page with the word
    "Contents" (TOC_WORD_RX) as a line of its own and the next pages that go on listing titles with page numbers."""
    out = []
    for i, (_, t) in enumerate(pages):
        if any(TOC_WORD_RX.match(_plain(line) or "x") for line in t.splitlines() if len(line) < 60):
            j = i + 1
            while j < len(pages) and j <= i + 4 and len(_toc_lines(pages[j][1])) >= 3:
                j += 1
            out.append((i, j))
    return out


def toc_entries(pages, spans=None):
    """Outline from the contents page: [(num, title, PDF page, level)]. The printed page numbers of the contents are
    turned into PDF pages by the offset most titles agree on (found again in the text after the contents)."""
    for i, j in spans if spans is not None else toc_pages(pages):
        entries = [e for x in range(i, j) for e in _toc_lines(pages[x][1])]
        if len(entries) < MIN_HEADS:
            continue
        toc_nos = {pages[x][0] for x in range(i, j)}
        body = [(no, _key(t)) for no, t in pages if no not in toc_nos]
        offsets = []
        for _, title, printed in entries:
            k = _key(title)[:30]
            if len(k) < 8:
                continue
            hit = next((no for no, t in body if k in t and no >= printed - 5), None)
            if hit is not None:
                offsets.append(hit - printed)
        if not offsets:
            continue
        best, cnt = max(((o, offsets.count(o)) for o in set(offsets)), key=lambda x: (x[1], -abs(x[0])))
        if cnt < max(2, 0.3 * len(offsets)):
            continue
        first, last = pages[0][0], pages[-1][0]
        out = [
            (
                num,
                (f"{num} {title}" if num else title)[:120],
                min(max(printed + best, first), last),
                num.count(".") + 1 if num else 1,
            )
            for num, title, printed in entries
        ]
        return sorted(out, key=lambda e: e[2])
    return []


def _first(heads):
    """Heads without repeats (the same number, or the same title without one): the first of each stays, in order."""
    seen, out = set(), []
    for h in heads:
        key = (h[3], h[0] or h[1])
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out


GIVEN_MIN = 2  # an outline of the file with fewer entries (a single bookmark "Cover") is not taken


def given_heads(pages, given):
    """[(num, title, page, level)] of the outline a file gives itself ([[level, title, page or None]]: PDF bookmarks,
    DOCX heading styles): a page given is kept (within the text), else the first page from the previous entry on
    whose text the title is found (as toc_entries finds them); an entry found nowhere is left out."""
    if not given or not pages:
        return []
    first, last = pages[0][0], pages[-1][0]
    keys = [(no, _key(t)) for no, t in pages]
    out, at = [], first
    for level, title, page in given:
        title = re.sub(r"\s+", " ", str(title)).strip()
        if not title:
            continue
        if page is None:
            k = _key(title)[:30]
            page = next((no for no, t in keys if no >= at and k in t), None) if len(k) >= 4 else None
            if page is None:
                continue
        page = min(max(int(page), first), last)
        at = page
        m = NUM_HEAD_RX.match(title)
        out.append((m.group(1) if m else "", title[:120], page, max(1, int(level))))
    return out


def build(pages, given=None):
    """pages [(no, text)] -> (outline rows (num, title, page, page_end, level), objects {(kind, num): page}).
    The outline the file gives itself (given: PDF bookmarks, DOCX heading styles; given_heads) comes first; else it
    comes from numbered Markdown headings; a text without them gets it from the contents page, else from numbered
    lines, Markdown headings without numbers and lines in capitals (BOOKMAP_VERSION 2)."""
    tracker = SectionTracker(pages)  # its table-of-contents pages and running headers are skipped here too
    heads, objects = [], {}
    for no, text in pages:
        if no in tracker.toc:
            continue
        for line in text.splitlines():
            h = heading_text(line)
            if h and h not in tracker.running:
                m, c = NUM_HEAD_RX.match(h), CHAPTER_RX.match(h)
                if c:
                    heads.append((c.group(2).upper(), h[:120], no, 0))
                elif m and _usable(h[m.end() :]):
                    heads.append((m.group(1), h[:120], no, m.group(1).count(".") + 1))
        for kind, rx in DEF_RX.items():
            for m in rx.finditer(text):
                num = norm(m.group(1))
                if kind == "f" and not formula_number(num):
                    continue  # a year in brackets at the end of a line is not an equation number
                objects.setdefault((kind, num), no)
    own = given_heads(pages, given)
    if len(own) >= GIVEN_MIN:
        heads = own
    elif len(heads) < MIN_HEADS and len(pages) >= MIN_PAGES:
        spans = toc_pages(pages)
        tracker.toc |= {pages[x][0] for i, j in spans for x in range(i, j)}  # the contents list every number: skip it
        guess = toc_entries(pages, spans) or heads
        for more in (_flat_numbered, _plain_md, _upper_lines):
            if len(guess) >= MIN_HEADS:
                break
            guess = _first(sorted(guess + more(pages, tracker), key=lambda h: h[2]))
        if len(guess) >= MIN_HEADS:  # a guess of one or two lines is noise more often than not
            heads = guess
    last = pages[-1][0] if pages else 0
    outline, seen = [], set()
    for i, (num, title, page, level) in enumerate(heads):
        mark = (level, num or title)
        if mark in seen:  # a running header that slipped through, or a repeated title: keep the first
            continue
        seen.add(mark)
        # a section ends where the next one of the same or a higher level starts; a chapter, at the next chapter
        end = next((p for _, _, p, l2 in heads[i + 1 :] if l2 == 0 or (level > 0 and l2 <= level)), last + 1)
        outline.append((num, title, page, max(page, end - 1), level))
    return outline, objects
