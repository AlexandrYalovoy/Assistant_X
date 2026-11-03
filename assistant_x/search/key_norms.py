# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The key norms of the library: for the typical design topics of a profile (key_topics.json: the words of a
question, the searches, what a page must show), the pages of the norms that answer them, verified on their text, in
the order of the hierarchy of documents. search_library puts the key norms of the topic of a question first: the
governing standard of a design question is found even when its table is far from the words of the question by
meaning (the velocity table of GOST R 58367 for "how to choose the diameter of a gas pipeline").

    assistant-x key-norms --refresh  build index/key_norms.json of the workspace anew (searches, verifies, writes)
    assistant-x key-norms --show     the topics and their pages

After every build of the search base (an intake applied, a base package installed or updated, documents taken out)
update() brings the list up to date without a search: the entries of documents gone or changed are dropped, the pages
of new or changed norms are verified against every topic by the same rule; "seen" keeps the sha of the card of every
norm verified. New topics are a deliberate step (key_topics.json of the profile), never automatic.

index/key_norms.json is library data: a base package carries it (its codes remapped on install).
Every entry was verified: its page has the words of the topic and a value (a number with its unit, a table row);
its evidence is the quote of the page. The others are dropped and counted."""

import argparse, datetime, json, os, re, sys

from assistant_x.server import quotes

FILE = "key_norms.json"
PER_TOPIC = 5  # verified pages kept for a topic
PER_DOC = 2  # of one document
MAX_LEVEL = 8  # the organization standards and higher: methodical documents and books are not key norms
FIRST = 4  # key norm pages put first in an answer
CANDIDATES = 20  # pages of shelf N looked at per search of a topic


def topics_of(cfg):
    """The topics of the profile of the workspace ([] when the profile has none)."""
    from assistant_x.core import config

    p = config.profile_file("key_topics.json", {"profile": cfg.get("profile")})
    return json.loads(p.read_text(encoding="utf-8"))["topics"] if p else []


def path_of(cfg):
    return os.path.join(os.path.dirname(cfg["catalog"]), FILE)


def words(text):
    """The words of a text in lower case, the Cyrillic yo read as ye (the stems of the topics are written without it)."""
    return quotes.WORD.findall((text or "").lower().replace(chr(0x451), chr(0x435)))


def has(groups, ws):
    """Does every group have a stem that starts one of the words ws?"""
    return all(any(any(w.startswith(s) for w in ws) for s in g) for g in groups)


def evidence(topic, text):
    """The quote of a page that proves the topic: the sentence or table row with a value (topic["value"]) and the most
    words of the topic's searches; "" when the page shows no value or lacks the words of the topic."""
    ws = words(text)
    if not has(topic["verify"], ws) or not has(topic["ask"], ws):  # the object of the topic too, not only its value
        return ""
    value = re.compile(topic["value"], re.I)
    want = quotes.stems(" ".join(topic["queries"]))
    best, score = "", -1.0
    for kind, unit, header in quotes.units(text):
        if not value.search(unit):
            continue
        full = f"{header}: {unit}" if kind == "row" and header else unit
        if not has(topic["verify"], words(full)):  # the value must be of the topic, not one elsewhere on the page
            continue
        sc = len(quotes.found(want, full)) + (0.5 if kind == "row" else 0)
        if sc > score:
            best, score = full, sc
    return quotes.cut(best, quotes.QUOTE_CHARS) if score > 0 else ""


def build(lib, topics, say=print):
    """{topics: [{id, name, ask, entries: [{code, designation, title, level, pdf_page, quote}]}], verified, dropped}.
    The norms of a supplement jurisdiction (American, European… of the profile) are no key norms: the key norms are
    the ones that govern."""
    from assistant_x.search import jurisdiction

    jur = jurisdiction.load(lib.cfg.get("profile"))
    out, verified, dropped = [], 0, 0
    for t in topics:
        seen, entries, per_doc = set(), [], {}
        for q in t["queries"]:
            for r in lib.search(q, k=CANDIDATES, sections=["N"]):
                at = (r["code"], r["page"])
                if at in seen or r.get("kind") == "card" or (r.get("level") or 99) > MAX_LEVEL:
                    continue
                if jur and jur.of(r) in jur.extra:
                    continue
                seen.add(at)
                row = lib.con.execute("SELECT text FROM pages WHERE code=? AND page=?", at).fetchone()
                quote = evidence(t, row[0] if row else "")
                if not quote:
                    dropped += 1
                    continue
                verified += 1
                if per_doc.get(r["code"], 0) >= PER_DOC:
                    continue
                per_doc[r["code"]] = per_doc.get(r["code"], 0) + 1
                doc = lib.con.execute("SELECT designation, title FROM docs WHERE code=?", (r["code"],)).fetchone()
                entries.append(
                    dict(
                        code=r["code"],
                        designation=(doc[0] or "").split(" / ")[-1] if doc else "",
                        title=doc[1] if doc else r.get("title", ""),
                        level=r.get("level"),
                        pdf_page=r["page"],
                        quote=quote,
                    )
                )
        entries.sort(key=lambda e: e["level"] if e["level"] is not None else 99)  # stable: the search order in a level
        out.append(dict(id=t["id"], name=t["name"], ask=t["ask"], entries=entries[:PER_TOPIC]))
        say(f"{t['id']}: {len(entries[:PER_TOPIC])} pages ({', '.join(e['code'] for e in entries[:PER_TOPIC])})")
    seen = {c: s or "" for c, s in lib.con.execute("SELECT code, card_sha FROM docs WHERE code LIKE 'N-%'")}
    return dict(
        version=1,
        built=datetime.date.today().isoformat(),
        topics=out,
        verified=verified,
        dropped=dropped,
        seen=seen,
    )


