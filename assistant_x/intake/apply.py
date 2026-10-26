# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""Apply a built intake batch (<work>/out from build.py) to the project:
originals moved from inbox to library (duplicates to _duplicates, dropped to _rejected), PDF copies of
DOC/DOCX beside them, cards (JSON) and texts to index, CATALOG.md and sources_to_update.md made again from all the
cards (search/catalog.py), rows to intake_events.tsv and ocr_quality.tsv (the recognition score), then manifest.tsv
(manifest.py) and journal.md (core/journal.py), empty folders of inbox removed (the service folders stay). Checks
everything first; --dry-run only shows the plan.

The apply is a transaction with a journal (<work>/out/apply.journal.json): the checks pass first, then "started" is
written, then every step and every move is noted as it is done. An apply that was interrupted (the PC switched off,
an error) is continued with --resume: the moves already made and the steps already done are skipped, the catalog,
the events get no row twice. The catalog and the sources are made from the cards as a whole (a temporary file and
os.replace); missing index files are made first (core/index_files.py).

A new version (versions.json of the build): the original of a replaced document goes to inbox\_to_delete\replaced_<date>
with its card and text (index\cards, index\texts beside it), the new one takes its code; for two versions kept
both, the card of the old one gets the code of the new one in doc.other_versions.
Usage: assistant-x intake apply [--work DIR] [--dry-run | --resume]"""

import datetime, json, os, shutil
from pathlib import Path

from assistant_x.core import card as C
from assistant_x.core import index_files
from assistant_x.intake import config as intake_cfg
from assistant_x.core.formats import EVENT_ERROR, PAGES_SUFFIX
from assistant_x.core import journal
from assistant_x.core.txn import Journal, exists, move, write_whole  # noqa: F401 — apply.move and the others for the callers
from assistant_x.intake import manifest
from assistant_x.intake.state import State


def resolve(cfg, place):
    """'inbox\\a\\b.pdf' / 'library\\…' -> path under the configured folders."""
    head, _, rest = place.partition("\\")
    base = {"inbox": cfg.inbox, "library": cfg.library}.get(head)
    if base is None:
        raise ValueError(f"unknown folder in {place}")
    return base.joinpath(*[p for p in rest.split("\\") if p])


def write_views(cfg, date):
    """CATALOG.md and sources_to_update.md of the index made again from all its cards."""
    from assistant_x.search import catalog

    return catalog.write(cfg.index, date, profile=cfg)


def add_other_version(card_path, code):
    """The code of another version into doc.other_versions of a card."""
    card = C.load(card_path)
    have = card["doc"].get("other_versions") or []
    if code not in have:
        card["doc"]["other_versions"] = sorted(set(have) | {code})
        C.dump(card, card_path)


def new_events(path, events):
    """The events that are not in intake_events.tsv yet (an interrupted apply may have written some)."""
    if not Path(path).exists():
        return events
    have = set(Path(path).read_text(encoding="utf-8").splitlines())
    return [e for e in events if "\t".join(journal.cell(x) for x in e) not in have]


def remove_empty_dirs(inbox):
    """Empty folders of inbox, bottom up (os.rmdir only: a folder with files stays); never the service ones."""
    top = intake_cfg.lp(inbox)
    removed = []
    for dp, dns, fns in os.walk(top, topdown=False):
        if os.path.normcase(dp) == os.path.normcase(top):
            continue
        rel = os.path.relpath(dp, top)
        if rel.split(os.sep)[0] in intake_cfg.SERVICE:
            continue
        try:
            os.rmdir(dp)
            removed.append(rel)
        except OSError:
            pass
    return removed


JOURNAL = "apply.journal.json"
STEPS = (
    "moves",
    "copies",
    "old versions",
    "cards",
    "texts",
    "other versions",
    "catalog",
    "events",
    "ocr",
    "manifest",
    "journal",
    "dirs",
    "stale",
    "vocab",
)


def code_conflicts(cfg, out):
    """The codes of a built batch that a card of the library has meanwhile (another batch applied after this one was
    built), a replaced code aside."""
    vp = out / "versions.json"
    replaced = set(json.loads(vp.read_text(encoding="utf-8")).get("replaced", [])) if vp.exists() else set()
    taken = set(C.paths(cfg.index / "cards"))
    return sorted(p.stem for p in (out / "cards").glob("*.json") if p.stem in taken and p.stem not in replaced)


def renumber(cfg, work, conflicts):
    """Give the documents whose codes were taken the next free ones and build the batch again (its cards, texts,
    moves, events: everything that names a code); the order of the tids keeps it deterministic."""
    from assistant_x.intake import build as intake_build

    codes_p, out = work / "codes.json", work / "out"
    codes = json.loads(codes_p.read_text(encoding="utf-8"))
    taken = {c[: 2 + C.DIGITS] for c in conflicts}  # a part code N-00012-02: its document N-00012
    codes = {t: c for t, c in codes.items() if c not in taken}
    codes_p.write_text(json.dumps(codes, indent=0), encoding="utf-8")
    params = json.loads((out / "build.json").read_text(encoding="utf-8")) if (out / "build.json").exists() else {}
    return intake_build.build(cfg, work, date=params.get("date"), personal=params.get("personal", False))


def apply(cfg, work, dry=False, date=None, resume=False):
    from assistant_x.intake.build import base_open

    work, out = Path(work), Path(work) / "out"
    base = base_open(cfg) if not dry else ""
    if base:
        print(base)
        return 1
    if not (out / "moves.json").exists():
        print(f"No {out}: run assistant-x intake build first")
        return 1
    if not (out / "applied.json").exists() and not (out / JOURNAL).exists():
        conflicts = code_conflicts(cfg, out)  # before the first move: a batch applied in between took these codes
        if conflicts:
            print(
                f"The codes {', '.join(conflicts)} were taken by a batch applied after this one was built: "
                "the documents get the next free codes" + (" (a trial run: the batch is built again)" if dry else "")
            )
            if renumber(cfg, work, conflicts) != 0:
                print("Apply stopped: the batch could not be built again with new codes.")
                return 1
    if (out / "applied.json").exists():
        print(f"The batch is applied already ({out / 'applied.json'}). For a new one: assistant-x intake build again.")
        return 1
    jr = Journal(out / JOURNAL)
    if jr.data and not resume:
        print(
            f"An apply of this batch was interrupted (started {jr.data['started']}, done: "
            f"{', '.join(jr.data['steps']) or 'some moves'}): continue it with assistant-x intake apply --resume"
        )
        return 1
    if resume and not jr.data:
        print("Nothing to resume: this batch has no interrupted apply (assistant-x intake apply starts it).")
        return 1
    date = jr.data["date"] if jr.data else (date or datetime.date.today().isoformat())
    # names as robocopy and the backup take them (NFC, no zero-width characters): the originals keep their folders
    moves = [
        {**m, "dst": intake_cfg.safe_place(m["dst"])} for m in json.loads((out / "moves.json").read_text(encoding="utf-8"))
    ]
    pdfs = json.loads((out / "pdfcopies.json").read_text(encoding="utf-8"))
    cards = sorted((out / "cards").glob("*.json"))
    texts = sorted((out / "texts").glob("*.md"))
    events = [ln.split("\t") for ln in (out / "events.tsv").read_text(encoding="utf-8").splitlines() if ln.strip()]
    vp = out / "versions.json"
    versions = json.loads(vp.read_text(encoding="utf-8")) if vp.exists() else {"replaced": [], "linked": []}
    state = State(work / "state.sqlite")
    for r in state.all("error"):  # files that stay in inbox: the journal says why
        events.append(
            [
                date,
                "inbox\\" + r["rel"].replace("/", "\\"),
                r.get("size") or "—",
                r.get("sha") or "—",
                "—",
                "—",
                f"{EVENT_ERROR}: {r.get('why') or 'see summary.md'}",
            ]
        )
    if jr.data:
        print(
            f"Resuming the apply of {jr.data['started']}: steps done {', '.join(jr.data['steps']) or 'none'}, "
            f"moves made {len(jr.data['moved'])} of {len(moves)}."
        )
        problems = resume_problems(cfg, moves, set(jr.data["moved"]))
    else:
        problems = check(cfg, moves, pdfs, cards, texts, set(versions["replaced"]))
    if problems:
        print("Apply stopped:")
        for p in problems[:50]:
            print(f"  {p}")
        return 1
    print(
        f"Moves {len(moves)}, PDF copies {len(pdfs)}, cards {len(cards)}, texts {len(texts)}, events {len(events)}; "
        "the catalog and the sources to update are made again from the cards."
    )
    if versions["replaced"]:
        print(
            f"New versions replace {', '.join(versions['replaced'])}: the old originals, cards and texts go to "
            f"inbox\\_to_delete\\replaced_{date}."
        )
    if dry:
        for mv in moves[:30]:
            print(f"  {mv['src']}  →  {mv['dst']}")
        if len(moves) > 30:
            print(f"  … and {len(moves) - 30} more")
        missing = [p for p in ("cards", "texts") if not (cfg.index / p).is_dir()]
        if missing:
            print(f"  missing index files are made empty first: {', '.join(missing)}")
        print("Trial run: nothing changed.")
        return 0
    if not jr.data:
        for p in index_files.ensure(cfg.index, date, templates=False):
            print(f"Made in index: {p if isinstance(p, str) else Path(p).name}")
        jr.start(date)
    run_steps(cfg, jr, out, moves, pdfs, cards, texts, events, state, date, versions)
    (out / "applied.json").write_text(
        json.dumps(
            {"date": date, "moves": len(moves), "removed_dirs": jr.data.get("removed_dirs", [])},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    jr.data["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
    jr.save()
    left = [
        rel for rel in os.listdir(intake_cfg.lp(cfg.inbox)) if rel not in intake_cfg.SERVICE and rel.lower() != "_readme.md"
    ]
    print(f"Done. Empty folders removed: {len(jr.data.get('removed_dirs', []))}.")
    if left:
        print("Left in inbox (to sort, or to decide with the user): " + ", ".join(left[:30]))
    print(
        "Next: assistant-x build and assistant-x embed (or scripts\\library_report.bat)"
        + (", then a commit." if (Path(cfg.root) / ".git").exists() else ".")
    )
    return 0


def check(cfg, moves, pdfs, cards, texts, replaced=()):
    """Problems that stop an apply before anything moves (an empty list: the apply may start). replaced: the codes a
    new version takes over: their card and text are expected, and the place of their old original is freed by an
    earlier move."""
    problems, freed = [], set()
    for mv in moves:
        src, dst = resolve(cfg, mv["src"]), resolve(cfg, mv["dst"])
        if not exists(src):
            problems.append(f"no source file: {mv['src']}")
        if exists(dst) and mv["dst"] not in freed:
            problems.append(f"the place is taken already: {mv['dst']}")
        freed.add(mv["src"])
    dsts = [m["dst"] for m in moves] + [p["dst"] for p in pdfs]
    problems += [f"two files to one place: {d}" for d in sorted({d for d in dsts if dsts.count(d) > 1})]
    for p in pdfs:
        if exists(resolve(cfg, p["dst"])):
            problems.append(f"the place is taken already: {p['dst']}")
    for c in cards:
        if c.stem in replaced:
            continue
        if (cfg.index / "cards" / c.name).exists():
            problems.append(f"a card exists already: index\\cards\\{c.name}")
    for t in texts:
        if t.stem in replaced:
            continue
        if (cfg.index / "texts" / t.name).exists():
            problems.append(f"a text exists already: index\\texts\\{t.name}")
    return problems


def resume_problems(cfg, moves, made):
    """On --resume: a move is done when it is in the journal, or when its source is gone and its place holds the file
    (the PC went off between the move and the note); the others must still be possible."""
    problems = []
    for i, mv in enumerate(moves):
        if i in made:
            continue
        src, dst = resolve(cfg, mv["src"]), resolve(cfg, mv["dst"])
        if not exists(src) and exists(dst):
            made.add(i)
        elif not exists(src):
            problems.append(f"no source file and nothing at its place: {mv['src']} → {mv['dst']}")
        elif exists(dst):
            problems.append(f"the place is taken already: {mv['dst']}")
    return problems


def run_steps(cfg, jr, out, moves, pdfs, cards, texts, events, state, date, versions=None):
    """The steps of an apply in order; each one is noted in the journal when it is done."""

    def step(name):
        return not jr.done(name)

    if step("moves"):
        made = set(jr.data["moved"])
        try:
            for i, mv in enumerate(moves):
                src, dst = resolve(cfg, mv["src"]), resolve(cfg, mv["dst"])
                if i not in made and exists(src):
                    move(src, dst)
                if i not in made:
                    jr.moved(i)
                if mv.get("tid"):
                    state.update(mv["tid"], status="applied", place=mv["dst"])
        finally:
            (out / "moved.json").write_text(
                json.dumps([moves[i] for i in sorted(set(jr.data["moved"]))], ensure_ascii=False, indent=0), encoding="utf-8"
            )
        jr.mark("moves")
    if step("copies"):
        for p in pdfs:
            dst = resolve(cfg, p["dst"])
            os.makedirs(intake_cfg.lp(dst.parent), exist_ok=True)
            shutil.copy2(p["src"], intake_cfg.lp(dst))
        jr.mark("copies")
    replaced = (versions or {}).get("replaced", [])
    if step("old versions"):  # the card and the text of a replaced document go beside its old original
        aside = Path(cfg.inbox) / "_to_delete" / f"replaced_{date}" / "index"
        for c in replaced:
            for p in (
                cfg.index / "cards" / f"{c}.json",
                cfg.index / "texts" / f"{c}.md",
                cfg.index / "texts" / f"{c}{PAGES_SUFFIX}",
            ):
                if p.exists():
                    move(p, aside / p.parent.name / p.name)
        jr.mark("old versions")
    if step("cards"):
        for c in cards:
            shutil.copyfile(c, cfg.index / "cards" / c.name)
        jr.mark("cards")
    if step("texts"):
        for t in texts:  # a text and what is known of its pages (<code>.pages.json) go together
            shutil.copyfile(t, cfg.index / "texts" / t.name)
            if t.with_suffix(PAGES_SUFFIX).exists():
                shutil.copyfile(t.with_suffix(PAGES_SUFFIX), cfg.index / "texts" / f"{t.stem}{PAGES_SUFFIX}")
        jr.mark("texts")
    if step("other versions"):
        for v in (versions or {}).get("linked", []):
            card = cfg.index / "cards" / f"{v['other']}.json"
            if card.exists():
                add_other_version(card, v["code"])
        jr.mark("other versions")
    if step("catalog"):
        write_views(cfg, date)
        jr.mark("catalog")
    if step("events"):
        journal.append_events(cfg.index / "intake_events.tsv", new_events(cfg.index / "intake_events.tsv", events))
        jr.mark("events")
    if step("ocr"):
        if (out / "ocr.tsv").exists():
            from assistant_x.intake.tools import ocr_score

            rows = ocr_score.read_tsv(cfg.index / ocr_score.TSV_NAME)
            rows.update(ocr_score.read_tsv(out / "ocr.tsv"))
            ocr_score.write_tsv(cfg.index / ocr_score.TSV_NAME, rows)
        jr.mark("ocr")
    if step("manifest"):
        manifest.main(["--root", str(cfg.root)])
        jr.mark("manifest")
    if step("journal"):
        journal.sync(cfg.index)
        jr.mark("journal")
    if step("dirs"):
        jr.data["removed_dirs"] = remove_empty_dirs(cfg.inbox)
        jr.mark("dirs")
    if step("stale"):  # the search says the base is behind until build_index runs
        from assistant_x.core.common import load_config, mark_index_stale

        mark_index_stale(load_config(str(cfg.path)), date)
        jr.mark("stale")
    if step("vocab"):  # the vocabulary of the recognition score grows with the library (assistant-x intake vocab by hand)
        from assistant_x.intake.tools import ocr_score

        words, stems, docs = ocr_score.build_vocab(str(cfg.index / "texts"), str(cfg.ocr_vocab))
        print(
            f"Vocabulary of the recognition score: {words} word forms and {stems} stems of {docs} documents → {cfg.ocr_vocab}"
        )
        jr.mark("vocab")
