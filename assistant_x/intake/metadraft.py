# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Draft of meta.jsonl from each processed text: from the first 3 pages the designation (national standards, API,
ISO…), year, publisher or organisation, likely title, the genre (doc_type) and the shelf it goes on;
from the whole text the contents (toc), the tables, the designations it refers to and, for a journal issue, its
articles (units). Claude checks and corrects the draft and writes what the code cannot (the English title, the
summary, the topics, the keywords): the draft suggests, it does not decide. Written to <work>/meta_draft.jsonl by
assistant-x intake run; by hand:
Usage: python -m assistant_x.intake.metadraft <work dir>      (state.sqlite and md/ there)
The words of the documents come from the language packs (lang/<code>/documents.json)."""

import datetime, json, re, sys
from pathlib import Path

from assistant_x.core import config, lang
from assistant_x.core.formats import PAGE_WORDS, extensions, pages_path, read_outline

# designations of standards and norms: one alternation (the longer forms of a pack first), never inside a word
# ("OST" inside "GOST"); a match is a designation when its number is (designation_number)
DESIGNATIONS = lang.words("designations")
DESIG_ANY = re.compile(r"(?<![^\W\d_])(?:" + "|".join(f"(?:{rx})" for rx in DESIGNATIONS) + ")") if DESIGNATIONS else None
# words right before a designation that cite another document ("according to GOST …"): not the document's own
CITE_BEFORE = re.compile(rf"(?i)(?:^|[\s(«\"])(?:{lang.alt('designation_cite_words')})[\s«\"(]*$")
PUBLISHED = re.compile(
    rf"(?m)(?:^|\s)({lang.alt('publish_places')})\s*[:.]\s*"
    r"([^,\n]{2,60}),\s*((?:19|20)\d{2})"
)
PUBLISHER = re.compile(rf"(?i)({lang.alt('publisher_words')})\s*[«\"]?([^»\"\n,]{{2,50}})")
ORG = re.compile(rf"((?:{lang.alt('company_forms')})\s*[«\"][^»\"\n]{{2,60}}[»\"])")
FOREIGN_ORG = re.compile(rf"\b({lang.alt('known_publishers')})\b")
YEAR = re.compile(r"(?<![\d.])((?:19|20)\d{2})(?![\d])")
# "replaces GOST …" on the title page: the designation of the document this one supersedes (a version hint)
SUPERSEDES = re.compile(f"(?i){lang.alt('supersedes')}")
SKIP_TITLE = re.compile(rf"(?i)^({lang.alt('not_title')})")
# the genres the words of the first pages suggest (doc_type_words of the packs and the profile), in the order of the
# genres of schemas/card-1.json; the first rule that matches wins (a designation of a standard comes before all of them)
TYPE_ORDER = tuple(t for t in config.doc_types() if t != "other")
TYPE_RULES = [(t, re.compile("(?i)" + "|".join(lang.lists("doc_type_words").get(t, [])))) for t in TYPE_ORDER]
PAGES_RX = re.compile(rf"(?:^|\n)=== (?:{PAGE_WORDS}) \d+ ===\n")
UPPER = lang.chars("upper")


def pages_of(md, n=3):
    parts = PAGES_RX.split(md)
    return [p for p in parts[1:] if p.strip()][:n] if len(parts) > 1 else [md]


def all_pages(md):
    """The texts of every page in order: the place of a text in the list is its PDF page (an empty page included)."""
    from assistant_x.core.common import split_pages

    pages = split_pages(md)
    if not pages:
        return [md] if md.strip() else []
    by = dict(pages)
    return [by.get(i, "") for i in range(1, max(by) + 1)]


def plain(text):
    text = text.replace("­", "-")  # a soft hyphen inside "58367-2019" comes from the text layer
    text = re.sub(r"<br>|<[^>]+>|[*_#|`]", " ", text)
    # a no-break or narrow space of the text layer is a space for the words of the packs (a genre phrase of two words)
    return re.sub(r"[ \t   ]+", " ", text)


# capitals spaced out in pieces of 1-3 letters ("S T A N D A R D", "IN TER STA TE"): four pieces and more
SPACED = re.compile(rf"(?<![\w-])(?:[{UPPER}]{{1,3}} ){{3,}}[{UPPER}]{{1,3}}(?![\w-])")
DROP_CAP = re.compile(rf"\b([{UPPER}]) ([{UPPER}][\w-]+) ([\w-]+)\b")
REPEAT_WORD = re.compile(r"(?i)\b([\w-]+)(?: \1\b)+")
REPEAT_PHRASE = re.compile(r"(?i)\b([\w-]+(?: [\w-]+){1,7}) \1\b")


def tidy(line):
    """A line of the texts of national standards from the registry site: two text layers give a drop cap with
    the word spaced out ("I INTERSTATE N T E R S T A T E") and repeats ("GENERAL GENERAL REQUIREMENTS REQUIREMENTS"):
    spaced letters joined, a drop cap with the word and its spaced rest made one word, repeats dropped."""
    s = SPACED.sub(lambda m: m.group(0).replace(" ", ""), line)
    s = DROP_CAP.sub(lambda m: m.group(2) if (m.group(1) + m.group(3)).upper() == m.group(2).upper() else m.group(0), s)
    return " ".join(drop_repeats(s.split()))


def drop_repeats(tokens):
    """A run of 1-8 words said twice in a row ("Crown blocks, crown blocks, travelling blocks, travelling blocks,"): the second
    copy dropped; words compared without case and punctuation."""
    key = [re.sub(r"[^\w-]", "", t).lower() for t in tokens]
    for k in range(8, 0, -1):
        i = 0
        while i + 2 * k <= len(tokens):
            if all(key[i : i + k]) and key[i : i + k] == key[i + k : i + 2 * k]:
                del tokens[i + k : i + 2 * k], key[i + k : i + 2 * k]
            else:
                i += 1
    return tokens


GOST_HEAD = re.compile(f"(?i){lang.alt('standard_head')}")  # the line before the title of a national standard
GOST_END = re.compile(f"(?i){lang.alt('standard_end')}")  # the line after it
DESIGNATION_START = re.compile(rf"({lang.alt('designation_words')})\b")
NATIONAL = tuple(lang.words("national_standard"))  # designations whose title page gives the title (gost_title)
NOT_STANDARDS = re.compile(rf"({lang.alt('not_standards')})\b")  # designations that are no standard (specifications)


def gost_title(pages):
    """Title of a national standard by its title page: the lines in capitals after the head line ("… STANDARD") up to
    the end line ("Official edition"): "ELECTRIC DRILLS" + "GENERAL TECHNICAL REQUIREMENTS" -> "Electric drills. General
    technical requirements"."""
    lines = [tidy(plain(x)).strip(" .:-–") for x in (pages[0] if pages else "").split("\n")]
    lines = [x for x in lines if x]
    start = next((i + 1 for i, x in enumerate(lines) if GOST_HEAD.match(x)), None)
    if start is None:
        return ""
    parts = []
    for x in lines[start:]:
        if GOST_END.match(x):
            break
        first = x.split()[0]
        if DESIGNATION_START.match(x) or sum(c.isalpha() for c in first) < 3 or first.upper() != first:
            continue  # the designation again, a catalogue code ("11—98B3"), a line of plain text
        parts.append(sentence(x))
    return ". ".join(parts[:3])


