# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""Take documents out of the library (one that got in by mistake): nothing is deleted, everything goes aside.

    assistant-x remove N-00268 [L-00012 …] [--why "a duplicate of another edition"] [--dry-run]

For every code (and the parts of a document of several files, N-00268-02 …) the plan lists the originals in library
(manifest.tsv; a PDF copy of a DOCX too), the card index\cards\<code>.json and the text index\texts\<code>.md with
<code>.pages.json and <code>.hidden.json. The removal moves them into inbox\_to_delete\removed_<code>_<date>\ under the
same folders (library\…, index\cards, index\texts), takes the code out of the other_versions of the other cards and
its row out of ocr_quality.tsv, writes an event per file to intake_events.tsv ("removed: <why>"; event_kind "removed":
a file that comes back is no duplicate, intake/prepare.known_hashes), makes manifest.tsv, journal.md, CATALOG.md and
sources_to_update.md again, keeps the code reserved (index\codes.json: a number never comes back) and rebuilds the base
by words (build_index drops the fragments and the vectors of the code; no embeddings are computed). changes.log notes
it. The removal is a transaction with a journal (index\remove.journal.json): an interrupted one is continued by the
same command (the moves already made are skipped)."""

import argparse, datetime, sys

from assistant_x.core import card as C
from assistant_x.core import journal
from assistant_x.core.formats import EVENT_REMOVED, PAGES_SUFFIX
from assistant_x.core.txn import Journal, exists, move
from assistant_x.intake import config as intake_cfg
from assistant_x.intake import manifest

JOURNAL = "remove.journal.json"
STEPS = ("moves", "links", "ocr", "events", "manifest", "journal", "codes", "catalog", "dirs", "build")


def say(*a):
    print(*a, flush=True)


def codes_of(cfg, code):
    """The code and the codes of its parts that have a card or a row of the manifest, in order."""
    main = C.main_code(code)
    cards = [c for c in C.paths(cfg.index / "cards") if C.main_code(c) == main]
    rows = [r["code"] for r in manifest.load(manifest.manifest_path(cfg.root)).values() if r.get("code")]
    found = sorted({c for c in cards + rows if C.main_code(c) == main})
    return found if code == main else [c for c in found if c == code]


def plan(cfg, codes, date):
    """[(place of a file under the workspace, its place in the folder aside, code)] of the documents of codes."""
    items = []
    rows = manifest.load(manifest.manifest_path(cfg.root))
    for code in codes:
        aside = f"inbox\\_to_delete\\removed_{C.main_code(code)}_{date}"
        for rel, r in sorted(rows.items()):
            if r.get("code") == code:
                items.append((rel, f"{aside}\\{rel}", code))
        for name in (f"{code}.json",):
            if (cfg.index / "cards" / name).exists():
                items.append((f"index\\cards\\{name}", f"{aside}\\index\\cards\\{name}", code))
        for name in (f"{code}.md", f"{code}{PAGES_SUFFIX}", f"{code}.hidden.json"):
            if (cfg.index / "texts" / name).exists():
                items.append((f"index\\texts\\{name}", f"{aside}\\index\\texts\\{name}", code))
    return items


def path_of(cfg, place):
    """'library\\a\\b.pdf', 'index\\cards\\x.json', 'inbox\\…' -> the path under the folders of the workspace."""
    head, _, rest = place.partition("\\")
    base = {"inbox": cfg.inbox, "library": cfg.library, "index": cfg.index}[head]
    return base.joinpath(*[p for p in rest.split("\\") if p])


def describe(cfg, codes, items):
    """The plan in words: the documents with their titles and the files that go aside."""
    out = []
    for code in codes:
        p = cfg.index / "cards" / f"{code}.json"
        title = ""
        if p.exists():
            try:
                doc = C.load(p).get("doc") or {}
                title = C.text(doc.get("title")) or ""
            except C.CardError:
                title = ""
        out.append(f"{code} «{title or 'no card'}»:")
        out += [f"  {src}  →  {dst}" for src, dst, c in items if c == code]
    return out


def remove(cfg, codes, why="", dry=False, date=None, build=True):
    from assistant_x.core import debuglog

    jr = Journal(cfg.index / JOURNAL)
    if jr.data and sorted(jr.data.get("codes", [])) != sorted(codes):
        say(
            f"A removal of {', '.join(jr.data['codes'])} was interrupted: finish it first (assistant-x remove "
            f"{' '.join(jr.data['codes'])})."
        )
        return 1
    date = jr.data["date"] if jr.data else (date or datetime.date.today().isoformat())
    if jr.data:
        items, why = [tuple(x) for x in jr.data["items"]], jr.data.get("why", why)
        say(f"Resuming the removal of {jr.data['started']}: steps done {', '.join(jr.data['steps']) or 'none'}.")
    else:
        found = []
        for code in codes:
            if not C.is_code(code):
                say(f"Not a code: {code}")
                return 1
            mine = codes_of(cfg, code)
            if not mine:
                say(f"No document {code} in the library (no card, no file of the manifest).")
                return 1
            found += [c for c in mine if c not in found]
        codes = found
        items = plan(cfg, codes, date)
    say(f"Removal of {', '.join(codes)}" + (f" ({why})" if why else "") + ": nothing is deleted, everything goes aside.")
    for line in describe(cfg, codes, items):
        say(line)
    if dry:
        say("Trial run: nothing changed.")
        return 0
    if not jr.data:
        jr.start(date, codes=codes, why=why, items=[list(x) for x in items])
    run_steps(cfg, jr, codes, items, why, date, build)
    jr.path.unlink()
    debuglog.log_change("library_remove", {"codes": codes, "why": why}, "done")
    say(f"Done: {len(items)} files in inbox\\_to_delete; the codes {', '.join(codes)} stay reserved.")
    return 0


def run_steps(cfg, jr, codes, items, why, date, build=True):
    """The steps of a removal in order; each one is noted in the journal when it is done."""

    def step(name):
        return not jr.done(name)

    if step("moves"):
        made = set(jr.data["moved"])
        for i, (src, dst, _) in enumerate(items):
            s, d = path_of(cfg, src), path_of(cfg, dst)
            if i not in made and exists(s) and not exists(d):
                move(s, d)
            if i not in made:
                jr.moved(i)
        jr.mark("moves")
    if step("links"):  # the other versions of the removed documents no longer name them
        gone = set(codes)
        for code, p in C.paths(cfg.index / "cards").items():
            card = C.load(p)
            have = card["doc"].get("other_versions") or []
            if gone & set(have):
                left = [c for c in have if c not in gone]
                if left:
                    card["doc"]["other_versions"] = left
                else:
                    card["doc"].pop("other_versions", None)
                C.dump(card, p)
        jr.mark("links")
    if step("ocr"):
        from assistant_x.intake.tools import ocr_score

        tsv = cfg.index / ocr_score.TSV_NAME
        rows = ocr_score.read_tsv(tsv)
        if set(codes) & set(rows):
            ocr_score.write_tsv(tsv, {c: r for c, r in rows.items() if c not in codes})
        jr.mark("ocr")
    if step("events"):
        rows = manifest.load(manifest.manifest_path(cfg.root))
        events = []
        for src, dst, code in items:
            r = rows.get(src) or {}
            events.append(
                [
                    date,
                    src,
                    r.get("size") or "—",
                    (r.get("sha256") or "")[:16] or "—",
                    code,
                    dst.rsplit("\\", 1)[0] + "\\",
                    f"{EVENT_REMOVED}: {why or 'taken out of the library by the user'}",
                ]
            )
        journal.append_events(cfg.index / "intake_events.tsv", events)
        jr.mark("events")
    if step("manifest"):
        manifest.main(["--root", str(cfg.root)])
        jr.mark("manifest")
    if step("journal"):
        journal.sync(cfg.index)
        jr.mark("journal")
    if step("codes"):
        C.raise_high_water(cfg.index, codes)
        jr.mark("codes")
    if step("catalog"):
        from assistant_x.search import catalog

        catalog.write(cfg.index, date, profile=cfg)
        jr.mark("catalog")
    if step("dirs"):  # the folder of a document of several files left empty
        for src, _, _ in items:
            if src.startswith("library\\"):
                d = path_of(cfg, src).parent
                while d != cfg.library and d.is_dir() and not any(d.iterdir()):
                    d.rmdir()
                    d = d.parent
        jr.mark("dirs")
    if step("build") and build:
        from assistant_x.core import proc

        rc = proc.call([sys.executable, "-m", "assistant_x.search.build_index", "--config", str(cfg.path)])
        if rc:
            raise SystemExit(f"build_index failed (code {rc}): the files are aside; run assistant-x remove again")
        jr.mark("build")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="assistant-x remove", description=__doc__.split("\n\n")[0])
    ap.add_argument("codes", nargs="+", help="the codes of the documents (N-00268; a part: N-00268-02)")
    ap.add_argument("--why", default="", help="why the documents leave the library (into the journal)")
    ap.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
    ap.add_argument("--config", help="assistant_x.toml of the workspace (default: the one in use)")
    a = ap.parse_args(argv)
    cfg = intake_cfg.load(a.config) if a.config else intake_cfg.load()
    codes = list(dict.fromkeys(c.strip().upper() for c in a.codes))
    return remove(cfg, codes, a.why.strip(), a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