def update(cfg, db=None, say=print):
    """The key norms after a build of the search base, without a search: (added, dropped), or None when the library
    has no key norms or its profile no topics. The entries of documents no longer in the base, or whose card changed
    (a new edition under its code, a card corrected), are dropped; the pages of the norms not seen yet (new or changed)
    are verified against every topic (evidence: the words of the topic and its value in one line), the best page of a
    document for a topic kept; a topic keeps PER_TOPIC pages, the highest level first. A list built before "seen"
    existed takes the norms of the base as seen (assistant-x key-norms --refresh verifies them all)."""
    from assistant_x.core import config, hierarchy
    from assistant_x.core.common import connect
    from assistant_x.search import jurisdiction

    data, topics = read(path_of(cfg)), topics_of(cfg)
    if not data or not topics:
        return None
    con = connect(db or cfg["db"], readonly=True)
    try:
        docs = {
            r[0]: r
            for r in con.execute(
                "SELECT code, card_sha, designation, title, json_extract(card, '$.doc.jurisdiction') FROM docs "
                "WHERE code LIKE 'N-%'"
            )
        }
        seen = data.get("seen")
        if seen is None:
            seen = {c: r[1] or "" for c, r in docs.items()}
        gone = {c for c in seen if c not in docs or (docs[c][1] or "") != seen[c]}
        fresh = [c for c, r in docs.items() if seen.get(c) != (r[1] or "") or c in gone]
        prof = config.profile_dir(cfg.get("profile")) if cfg.get("profile") else None
        hier = hierarchy.load(cfg.get("workspace"), prof)
        jur = jurisdiction.load(cfg.get("profile"))
        dropped = 0
        for t in data.get("topics", []):
            keep = [e for e in t.get("entries", []) if e["code"] in docs and e["code"] not in gone]
            dropped += len(t.get("entries", [])) - len(keep)
            t["entries"] = keep
        added = 0
        by_id = {t["id"]: t for t in data.get("topics", [])}
        for code in fresh:
            _, sha, designation, title, field = docs[code]
            level = hier.rank(designation, title, code)
            row = {"designation": designation, "title": title, "jurisdiction": field or ""}
            if level > MAX_LEVEL or (jur and jur.of(row) in jur.extra):
                seen[code] = sha or ""
                continue
            pages = [(p, t, words(t)) for p, t in con.execute("SELECT page, text FROM pages WHERE code=?", (code,))]
            for topic in topics:
                best = None
                for page, text, ws in pages:
                    if not (has(topic["verify"], ws) and has(topic["ask"], ws)):
                        continue
                    quote = evidence(topic, text)
                    score = len(quotes.found(quotes.stems(" ".join(topic["queries"])), quote)) if quote else 0
                    if quote and (best is None or score > best[0]):
                        best = (score, page, quote)
                if not best:
                    continue
                t = by_id.setdefault(topic["id"], dict(id=topic["id"], name=topic["name"], ask=topic["ask"], entries=[]))
                if not any(e["code"] == code for e in t["entries"]):
                    t["entries"].append(
                        dict(
                            code=code,
                            designation=(designation or "").split(" / ")[-1],
                            title=title,
                            level=level,
                            pdf_page=best[1],
                            quote=best[2],
                        )
                    )
                    added += 1
            seen[code] = sha or ""
        for c in [c for c in seen if c not in docs]:
            del seen[c]
        for t in by_id.values():
            t["entries"] = sorted(t["entries"], key=lambda e: e["level"] if e.get("level") is not None else 99)
            t["entries"] = t["entries"][:PER_TOPIC]
        data["topics"], data["seen"] = list(by_id.values()), seen
    finally:
        con.close()
    write(path_of(cfg), data)
    say(f"Key norms: +{added}, -{dropped} (assistant-x key-norms --show lists them).")
    return added, dropped


