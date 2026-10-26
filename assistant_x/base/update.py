# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""assistant-x base update and base remove: a new version of an installed package, or the package out of the
library. The documents of the library that are not of the package never change, and none of them is renumbered.

    assistant-x base update PACKAGE [--confirm] [--resume | --rollback]
    assistant-x base remove ID [--confirm] [--resume | --rollback]

An update matches the documents of the new version with the ones the library has by the package id and their code in
the package (intake.package.code), whatever their code here is:
  unchanged  the same original, text and card: only the version in the card changes
  changed    another original, text or card: the old files go to inbox\_to_delete\updated_<id>_<date>, the new ones
             come under the code the document has here
  new        under its package code when that is free here and was never given here to another document (a number
             never comes back; a reference package keeps its numbering and the report lists the reuse), else under
             the next free code of its shelf (its package code stays in intake.package.code)
  removed    the documents the new version no longer has go to inbox\_to_delete\removed_<id>_<date>
A remove puts every document of the package into inbox\_to_delete\removed_<id>_<date> and forgets the package. Both are
transactions like the install (base/install.py: journal, marker, backup, --resume, --rollback), then build, embed
(an update) and check. The numbers of the codes of removed documents never come back (index\codes.json).
"""

import argparse, datetime, hashlib, json, os, re, shutil, sys

from assistant_x.base import install as B, package as P, registry
from assistant_x.core import card as C
from assistant_x.core import config as settings
from assistant_x.core.txn import Journal, exists, lp


def _comparable(card, mapping=None):
    """What decides whether a document changed: its doc block and its files (codes as in this library), not the
    version of the package nor the dates of its intake."""
    c = C.remap(card, mapping or {})[0] if mapping else json.loads(json.dumps(card))
    file = dict(c.get("file") or {})
    return json.dumps(
        {"doc": c.get("doc"), "file": file, "doc_type": c.get("doc_type"), "section": c.get("section")},
        sort_keys=True,
        ensure_ascii=False,
    )


def text_sha(texts, code):
    from assistant_x.base.export import text_sha as sha

    return sha(texts, code)


def local_of(w, ident):
    """{package code: (local code, card)} of the documents of the package in the library."""
    out = {}
    for code, p in C.paths(w.cards).items():
        card = C.load(p)
        pkg = (card.get("intake") or {}).get("package") or {}
        if pkg.get("id") == ident:
            out[pkg.get("code") or code] = (code, card)
    return out


def package_text_sha(pkg, code):
    """text_sha of a text of a package read where it lies (no extraction): the same bytes as read from a file in text
    mode (universal newlines), with its .pages.json."""
    from assistant_x.core.common import strip_invisible
    from assistant_x.core.formats import PAGES_SUFFIX

    names = set(pkg.names())
    for ext in (".md", ".txt"):
        if f"texts/{code}{ext}" in names:
            raw = pkg.read(f"texts/{code}{ext}").decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
            side = f"texts/{code}{PAGES_SUFFIX}"
            extra = pkg.read(side) if side in names else b""
            return hashlib.sha256(strip_invisible(raw).encode() + b"\0" + extra).hexdigest()
    return ""


def plan_of_package(w, path, ident):
    """The plan of an update read from the package where it lies: nothing is extracted, no journal is started (a
    "what would change" question copies nothing and holds no lock)."""
    from assistant_x.base import inspection as I

    with P.Package(path) as pkg:
        pcards, _ = I.package_cards(pkg)
        return plan_update(
            w,
            None,
            ident,
            pcards=pcards,
            sha_of=lambda code: package_text_sha(pkg, code),
            reference=pkg.manifest.get("codes") == "reference",
        )


def plan_update(w, pkg_dir, ident, pcards=None, sha_of=None, reference=None):
    """{mapping: package code -> local code, unchanged, changed, new, removed} of an update from its extracted
    package (pkg_dir), or from the cards and the text sha of a package read where it lies (pcards, sha_of)."""
    local = local_of(w, ident)
    if pcards is None:
        pcards = {c: C.load(p) for c, p in C.paths(pkg_dir / "cards").items()}
        sha_of = lambda code: text_sha(str(pkg_dir / "texts"), code)  # noqa: E731
    if reference is None:
        reference = json.loads((pkg_dir / P.MANIFEST).read_text(encoding="utf-8")).get("codes") == "reference"
    by_pkg = {
        (card.get("intake") or {}).get("package", {}).get("code") or code: (code, card) for code, card in pcards.items()
    }
    from assistant_x.base import inspection as I

    taken = set(C.paths(w.cards))
    marks = C.high_water(w.index)  # a number at or below its mark that no document has now was given once: retired
    former = I.lineage(w.index, ident)
    high = dict(marks)
    for code in taken:
        m = C.CODE_RX.match(code)
        high[m["letter"]] = max(high.get(m["letter"], 0), int(m["num"]))
    mapping, unchanged, changed, new, reused = {}, [], [], [], []
    for pcode in sorted(by_pkg):
        here_code, card = by_pkg[pcode]
        if pcode in local:
            lcode, lcard = local[pcode]
            m = {here_code: lcode} if here_code != lcode else {}
            same = (
                _comparable(card, m) == _comparable(lcard)
                and sha_of(here_code) == text_sha(str(w.texts), lcode)
                and all(sha_of(sub) == text_sha(str(w.texts), C.map_code(sub, m)) for sub, _ in B._entries(card)[1:])
            )
            (unchanged if same else changed).append(lcode)
            if m:
                mapping[here_code] = lcode
        else:
            retired = (
                here_code not in taken
                and here_code not in former
                and int(C.CODE_RX.match(here_code)["num"]) <= marks.get(here_code[0], 0)
            )
            if retired and reference:  # the reference numbering is kept: the reuse is told in the report
                reused.append(here_code)
            elif here_code in taken or retired:
                letter = here_code[0]
                high[letter] = high.get(letter, 0) + 1
                mapping[here_code] = C.new_code(letter, high[letter])
            taken.add(mapping.get(here_code, here_code))
            new.append(mapping.get(here_code, here_code))
    removed = sorted(lcode for pcode, (lcode, _) in local.items() if pcode not in by_pkg)
    # the unchanged documents are not placed again: their files in the work folder are left out
    skip = [here for here, _ in by_pkg.values() if mapping.get(here, here) in unchanged]
    return {
        "mapping": mapping,
        "unchanged": sorted(unchanged),
        "changed": sorted(changed),
        "new": sorted(new),
        "removed": removed,
        "skip": sorted(skip),
        "reused": sorted(reused),
    }


def aside_moves(w, codes, folder):
    """[(src, dst)] of every file of these documents of the library into folder (relative to the workspace)."""
    root = str(w.root)
    idx_rel = B._rel(w.index, root)
    out = []
    for code in codes:
        card = C.load(w.cards / f"{code}.json")
        files = [f"{idx_rel}/cards/{code}.json"] + [x for _, e in B._entries(card) for x in B._files(e, idx_rel)]
        out += [(f, f"{folder}/{f}") for f in dict.fromkeys(files) if exists(os.path.join(root, *f.split("/")))]
    return out


def update(path, confirm=False, resume=False, rollback=False, config=None, say=print):
    from assistant_x.core import lock
    from assistant_x.core.common import clear_maintenance, load_config

    w, raw = settings.load(config)
    cfg = load_config(config)
    with P.Package(path) as pkg:
        man, identity = pkg.manifest, pkg.identity()
    ident, version = man["id"], man["version"]
    stage = B.staging(w, ident)
    jr = Journal(stage / B.JOURNAL)
    other = B.other_package(jr, identity) if jr.data and jr.data.get("kind") == "update" else ""
    if other:
        say(other)
        return 1
    if jr.data and jr.data.get("kind") != "update":
        say(
            f"An {jr.data.get('kind', 'install')} of {ident} was interrupted: finish it first "
            f"(assistant-x base {jr.data.get('kind', 'install')} … --resume or --rollback)."
        )
        return 1
    if rollback:
        if not jr.data:
            say("Nothing to undo: no update of this package was interrupted.")
            return 1
        with lock.heavy_task("base update"), lock.hold(w.work, "base update"):
            return B.undo(w, cfg, jr, stage, say)
    if jr.data and not resume:
        say(f"An update of {ident} was interrupted: assistant-x base update PACKAGE --resume, or --rollback")
        return 1
    if resume and not jr.data:
        say("Nothing to resume: no update of this package was interrupted.")
        return 1
    if not jr.data:
        installed = registry.get(w.index, ident)
        if not installed:
            say(f"The package {ident} is not installed here: assistant-x base install.")
            return 1
        if installed.get("version") == version:
            say(f"The package {ident} {version} is installed already: nothing to update.")
            return 0
        from assistant_x.base import inspection as I

        problems = [
            p for p in I.inspect(cfg, raw, path, work=str(w.work))["problems"] if not p.startswith("card ")
        ]  # the cards of the package pass by their own rules here
        with P.Package(path) as pkg:
            problems += B.check_entries(pkg)
        if problems:
            say("The update cannot start:\n" + "\n".join(f"  {p}" for p in problems[:30]))
            return 1
        if not confirm:  # the plan only: read from the package where it lies, nothing extracted, no journal
            say(text(plan_of_package(w, path, ident), ident, installed["version"], version))
            say("Nothing changed. To update: the same command with --confirm.")
            return 0
    date = jr.data["date"] if jr.data else datetime.date.today().isoformat()
    try:
        with lock.heavy_task("base update"), lock.hold(w.work, "base update"):
            from assistant_x.intake.build import code_lock

            lock_f = code_lock(w.index)
            if lock_f is None:
                say("Another process holds the lock of the code numbers: run the update again when it has ended.")
                return 1
            try:
                if not jr.data:
                    stage.mkdir(parents=True, exist_ok=True)
                    jr.start(
                        date,
                        kind="update",
                        package=os.path.abspath(path),
                        id=ident,
                        version=version,
                        old_version=registry.get(w.index, ident)["version"],
                        identity=identity,
                    )
                return run_update(w, cfg, path, jr, stage, date, say)
            finally:
                lock_f.close()
                clear_maintenance(cfg["index_dir"])
    except B.Stop as e:
        say(f"The update stopped: {e.code}")
        return 1


def run_update(w, cfg, path, jr, stage, date, say):
    from assistant_x.core.common import clear_maintenance, mark_index_stale, set_maintenance

    root, pkg_dir = str(w.root), stage / "pkg"
    ident, version = jr.data["id"], jr.data["version"]
    lib_rel, idx_rel = B._rel(w.library, root), B._rel(w.index, root)

    def step(name):
        return not jr.done(name)

    if step("extract"):
        if pkg_dir.exists():
            shutil.rmtree(pkg_dir)
        with P.Package(path) as pkg:
            B.extract(pkg, str(pkg_dir))
        jr.mark("extract")
    if step("plan"):
        plan = plan_update(w, pkg_dir, ident)
        plan.update(renumbered="package" if plan["mapping"] else "", replace=[], adopt=None)
        jr.data["plan"] = plan
        jr.data["own_moves"] = []
        jr.data["out_moves"] = aside_moves(w, plan["changed"], f"inbox/_to_delete/updated_{ident}_{date}") + aside_moves(
            w, plan["removed"], f"inbox/_to_delete/removed_{ident}_{date}"
        )
        jr.mark("plan")
    plan = jr.data["plan"]
    if step("marker"):
        set_maintenance(cfg["index_dir"], f"update of the base package {ident} to {version}")
        mark_index_stale(cfg, date)
        jr.mark("marker")
    if step("backup"):
        jr.data["backup"] = B.backup(w, ident)
        jr.mark("backup")
    if step("aside"):
        B.run_moves(jr, "aside_done", [tuple(m) for m in jr.data["out_moves"]], root)
        jr.mark("aside")
    if step("package"):
        pcards = {c: C.load(p) for c, p in C.paths(pkg_dir / "cards").items()}
        B.prepare_package(pkg_dir, pcards, plan["mapping"], set(plan["skip"]), ident, version)
        jr.mark("package")
    if step("place"):
        placed, src_rel = [], B._rel(pkg_dir, root)
        for dp, _, fns in os.walk(lp(pkg_dir)):
            for f in fns:
                rel = os.path.relpath(os.path.join(dp, f), lp(pkg_dir)).replace(os.sep, "/")
                if rel.startswith(("cards/", "texts/")):
                    placed.append((f"{src_rel}/{rel}", f"{idx_rel}/{rel}"))
                elif rel.startswith("library/"):
                    placed.append((f"{src_rel}/{rel}", lib_rel + rel[len("library") :]))
        jr.data["placed"] = sorted(placed)
        jr.save()
        B.run_moves(jr, "placed_done", [tuple(m) for m in jr.data["placed"]], root)
        jr.mark("place")
    if step("tables"):
        update_tables(w, pkg_dir, jr, date)
        jr.mark("tables")
    if step("build"):
        jr.data["full"] = B.build_only(str(w.config))
        jr.mark("build")
    if step("vectors"):
        jr.data["vectors"] = B.package_vectors(w, pkg_dir, ident)
        jr.mark("vectors")
    if step("base"):
        jr.data["base"] = B.build_base(str(w.config), say, full=jr.data["full"])
        jr.mark("base")
    clear_maintenance(cfg["index_dir"])
    report(w, jr, say)
    shutil.rmtree(stage)
    return 0


def update_tables(w, pkg_dir, jr, date):
    from assistant_x.core import journal
    from assistant_x.intake import manifest
    from assistant_x.intake.tools import ocr_score
    from assistant_x.search import catalog

    plan, ident, version = jr.data["plan"], jr.data["id"], jr.data["version"]
    for code in plan["unchanged"]:  # the same document: only the version it is of
        p = w.cards / f"{code}.json"
        card = C.load(p)
        card["intake"]["package"]["version"] = version
        C.dump(card, p)
    p = pkg_dir / "ocr_quality.tsv"
    if p.exists():
        rows = ocr_score.read_tsv(w.index / ocr_score.TSV_NAME)
        rows.update(ocr_score.read_tsv(p))
        ocr_score.write_tsv(w.index / ocr_score.TSV_NAME, rows)
    rows = {
        k: v for k, v in ocr_score.read_tsv(w.index / ocr_score.TSV_NAME).items() if C.main_code(k) not in plan["removed"]
    }
    ocr_score.write_tsv(w.index / ocr_score.TSV_NAME, rows)
    ev = [[date, "—", "—", "—", c, "—", f"done: updated from package {ident} {version}"] for c in plan["changed"]]
    there = {v: k for k, v in plan["mapping"].items()}
    ev += [
        [
            date,
            "—",
            "—",
            "—",
            c,
            "—",
            f"done: installed from package {ident} {version}" + (f" (its code there {there[c]})" if c in there else ""),
        ]
        for c in plan["new"]
    ]
    ev += [
        [
            date,
            "—",
            "—",
            "—",
            c,
            f"inbox\\_to_delete\\removed_{ident}_{date}\\",
            f"to delete: no longer in package {ident} {version}",
        ]
        for c in plan["removed"]
    ]
    journal.append_events(w.index / "intake_events.tsv", ev)
    C.raise_high_water(w.index, list(C.paths(w.cards)) + plan["removed"])
    entry = dict(
        registry.get(w.index, ident) or {}, id=ident, version=version, updated=date, documents=len(local_of(w, ident))
    )
    registry.put(w.index, entry)
    catalog.write(w.index, date, profile=settings.load(str(w.config))[1])
    manifest.main(["--root", str(w.root)])
    journal.sync(w.index)


def text(plan, ident, old, new):
    lines = [
        f"Update of {ident} {old} -> {new}: unchanged {len(plan['unchanged'])}, changed {len(plan['changed'])}, "
        f"new {len(plan['new'])}, removed {len(plan['removed'])}."
    ]
    for what in ("changed", "new", "removed"):
        if plan[what]:
            lines.append(f"  {what}: {', '.join(plan[what][:40])}" + (" …" if len(plan[what]) > 40 else ""))
    moved = {k: v for k, v in plan["mapping"].items() if v not in plan["unchanged"]}
    if moved:
        lines.append("  package code -> code here: " + ", ".join(f"{a} -> {b}" for a, b in sorted(moved.items())))
    if plan.get("reused"):
        lines.append(
            "  codes once given here to documents since removed, reused by the reference numbering: "
            + ", ".join(plan["reused"])
        )
    return "\n".join(lines)


def report(w, jr, say):
    d = jr.data
    plan, base = d["plan"], d.get("base") or {}
    kind = d.get("kind")
    lines = [
        f"# {'Update' if kind == 'update' else 'Removal'} of the base package {d['id']}"
        + (f" {d.get('old_version')} -> {d['version']}" if kind == "update" else ""),
        "",
        f"Date: {d['date']}. Backup of the index: {d.get('backup')}.",
        "",
    ]
    if kind == "update":
        lines.append(text(plan, d["id"], d.get("old_version"), d["version"]))
    else:
        lines.append(f"Documents to inbox\\_to_delete: {', '.join(plan['removed']) or 'none'}")
    vec = d.get("vectors") or {}
    if vec.get("offered"):
        lines.append(
            f"Vectors from the package: {vec.get('added', 0)} of {vec['offered']}"
            + (f" (check by encoding again: {vec['verified']})" if vec.get("verified") else "")
            + (f"; {vec['note']}" if vec.get("note") else "")
            + "."
        )
    lines += [f"- {n}" for n in base.get("notes") or []]
    w.reports.mkdir(parents=True, exist_ok=True)
    path = w.reports / f"base_{kind}_{d['id']}_{datetime.datetime.now():%Y%m%d-%H%M%S}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    say(f"Report: {path}")


def remove(ident, confirm=False, resume=False, rollback=False, config=None, say=print):
    from assistant_x.core import lock
    from assistant_x.core.common import clear_maintenance, load_config, mark_index_stale, set_maintenance

    if not re.fullmatch(P.ID_RX, ident or ""):
        say(f"{ident!r} is not the id of a package (lower-case letters, digits, '.', '_' and '-').")
        return 1
    w, _ = settings.load(config)
    cfg = load_config(config)
    stage = B.staging(w, ident)
    jr = Journal(stage / B.JOURNAL)
    if jr.data and jr.data.get("kind") != "remove":
        say(f"An {jr.data.get('kind', 'install')} of {ident} was interrupted: finish it first.")
        return 1
    if rollback:
        if not jr.data:
            say("Nothing to undo: no removal of this package was interrupted.")
            return 1
        with lock.heavy_task("base remove"), lock.hold(w.work, "base remove"):
            return B.undo(w, cfg, jr, stage, say)
    if jr.data and not resume:
        say(f"A removal of {ident} was interrupted: assistant-x base remove {ident} --resume, or --rollback")
        return 1
    if not jr.data and not registry.get(w.index, ident):
        say(f"The package {ident} is not installed here.")
        return 1
    local = local_of(w, ident)
    if not jr.data and not confirm:
        say(
            f"Removal of {ident}: its {len(local)} documents go to inbox\\_to_delete\\removed_{ident}_<date> "
            f"({', '.join(sorted(c for c, _ in local.values())[:40])}); the user's own documents stay. "
            "To remove: the same command with --confirm."
        )
        return 0
    date = jr.data["date"] if jr.data else datetime.date.today().isoformat()
    root = str(w.root)
    try:
        with lock.heavy_task("base remove"), lock.hold(w.work, "base remove"):
            if not jr.data:
                stage.mkdir(parents=True, exist_ok=True)
                codes = sorted(c for c, _ in local.values())
                jr.start(
                    date,
                    kind="remove",
                    id=ident,
                    version=registry.get(w.index, ident)["version"],
                    plan={"removed": codes, "mapping": {}},
                    own_moves=[],
                    placed=[],
                    out_moves=aside_moves(w, codes, f"inbox/_to_delete/removed_{ident}_{date}"),
                )
            if not jr.done("marker"):
                set_maintenance(cfg["index_dir"], f"removal of the base package {ident}")
                mark_index_stale(cfg, date)
                jr.mark("marker")
            if not jr.done("backup"):
                jr.data["backup"] = B.backup(w, ident)
                jr.mark("backup")
            if not jr.done("aside"):
                B.run_moves(jr, "aside_done", [tuple(m) for m in jr.data["out_moves"]], root)
                jr.mark("aside")
            if not jr.done("tables"):
                from assistant_x.core import journal
                from assistant_x.intake import manifest
                from assistant_x.intake.tools import ocr_score
                from assistant_x.search import catalog

                removed = jr.data["plan"]["removed"]
                rows = {
                    k: v
                    for k, v in ocr_score.read_tsv(w.index / ocr_score.TSV_NAME).items()
                    if C.main_code(k) not in removed
                }
                if (w.index / ocr_score.TSV_NAME).exists():
                    ocr_score.write_tsv(w.index / ocr_score.TSV_NAME, rows)
                journal.append_events(
                    w.index / "intake_events.tsv",
                    [
                        [
                            date,
                            "—",
                            "—",
                            "—",
                            c,
                            f"inbox\\_to_delete\\removed_{ident}_{date}\\",
                            f"to delete: package {ident} removed",
                        ]
                        for c in removed
                    ],
                )
                C.raise_high_water(w.index, removed)
                registry.remove(w.index, ident)
                catalog.write(w.index, date, profile=settings.load(str(w.config))[1])
                if w.library.is_dir():
                    manifest.main(["--root", root])
                journal.sync(w.index)
                jr.mark("tables")
            if not jr.done("base"):
                jr.data["base"] = B.build_base(str(w.config), say)
                jr.mark("base")
            clear_maintenance(cfg["index_dir"])
            report(w, jr, say)
            shutil.rmtree(stage)
            say(f"Removed {ident}: {len(jr.data['plan']['removed'])} documents to inbox\\_to_delete.")
            return 0
    except B.Stop as e:
        say(f"The removal stopped: {e.code}")
        return 1
    finally:
        clear_maintenance(cfg["index_dir"])


def main_update(argv=None):
    ap = argparse.ArgumentParser(prog="assistant-x base update")
    ap.add_argument("package")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--config")
    a = ap.parse_args(argv)
    try:
        return update(a.package, confirm=a.confirm, resume=a.resume, rollback=a.rollback, config=a.config)
    except P.PackageError as e:
        raise SystemExit(str(e))


def main_remove(argv=None):
    ap = argparse.ArgumentParser(prog="assistant-x base remove")
    ap.add_argument("id")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--config")
    a = ap.parse_args(argv)
    return remove(a.id, confirm=a.confirm, resume=a.resume, rollback=a.rollback, config=a.config)


if __name__ == "__main__":
    sys.exit(main_update())