def sentence(line):
    """ "FIELD FACILITIES Process design" -> "Field facilities. Process design": the words in capitals become a
    sentence, the rest follows after a full stop."""
    words = line.split()
    k = next((i for i, w in enumerate(words) if w.upper() != w), len(words))
    head = " ".join(words[:k])
    head = head[0] + head[1:].lower() if head else ""
    rest = " ".join(words[k:])
    return head + (". " + rest if rest and head else rest)


# the usual words of the titles of standards: an English title only when every word is known
EN = lang.table("title_words_en")
TITLE_PHRASES = lang.table("title_phrases")  # phrases translated as one word
TITLE_WORDS_RX = re.compile(rf"[{lang.chars('title_letters')}_-]+")


def en_title(ru):
    """A title of a standard in the document language -> "Electric-Drills-General-Technical-Requirements", or ""."""
    s = ru.lower()
    for a, b in TITLE_PHRASES.items():
        s = s.replace(a, b)
    words = TITLE_WORDS_RX.findall(s)
    if not words:
        return ""
    out = []
    for w in words:
        t = EN.get(w.replace("_", " "))
        if not t:
            return ""
        out.append(t)
    return "-".join(dict.fromkeys(out))


def designation_number(d):
    """True when the number of a designation is one: two groups of digits, or one of three digits and more, or one
    with a letter ("API 6A"); never a last group of six digits and more after a dot that ends in a year (the year
    glued to the number by OCR, "12.2.0632015"; "231.1311500.2015" is a number). "RD 0", "SP 2" are pieces of a line,
    not designations."""
    groups = re.findall(r"\d+|\b[IVX]+\b", d)
    if groups and len(groups[-1]) >= 6 and re.search(r"\.\d{2,}(?:19|20)\d\d$", d):
        return False
    return len(groups) >= 2 or any(len(g) >= 3 for g in groups) or bool(re.search(r"\d[A-Z]\b", d))


