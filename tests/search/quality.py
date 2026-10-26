# Assistant X вЂ” Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The quality stand of the search: the text documents of the golden corpus (tests/corpus/documents.py) as a library
of their own, every phrase the corpus expects on a page a control question for that page, asked in two forms and four
ways; hit@5 (the page among the first five results) and MRR (the reciprocal rank of the page in the first ten).

  forms   phrase вЂ” the phrase as it is; loose вЂ” its words of three letters or more, every other one of a long phrase,
          in reverse order (another order and fewer words: what the words alone find less well)
  modes   words (FTS5 only), meaning (dense_search alone), hybrid (words + meaning, RRF), rerank (hybrid + reranker)

The model is the fake one (tests/search/fake_embedder.py: a hashed bag of stems), so the numbers measure the
plumbing of the search (the fusion, the weights, the pool, the filters, the merging of a page), fast and the same on
every PC: a change that loses a page here broke something. What bge-m3 and the reranker do on real documents comes
from assistant-x eval --from-cards on a user's library (the questions of its cards), never from here.

tests/search/test_quality.py fails when a number falls below tests/search/quality_baseline.json; the baseline is
written on purpose:

    python -m tests.search.quality [--baseline]
"""

import json, os, re, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASELINE = HERE / "quality_baseline.json"
K, HIT = 10, 5
TOLERANCE = 0.001  # the stand is deterministic: any real drop counts
LETTER = {"standard": "N", "book": "L", "serial_issue": "J", "drawing": "E"}  # other genres: X
MODES = ("words", "meaning", "hybrid", "rerank")


def loose(phrase):
    words = re.findall(r"[^\W\d_]{3,}", phrase)
    return " ".join(reversed(words[::2] if len(words) > 4 else words))


def make_base(root, **search):
    """The corpus in root/corpus, its text PDFs as a library in root/lib (texts by PyMuPDF, a card each), built and
    embedded with the fake model; search: more [search] settings of assistant_x.toml. Returns (Library with the
    fakes, [(form, question, code, page)])."""
    import pymupdf
    from assistant_x.core import card as C
    from assistant_x.core.common import load_config
    from assistant_x.search import catalog
    from tests.corpus import documents
    from tests.search.conftest import build, card, write
    from tests.search.fake_embedder import embed, fake_library

    cases = documents.make(os.path.join(root, "corpus"))
    lib = os.path.join(root, "lib")
    idx = os.path.join(lib, "index")
    write(os.path.join(idx, "journal.md"), "# Journal (quality)\n")
    questions, n = [], {}
    for c in cases:
        if c["needs"] or not c["file"].endswith(".pdf"):
            continue  # scans and DOCX need OCR or LibreOffice: the intake corpus covers them
        src = os.path.join(root, "corpus", "library" if c["library"] else "inbox", c["file"])
        pages = [p.get_text() for p in pymupdf.open(src)]
        letter = LETTER.get(c["doc_type"], "X")
        n[letter] = n.get(letter, 100) + 1  # from 00101: the extras of the mini library's codes (conftest.MORE) stay out
        code = f"{letter}-{n[letter]:05d}"
        title = c["name"].replace("_", " ")
        doc = card(
            code,
            f"Corpus {title}",
            f"РљРѕСЂРїСѓСЃ {title}",
            c["doc_type"] or "other",
            "01_Corpus",
            c["file"],
            "pdf_text",
            len(pages),
        )
        # the contents: the headings the corpus expects, each at the first page that has it (the chapter boost)
        at = [(h, next((i + 1 for i, p in enumerate(pages) if h.lower() in p.lower()), None)) for h in c["headings"]]
        doc["doc"]["toc"] = [{"level": 1, "pdf_from": p, "title": {"ru": h}} for h, p in at if p]
        C.dump(doc, os.path.join(idx, "cards", f"{code}.json"))
        write(
            os.path.join(idx, "texts", f"{code}.md"),
            "".join(f"=== page {i + 1} ===\n\n{p.strip()}\n\n" for i, p in enumerate(pages)),
        )
        for page, phrases in c["phrases"].items():
            for ph in phrases:
                questions.append(("phrase", ph, code, page))
                if loose(ph) and loose(ph) != ph:
                    questions.append(("loose", loose(ph), code, page))
    catalog.write(idx, "2026-10-25", {"profile": "oil-gas-ru"})
    path = os.path.join(lib, "assistant_x.toml")
    more = "".join(f"{k} = {json.dumps(v)}\n" for k, v in search.items())
    write(
        path,
        'profile = "oil-gas-ru"\n\n[paths]\ndb = "search/db"\nmodels = "models"\n\n[search]\n'
        'embed_model = "models/bge-m3"\nrerank = false\ncommon_term_share = 1.0\n' + more,
    )
    build(path)
    embed(path)
    return fake_library(load_config(path)), questions


def ranks(lib, q, mode):
    """[(code, page)] of the results of one question in one mode."""
    if mode == "meaning":
        rows = {r[0]: (r[1], r[2]) for r in lib.con.execute("SELECT id, code, page FROM chunks")}
        return list(dict.fromkeys(rows[i] for i in lib.dense_search(q, n=K * 4)))[:K]
    res = lib.search(q, k=K, dense=mode != "words", rerank=mode == "rerank")
    return [(r["code"], r["page"]) for r in res]


def measure(lib, questions):
    """{"<mode> <form>": {"n", "hit5", "mrr"}} and the misses [(mode, form, question, code, page)]."""
    out, misses = {}, []
    for mode in MODES:
        for form in ("phrase", "loose"):
            got = []
            for f, q, code, page in questions:
                if f != form:
                    continue
                found = ranks(lib, q, mode)
                rank = next((i + 1 for i, x in enumerate(found) if x == (code, page)), None)
                got.append(rank)
                if not rank or rank > HIT:
                    misses.append((mode, form, q, code, page))
            n = len(got) or 1
            out[f"{mode} {form}"] = dict(
                n=len(got),
                hit5=round(sum(bool(r and r <= HIT) for r in got) / n, 3),
                mrr=round(sum(1 / r for r in got if r) / n, 3),
            )
    return out, misses


def below(now, base):
    """[(key, metric, now, baseline)] of the numbers below the baseline."""
    return [
        (key, m, now.get(key, {}).get(m), v)
        for key, ms in (base or {}).items()
        for m, v in ms.items()
        if m != "n" and (now.get(key, {}).get(m) is None or now[key][m] < v - TOLERANCE)
    ]


def table(res):
    lines = [f"{'mode form':16} {'n':>3} {'hit@5':>6} {'MRR':>6}"]
    lines += [f"{key:16} {m['n']:>3} {m['hit5']:>6.3f} {m['mrr']:>6.3f}" for key, m in res.items()]
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    from tests.corpus.report import cleanup, isolate

    root = isolate()
    try:
        lib, qs = make_base(tempfile.mkdtemp(dir=root))
        res, misses = measure(lib, qs)
        del lib
    finally:
        cleanup(root, keep="--keep" in argv)
    sys.stdout.reconfigure(encoding="utf-8")
    print(table(res))
    for m in misses if "-v" in argv else ():
        print("MISS", *m)
    if "--baseline" in argv:
        BASELINE.write_text(json.dumps(res, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print(f"baseline written to {BASELINE}")
    else:
        low = below(res, json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {})
        print("Below the baseline: " + ("; ".join(f"{k} {m} {v} < {b}" for k, m, v, b in low) if low else "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
