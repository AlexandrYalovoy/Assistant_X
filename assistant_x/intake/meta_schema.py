# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""meta.jsonl of an intake batch: what Claude writes about each processed file, one JSON object per line
(several lines of one tid are merged, later lines win). build.py checks it here before giving codes.

A line is one of:
  document  {"tid": "T0001", "sec": "<letter of a shelf, schemas/shelves.json>", "doc_type": "<genre of the schema>",
             "en": "English-Title-3-7-words" (the file name), "au": "Author-or-Designation" (Latin, the file name),
             the fields of the `doc` block of a card (schemas/card-1.json): title, designation, authors, year,
             publisher, edition, lang, scope, summary, topics, keywords, terms, questions, toc, tables, references,
             units, serial, page_offset, note;
             "replaces": "N-00001" | "other_version": "N-00001" (a new version: versions.py),
             "issues": [{"what", "need", "priority"}] (what is wrong with the source),
             "quality_ok": true (the problems the quality report found are not issues)}
  part      {"tid": "T0002", "part": "T0001", "what": "Scan", "order": 2}  — file of a multi-file document; "order"
            (optional) places it among the parts, else they go by file name ("Chapter 2" before "Chapter 10")
  duplicate {"tid": "T0003", "dupof": "T0001" | "L-00012", "why": "…"}
  dropped   {"tid": "T0004", "drop": "administrative pages only"}  — to inbox\\_rejected