def designations_in(text):
    """[(start, end, designation)] of the designations named in a text, in order; a match that is the tail of a longer
    one ending at the same place is dropped."""
    if DESIG_ANY is None:
        return []
    out = []
    for m in DESIG_ANY.finditer(text):
        d = re.sub(r"\s+", " ", m.group(0)).strip(" .-–")
        if d and designation_number(d):
            out.append((m.start(), m.start() + len(m.group(0).rstrip(" .-–")), d))
    ends = {}
    for s, e, d in out:
        if e not in ends or s < ends[e][0]:
            ends[e] = (s, d)
    return [(s, e, d) for s, e, d in out if ends[e][0] == s]


def designation(text):
    """The designation of the first standard named in the text, or None."""
    found = designations_in(text)
    return found[0][2] if found else None


def own_designation(pages):
    """The designation of the document itself, or None: on its first two pages, standing at the start of a line
    (alone, with the words of its title, or after a head line in capitals such as "NATIONAL STANDARD") and not cited
    ("according to GOST …", the end of the line before). A book that cites a standard in its preface is no
    standard (audit 6, M-021)."""
    for page in pages[:2]:
        prev = ""
        for raw in page.split("\n"):
            line = tidy(plain(raw)).strip(" \t>")
            if not line:
                continue
            found = designations_in(line)
            if found:
                start, _, d = found[0]
                before = line[:start].strip(' «"(-–:')
                head = not before or GOST_HEAD.match(before) or (len(before.split()) <= 5 and before.upper() == before)
                if head and not CITE_BEFORE.search(before or prev):
                    return d
            prev = line
    return None


def year_of(text, desig=None):
    now = datetime.date.today().year
    if desig:
        m = re.search(r"[-–:.](\d{4})$|[-–](\d{2})$", desig)
        if m:
            y = int(m.group(1) or m.group(2))
            y = y if y > 1000 else (1900 + y if y > now % 100 else 2000 + y)
            if 1900 <= y <= now + 1:
                return str(y)
    m = PUBLISHED.search(text)
    if m:
        return m.group(3)
    years = [int(y) for y in YEAR.findall(text) if 1900 <= int(y) <= now + 1]
    if not years:
        return ""
    # the edition year is usually the latest year on the title pages (later reprints aside)
    common = max(set(years), key=lambda y: (years.count(y), y))
    return str(max(common, max(years)) if max(years) - common <= 3 else common)


def publisher_of(text):
    m = PUBLISHED.search(text)
    if m:
        return f"{m.group(1)}: {m.group(2).strip()}, {m.group(3)}"
    for rx in (PUBLISHER, ORG):
        m = rx.search(text)
        if m:
            return re.sub(r"\s+", " ", m.group(0)).strip()
    m = FOREIGN_ORG.search(text)
    return m.group(1) if m else ""


CAPS2_RX = re.compile(rf"\b[{UPPER}]{{2,}}\b")
WORDS2_RX = re.compile(rf"[{lang.chars('letters')}]{{2,}}")
# a person's name with initials ("Ivanov I. I.", "I. I. Ivanov"): a line of them is a list of authors or editors
NAME_RX = re.compile(rf"\b[{UPPER}][^\W\d_]+\s+[{UPPER}]\.\s?[{UPPER}]\.|\b[{UPPER}]\.\s?[{UPPER}]\.\s?[{UPPER}][^\W\d_]+")
NAMES_PAGE = 0.4  # a page whose lines are names in this share and more is a page of authors or an editorial board