def check(cfg, con):
    """[warnings] of index/key_norms.json against the base: a code not in it, a page it lacks, a quote no longer on
    its page; [] when the library has no key norms."""
    data = read(path_of(cfg))
    if not data:
        return []
    out = []
    for t in data.get("topics", []):
        for e in t.get("entries", []):
            row = con.execute("SELECT text FROM pages WHERE code=? AND page=?", (e["code"], e["pdf_page"])).fetchone()
            if row is None:
                out.append(f"key norms, {t['id']}: {e['code']} PDF {e['pdf_page']} is not in the base")
            elif not has(t.get("ask") or [], words(row[0])):
                out.append(f"key norms, {t['id']}: {e['code']} PDF {e['pdf_page']} no longer has the words of the topic")
    return out


_cache = {}


def load(cfg):
    """The key norms of the workspace ({} when none), read again when the file changes."""
    p = path_of(cfg)
    try:
        st = os.stat(p)
        stamp = (st.st_mtime_ns, st.st_size)  # two writes within one tick of the clock differ by their size
    except OSError:
        return {}
    if _cache.get(p, (None,))[0] != stamp:
        try:
            _cache[p] = (stamp, json.loads(open(p, encoding="utf-8").read()))
        except (OSError, ValueError):
            _cache[p] = (stamp, {})
    return _cache[p][1]


def asks(groups, ws):
    """Is a question of a topic: every group of its 'ask' in the words ws, or, for a topic of three groups or more,
    all but the last (the object or the place: a pipeline, a site) — a small model rewords the question of the user
    and drops that word; what is asked and of what medium (a velocity of gas, not of oil) must stay."""
    hit = [any(any(w.startswith(s) for w in ws) for s in g) for g in groups]
    return all(hit) or (len(groups) >= 3 and all(hit[:-1]))


def match(data, query):
    """The topics of the key norms a question is about (asks)."""
    ws = words(query)
    return [t for t in (data or {}).get("topics", []) if t.get("entries") and asks(t["ask"], ws)]


def entries_for(data, query, n=FIRST):
    """The key norm pages of the topics of a question, the highest level first, n at most, no page twice."""
    got, seen = [], set()
    for t in match(data, query):
        for e in t["entries"]:
            if (e["code"], e["pdf_page"]) not in seen:
                seen.add((e["code"], e["pdf_page"]))
                got.append(e)
    got.sort(key=lambda e: e["level"] if e.get("level") is not None else 99)
    return got[:n]


def read(path):
    try:
        return json.loads(open(path, encoding="utf-8").read())
    except (OSError, ValueError):
        return None


def write(path, data):
    path = str(path)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)


def merge(own, other, skip=()):
    """The key norms of a library and of a package together: a topic of both keeps the pages of both (no page twice,
    the highest level first, PER_TOPIC * 2 at most); skip: codes of the package not installed."""
    topics = {t["id"]: dict(t, entries=list(t.get("entries", []))) for t in own.get("topics", [])}
    for t in other.get("topics", []):
        es = [e for e in t.get("entries", []) if e["code"] not in skip]
        if t["id"] not in topics:
            topics[t["id"]] = dict(t, entries=[])
        have = {(e["code"], e["pdf_page"]) for e in topics[t["id"]]["entries"]}
        topics[t["id"]]["entries"] += [e for e in es if (e["code"], e["pdf_page"]) not in have]
    for t in topics.values():
        t["entries"] = sorted(t["entries"], key=lambda e: e["level"] if e.get("level") is not None else 99)
        t["entries"] = t["entries"][: PER_TOPIC * 2]
    return dict(other or own, topics=list(topics.values()))


def remap(data, codes):
    """The key norms with the codes renamed by an install ({old: new}); merge() leaves out the ones not installed."""
    out = dict(data, topics=[])
    for t in data.get("topics", []):
        es = [dict(e, code=codes.get(e["code"], e["code"])) for e in t.get("entries", [])]
        out["topics"].append(dict(t, entries=es))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="assistant-x key-norms", description=__doc__.split("\n\n")[0])
    ap.add_argument("--show", action="store_true", help="the topics and their pages")
    ap.add_argument("--refresh", action="store_true", help="build the list anew (the default)")
    a = ap.parse_args(argv)
    from assistant_x.core.common import load_config
    from assistant_x.search.retrieval import Library

    cfg = load_config()
    if a.show:
        data = load(cfg)
        for t in data.get("topics", []):
            print(f"{t['id']}: " + "; ".join(f"{e['code']} p.{e['pdf_page']}" for e in t["entries"]))
        return 0
    topics = topics_of(cfg)
    if not topics:
        print("The profile of this workspace has no key topics (key_topics.json).")
        return 0
    lib = Library(cfg)
    lib.warm_up()
    data = build(lib, topics)
    p = path_of(cfg)
    write(p, data)
    n = sum(len(t["entries"]) for t in data["topics"])
    print(f"Written {p}: {len(data['topics'])} topics, {n} pages ({data['verified']} verified, {data['dropped']} dropped).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