The `doc` fields are checked by core/card.py as the card will be: the card languages (English and the document
languages of the workspace) in
every searchable text, the limits of the schema.
Usage: python -m assistant_x.intake.meta_schema <batch folder | its meta.jsonl>   prints the errors, exit 1 if any."""

import datetime, json, re, sys
from pathlib import Path

from assistant_x.core import card as C

KINDS = ("sec", "part", "dupof", "drop")
DOC_FIELDS = tuple(C.schema()["$defs"]["doc"]["properties"])
CONTROL = {
    "tid",
    "sec",
    "doc_type",
    "en",
    "au",
    "replaces",
    "other_version",
    "version_of",
    "supersedes",
    "question",
    "issues",
    "quality_ok",
    "part",
    "what",
    "order",
    "dupof",
    "why",
    "drop",
    "draft",
    "code_hint",
    "ocr_score",
}
KNOWN = CONTROL | set(DOC_FIELDS)
TID = re.compile(r"^T\d{4,}$")
PRIORITIES = ("high", "medium", "low")


def load(path):
    """({tid: merged fields}, [errors of lines that are not JSON objects with a tid])."""
    meta, errors = {}, []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                m = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"line {n}: not JSON ({e.msg})")
                continue
            if not isinstance(m, dict) or not str(m.get("tid") or "").strip():
                errors.append(f"line {n}: no tid")
                continue
            meta[m["tid"]] = {**meta.get(m["tid"], {}), **m}
    return meta, errors


def doc_of(m):
    """The `doc` block of the card of a document line: its doc fields, the optional ones empty."""
    return C.complete({"doc": {k: m[k] for k in DOC_FIELDS if k in m}})["doc"]


def card_of(m, code=None, date=None):
    """The card a document line would give (without its file block): for checking and for build.py."""
    sec = str(m.get("sec") or "")
    return C.complete(
        {
            "schema": C.SCHEMA_VERSION,
            "code": code or f"{sec if re.fullmatch('[A-Z]', sec) else 'X'}-00001",
            "section": sec,
            "doc_type": m.get("doc_type"),
            "doc": doc_of(m),
            "file": {"format": {"kind": "other", "pages": None}, "library": "", "text": ""},
            "intake": {"date": date or datetime.date.today().isoformat(), "personal": False},
        }
    )


def check(meta, tids=None, year=None, sections=None, languages=("en",), topics=None):
    """Errors of merged meta; tids: the files of the batch (state), when known; sections: the letters of the shelves
    (None: any capital letter); languages: the card languages; topics: the controlled
    list of topics, when it has one."""
    year = year or datetime.date.today().year
    errors = []
    for tid, m in sorted(meta.items()):
        e = lambda msg: errors.append(f"{tid}: {msg}")
        if not TID.match(tid):
            e("tid not of the form T0001")
        if tids is not None and tid not in tids:
            e("no such file in the batch (state.sqlite)")
        kinds = [k for k in KINDS if m.get(k)]
        if len(kinds) != 1:
            e(
                "exactly one of the fields sec (document), part (part), dupof (duplicate), drop (rejected) is needed"
                + (f", but there are {', '.join(kinds)}" if kinds else "")
            )
            continue
        unknown = sorted(set(m) - KNOWN)
        if unknown:
            e(f"unknown fields {', '.join(unknown)}")
        if kinds[0] == "sec":
            sec = m["sec"]
            if not (re.fullmatch(r"[A-Z]", str(sec)) and (sections is None or sec in sections)):
                e(
                    f"section sec={sec!r}, "
                    + (f"one of {' '.join(sections)} is needed" if sections else "the letter of a shelf is needed")
                )
            if not str(m.get("en") or "").strip() or not re.search(r"[A-Za-z]", str(m.get("en"))):
                e(
                    'the field "en" is missing or not English: the short English title the file name is made from '
                    '(e.g. "Oil separation handbook"); title.en does not replace it'
                )
            yr = m.get("year")
            if isinstance(yr, int) and not 1900 <= yr <= year + 1:
                e(f"year {yr} outside 1900..{year + 1}")
            for x in C.validate(card_of(m), languages, topics=topics):
                if not x.startswith(("code ", "section ")):  # the section is checked above
                    e(x)
            if m.get("replaces") and m.get("other_version"):
                e("replaces and other_version together: one answer of the user")
            for k in ("replaces", "other_version"):
                if m.get(k) and not (C.is_code(str(m[k])) and not C.CODE_RX.match(str(m[k]))["part"]):
                    e(f"{k}: a code of a document of the library like N-00001, not {m[k]!r}")
            if m.get("replaces") and C.is_code(str(m["replaces"])) and str(m["replaces"])[0] != sec:
                e(
                    f"replaces {m['replaces']}: a new version keeps the section of the old one ({m['replaces'][0]}, not {sec})"
                )
            issues = m.get("issues")
            for i, x in enumerate([] if issues is None else issues if isinstance(issues, list) else [None]):
                if not (isinstance(x, dict) and str(x.get("what") or "").strip() and x.get("priority") in PRIORITIES):
                    e(f"issues/{i}: an object {{what, need, priority: {' | '.join(PRIORITIES)}}}")
        elif kinds[0] == "part":
            p = meta.get(m["part"])
            if m["part"] == tid:
                e("part refers to itself")
            elif not p:
                e(f"part refers to {m['part']}, which is not in meta.jsonl")
            elif not p.get("sec"):
                e(f"part refers to {m['part']}, which is not a document (no sec)")
            if "order" in m and not (isinstance(m["order"], int) and not isinstance(m["order"], bool) and m["order"] >= 1):
                e(f"order={m['order']!r}: the place of the part among the parts of its document, a whole number from 1")
        elif kinds[0] == "dupof":
            d = m["dupof"]
            if not (C.is_code(d) or d in meta or (tids is not None and d in tids)):
                e(f"dupof={d!r}: a code N-00001 or a tid of a file of the batch is needed")
    return errors


def _key(s):
    """A text for comparing a designation: the skeleton of the letters (case, look-alike letters, dashes), no spaces."""
    from assistant_x.core.common import skeleton

    return re.sub(r"\s+", "", skeleton(str(s)))


def _stems(s):
    from assistant_x.core.common import tokens

    return {t for t in tokens(str(s), drop_stop=True) if len(t) >= 3 and not t[0].isdigit()}


def _texts(value):
    if isinstance(value, dict):
        return [x for v in value.values() for x in (v if isinstance(v, list) else [v])]
    return value if isinstance(value, list) else [value] if value else []


def text_checks(meta, texts, names=None):
    """(errors, warnings) of the document lines against the texts of their files ({tid: Markdown}; names: {tid: file
    name}): a designation must be on the first 3 pages (or in the file name; its digits are enough after OCR), the year
    should be in the text, half of the keywords in the languages of the document should be in it, and the title
    must share a word with the first pages of a text of two pages or more (a line written for another tid)."""
    from assistant_x.core.common import split_pages

    errors, warnings = [], []
    for tid, m in sorted(meta.items()):
        text = texts.get(tid)
        if not m.get("sec") or not text:
            continue
        pages = split_pages(text) or [(1, text)]
        first = "\n".join(t for _, t in pages[:3])
        first_key, name_key = _key(first), _key((names or {}).get(tid, ""))
        for d in _texts(m.get("designation")):
            k = _key(d)
            digits = max(re.findall(r"[\d][\d.\-/]*\d", k), key=len, default="")
            if k and k not in first_key and k not in name_key and not (len(digits) >= 4 and digits in first_key):
                if not any(_key(x) in first_key for x in _texts(m.get("designation")) if x != d):
                    errors.append(f"{tid}: the designation {d!r} is not on the first 3 pages of the text")
                break
        yr = m.get("year")
        if isinstance(yr, int) and str(yr) not in text:
            warnings.append(f"{tid}: the year {yr} does not occur in the text")
        stems_all = _stems(text)
        for lg in [x for x in (m.get("lang") or []) if x != "en"] or (m.get("lang") or []):
            kws = (m.get("keywords") or {}).get(lg) or []
            found = sum(bool(_stems(k)) and _stems(k) <= stems_all for k in kws)
            if kws and found < len(kws) / 2:
                warnings.append(f"{tid}: {found} of {len(kws)} keywords ({lg}) occur in the text")
        title = _stems(" ".join(_texts(m.get("title"))))
        if len(pages) >= 2 and title and not title & _stems(first):
            errors.append(f"{tid}: the title shares no word with the first pages of the text: a line of another file?")
    return errors, warnings


def batch_texts(work):
    """{tid: Markdown} of the processed files of a batch."""
    return {p.stem: p.read_text(encoding="utf-8") for p in (Path(work) / "md").glob("T*.md")}


def profile_rules(raw):
    """The keyword arguments of check() for the settings raw: the shelves, the card languages, the topics of the
    profile."""
    from assistant_x.core import config

    return {
        "sections": [s["letter"] for s in config.sections(raw)],
        "languages": config.card_languages(raw),
        "topics": config.topics(raw),
    }


def check_batch(raw, work):
    """(meta, errors, warnings) of the meta.jsonl of a batch by the rules of the profile of raw (the settings): the one
    check of check-meta (intake_save_meta) and of build, so the cards Claude was told are fine build. Without the
    state.sqlite of the batch the tids are not checked against its files."""
    work = Path(work)
    meta, errors = load(work / "meta.jsonl")
    names = None
    if (work / "state.sqlite").exists():
        from assistant_x.intake.state import State

        names = {r["tid"]: r["rel"].rsplit("/", 1)[-1] for r in State(work / "state.sqlite").all()}
    errors += check(meta, set(names) if names is not None else None, **profile_rules(raw))
    bad, warnings = text_checks(meta, batch_texts(work), names or {})
    return meta, errors + bad, warnings


def main(argv):
    if not argv:
        sys.exit(__doc__)
    from assistant_x.core import config

    path = Path(argv[0])
    meta, errors, warnings = check_batch(config.load()[1], path if path.is_dir() else path.parent)
    for x in errors:
        print(x)
    for x in warnings:
        print(f"warning: {x}")
    print(f"Lines by file: {len(meta)}, errors: {len(errors)}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