def _title_lines(page, desig):
    """[(line, is a heading)] of a page that may be a title; None for a page of names."""
    lines, names, seen = [], 0, 0
    for raw in page.split("\n"):
        head = raw.lstrip().startswith("#")
        s = tidy(plain(raw)).strip(" .:-–")
        if desig:
            s = s.replace(desig, "").strip(" .:-–")
        if not s:
            continue
        seen += 1
        n = len(NAME_RX.findall(plain(raw)))  # before tidy(): it takes "I. I." for a repeated word
        names += n > 0
        if (
            8 <= len(s) <= 200
            and not n
            and not SKIP_TITLE.match(s)
            and not re.match(r"^\d+(\.\d+)*\.?\s", s)
            and sum(c.isalpha() for c in s) >= 0.6 * len(s.replace(" ", ""))
        ):
            lines.append((s, head))
    return None if seen and names >= NAMES_PAGE * seen and names >= 2 else lines


def title_of(pages, desig=None):
    """Likely title from the first page that has one of the first three (a page of authors, an editorial board or
    the imprint is passed over): a heading, else the longest line that starts in capitals
    ("OIL AND GAS SEPARATORS General requirements" -> "Oil and gas separators. General requirements"), else the first
    line."""
    lines = []
    for page in (pages or [""])[:3]:
        lines = _title_lines(page, desig)
        if lines:
            break
    if not lines:
        return ""
    for s, head in lines:
        if head:
            return s
    caps = [s for s, _ in lines if len(CAPS2_RX.findall(" ".join(s.split()[:2]))) == min(2, len(s.split()))]
    if caps:
        t = max(caps, key=len)
        words = t.split()
        k = next((i for i, w in enumerate(words) if w.upper() != w), len(words))
        upper = " ".join(words[:k])
        if not upper:  # the first word has a lowercase letter (a plural of a designation): keep the line as is
            return t
        upper = upper[0] + upper[1:].lower()
        return upper + (". " + " ".join(words[k:]) if k < len(words) else "")
    return lines[0][0]


# the genre a file format gives by itself (a slide deck, a spreadsheet: the card schema calls a table of data a dataset)
TYPE_BY_EXT = {"ppt": "presentation", "pptx": "presentation", "odp": "presentation", "pps": "presentation"}
TYPE_BY_EXT.update(dict.fromkeys(("xls", "xlsx", "xlsm", "ods", "csv"), "dataset"))


def doc_type_of(text, desig, ext=""):
    """The genre the first pages suggest: a slide deck or a spreadsheet by its format, a standard by its own
    designation, else by the words of the language packs (doc_type_words), a book by its imprint ("place: publisher,
    1984"), else other."""
    if ext and ext.lower() in TYPE_BY_EXT:
        return TYPE_BY_EXT[ext.lower()]
    if desig and not NOT_STANDARDS.match(desig):
        return "standard"
    for t, rx in TYPE_RULES:
        if rx.pattern != "(?i)" and rx.search(text):
            return t
    return "book" if PUBLISHED.search(text) else "other"


def shelf_of(doc_type, profile=None):
    """The shelf whose document types hold doc_type (schemas/shelves.json; the shelf of "other", else the last one)."""
    from assistant_x.core import config

    shelves = config.sections(profile)
    for want in (doc_type, "other"):
        s = next((x for x in shelves if want in x.get("doc_types", ())), None)
        if s:
            return s["letter"]
    return shelves[-1]["letter"] if shelves else "X"


def section_of(text, desig, profile=None):
    """The shelf the first pages suggest (doc_type_of, then shelf_of)."""
    return shelf_of(doc_type_of(text, desig), profile)


def text_lang(md):
    """The languages of a text by the letters of the language packs (core/common.langs_of, from 20 letters on, so a
    title page is enough): ["ru"], ["en"], ["ru", "en"], or [] for too little text."""
    from assistant_x.core.common import langs_of, split_pages

    pages = split_pages(md) or [(1, md)]
    lg = langs_of("".join(t for _, t in pages), min_letters=20)
    return lg.split("+") if lg else []


# headings that are no section: the names of pictures pymupdf4llm writes as headings ("img_12.png"), file names
NOT_HEADING = re.compile(r"(?i)^(?:img|image|fig|picture)[_\d]|\.(?:png|jpe?g|gif|bmp|tiff?|emf|wmf)\b")


