# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Map of each document in the base: its outline (numbered sections and chapters with pages), where its tables, figures,
formulas and appendices are, and so where a reference like "see table 4.2" or "see 5.3" in a fragment leads. The
captions and reference words come from the language packs (lang/<code>/references.json).
build_index.py fills it, search.py adds the pages a found fragment refers to, mcp_server.py shows it as book_map.
Usage: python -m assistant_x.search.bookmap L-00015 [--page 300] [--config assistant_x.toml]"""

import argparse, re, sqlite3

from assistant_x.core import lang
from assistant_x.core.common import load_config, connect, meta

# the map itself is made from the text by core/textmap.py (the intake drafts the contents of a card with it too)
from assistant_x.core.textmap import (  # noqa: F401 — their former home: the names stay importable from here
    DEF_RX,  # noqa: F401
    NUM,
    _first,  # noqa: F401
    _toc_lines,  # noqa: F401
    build,
    formula_number,  # noqa: F401
    has_formula,  # noqa: F401
    norm,
    toc_entries,  # noqa: F401
    toc_pages,  # noqa: F401
)

BOOKMAP_VERSION = "3"  # 2-3: outlines of texts without numbered Markdown headings (contents page, plain lines)

SCHEMA = """
CREATE TABLE IF NOT EXISTS outline(code TEXT, num TEXT, title TEXT, page INTEGER, page_end INTEGER, level INTEGER);
CREATE INDEX IF NOT EXISTS outline_doc ON outline(code, page);
CREATE TABLE IF NOT EXISTS objects(code TEXT, kind TEXT, num TEXT, page INTEGER);
CREATE INDEX IF NOT EXISTS objects_doc ON objects(code, kind, num);
CREATE TABLE IF NOT EXISTS given_outline(code TEXT, level INTEGER, title TEXT, page INTEGER);
CREATE INDEX IF NOT EXISTS given_outline_doc ON given_outline(code);
"""

# references in running text: "see table 4.2", "fig. 3-1", "formula (12)", "equation (5.3)", "appendix B", "cl. 5.3"
REF_RX = re.compile(rf"(?P<k>{lang.alt('ref_words')})\s*№?\s*\(?\s*" + NUM + r"\s*\)?", re.I)
REF_KINDS = [(w, k) for w, k in lang.words("ref_kinds")]  # the start of a reference word -> its kind


def ref_kind(word):
    w = word.lower()
    for start, kind in REF_KINDS:
        if w.startswith(start):
            return kind
    return "s"  # a clause, a section, a subsection


def store_given(con, code, given):
    """The outline the file of a document gives itself ([[level, title, page or None]], its .pages.json)."""
    con.execute("DELETE FROM given_outline WHERE code=?", (code,))
    con.executemany("INSERT INTO given_outline VALUES(?,?,?,?)", [(code, *x) for x in given or []])


def store(con, code, pages):
    con.execute("DELETE FROM outline WHERE code=?", (code,))
    con.execute("DELETE FROM objects WHERE code=?", (code,))
    given = [
        (r[0], r[1], r[2])
        for r in con.execute("SELECT level, title, page FROM given_outline WHERE code=? ORDER BY rowid", (code,))
    ]
    outline, objects = build(pages, given)  # the outline of the file (its .pages.json) first
    con.executemany("INSERT INTO outline VALUES(?,?,?,?,?,?)", [(code, *o) for o in outline])
    con.executemany("INSERT INTO objects VALUES(?,?,?,?)", [(code, k, n, p) for (k, n), p in objects.items()])


def pages_from_base(con, code):
    """The pages of a document as the base holds them (the table pages), so maps can be made for all documents
    without reading the text files again."""
    return [(r[0], r[1]) for r in con.execute("SELECT page, text FROM pages WHERE code=? ORDER BY page", (code,))]


def update(con, codes=None):
    """Maps for the documents in codes, or for all of them when the map version changed (first run included)."""
    con.executescript(SCHEMA)
    if meta(con, "bookmap_version") != BOOKMAP_VERSION:
        codes = [r[0] for r in con.execute("SELECT code FROM docs")]
    for code in codes or []:
        store(con, code, pages_from_base(con, code))
    con.execute("INSERT OR REPLACE INTO meta VALUES('bookmap_version', ?)", (BOOKMAP_VERSION,))
    con.commit()
    return len(codes or [])


class Maps:
    """Lookups over the maps for search.py; tables missing (base built before maps): everything is empty."""

    def __init__(self, con):
        """con: a connection, or a function returning the connection of the calling thread (search.Library)."""
        self._con = con
        self.ok = bool(self.con.execute("SELECT 1 FROM sqlite_master WHERE name='objects'").fetchone())

    @property
    def con(self):
        # a connection object is callable too, so its type is checked rather than callable()
        return self._con if isinstance(self._con, sqlite3.Connection) else self._con()

    def section_at(self, code, page):
        """Deepest numbered section that covers the page."""
        if not self.ok:
            return None
        r = self.con.execute(
            "SELECT num, title, page, page_end FROM outline WHERE code=? AND page<=? AND page_end>=? "
            "ORDER BY level DESC, page DESC LIMIT 1",
            (code, page, page),
        ).fetchone()
        return dict(r) if r else None

    def targets(self, code, page, text, limit=6):
        """[(label, page)] that the references in text lead to, other than the page itself."""
        if not self.ok:
            return []
        out, seen = [], set()
        for m in REF_RX.finditer(text):
            kind, num = ref_kind(m.group("k")), norm(m.group(2))
            if (kind, num) in seen:
                continue
            seen.add((kind, num))
            if kind in ("s", "c"):
                r = self.con.execute(
                    "SELECT page FROM outline WHERE code=? AND num=? ORDER BY page LIMIT 1", (code, num)
                ).fetchone()
            else:
                r = self.con.execute(
                    "SELECT page FROM objects WHERE code=? AND kind=? AND num=?", (code, kind, num)
                ).fetchone()
            if r and abs(r[0] - page) >= 1:
                out.append((m.group(0).strip(), r[0]))
                if len(out) >= limit:
                    break
        return out

    def outline(self, code, page=None, around=40):
        """Outline rows of a document; with page, only the part of the book near it (a big book has hundreds)."""
        if not self.ok:
            return []
        rows = [
            dict(r)
            for r in self.con.execute(
                "SELECT num, title, page, page_end, level FROM outline WHERE code=? ORDER BY page, level", (code,)
            )
        ]
        if page is not None and len(rows) > 2 * around:
            i = next((j for j, r in enumerate(rows) if r["page"] > page), len(rows))
            rows = [r for r in rows if r["level"] <= 1] + rows[max(0, i - around // 2) : i + around // 2]
            rows = sorted(
                {(r["page"], r["level"], r["num"]): r for r in rows}.values(), key=lambda r: (r["page"], r["level"])
            )
        return rows

    def objects(self, code, start=None, end=None):
        if not self.ok:
            return []
        q, args = "SELECT kind, num, page FROM objects WHERE code=?", [code]
        if start is not None:
            q += " AND page BETWEEN ? AND ?"
            args += [start, end]
        return [dict(r) for r in self.con.execute(q + " ORDER BY page", args)]


KIND_NAME = {"t": "table", "r": "fig.", "f": "formula", "a": "app."}


def render(maps, code, page=None):
    rows = maps.outline(code, page)
    if not rows:
        return f"No map for {code}: no numbered sections were found in the text."
    lines = [f"Map of {code}: section — PDF pages"]
    for r in rows:
        pad = "  " * max(0, r["level"] - 1)
        mark = " ◀" if page is not None and r["page"] <= page <= r["page_end"] and r["level"] > 0 else ""
        lines.append(f"{pad}{r['title']} — {r['page']}" + (f"–{r['page_end']}" if r["page_end"] > r["page"] else "") + mark)
    if page is not None:
        sec = maps.section_at(code, page)
        lo, hi = (sec["page"], sec["page_end"]) if sec else (page - 5, page + 5)
        objs = maps.objects(code, lo, hi)
        if objs:
            lines.append(
                f"\nIn this section (PDF {lo}–{hi}): "
                + "; ".join(f"{KIND_NAME[o['kind']]} {o['num']} — {o['page']}" for o in objs[:40])
            )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("--page", type=int)
    ap.add_argument("--config")
    a = ap.parse_args()
    con = connect(load_config(a.config)["db"], readonly=True)
    print(render(Maps(con), a.code.upper(), a.page))


if __name__ == "__main__":
    from assistant_x.core import debuglog

    debuglog.run(main, "bookmap")
