# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The key norms of the library: for the typical design topics of a profile (key_topics.json: the words of a
question, the searches, what a page must show), the pages of the norms that answer them, verified on their text, in
the order of the hierarchy of documents. search_library puts the key norms of the topic of a question first: the
governing standard of a design question is found even when its table is far from the words of the question by
meaning (the velocity table of GOST R 58367 for "how to choose the diameter of a gas pipeline").

    assistant-x key-norms            build index/key_norms.json of the workspace (searches, verifies, writes)
    assistant-x key-norms --show     the topics and their pages

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
    return dict(
        version=1,
        built=datetime.date.today().isoformat(),
        topics=out,
        verified=verified,
        dropped=dropped,
    )


_cache = {}


def load(cfg):
    """The key norms of the workspace ({} when none), read again when the file changes."""
    p = path_of(cfg)
    try:
        stamp = os.path.getmtime(p)
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