def _chapter_titles(toc, pages):
    """ "Chapter 3" alone: the title is the next line of its page ("Chapter 3. Separation of gas")."""
    from assistant_x.core import textmap

    by = dict(pages)
    for t in toc:
        m = textmap.CHAPTER_RX.match(t["title"])
        if not m or t["title"][m.end() :].strip(" .:-–"):
            continue
        lines = [textmap._plain(x) for x in by.get(t["pdf_from"], "").splitlines()]
        lines = [x for x in lines if x]
        at = next((i for i, x in enumerate(lines) if x.strip(" .:-–") == t["title"].strip(" .:-–")), None)
        nxt = lines[at + 1].strip(" .:-–") if at is not None and at + 1 < len(lines) else ""
        if nxt and len(WORDS2_RX.findall(nxt)) >= 2 and not nxt[:1].isdigit() and len(nxt) <= 120:
            t["title"] = f"{t['title'].strip(' .:-–')}. {nxt}"[:120]
    return toc


def heading_ok(title):
    """A title of a guessed contents: two words at least (a numbered one, one word of four letters), no picture name,
    no formula, no number that is not a section number, no service line ("Moscow, 2005", the imprint)."""
    from assistant_x.core import textmap

    t = title.strip()
    if not t or NOT_HEADING.search(t) or "=" in t or SKIP_TITLE.match(t):
        return False
    m = textmap.NUM_HEAD_RX.match(t)
    if t[:1].isdigit() and not m:
        return False
    words = WORDS2_RX.findall(t[m.end() :] if m else t)
    return len(words) >= 2 or bool(m and any(len(w) >= 4 for w in words))


TOC_KEEP = 0.5  # a guessed contents that loses more than half of its entries to heading_ok is noise: left out


def contents(pages, given=None):
    """(toc [{level, pdf_from, title}], tables [{label, pdf_page}]) of a text. The outline the file gives itself (PDF
    bookmarks, DOCX styles) as it is; else the entries of its contents page with their pages, else core/textmap.build
    (numbered headings, numbered lines, plain headings). A guessed contents is checked entry by entry (heading_ok) and
    left out when it is noise — fewer than 3 entries, all on one page, most entries dropped: an empty contents is
    better than a wrong one. Titles in the language of the text."""
    from assistant_x.core import textmap

    outline, objects = textmap.build(pages, given)
    guessed = len(textmap.given_heads(pages, given)) < textmap.GIVEN_MIN
    entries = textmap.toc_entries(pages) if guessed else []
    if len(entries) >= textmap.MIN_HEADS:  # the contents page of the document itself, with its page numbers
        outline = [(num, title, page, page, level) for num, title, page, level in entries]
    chapters = any(level == 0 for *_, level in outline)
    toc = [
        {"level": max(1, min(6, level + 1 if chapters else level)), "pdf_from": page, "title": title}
        for _, title, page, _, level in outline
    ][:300]
    if guessed and toc:
        toc = _chapter_titles(toc, pages)
        kept = [t for t in toc if heading_ok(t["title"])]
        noisy = len(kept) < textmap.MIN_HEADS or len({t["pdf_from"] for t in kept}) == 1 or len(kept) < TOC_KEEP * len(toc)
        toc = [] if noisy else kept
    tables = [
        {"label": f"Table {num}", "pdf_page": page}
        for (kind, num), page in sorted(objects.items(), key=lambda x: x[1])
        if kind == "t"
    ][:100]
    return toc, tables


def references(text, own=None):
    """The designations of other documents named in a text, in the order found, without the document's own."""
    found = {}
    for start, _, d in designations_in(text):
        if d != own:
            found.setdefault(d, start)
    return [{"designation": d} for d in sorted(found, key=found.get)][:200]


def units_of(pages):
    """The articles of a journal issue from its contents page: [{kind, title, pdf_from}] (textmap.toc_entries)."""
    from assistant_x.core import textmap

    return [{"kind": "article", "title": title, "pdf_from": page} for _, title, page, _ in textmap.toc_entries(pages)][:300]


