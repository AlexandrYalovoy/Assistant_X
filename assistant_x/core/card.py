# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Document cards: index/cards/<code>.json, strict JSON checked by the JSON Schema assistant_x/schemas/card-1.json.

A card is the one source of truth about a document: the catalog, the list of sources to update and the docs table of
the base are made from the cards. Two blocks: `doc` (the meaning, written by Claude from the drafts of the intake) and
`file` (format, recognition, paths, hashes; written by the code). Text fields searched by exact words are maps
{language: text}: 'en' always, and every language the documents are read in (config.card_languages).

Nobody reads the cards by eye: they serve Claude (brief) and the code (search_text, unit_text, the index)."""

import functools, hashlib, json, os, re
from pathlib import Path

SCHEMA_VERSION = 1
SCHEMA_FILE = Path(__file__).resolve().parent.parent / "schemas" / f"card-{SCHEMA_VERSION}.json"
CODE_RX = re.compile(r"^(?P<letter>[A-Z])-(?P<num>\d{5})(?:-(?P<part>\d{2,3}))?$")  # N-00012, E-00006-02
CODE_IN_TEXT_RX = re.compile(r"(?<![\w-])[A-Z]-\d{5}(?:-\d{2,3})?(?![\w-])")
DIGITS = 5
# the fields of `doc` that are maps {language: …} (keywords: lists of words per language)
TEXT_MAPS = ("title", "designation")
FORMAT_KINDS = ("pdf_text", "pdf_mixed", "pdf_scan", "pdf_no_ocr", "doc", "presentation", "image", "other")
# fields of `doc` brief() shows by default, in this order; toc and the file only when asked
BRIEF_FIELDS = (
    "designation",
    "adopts",
    "amends",
    "title",
    "authors",
    "year",
    "edition",
    "publisher",
    "lang",
    "serial",
    "scope",
    "summary",
    "topics",
    "keywords",
    "terms",
    "questions",
    "units",
    "tables",
    "references",
    "other_versions",
    "page_offset",
    "note",
)


class CardError(ValueError):
    pass


@functools.lru_cache(maxsize=1)
def schema():
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def _validator():
    import jsonschema

    return jsonschema.Draft202012Validator(schema())


def doc_types():
    """The universal genres of the schema (doc_type)."""
    return tuple(schema()["$defs"]["doc_type"]["enum"])


# ---------- codes ----------


def code_rx(letters):
    """Regex of the codes (and the codes of parts) of these section letters: groups letter, num, part."""
    letters = "".join(sorted(set(letters))) or "A-Z"
    return re.compile(rf"^(?P<letter>[{letters}])-(?P<num>\d{{{DIGITS}}})(?:-(?P<part>\d{{2,3}}))?$")


def new_code(letter, n):
    """('N', 12) -> 'N-00012'."""
    if not re.fullmatch(r"[A-Z]", letter or "") or not 0 < int(n) < 10**DIGITS:
        raise CardError(f"no code for the letter {letter!r} and the number {n!r}")
    return f"{letter}-{int(n):0{DIGITS}d}"


def part_code(code, k):
    """('N-00012', 2) -> 'N-00012-02': the code of file k of a document of several files."""
    return f"{code}-{int(k):02d}"


def main_code(code):
    """'E-00006-02' -> 'E-00006'; a code of a document is returned as it is."""
    m = CODE_RX.match(code or "")
    return f"{m['letter']}-{m['num']}" if m else code


def is_code(code):
    return bool(CODE_RX.match(code or ""))


# index/codes.json: {letter: the highest number ever given}. A number never comes back, even after its document was
# removed or replaced by a package update: an old citation must not name another document. The intake gives numbers
# above the mark; a base package whose code is at or below it and is not in the library now gets a new code at its
# install or update (base/inspection.code_plan "retired"), unless the same package document had that code here before
# or a reference package keeps its numbering (the reuse is then listed in the report: docs/PACKAGES.md).
CODES_FILE = "codes.json"


def high_water(index):
    """{letter: highest number given} of index/codes.json ({} when there is none or it does not read)."""
    try:
        data = json.loads((Path(index) / CODES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: int(v) for k, v in (data.get("high") or {}).items() if re.fullmatch(r"[A-Z]", k)}


def raise_high_water(index, codes):
    """Raise the marks of index/codes.json to the codes given (codes of parts count for their document); never lowers."""
    high = high_water(index)
    new = dict(high)
    for code in codes:
        m = CODE_RX.match(code or "")
        if m:
            new[m["letter"]] = max(new.get(m["letter"], 0), int(m["num"]))
    if new != high:
        path = Path(index) / CODES_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({"high": dict(sorted(new.items()))}, indent=1) + "\n", encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    return new


# ---------- renumbering: new codes for documents (the install of a base package) ----------
# a code at the start of a file or folder name: "N-00012_Title.pdf", "N-00012-02_Trials.pdf", "N-00012.md"
NAME_CODE_RX = re.compile(r"^(?P<code>[A-Z]-\d{5})(?P<part>-\d{2,3})?(?=[_.]|$)")


def map_code(code, mapping):
    """A code (of a document or of a part) under mapping {old document code: new document code}: the part keeps its
    number ('N-00012-02' -> 'N-00040-02'); a code mapping does not name stays."""
    m = CODE_RX.match(code or "")
    if not m:
        return code
    main = f"{m['letter']}-{m['num']}"
    return mapping[main] + code[len(main) :] if main in mapping else code


def map_text(text, mapping):
    """Every code in a free text under mapping (CODE_IN_TEXT_RX)."""
    return CODE_IN_TEXT_RX.sub(lambda m: map_code(m.group(0), mapping), text) if text else text


def map_path(path, mapping):
    """A path of the workspace ('library/01_Standards/N-00012_x/N-00012-02_y.pdf') with the code at the start of every
    part of it under mapping."""
    if not path:
        return path
    parts = re.split(r"([\\/])", path)
    return "".join(NAME_CODE_RX.sub(lambda m: map_code(m["code"], mapping) + (m["part"] or ""), p) for p in parts)


def check_mapping(mapping):
    """The problems of a mapping {old: new} (an empty list: fine): codes of documents only, the letter (the shelf) kept,
    no two old codes to one new code."""
    out = []
    for old, new in mapping.items():
        mo, mn = CODE_RX.match(old or ""), CODE_RX.match(new or "")
        if not mo or not mn or mo["part"] or mn["part"]:
            out.append(f"{old} -> {new}: a mapping takes codes of documents")
        elif mo["letter"] != mn["letter"]:
            out.append(f"{old} -> {new}: the letter of a code is its shelf and stays")
    news = list(mapping.values())
    out += [f"two documents to {c}" for c in sorted({c for c in news if news.count(c) > 1})]
    return out


def remap(card, mapping):
    """(the card under mapping {old document code: new document code}, [where a free text named a code]): its code,
    the codes and paths of its file and parts, hidden_text, issues, other_versions; codes inside note, summary, scope
    and the texts of the issues too (listed, so the user can see them). intake.package.code is the code in the package
    and stays as it is."""
    card = json.loads(json.dumps(card))
    notes = []
    card["code"] = map_code(card.get("code"), mapping)
    file, doc = card.get("file") or {}, card.get("doc") or {}
    for entry in [file] + list(file.get("parts") or []):
        if entry.get("code"):
            entry["code"] = map_code(entry["code"], mapping)
        for k in ("library", "text", "pdf_copy"):
            if entry.get(k):
                entry[k] = map_path(entry[k], mapping)
    for h in file.get("hidden_text") or []:
        if h.get("code"):
            h["code"] = map_code(h["code"], mapping)
    for i, issue in enumerate(file.get("issues") or []):
        if issue.get("code"):
            issue["code"] = map_code(issue["code"], mapping)
        for k in ("what", "need"):
            new = map_text(issue.get(k), mapping)
            if new != issue.get(k):
                notes.append(f"file/issues/{i}/{k}")
                issue[k] = new
    if doc.get("other_versions"):
        doc["other_versions"] = sorted({map_code(c, mapping) for c in doc["other_versions"]})
    for k in ("note", "summary", "scope"):
        new = map_text(doc.get(k), mapping)
        if new != doc.get(k):
            notes.append(f"doc/{k}")
            doc[k] = new
    return card, notes


def renames(card, mapping, index="index"):
    """[(old path, new path)] of the files of a card under mapping, relative to the workspace with '/': the card
    itself, the text and its .pages.json of the document and of every part, the original and its PDF copy in the
    library (a file of a multi-file folder moves with the folder's new name). Only the paths that change; whether a
    file is there (a .pages.json, a text) is the caller's matter."""
    out = []
    code = card.get("code") or ""
    if map_code(code, mapping) != code:
        out.append((f"{index}/cards/{code}.json", f"{index}/cards/{map_code(code, mapping)}.json"))
    file = card.get("file") or {}
    for entry in [dict(file, code=code)] + list(file.get("parts") or []):
        sub = entry.get("code") or ""
        text = entry.get("text") or (f"{index}/texts/{sub}.md" if sub else "")
        paths = [
            text,
            re.sub(r"\.(md|txt)$", "", text) + ".pages.json" if text else "",
            entry.get("library") or "",
            entry.get("pdf_copy") or "",
        ]
        for p in dict.fromkeys(x for x in paths if x):
            new = map_path(p, mapping)
            if new != p:
                out.append((p, new))
    return out


# ---------- reading and writing ----------


def dumps(card):
    """The JSON text of a card: sorted keys, one space of indent, UTF-8 letters as they are, LF, a trailing newline."""
    return json.dumps(card, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


def dump(card, path):
    """Write a card at once (a temporary file and os.replace: a reader sees the old card or the new one)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(dumps(card), encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def load(path):
    """A card from its file, migrated to the current schema (not validated: validate())."""
    try:
        card = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise CardError(f"{Path(path).name}: not JSON ({e.msg}, line {e.lineno})") from e
    if not isinstance(card, dict):
        raise CardError(f"{Path(path).name}: not a JSON object")
    return migrate(card)


def sha(path):
    """sha256 of the bytes of a card file: the index rebuild reads again only the cards that changed."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def paths(cards_dir):
    """{code: path} of the cards of a folder (names starting with '_' are notes, not cards)."""
    d = Path(cards_dir)
    return {p.stem: p for p in sorted(d.glob("*.json")) if not p.name.startswith("_")} if d.is_dir() else {}


# schema version -> the function that turns a card of that version into one of the next version
MIGRATIONS = {}


def migrate(card):
    """A card of an earlier schema brought to SCHEMA_VERSION step by step (no steps yet: schema 1 is the first)."""
    v = card.get("schema")
    while v != SCHEMA_VERSION:
        if v not in MIGRATIONS:
            raise CardError(f"{card.get('code', '?')}: unknown card schema {v!r} (this program reads {SCHEMA_VERSION})")
        card = MIGRATIONS[v](card)
        v = card.get("schema")
    return card


# ---------- checking ----------


def _where(path):
    return "/".join(str(p) for p in path) or "card"


def text_maps(card):
    """[(where, map)] of every map {language: …} of a card: title, designation, keywords, terms, toc, tables, units,
    the name of a serial."""
    doc = card.get("doc") or {}
    out = [(k, doc[k]) for k in TEXT_MAPS + ("keywords",) if isinstance(doc.get(k), dict)]
    for key, sub in (("terms", "name"), ("toc", "title"), ("tables", "title"), ("units", "title")):
        for i, x in enumerate(doc.get(key) or []):
            if isinstance(x, dict) and isinstance(x.get(sub), dict):
                out.append((f"{key}/{i}/{sub}", x[sub]))
    if isinstance((doc.get("serial") or {}).get("name"), dict):
        out.append(("serial/name", doc["serial"]["name"]))
    return out


def validate(card, languages=("en",), sections=None, topics=None):
    """Errors of a card (an empty list: it is fine): the schema, the languages every map needs (languages: the
    card languages of the workspace, config.card_languages), the code and the section agreeing, the codes of the parts,
    the section among the letters of the shelves (sections: config.sections), the topics among the controlled list of
    the profile (topics, when it has one)."""
    errors = [
        f"{_where(e.absolute_path)}: {e.message}"
        for e in sorted(_validator().iter_errors(card), key=lambda e: list(map(str, e.absolute_path)))
    ]
    if not isinstance(card, dict):
        return errors
    need = list(dict.fromkeys(["en", *(languages or ())]))
    for where, m in text_maps(card):
        missing = [x for x in need if not m.get(x)]
        if missing:
            errors.append(f"doc/{where}: no text in {', '.join(missing)}")
    code, sec = card.get("code") or "", card.get("section") or ""
    m = CODE_RX.match(code)
    if m and m["part"]:
        errors.append(f"code {code}: a card has the code of a document, not of a part")
    if m and sec and m["letter"] != sec:
        errors.append(f"code {code} and section {sec} disagree: the letter of the code is the section")
    if sections is not None and sec and sec not in sections:
        errors.append(f"section {sec}: not a shelf of the library ({' '.join(sections)})")
    file = card.get("file") or {}
    seen = set()
    for i, p in enumerate(file.get("parts") or []):
        pc = p.get("code", "") if isinstance(p, dict) else ""
        if pc and main_code(pc) != code:
            errors.append(f"file/parts/{i}: the part {pc} is not of {code}")
        if pc in seen:
            errors.append(f"file/parts/{i}: the part {pc} twice")
        seen.add(pc)
    for i, h in enumerate(file.get("hidden_text") or []):
        if isinstance(h, dict) and h.get("code") and main_code(h["code"]) != code:
            errors.append(f"file/hidden_text/{i}: {h['code']} is not {code} or one of its parts")
    doc = card.get("doc") or {}
    if code in (doc.get("other_versions") or []):
        errors.append("doc/other_versions: the code of the card itself")
    if topics:
        unknown = [t for t in doc.get("topics") or [] if t not in topics]
        if unknown:
            errors.append(f"doc/topics: not in the topics of the profile: {', '.join(unknown)}")
    return errors


# ---------- defaults ----------


def empty_doc():
    return {
        "authors": [],
        "designation": None,
        "edition": "",
        "keywords": {"en": []},
        "lang": [],
        "other_versions": [],
        "page_offset": {"checked": False, "value": 0},
        "publisher": "",
        "questions": [],
        "references": [],
        "scope": "",
        "summary": "",
        "tables": [],
        "terms": [],
        "title": {"en": ""},
        "toc": [],
        "topics": [],
        "year": None,
    }


def empty_file():
    return {
        "format": {"kind": "other", "pages": None},
        "hidden_text": [],
        "issues": [],
        "library": "",
        "parts": [],
        "pdf_copy": "",
        "sha256": "",
        "size": None,
        "source_name": "",
        "text": "",
    }


def complete(card):
    """The card with the optional fields of doc and file present (empty), the way the intake writes every card.
    designation stays out when the document has none."""
    doc = {**empty_doc(), **(card.get("doc") or {})}
    if doc.get("designation") is None:
        doc.pop("designation")
    return {**card, "doc": doc, "file": {**empty_file(), **(card.get("file") or {})}}


# ---------- what the code and Claude read ----------


def text(m, lang="en"):
    """A map {language: text} -> the text in lang, else in English, else the first one; a plain string as it is."""
    if isinstance(m, dict):
        return m.get(lang) or m.get("en") or next((v for v in m.values() if v), "")
    return m or ""


def all_texts(m):
    """Every language of a map, without repeats (the same text in two languages once)."""
    if isinstance(m, dict):
        return list(dict.fromkeys(v for v in m.values() if v))
    return [m] if m else []


def _joined(m, sep=" / "):
    return sep.join(all_texts(m))


DESIG_KEY_RX = re.compile(r"[\s\-–—_.,:/]+")


def designation_key(d):
    """A designation for exact comparison: capitals, without spaces, dashes, dots ('GOST R 51858-2002' and
    'gost r 51858–2002' are the same); '' for an empty one."""
    return DESIG_KEY_RX.sub("", (d or "").upper())


def keywords(doc):
    """Every keyword of every language, without repeats."""
    kw = doc.get("keywords") or {}
    return list(dict.fromkeys(w for ws in kw.values() for w in ws))


def card_langs(doc):
    """The languages of a card: the keys of its language maps (title, designation, keywords, the names of the terms),
    in their first order; ["en"] for a card without any."""
    maps = [doc.get("title"), doc.get("designation"), doc.get("keywords")] + [t.get("name") for t in doc.get("terms") or []]
    return list(dict.fromkeys(k for m in maps if isinstance(m, dict) for k, v in m.items() if v)) or ["en"]


def _in(m, lang):
    """The text of a language map in lang; a plain string as it is; '' when the map lacks lang (no other language
    mixed into the fragment of this one)."""
    return (m.get(lang) or "") if isinstance(m, dict) else (m or "")


def search_texts(card):
    """The card as fragments of the search, [(kind, lang, text)]: a 'card' fragment per language of the card (its
    designation in that language, else every one of them; its title, keywords and terms in that language; the scope
    and the summary in each) and one 'card_q' fragment of its questions and topics (lang ""). A vector of one language
    is closer to a question in that language than a vector of two languages mixed; the questions, a list of what the
    document answers, are a fragment of their own so they are not diluted by the rest."""
    doc = card.get("doc") or {}
    out = []
    for lang in card_langs(doc):
        lines = [
            _in(doc.get("designation"), lang) or _joined(doc.get("designation")),
            ", ".join(doc.get("adopts") or []),
            _in(doc.get("title"), lang),
            doc.get("scope") or "",
            doc.get("summary") or "",
        ]
        kw = (doc.get("keywords") or {}).get(lang) or []
        if kw:
            lines.append("; ".join(kw))
        for t in doc.get("terms") or []:
            name = _in(t.get("name"), lang)
            if name:
                lines.append(" — ".join(x for x in [name, t.get("expansion") or ""] if x))
        text = "\n".join(x for x in lines if x)
        if text:
            out.append(("card", lang, text))
    qs = [q for q in doc.get("questions") or [] if q.strip()]
    if doc.get("topics"):
        qs.append(", ".join(x.replace("_", " ") for x in doc["topics"]))
    if qs:
        out.append(("card_q", "", "\n".join(qs)))
    return out


def search_text(card):
    """The card as one text of the search: title, designation, scope, summary, keywords, terms, questions, topics,
    in every language the card has (the index gives it as several fragments: search_texts)."""
    doc = card.get("doc") or {}
    lines = [_joined(doc.get("designation")), ", ".join(doc.get("adopts") or []), _joined(doc.get("title"))]
    lines += [doc.get("scope") or "", doc.get("summary") or ""]
    if keywords(doc):
        lines.append("; ".join(keywords(doc)))
    for t in doc.get("terms") or []:
        lines.append(" — ".join(x for x in [_joined(t.get("name")), t.get("expansion") or ""] if x))
    lines += doc.get("questions") or []
    if doc.get("topics"):
        lines.append(", ".join(x.replace("_", " ") for x in doc["topics"]))
    return "\n".join(x for x in lines if x)


def unit_text(unit):
    """A logical unit of a document (an article of a journal issue, a paper, a standard of a compilation) as a
    fragment of the search: its title, authors and summary."""
    return "\n".join(
        x for x in [_joined(unit.get("title")), ", ".join(unit.get("authors") or []), unit.get("summary") or ""] if x
    )


def format_line(fmt):
    """The format of a file in words, for the assistant and the reports: 'PDF scan (OCR, errors possible), 48 pages'."""
    fmt = fmt or {}
    kind, n = fmt.get("kind"), fmt.get("pages")
    pages = "? pages" if not n else "1 page" if n == 1 else f"{n} pages"
    if kind == "pdf_text":
        return f"PDF with text, {pages}"
    if kind == "pdf_mixed":
        return f"PDF with text, some pages are scans ({fmt.get('ocr_pages', 0)} recognized), {pages}"
    if kind == "pdf_scan":
        return f"PDF scan (OCR, errors possible), {pages}"
    if kind == "pdf_no_ocr":
        return f"PDF scan without OCR ({fmt.get('no_ocr_pages', 0)} pages without text), {pages}"
    if kind == "doc":
        return f"DOC (for page references: the PDF beside it), {pages}"
    if kind == "presentation":
        return f"Presentation, {n or '?'} slides (slide = page)"
    if kind == "image":
        return f"Image, {pages}"
    return f"Other, {pages}"


def ocr_share(fmt):
    """Share of the pages read by OCR, or None when unknown."""
    fmt = fmt or {}
    kind, n = fmt.get("kind"), fmt.get("pages") or 0
    if kind in ("pdf_text", "doc", "presentation"):
        return 0.0
    if kind == "pdf_scan" or kind == "image":
        return 1.0
    if kind == "pdf_mixed" and n:
        return round(fmt.get("ocr_pages", 0) / n, 2)
    return None


def page_line(doc):
    """How a printed page relates to a PDF page, in words."""
    po = doc.get("page_offset") or {}
    v = po.get("value", 0)
    rel = "printed page = PDF page" + (f" - {v}" if v > 0 else f" + {-v}" if v < 0 else "")
    return rel + ("" if po.get("checked") else " (not checked)")


def _render(key, value, doc):
    """One field of brief(): its label and its text, or None when the field is empty."""
    if value in (None, "", [], {}):
        return None
    if key in ("title", "designation"):
        return " / ".join(f"{t}" for t in all_texts(value))
    if key == "keywords":
        return "; ".join(f"{lang}: {', '.join(ws)}" for lang, ws in value.items() if ws)
    if key in ("authors", "lang", "topics", "other_versions"):
        return ", ".join(value)
    if key == "questions":
        return " | ".join(value)
    if key == "terms":
        return "; ".join(_joined(t.get("name")) + (f" ({t['expansion']})" if t.get("expansion") else "") for t in value)
    if key == "tables":
        return "; ".join(
            f"{t['label']}" + (f" «{_joined(t['title'])}»" if t.get("title") else "") + f" — PDF {t['pdf_page']}"
            for t in value
        )
    if key == "references":
        return ", ".join(r["designation"] for r in value)
    if key == "page_offset":
        return page_line(doc)
    if key == "serial":
        bits = [
            _joined(value.get("name")),
            value.get("issn") and f"ISSN {value['issn']}",
            value.get("volume") not in (None, "") and f"vol. {value['volume']}",
            value.get("number") not in (None, "") and f"no. {value['number']}",
        ]
        return ", ".join(str(b) for b in bits if b)
    if key == "units":
        return "".join(
            f"\n  - PDF {u['pdf_from']}: {_joined(u['title'])}"
            + (f" — {', '.join(u['authors'])}" if u.get("authors") else "")
            + (f". {u['summary']}" if u.get("summary") else "")
            for u in value
        )
    if key == "toc":
        return "".join(f"\n  {'  ' * (t['level'] - 1)}{_joined(t['title'])} — PDF {t['pdf_from']}" for t in value)
    return str(value)


LABELS = {
    "other_versions": "Other versions",
    "page_offset": "Page numbering",
    "lang": "Language",
    "toc": "Contents",
    "units": "Contents (units)",
}


def brief(card, fields=None):
    """Compact text of a card for the assistant. Without fields: everything of `doc` but the table of contents; fields: only
    these keys of `doc` ('toc' among them), 'file' for the file block, 'issues' for the problems of the source."""
    doc = card.get("doc") or {}
    file = card.get("file") or {}
    want = list(fields) if fields else list(BRIEF_FIELDS)
    head = f"{card.get('code')} · {text(doc.get('title'))}"
    lines = [
        head,
        f"Type: {card.get('doc_type')}; section: {card.get('section')}"
        + ("; a personal document of the user (added on their PC)" if (card.get("intake") or {}).get("personal") else ""),
    ]
    for key in want:
        if key == "file":
            lines.append(
                f"File: {file.get('library') or '—'}; {format_line(file.get('format'))}"
                + (f"; PDF copy: {file['pdf_copy']}" if file.get("pdf_copy") else "")
            )
            for p in file.get("parts") or []:
                lines.append(
                    f"  part {p['code']}: {p.get('library') or '—'}"
                    + (f" ({p['what']})" if p.get("what") else "")
                    + ("" if p.get("text") else " — no text")
                )
            continue
        if key == "issues":
            for i in file.get("issues") or []:
                if not i.get("closed"):
                    lines.append(f"Issue: {i['what']} — {i.get('need') or '?'} (priority: {i['priority']})")
            continue
        s = _render(key, doc.get(key), doc)
        if s is not None:
            lines.append(f"{LABELS.get(key, key.replace('_', ' ').capitalize())}: {s}")
    if not fields:
        parts = [p["code"] for p in file.get("parts") or []]
        if parts:
            lines.append(f"Parts (each with its own PDF pages): {', '.join(parts)}")
        if doc.get("toc"):
            lines.append(f"Contents: {len(doc['toc'])} entries (document_info with fields=['toc'], or book_map)")
    return "\n".join(lines)
