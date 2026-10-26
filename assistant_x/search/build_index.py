# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build or update library.sqlite from the cards (index/cards/<code>.json) and the texts (index/texts) of index/.
Every document gives fragments of four kinds (chunks.kind): 'text' (the pages of its text), 'card' (the card itself,
one fragment per language of the card: designation, title, scope, summary, keywords, terms), 'card_q' (the questions
and topics of the card) and 'unit' (an
article of a journal issue, a paper of proceedings: its title, authors and summary, at its first page). The text of
every page goes into the table pages exactly, with what <code>.pages.json knows of it (printed label, source,
recognition score, flags); a text fragment is a range of offsets into its page. Only the documents whose text (or
.pages.json) changed are looked at again (docs.text_sha), and in them only the pages whose text or fragments changed
are chunked again: the fragments of the other pages keep their numbers and vectors. Only the cards whose sha256
changed (docs.card_sha) are read again; new fragments get vectors later (embed.py). The contents of a card go into
the table toc (with the last page of every
entry), the designations it refers to into links (with the code of the document of the library they name).
CATALOG.md and sources_to_update.md are made again from the cards (search/catalog.py).
--full builds a new file library-<time>.sqlite; the search reads the old base until embed.py has given the new one
its vectors and switches to it (common.DB_NEXT, DB_CURRENT); without vectors in the old base it switches at once.
Usage: assistant-x build [--config assistant_x.toml] [--full] [--no-check]
Before building, check_index.py checks the cards and the texts; errors stop the build (--no-check skips it).
The recognition score of each text comes from index/ocr_quality.tsv (docs.ocr_score; a low one goes into quality)."""

import argparse, datetime, hashlib, json, os
from pathlib import Path

from assistant_x.core import card as C
from assistant_x.core import config as settings
from assistant_x.search import bookmap, catalog
from assistant_x.core.common import (
    load_config,
    connect,
    meta,
    touch,
    new_vectors_file,
    drop_stale_vectors,
    SCHEMA,
    BASE_SCHEMA,
    CHUNK_VERSION,
    split_pages,
    chunk_doc,
    chunk_search_text,
    stem_text,
    exact_text,
    strip_invisible,
    text_stats,
    quality_note,
    folder_bytes,
    clear_index_stale,
    free_space_problem,
    read_ocr_scores,
    OCR_SCORES,
    vectors_path,
    next_db,
    set_pointer,
    switch_db,
    drop_stale_dbs,
    DB_NEXT,
)
from assistant_x.core.formats import TEXT_FORMAT, pages_path, read_outline, read_pages_info

# a part with no text (a drawing, a photo, an empty scan): nothing of it is found by the search, its pages are images
NO_TEXT = "no text: this part has no recognized text (a drawing, a photo or an empty scan) — look at the page image"
DOC_COLUMNS = (
    "code",
    "title",
    "designation",
    "doc_type",
    "section",
    "year",
    "format",
    "topics",
    "file",
    "page_offset",
    "card",
    "card_sha",
    "text_file",
    "text_sha",
    "pages",
    "parent",
    "source",
    "lang",
    "quality",
    "issue",
    "ocr_share",
    "ocr_score",
    "personal",
)


def text_file(texts_dir, code):
    for ext in (".md", ".txt"):
        p = os.path.join(texts_dir, code + ext)
        if os.path.exists(p):
            return p
    return None


def load_cards(cards_dir):
    """{code: (card, sha256 of its file)}; a broken card is left out (check_index reports it)."""
    out = {}
    for code, p in C.paths(cards_dir).items():
        try:
            out[code] = (C.load(p), C.sha(p))
        except C.CardError:
            continue
    return out


def hidden_line(file, code):
    """The hidden text of one file of a card in words, for quality_note ('' when none was found)."""
    return "; ".join(
        f"{h['fragments']} fragments" + (f", PDF pages {', '.join(map(str, h['pages']))}" if h.get("pages") else "")
        for h in file.get("hidden_text") or []
        if h.get("code", code) == code
    )


def issue_line(file, code, main):
    """The open issues of a card for one of its files (a part also has the issues of the whole document)."""
    return " | ".join(
        f"{i['what']} — {i.get('need') or '?'} (priority: {i['priority']})"
        for i in file.get("issues") or []
        if not i.get("closed") and i.get("code", main) in (code, main)
    )


def doc_rows(card, sha, profile=None):
    """The rows of docs of a card: the document itself and each of its parts (a code <code>-NN of its own)."""
    doc, file = card["doc"], card["file"]
    lang = (doc.get("lang") or ["en"])[0]
    title = catalog.title_of(card, 400)
    base = dict(
        code=card["code"],
        title=title,
        designation=" / ".join(C.all_texts(doc.get("designation"))),
        doc_type=card["doc_type"],
        section=settings.section_name(card["section"], profile),
        year=doc.get("year"),
        format=C.format_line(file.get("format")),
        topics=", ".join(doc.get("topics") or []),
        file=file.get("library") or "",
        page_offset=C.page_line(doc),
        card=json.dumps(card, ensure_ascii=False, sort_keys=True),
        card_sha=sha,
        parent="",
        source=file.get("source_name") or "",
        lang=",".join(doc.get("lang") or []),
        personal=int(bool((card.get("intake") or {}).get("personal"))),
        _file=file,
        _lang=lang,
    )
    rows = [base]
    for p in file.get("parts") or []:
        num = p["code"].rsplit("-", 1)[1]
        what = p.get("what") or os.path.splitext(p.get("source_name") or "")[0]
        rows.append(
            dict(
                base,
                code=p["code"],
                title=f"{title} (part {num}" + (f": {what})" if what else ")"),
                format=C.format_line(p.get("format")),
                file=p.get("library") or "",
                parent=card["code"],
                source=p.get("source_name") or "",
                _file=p,
            )
        )
    return rows


def toc_rows(card, pages):
    """[(code, level, title_en, title, pdf_from, pdf_to)] of the contents of a card: an entry ends where the next
    one of the same or a higher level starts (on that page: it may start in the middle of it), the last at the end."""
    toc = card["doc"].get("toc") or []
    last = max(pages or 0, max((t["pdf_from"] for t in toc), default=0))
    out = []
    for i, t in enumerate(toc):
        end = next((x["pdf_from"] for x in toc[i + 1 :] if x["level"] <= t["level"]), last)
        out.append(
            (
                card["code"],
                t["level"],
                C.text(t["title"]),
                " / ".join(C.all_texts(t["title"])),
                t["pdf_from"],
                max(t["pdf_from"], end),
            )
        )
    return out


def link_rows(cards):
    """[(code, designation, target_code)] of every reference of every card; the target is the document of the library
    with that designation in any language ('' when the library has none)."""
    by_key = {}
    for code, (c, _) in cards.items():
        for d in C.all_texts(c["doc"].get("designation")):
            by_key.setdefault(C.designation_key(d), code)
    out = []
    for code, (c, _) in sorted(cards.items()):
        for r in c["doc"].get("references") or []:
            target = by_key.get(C.designation_key(r["designation"]), "")
            out.append((code, r["designation"], target if target != code else ""))
    return out


def add_chunk(con, next_id, code, page, n, head, kind, search, start=None, end=None, lead=None, own_text=None):
    """One fragment and its row of the word index; search: the text it is searched by (chunk_search_text, or the own
    text of a card or a unit)."""
    con.execute(
        "INSERT INTO chunks(id,code,page,n,heading,kind,start,end,lead,own_text) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (next_id, code, page, n, head, kind, start, end, lead, own_text),
    )
    # the section heading is searchable too: a paragraph deep in "Losses from breathing" may not repeat it
    con.execute(
        "INSERT INTO chunks_fts(rowid, stem, exact) VALUES(?,?,?)",
        (next_id, stem_text(f"{head}\n{search}"), exact_text(f"{head}\n{search}")),
    )
    return next_id + 1


def card_chunks(con, next_id, card):
    """The fragments of the card (page 0: no page of the text; core/card.search_texts: a 'card' fragment per
    language, a 'card_q' one of its questions) and the fragments of its units (at their first page)."""
    for n, (kind, _, text) in enumerate(C.search_texts(card)):
        next_id = add_chunk(con, next_id, card["code"], 0, n, "card", kind, text, own_text=text)
    for n, u in enumerate(card["doc"].get("units") or []):
        text = C.unit_text(u)
        next_id = add_chunk(
            con, next_id, card["code"], u["pdf_from"], n, C.text(u["title"])[:240], "unit", text, own_text=text
        )
    return next_id


def read_text(texts_dir, code):
    """(path or None, the text without invisible characters, sha256 of the text and its .pages.json, [(page, text)],
    {page: what .pages.json knows}). The text of a page is the body between its marker and the next one, the blank
    lines around it left out."""
    tf = text_file(texts_dir, code)
    if not tf:
        return None, "", hashlib.sha256(b"").hexdigest(), [], {}
    raw = strip_invisible(open(tf, encoding="utf-8").read())
    side = pages_path(tf)
    extra = open(side, "rb").read() if os.path.exists(side) else b""
    sha = hashlib.sha256(raw.encode() + b"\0" + extra).hexdigest()
    return tf, raw, sha, [(n, t.strip("\n")) for n, t in split_pages(raw)], read_pages_info(side) or {}


def page_row(code, no, text, info):
    i = info.get(no) or {}
    return (
        code,
        no,
        text,
        hashlib.sha256(text.encode()).hexdigest(),
        i.get("label"),
        i.get("source"),
        i.get("ocr_score"),
        ",".join(i.get("flags") or []),
    )


def store_pages(con, next_id, code, pages, info):
    """The pages of a changed text into the base: every page row anew; the fragments of a page whose text and
    fragments (offsets, lead, heading) are the same stay with their numbers and vectors, the others are made anew.
    Returns (next fragment id, pages chunked again)."""
    old_sha = {r[0]: r[1] for r in con.execute("SELECT page, sha FROM pages WHERE code=?", (code,))}
    old = {}
    for r in con.execute(
        "SELECT page, n, heading, start, end, lead FROM chunks WHERE code=? AND kind='text' ORDER BY page, n", (code,)
    ):
        old.setdefault(r[0], []).append(tuple(r[1:]))
    new = {}
    for page, n, head, s, e, lead in chunk_doc(pages):
        new.setdefault(page, []).append((n, head, s, e, lead))
    texts, redone = dict(pages), 0
    con.execute("DELETE FROM pages WHERE code=?", (code,))
    con.executemany("INSERT INTO pages VALUES(?,?,?,?,?,?,?,?)", [page_row(code, no, t, info) for no, t in pages])
    for page in sorted(set(old) | set(new)):
        if (
            page in texts
            and old_sha.get(page) == hashlib.sha256(texts[page].encode()).hexdigest()
            and old.get(page) == new.get(page, [])
        ):
            continue
        ids = [r[0] for r in con.execute("SELECT id FROM chunks WHERE code=? AND page=? AND kind='text'", (code, page))]
        con.executemany("DELETE FROM chunks_fts WHERE rowid=?", [(i,) for i in ids])
        con.executemany("DELETE FROM chunks WHERE id=?", [(i,) for i in ids])
        for n, head, s, e, lead in new.get(page, []):
            next_id = add_chunk(
                con, next_id, code, page, n, head, "text", chunk_search_text(texts[page], s, e, lead), s, e, lead
            )
        redone += page in texts
    return next_id, redone


def main():
    ap = argparse.ArgumentParser(prog="assistant-x build")
    ap.add_argument("--config")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--no-check", action="store_true", help="do not check the cards and texts before building")
    a = ap.parse_args()
    cfg = load_config(a.config)
    if not a.no_check:  # a broken card or a missing text must not reach the search silently
        from assistant_x.search import check_index

        if check_index.run(cfg, quiet=True) > 0:
            raise SystemExit(
                "Build stopped: fix the errors (assistant-x check shows them again) or run assistant-x build --no-check."
            )
    low = free_space_problem(cfg["index_dir"], folder_bytes(cfg["texts_dir"], cfg["cards_dir"]))
    if low:
        raise SystemExit(low)
    os.makedirs(cfg["index_dir"], exist_ok=True)
    in_use = cfg["db"]
    if a.full:  # a new file: the search keeps reading the old base until the new one is complete (common.DB_NEXT)
        top = 0
        if os.path.exists(in_use):
            old = connect(in_use, readonly=True)
            top = max(
                int(meta(old, "max_chunk_id", 0) or 0), old.execute("SELECT coalesce(max(id), 0) FROM chunks").fetchone()[0]
            )
            old.close()
        cfg["db"] = os.path.join(cfg["index_dir"], f"library-{datetime.datetime.now():%Y%m%d-%H%M%S}.sqlite")
        con = connect(cfg["db"])
        con.executescript(SCHEMA)
        con.executescript(bookmap.SCHEMA)
        con.execute("INSERT INTO meta VALUES('max_chunk_id', ?)", (str(top),))  # ids never come back
        new_vectors_file(cfg, con)  # vectors point at fragments of the old base, so they start anew
        con.commit()
        print(f"Full build into a new file {os.path.basename(cfg['db'])}; the search keeps using the previous base.")
    else:
        cfg["db"] = next_db(cfg["index_dir"]) or in_use  # a rebuilt base waiting for vectors gets the changes
        con = connect(cfg["db"])
        if (
            con.execute("SELECT 1 FROM sqlite_master WHERE name='docs'").fetchone()
            and (meta(con, "base_schema") or "1") != BASE_SCHEMA
        ):
            old = meta(con, "base_schema") or "1"
            con.close()
            raise SystemExit(
                f"The base was built by an earlier version (base schema {old}, this one makes {BASE_SCHEMA}). "
                "Run assistant-x build --full, then assistant-x embed."
            )
        con.executescript(SCHEMA)
        con.executescript(bookmap.SCHEMA)
    if (
        not a.full
        and con.execute("SELECT count(*) FROM docs").fetchone()[0]
        and meta(con, "chunk_version", "1") != CHUNK_VERSION
    ):
        raise SystemExit(
            f"The base was built by an earlier version (fragments of version {meta(con, 'chunk_version', '1')}, "
            f"this one makes {CHUNK_VERSION}). Run assistant-x build --full, then assistant-x embed."
        )
    con.execute("INSERT OR REPLACE INTO meta VALUES('chunk_version', ?)", (CHUNK_VERSION,))
    con.execute("INSERT OR REPLACE INTO meta VALUES('base_schema', ?)", (BASE_SCHEMA,))
    con.execute("INSERT OR REPLACE INTO meta VALUES('text_format', ?)", (TEXT_FORMAT,))
    drop_stale_vectors(cfg, con)
    cards = load_cards(cfg["cards_dir"])
    known = {r["code"]: (r["text_sha"], r["card_sha"]) for r in con.execute("SELECT code, text_sha, card_sha FROM docs")}
    # fragment numbers are never reused, so a Claude still holding the old state cannot mix up fragments
    next_id = (
        max(int(meta(con, "max_chunk_id", 0)), con.execute("SELECT coalesce(max(id), 0) FROM chunks").fetchone()[0]) + 1
    )
    docs = [row for code in sorted(cards) for row in doc_rows(*cards[code], cfg)]
    scores = read_ocr_scores(cfg.get("ocr_scores") or os.path.join(os.path.dirname(cfg["catalog"]), OCR_SCORES))
    changed, changed_codes, cards_read, pages_redone = 0, [], 0, 0
    # card-only edits (title, quality, issues) re-chunk no text but must still wake a running search server
    rows_sql = f"SELECT {', '.join(DOC_COLUMNS)} FROM docs"
    before = set(con.execute(rows_sql).fetchall())
    for info in docs:
        code, main = info["code"], info["parent"] or info["code"]
        old_text, old_card = known.get(code, (None, None))
        tf, raw, sha, pages, page_info = read_text(cfg["texts_dir"], code)
        st = text_stats(pages)
        f = info.pop("_file")
        info.pop("_lang")
        info.update(
            text_file=os.path.basename(tf) if tf else "",
            text_sha=sha,
            pages=len(pages),
            lang=info["lang"] or st["lang"].replace("+", ","),
            quality=quality_note(st, info["format"], hidden_line(f, code), scores.get(code)) if pages else NO_TEXT,
            issue=issue_line(cards[main][0]["file"], code, main),
            ocr_share=C.ocr_share(f.get("format")),
            ocr_score=scores.get(code) if pages else None,
        )
        con.execute(
            f"INSERT OR REPLACE INTO docs({','.join(DOC_COLUMNS)}) VALUES({','.join(':' + c for c in DOC_COLUMNS)})", info
        )
        if not info["parent"] and old_card != info["card_sha"]:  # a new or changed card: its fragments and contents
            cards_read += 1
            con.execute("DELETE FROM toc WHERE code=?", (code,))
            con.executemany("INSERT INTO toc VALUES(?,?,?,?,?,?)", toc_rows(cards[code][0], len(pages)))
            drop_doc_chunks(con, code, ("card", "card_q", "unit"))
            next_id = card_chunks(con, next_id, cards[code][0])
            con.execute("INSERT OR REPLACE INTO meta VALUES('max_chunk_id', ?)", (str(next_id - 1),))
            con.commit()
        if old_text == sha or (not pages and code not in known):  # unchanged, or a part with no text (drawings)
            continue
        next_id, redone = store_pages(con, next_id, code, pages, page_info)
        bookmap.store_given(con, code, read_outline(pages_path(tf)) if tf else [])
        con.execute("INSERT OR REPLACE INTO meta VALUES('max_chunk_id', ?)", (str(next_id - 1),))
        changed += 1
        changed_codes.append(code)
        pages_redone += redone
        con.commit()  # one document at a time: an interrupted build keeps what is done
        print(f"{code}: {len(pages)} pages" + (f", {redone} of them chunked again" if redone < len(pages) else ""))
    removed = set(known) - {d["code"] for d in docs}
    for code in removed:
        drop_doc_chunks(con, code)
        con.execute("DELETE FROM docs WHERE code=?", (code,))
        for t in ("outline", "objects", "toc", "pages", "given_outline"):
            con.execute(f"DELETE FROM {t} WHERE code=?", (code,))
        print(f"{code}: removed from the index")
    con.execute("DELETE FROM links")
    con.executemany("INSERT INTO links VALUES(?,?,?)", link_rows(cards))
    mapped = bookmap.update(con, changed_codes)  # all documents when the map is new or its version changed
    clear_index_stale(cfg, con)  # the base has read what an apply brought
    if changed or removed or mapped or cards_read or set(con.execute(rows_sql).fetchall()) != before:
        touch(con)
    con.commit()
    if a.full or changed >= 20:  # merge index segments after a big batch; small additions FTS5 merges by itself
        con.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('optimize')")
        con.commit()
    n = con.execute("SELECT count(*) FROM chunks").fetchone()[0]
    todo = con.execute("SELECT count(*) FROM chunks WHERE vec_row IS NULL").fetchone()[0]
    print(
        f"Done: documents {len(cards)} (and parts {len(docs) - len(cards)}), texts updated {changed}, cards read "
        f"{cards_read}, pages chunked again {pages_redone}, fragments {n}, without meaning vectors {todo}."
    )
    con.close()  # the old base may be deleted right below: no connection of this process may hold any base
    n_docs, n_open = catalog.write(Path(cfg["catalog"]).parent, profile=cfg, cards={c: v[0] for c, v in cards.items()})
    print(f"Catalog: {n_docs} documents; sources to update: {n_open} open items.")
    if a.full:
        if had_vectors(cfg, in_use):  # switching now would leave the search without meaning for an hour
            set_pointer(cfg["index_dir"], DB_NEXT, cfg["db"])
            drop_stale_dbs(cfg)  # an earlier full build that never got its vectors
            print("The new base waits for its meaning vectors: run assistant-x embed, the search moves to it when it ends.")
        else:
            switch_db(cfg, cfg["db"])
            print("The search now uses the new base.")
    elif cfg["db"] != in_use:
        print(
            f"The changes went into the new base {os.path.basename(cfg['db'])}, which waits for its vectors (assistant-x embed)."
        )


def had_vectors(cfg, db):
    """True when the base db has meaning vectors in a file that exists."""
    if not os.path.exists(db):
        return False
    con = connect(db, readonly=True)
    try:
        path = vectors_path(cfg, con)
        return bool(meta(con, "dim")) and os.path.exists(path) and os.path.getsize(path) > 0
    finally:
        con.close()


def drop_doc_chunks(con, code, kinds=None):
    """The fragments of a document (of these kinds only, when given) out of the base and the word index."""
    q = "SELECT id FROM chunks WHERE code=?" + (f" AND kind IN ({','.join('?' * len(kinds))})" if kinds else "")
    ids = [r[0] for r in con.execute(q, (code, *(kinds or ())))]
    con.executemany("DELETE FROM chunks_fts WHERE rowid=?", [(i,) for i in ids])
    con.executemany("DELETE FROM chunks WHERE id=?", [(i,) for i in ids])


if __name__ == "__main__":
    from assistant_x.core import debuglog

    debuglog.run(main, "build_index")