def draft(md, rel="", profile=None, given=None):
    """Draft meta of one document from its Markdown text (fields of meta_schema; 'draft': true). The searchable texts
    are maps in the language of the document: Claude adds English (and the other card languages)."""
    pages = pages_of(md)
    text = plain("\n".join(pages))
    ext = Path(rel).suffix.lower().lstrip(".")
    desig = own_designation(pages)
    if not desig:  # the file name often carries the designation
        desig = designation(Path(rel).stem.replace("_", " "))
    yr = year_of(text, desig)
    doc_type = doc_type_of(text + "\n" + Path(rel).stem, desig, ext)
    langs = text_lang(md)
    lg = langs[0] if langs else "en"
    gost = gost_title(pages) if desig and desig.startswith(NATIONAL) else ""
    title = gost or title_of(pages, desig) or desig or ""
    out = {
        "tid": None,
        "sec": shelf_of(doc_type, profile),
        "doc_type": doc_type,
        "title": {lg: title} if title else {},
        "year": int(yr) if yr else None,
        "publisher": publisher_of(text),
        "lang": langs,
        "draft": True,
    }
    en = en_title(gost) if gost else ""
    if en:
        out["en"] = en
        out["title"]["en"] = en.replace("-", " ")
    if desig:
        latin = translit(desig)
        out["code_hint"] = desig
        out["designation"] = {lg: desig, **({"en": latin} if lg != "en" else {})}
        out["au"] = re.sub(r"[^A-Za-z0-9]+", "-", latin).strip("-")
    m = SUPERSEDES.search(text) if doc_type in ("standard", "regulation") else None
    if m:
        out["supersedes"] = next(g for g in m.groups() if g).strip()  # the group of the pack whose phrase matched
    every = [(i + 1, p) for i, p in enumerate(all_pages(md))]
    toc, tables = contents(every, given)
    out["toc"] = [{**t, "title": {lg: t["title"]}} for t in toc]
    out["tables"] = tables
    out["references"] = references(plain(md), desig)
    if doc_type == "serial_issue":
        out["units"] = [{**u, "title": {lg: u["title"]}} for u in units_of(every)]
    words = len(WORDS2_RX.findall(plain(md)))
    if ext in IMAGES and words < PICTURE_WORDS and not STAMP.search(md):  # a photo or a scrap, not a document
        out["drop"] = f"a picture without text (words recognized: {words})"
    return {k: v for k, v in out.items() if k == "tid" or v not in (None, "", [], {})}


IMAGES = set(extensions("image"))
PICTURE_WORDS = 25
# the title block of a drawing: a drawing is a document even with few words
STAMP = re.compile(f"(?i){lang.alt('drawing_stamp')}")


TR = lang.table("translit")  # letters of the document languages -> Latin, for file names
WORDS = lang.table("designation_latin")


def translit(s):
    s = " ".join(WORDS.get(w, w) for w in s.split())
    out = []
    for c in s:
        t = TR.get(c.lower(), c)
        out.append(t.capitalize() if c.isupper() and c.lower() in TR else t)
    return "".join(out)


def _number(s):
    s = s.upper()
    if s.isdigit():
        return int(s)
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    n = 0
    for a, b in zip(s, s[1:] + " "):
        n += -vals[a] if vals.get(b, 0) > vals[a] else vals[a]
    return n


def chapter_of(name):
    """The chapter number a file name gives ("Chapter 3. Separation", "03_Chapter_3"), or None."""
    from assistant_x.core import textmap

    stem = re.sub(r"^[\d\W_]+", "", re.sub(r"_+", " ", Path(name).stem)).strip()
    m = textmap.CHAPTER_RX.match(stem)
    return _number(m.group(2)) if m else None


def is_contents_name(name):
    from assistant_x.core import textmap

    stem = re.sub(r"^[\d\W_]+", "", re.sub(r"_+", " ", Path(name).stem)).strip()
    return bool(textmap.TOC_WORD_RX.match(stem))


BOOK_CHAPTERS = 3  # files named as chapters in one folder from which it is one book


def book_groups(rows):
    """[(folder, main tid, [part tids in order])] of the folders of a batch that hold one book in several files: a
    file named as the contents, or BOOK_CHAPTERS files and more named as chapters. The main file is the contents, else
    the first chapter; the parts go by chapter number (a file before the first chapter stays before it)."""
    from assistant_x.core.formats import natural_key

    folders = {}
    for r in rows:
        if "/" in r["rel"]:
            folders.setdefault(r["rel"].rsplit("/", 1)[0], []).append(r)
    out = []
    for folder, rs in sorted(folders.items()):
        if len(rs) < 2:
            continue
        rs = sorted(rs, key=lambda r: natural_key(r["rel"]))
        names = {r["tid"]: r["rel"].rsplit("/", 1)[-1] for r in rs}
        toc = [t for t, n in names.items() if is_contents_name(n)]
        chapters = {t: chapter_of(n) for t, n in names.items()}
        if not toc and sum(c is not None for c in chapters.values()) < BOOK_CHAPTERS:
            continue
        first = next((i for i, r in enumerate(rs) if chapters[r["tid"]] is not None), len(rs))

        def key(i, r):
            c = chapters[r["tid"]]
            return (0, c, i) if c is not None else (-1 if i < first else 1, 0, i)

        ordered = [r["tid"] for i, r in sorted(enumerate(rs), key=lambda x: key(*x))]
        main = toc[0] if toc else next(t for t in ordered if chapters[t] is not None)
        out.append((folder, main, [t for t in ordered if t != main]))
    return out


