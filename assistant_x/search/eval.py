# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check search quality on control questions of your own library: share of questions whose right document and page
are in the top results, mean reciprocal rank of the page, share of all answer places found, search time; overall and
by group (a «## …» heading of a questions file starts a group), and the share of questions whose quoted phrase is on
an answer page of the top results. The questions are yours: write questions.md (a table "| question | code:pages; … |"
or "| question | code:pages | "exact phrase" |", see parse) — the repository holds none.
Usage: assistant-x eval [--config assistant_x.toml] [--k 10] [--questions questions.md ...] [--from-cards] [--no-dense] [--rerank | --no-rerank]
                      [--fast] [--check] [--save] [--diff [--ref-db BASE]] [-v]
--fast: words only (no model, about 10 s), for the pre-commit hook; --check compares the result with the saved one
(eval_baseline.json) and fails when it got worse; --save stores the result as the new reference, with the rank and
the top results of every question; --diff lists the questions that got worse against the saved ranks (or against
the same questions asked of another base, --ref-db) and what now stands in the top in place of the right answer:
a document the reference base did not have [new], a result with the same text as another one [dup].
--from-cards: control questions without writing any: the questions of every card of the base (doc.questions, written
by the intake for what the document answers) and the titles of the units of a journal issue, each in every language
of the card; the right answer is any page of that document (code:*). The card itself, and the unit for its own
title, would answer word for word: their results are dropped before the scoring (no leakage), so the page of the
text has to be found. Groups: "cards: en", "units: ru"... by the language of the question. With questions.md the two
sets run together. This is how a user measures the real model on a real library (a hundred cards or more)."""

import argparse, json, os, re, sys, time
from assistant_x.core import gpu_guard
from assistant_x.core.common import load_config, skeleton, langs_of
from assistant_x.search.retrieval import Library

from assistant_x.core import lang, workspace


QUESTIONS = ["questions.md"]  # your own control questions, in the workspace (never in the repository)
BASELINE = None  # the baseline of the workspace in use (baseline_path), unless set


def baseline_path():
    return BASELINE or str(workspace.current().root / "eval_baseline.json")


TOLERANCE = 0.02  # --check: a drop of a metric by more than this fails
# a code letter may be typed in Cyrillic
CODE_RX = re.compile(rf"([{lang.chars('upper_basic')}])-0*(\d+)(-\d+)?")
ITEM_RX = re.compile(rf"([{lang.chars('upper_basic')}]-\d+(?:-\d+)?):(\*|\d+(?:-\d+)?)")
PHRASE_RX = re.compile(r'["«“](.+)["»”]')  # the third cell of a question: an exact phrase of the answer page


def norm(code):
    m = CODE_RX.match(code.strip().upper())  # E-00006-02: part 02 of E-00006
    return f"{m.group(1)}-{m.group(2)}{m.group(3) or ''}" if m else code.strip().upper()


def parse(path):
    """[(group, question, [(code, first page, last page)], phrase)]; the group is the last «## » heading, else the «# »
    title; phrase: the text in quotes of the optional third cell ("" when there is none)."""
    qs, group = [], ""
    for line in open(path, encoding="utf-8"):
        if line.startswith("#"):
            level, title = len(line) - len(line.lstrip("#")), line.strip("# \n")
            if level == 2 or not group:
                group = title
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        items = [ITEM_RX.fullmatch(i.strip()) for i in cells[1].split(";")] if len(cells) > 1 else [None]
        phrase = PHRASE_RX.fullmatch(cells[2]) if len(cells) == 3 else None
        if not line.startswith("|") or len(cells) not in (2, 3) or not all(items) or (len(cells) == 3 and not phrase):
            continue
        want = []
        for m in items:
            code, pages = m.groups()
            if pages.strip() == "*":
                want.append((norm(code), 0, 10**6))
            else:
                a, _, b = pages.partition("-")
                want.append((norm(code), int(a), int(b or a)))
        qs.append((group, cells[0], want, phrase.group(1).strip() if phrase else ""))
    return qs


CARD_KINDS = ("card", "card_q")  # the fragments of a card (search/build_index.card_chunks)


def card_questions(lib):
    """[(group, question, want, "", drop)] from the cards of the base of lib: drop = (code, kinds) whose results are
    not scored (the card answering its own question)."""
    out = []
    for r in lib.con.execute("SELECT code, card FROM docs WHERE coalesce(parent, '') = '' ORDER BY code"):
        try:
            doc = json.loads(r["card"] or "{}").get("doc") or {}
        except ValueError:
            continue
        want = [(norm(r["code"]), 0, 10**6)]
        for q in doc.get("questions") or []:
            if q.strip():
                out.append((f"cards: {langs_of(q, 1) or '?'}", q.strip(), want, "", (r["code"], CARD_KINDS)))
        for u in doc.get("units") or []:
            title = u.get("title")
            pairs = title.items() if isinstance(title, dict) else [(langs_of(title or "", 1), title)]
            for code, t in pairs:
                if (t or "").strip():
                    out.append((f"units: {code or '?'}", t.strip(), want, "", (r["code"], CARD_KINDS + ("unit",))))
    return out


def score(res, want):
    """(document found, rank of the first right page or None, answer places found) for one question."""
    got = [(norm(r["code"]), r["page"]) for r in res]
    # pages the result points to besides itself (e.g. referenced tables) also count as found
    seen = got + [(norm(r["code"]), pg) for r in res for pg in r.get("related_pages", [])]
    d = any(c == w[0] for c, _ in got for w in want)
    p = next((i + 1 for i, (c, pg) in enumerate(got) for w in want if c == w[0] and w[1] <= pg <= w[2]), None)
    found = sum(any(c == w[0] and w[1] <= pg <= w[2] for c, pg in seen) for w in want)
    return d, p, found


def same_phrase(text):
    """The comparison form of a phrase and of a page: its skeleton (common.skeleton: lower case, the folding of the
    languages and of look-alike letters, dashes, quotes, Markdown marks, spaces)."""
    return skeleton(text)


def quote_found(lib, res, want, phrase):
    """None without a phrase; else True when the phrase is on an answer page among the results (a card is no page)."""
    if not phrase:
        return None
    pages = {
        (r["code"], r["page"])
        for r in res
        if r.get("kind") != "card" and any(norm(r["code"]) == c and a <= r["page"] <= b for c, a, b in want)
    }
    goal = same_phrase(phrase)
    return any(goal in same_phrase(lib.pages(code, page, page)) for code, page in sorted(pages))


def summary(rows):
    """rows: [(doc, rank, found, places, quote)] -> metrics as shares; quote: the share of the questions with a phrase
    whose phrase is on an answer page of the results (None when no question of the rows has a phrase)."""
    n = len(rows) or 1
    quoted = [r[4] for r in rows if r[4] is not None]
    return dict(
        n=len(rows),
        doc=sum(r[0] for r in rows) / n,
        page=sum(bool(r[1]) for r in rows) / n,
        mrr=sum(1 / r[1] for r in rows if r[1]) / n,
        places=sum(r[2] for r in rows) / (sum(r[3] for r in rows) or 1),
        all_places=sum(r[2] == r[3] for r in rows) / n,
        quotes=len(quoted),
        quote=sum(quoted) / len(quoted) if quoted else None,
    )


def run(lib, qs, k=10, dense=None, rerank=None, verbose=False, out=print, per_question=None):
    """Ask every question; returns {group: metrics, '': all} and the times in seconds.
    per_question: a dict to receive {question: {'rank': rank of the right page or None, 'top': ['code:page', …]}}."""
    rows, times = {}, []
    for group, q, want, phrase, *more in qs:
        drop = more[0] if more else None  # (code, kinds): a card question, its own card is no answer
        st = {}
        t0 = time.perf_counter()
        res = lib.search(q, k=k + (3 if drop else 0), dense=dense, rerank=rerank, stats=st)
        times.append(time.perf_counter() - t0)
        if drop:
            res = [r for r in res if not (r["code"] == drop[0] and r.get("kind") in drop[1])][:k]
        d, p, found = score(res, want)
        quote = quote_found(lib, res, want, phrase)
        rows.setdefault(group, []).append((d, p, found, len(want), quote))
        if per_question is not None:
            per_question[q] = {
                "rank": p,
                "top": [f"{r['code']}:{r['page']}" for r in res],
                "text": [r["text"][:300] for r in res],
            }
        if verbose or not p:
            close = f", closeness {st['dense_top']:.2f}" if st.get("dense_top") is not None else ""
            top = ", ".join(f"{r['code']}:{r['page']}" for r in res[:6])
            out(
                f"{'OK ' if p else 'MISS'} {'#' + str(p) if p else '  '} {q}  (by words {st.get('words', 0)}{close})\n"
                f"      found: {top}" + ("\n      the phrase is not on an answer page" if quote is False else "")
            )
    res = {g: summary(r) for g, r in rows.items()}
    res[""] = summary([x for r in rows.values() for x in r])
    return res, times


def table(res, k):
    head = f"| Group | Questions | Document in top-{k} | Page in top-{k} | MRR | Places | All places | Quotes |"
    lines = [head, "|---|---|---|---|---|---|---|---|"]
    for g, m in sorted(res.items(), key=lambda x: x[0] == ""):
        quote = f"{m['quote']:.0%} of {m['quotes']}" if m.get("quote") is not None else "—"
        lines.append(
            f"| {g or 'Total'} | {m['n']} | {m['doc']:.0%} | {m['page']:.0%} | {m['mrr']:.2f} | "
            f"{m['places']:.0%} | {m['all_places']:.0%} | {quote} |"
        )
    return "\n".join(lines)


def worse_questions(now, ref):
    """[(question, old rank, new rank)] of the questions whose right page fell or dropped out of the top."""
    out = []
    for q, r in now.items():
        old = (ref.get(q) or {}).get("rank")
        if old and (not r["rank"] or r["rank"] > old):
            out.append((q, old, r["rank"]))
    return out


def same_text(a, b):
    """Two results with the same beginning of text: a second copy of one document."""
    wa, wb = set(re.findall(r"\w{4,}", a.lower())), set(re.findall(r"\w{4,}", b.lower()))
    return len(wa) >= 8 and len(wa & wb) >= 0.8 * min(len(wa), len(wb))


def diff_report(lib, qs, now, ref, known=None, out=print):
    """What stands above the right answer in each question that got worse. known: codes of the reference base
    (a code outside it is a new document)."""
    want = {q: w for _, q, w, *_ in qs}
    bad = worse_questions(now, ref)
    out(f"\nWorse than the reference: {len(bad)} questions of {len(now)}.")
    for q, old, new in bad:
        r = now[q]
        out(
            f"\n— {q}\n  key: {'; '.join(f'{c}:{a}-{b}' if b < 10**6 else f'{c}:*' for c, a, b in want.get(q, []))}"
            f"\n  place was {old}, now {new or 'out of the top'}; in the top before: {', '.join((ref[q].get('top') or [])[:old])}"
        )
        for i, (cp, text) in enumerate(zip(r["top"][: (new or len(r["top"])) - (1 if new else 0)], r["text"])):
            code = cp.split(":")[0]
            marks = []
            if known is not None and code.split("-")[0] + "-" + code.split("-")[1] not in known:
                marks.append("new")
            if any(same_text(text, t) for t in r["text"][:i]):
                marks.append("dup")
            title = (lib.doc(code) or {}).get("title", "")
            out(f"    {i + 1}. {cp} {'[' + ', '.join(marks) + '] ' if marks else ''}{title[:90]}")
    return bad


def worse(now, ref):
    """Metrics of the whole set that dropped by more than TOLERANCE against the reference."""
    return [
        f"{key}: {ref[key]:.3f} → {now[key]:.3f}"
        for key in ("page", "mrr", "places", "quote")
        if ref.get(key) is not None and now.get(key) is not None and now[key] < ref[key] - TOLERANCE
    ]


def main():
    ap = argparse.ArgumentParser(prog="assistant-x eval")
    ap.add_argument("--config")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--questions", nargs="*", default=QUESTIONS)
    ap.add_argument("--from-cards", action="store_true", help="the questions of the cards of the base as well")
    ap.add_argument("--no-dense", action="store_true")
    ap.add_argument("--rerank", action="store_true")
    ap.add_argument("--no-rerank", action="store_true")
    ap.add_argument("--fast", action="store_true", help="search by words only, without the model (about 10 s)")
    ap.add_argument("--check", action="store_true", help="compare with eval_baseline.json, exit code 1 when worse")
    ap.add_argument("--save", action="store_true", help="write the result into eval_baseline.json")
    ap.add_argument("--diff", action="store_true", help="questions worse than the reference, and what is in the top instead")
    ap.add_argument(
        "--ref-db", help="for --diff: the reference is the same questions to another base (e.g. a copy before an update)"
    )
    ap.add_argument("-v", action="store_true")
    gpu_guard.add_arguments(ap)
    a = ap.parse_args()
    t_start = time.perf_counter()
    cfg = load_config(a.config)
    files = [p if os.path.isabs(p) or os.path.exists(p) else str(workspace.current().root / p) for p in a.questions]
    files = [p for p in files if os.path.exists(p)]
    if not files and not a.from_cards:
        raise SystemExit(
            'No control questions: write questions.md in the workspace (rows "| question | L-00015:12-14; N-00001:3 |", '
            "an exact phrase of the answer page in quotes in a third cell if you like), give --questions FILE, "
            "or ask the questions of the cards: --from-cards."
        )
    qs = [q for p in files for q in parse(p)]
    lib = Library(cfg)  # no model is loaded yet: the device gpu_guard picks below goes into the same cfg
    if a.from_cards:
        qs += card_questions(lib)
        if not qs:
            raise SystemExit("The cards of the base have no questions (doc.questions) and no units.")
    dense = False if (a.fast or a.no_dense) else None
    rerank = False if (a.fast or a.no_rerank) else (a.rerank or None)
    if dense is not False or rerank:  # the models: one heavy task on the PC, room on the video card or an explicit --cpu
        gpu_guard.hold_machine("eval", wait=a.wait)
        # on a CPU: ~1 s per question by meaning, ~20 s with the reranker (an estimate)
        cfg["device"] = gpu_guard.check(
            cfg,
            "eval",
            units=len(qs) * (1 + (getattr(a, "ref_db", None) is not None)),
            unit="questions",
            cpu_s=20 if rerank else 1,
            wait=a.wait,
            cpu=a.cpu,
        )
    if qs and dense is not False:
        lib.search(qs[0][1], k=a.k)  # warm-up: model and vectors load once
    per_q = {}
    res, times = run(lib, qs, a.k, dense, rerank, a.v, per_question=per_q)
    mode = "fast" if a.fast else "full"
    from assistant_x.setup import download_models

    revs = download_models.revisions(cfg)  # the scores and the baselines hold for these revisions of the models
    print(
        f"\nMode: {'fast (words only)' if a.fast else 'full'}, k={a.k}. Models: "
        + ", ".join(f"{n} {r}" for n, r in revs.items())
        + ".\n"
        + table(res, a.k)
    )
    n = len(times) or 1
    print(
        f"Search time: mean {sum(times) / n * 1000:.0f} ms, max {max(times, default=0) * 1000:.0f} ms; "
        f"{time.perf_counter() - t_start:.1f} s in all."
    )
    key = f"{mode}_k{a.k}" + ("_cards" if a.from_cards else "")
    try:
        with open(baseline_path(), encoding="utf-8") as f:
            base = json.load(f)
    except (OSError, ValueError):
        base = {}
    if a.check:
        ref = base.get(key)
        if ref and mode == "full" and base.get(key + "_models") not in (None, revs):
            print(f"Note: the saved run was made with the models {base[key + '_models']}, this one with {revs}.")
        if not ref:
            print(f'Nothing to compare with: {os.path.basename(baseline_path())} has no run "{key}" (run with --save).')
        else:
            bad = worse(res[""], ref[""])
            if bad:
                print(
                    "The search got worse than the saved run: "
                    + "; ".join(bad)
                    + ". If that is intended, update the run: python eval.py "
                    + ("--fast " if a.fast else "")
                    + "--save"
                )
                sys.exit(1)
            print("Not worse than the saved run.")
    if a.diff:
        known = None
        if a.ref_db:
            ref_cfg = dict(cfg, db=os.path.abspath(a.ref_db), db_auto=False)  # the same device gpu_guard chose
            ref_lib = Library(ref_cfg)
            ref_q = {}
            run(ref_lib, qs, a.k, dense, rerank, out=lambda *_: None, per_question=ref_q)
            known = {r[0] for r in ref_lib.con.execute("SELECT code FROM docs")}
        else:
            ref_q = base.get(key + "_questions") or {}
            if not ref_q:
                print(
                    f'No answers per question in {os.path.basename(baseline_path())} (the run "{key}" was saved without them): '
                    "give --ref-db or save the run again (--save)."
                )
        if ref_q:
            diff_report(lib, qs, per_q, ref_q, known)
    if a.save:
        base[key + "_questions"] = {q: {"rank": r["rank"], "top": r["top"]} for q, r in per_q.items()}
        base[key] = res
        base[key + "_models"] = revs
        with open(baseline_path(), "w", encoding="utf-8") as f:
            json.dump(base, f, ensure_ascii=False, indent=1, sort_keys=True)
        print(f'Run "{key}" written to {os.path.basename(baseline_path())}.')


if __name__ == "__main__":
    from assistant_x.core import debuglog

    debuglog.run(main, "eval")