def group_books(drafts, rows):
    """The drafts of a folder book (book_groups) made one document: the main draft gets the folder name as its title
    and a question, every other file a part line in the order of the book. Claude checks it: the draft suggests."""
    by = {d["tid"]: d for d in drafts}
    rel = {r["tid"]: r["rel"] for r in rows}
    for folder, main, parts in book_groups(rows):
        d = by[main]
        lg = next(iter(d.get("title") or {}), None) or (d.get("lang") or ["en"])[0]
        d["title"] = {lg: re.sub(r"_+", " ", folder.rsplit("/", 1)[-1]).strip()}
        d.setdefault("question", []).append(
            f"the folder {folder} looks like one book in {len(parts) + 1} files: {', '.join(parts)} are drafted as its "
            "parts in this order (part lines); correct the order or make them documents of their own"
        )
        for k, t in enumerate(parts, 2):
            what = re.sub(r"_+", " ", Path(rel[t]).stem).strip()[:80]
            by[t].clear()
            by[t].update({"tid": t, "part": main, "what": what, "order": k, "draft": True})
    return drafts


def write_drafts(work, state, tids=None, index=None, profile=None, append=False):
    """meta_draft.jsonl for the done files (all, or the given tids); returns the number of lines written. index: the
    index of the library, to find the documents a file may be a new version of (versions.py); profile: the settings.
    append=True keeps the lines of the other files (a draft written as soon as a file is done, during the batch); the
    pass over all files at the end writes the file anew and groups the files of a folder book (group_books)."""
    from assistant_x.intake import versions

    work = Path(work)
    rows = [r for r in state.all("done") if tids is None or r["tid"] in tids]
    docs = versions.library(index) if index else []
    drafts = []
    for r in rows:
        md = work / "md" / f"{r['tid']}.md"
        given = read_outline(pages_path(md))  # the bookmarks or heading styles of the file
        d = draft(md.read_text(encoding="utf-8") if md.exists() else "", r["rel"], profile, given)
        d["tid"] = r["tid"]
        if r.get("ocr_score") is not None:  # recognition score 0-100 (tools/ocr_score.py), for Claude to see
            d["ocr_score"] = r["ocr_score"]
        hit = versions.find(d.get("code_hint"), " ".join((d.get("title") or {}).values()), docs) if docs else None
        if hit:
            d["version_of"] = hit[0]
            d.setdefault("question", []).append(versions.question(*hit))
        if r.get("suspect") and r["suspect"] != d.get("version_of"):
            # process.Batch.dup_verdict: much of the text in common, but not surely the same edition
            d.setdefault("question", []).append(
                f"shares much of its text with {r['suspect']} ({r.get('suspect_why') or 'similar phrases'}): the same "
                f'document (the worse copy gets {{"dupof": "{r["suspect"]}"}}) or another edition (keep it; for a '
                f'document of the library {{"replaces"}} or {{"other_version"}})?'
            )
        for share, other in r.get("pair") or []:  # intake.Batch.batch_pairs: the same document twice in a batch?
            d.setdefault("question", []).append(
                f"looks like {other} of this batch ({share:.0%} common phrases): which one to keep? The worse copy gets "
                f'{{"dupof": "{other}"}}, or keep both with a note when these are different editions'
            )
        drafts.append(d)
    if tids is None:
        group_books(drafts, rows)
    path = work / "meta_draft.jsonl"
    keep = []
    if append and path.exists():
        new = {d["tid"] for d in drafts}
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                if line.strip() and json.loads(line).get("tid") not in new:
                    keep.append(line)
            except ValueError:
                continue
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for line in keep:
            f.write(line + "\n")
        for d in drafts:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    tmp.replace(path)
    return len(drafts)


def main(argv):
    if not argv:
        sys.exit(__doc__)
    from assistant_x.intake.state import State

    n = write_drafts(argv[0], State(Path(argv[0]) / "state.sqlite"))
    print(f"Metadata draft: {n} lines in {Path(argv[0]) / 'meta_draft.jsonl'}")


if __name__ == "__main__":
    main(sys.argv[1:])
