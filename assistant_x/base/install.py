# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""assistant-x base install: a base package into this workspace, as a transaction that may be continued or undone.

    assistant-x base install PACKAGE                  the plan (inspect), nothing changes
    assistant-x base install PACKAGE --confirm [--keep own|package] [--answers answers.json] [--own-apart]
    assistant-x base install PACKAGE --resume         continue an install that was interrupted
    assistant-x base install PACKAGE --rollback       undo an install that was interrupted

answers.json: {"codes": "package" | "own"} (the same as --keep). When the codes collide, a reference package keeps
its codes unless the user chose "own"; a default package needs the choice (--keep or the answer "codes"), else nothing
starts. Duplicates are merged without a question (inspection.classify): the same file or the same content — one
stays (the higher recognition score; a tie: the library's), another edition — the newer stays; the one that loses
goes to inbox\_to_delete\merged_<date>, never deleted, and the report lists every pair.
--own-apart marks the documents of this library personal (intake.personal: the search filter scope="own" finds
them; nothing moves).

The steps, each noted in the journal .assistant_x\w\<id>\install.journal.json as it is done:
  marker      db\maintenance.json: a running search server lets the originals go and answers page images "being
              changed"; the base is marked behind the library
  backup      the small files of the index (cards, the tables, the views, packages.json, the settings, questions.md,
              eval_baseline.json; not the texts) to .assistant_x\backups\<time>-before-<id>.zip
  extract     the package into the short folder .assistant_x\w\<id>\pkg, every name checked first (no "..", no
              absolute path, no link, no device name, no ":", no two names equal but for the case, stored entries
              only, every size as declared), then every checksum
  plan        what goes where: the code plan of inspect, the answers, the documents to skip or to replace
  renames     the documents of the side that gets new codes: every file to a temporary name, then to its new name
              (a swap of two codes works); a file held by another program is tried again, then the install stops
              with the journal kept (--resume when Claude is closed)
  cards       the cards of the renumbered side rewritten, the manifest rows and the recognition scores renamed (no
              file hashed again), questions.md and eval_baseline.json, the fingerprints of the duplicate check of
              the codes dropped
  place       the documents of the package moved into library\ and index\; the documents that lost a merge by
              rule (inspection.classify) to inbox\_to_delete\merged_<date>, never deleted
  tables      ocr_quality.tsv, the events ("installed from package", "renumbered"), the marks of the code numbers,
              packages.json, the profile and the card languages of the package for an empty workspace, the
              catalog, manifest.tsv, journal.md
  build       assistant-x build (incremental; --full when the base is of another schema); a failed build stops
  vectors     the vectors of the package into the vector cache when they are of the model here, checked
              (base/vectors.py): only keys of fragments of the package documents without a vector, a sample encoded
              again when the model is here
  base        assistant-x embed (from the cache; a fragment it has not and no model here: the search by words until
              assistant-x embed runs), assistant-x check
  report      reports\base_install_<id>_<time>.md; the marker removed, the work folder emptied
"""

import argparse, datetime, json, os, re, shutil, sys, time, zipfile
from pathlib import Path

from assistant_x.base import inspection as I, package as P, registry, remap as R
from assistant_x.base.package import TOP, TOP_FILES, bad_name, check_entries  # noqa: F401 — the entry rules, shared
from assistant_x.core import card as C
from assistant_x.core import config as settings
from assistant_x.core.txn import Journal, exists, is_link, lp, move as txn_move

JOURNAL = "install.journal.json"
RETRIES, RETRY_S = 5, 2.0  # a file held by another program (Claude, an antivirus): tried again this often


class Stop(SystemExit):
    """The install stops; the journal stays (unless nothing was changed yet)."""


# ---------- the names of a package ----------


def extract(pkg, dst):
    """Every file of the package into dst, each of the size declared; then the checksums."""
    total = 0
    for name in pkg.names():
        target = lp(os.path.join(dst, *name.split("/")))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with pkg.open(name) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out, 1 << 20)
        if os.path.getsize(target) != pkg.size(name):
            raise Stop(f"{name}: {os.path.getsize(target)} bytes extracted, {pkg.size(name)} declared")
        total += os.path.getsize(target)
    with P.Package(dst) as staged:
        bad = staged.verify()
    if bad:
        raise Stop("The package is damaged: " + "; ".join(bad[:10]))
    return total


# ---------- moves that may meet a held file ----------


def move(src, dst):
    """txn.move, tried again while another program holds the file; then Stop (the journal stays)."""
    for i in range(RETRIES):
        try:
            return txn_move(src, dst)
        except PermissionError as e:
            if i == RETRIES - 1:
                raise Stop(
                    f"{src} is held by another program ({e.strerror}): close Claude Desktop (and Claude Code), "
                    "then assistant-x base install PACKAGE --resume"
                ) from e
            time.sleep(RETRY_S)


def run_moves(jr, key, moves, root):
    """The moves [(src, dst)] (workspace paths with '/') of a step; each noted in jr.data[key] when done. A move whose
    source is gone and whose target is there counts as done (a power cut between the move and the note)."""
    done = set(jr.data.setdefault(key, []))
    made = jr.data.setdefault("made_dirs", [])  # the folders the moves make: a rollback removes these, no other
    for k, (src, dst) in enumerate(moves):
        if k in done:
            continue
        s, d = within(root, src), within(root, dst)
        if exists(s):
            if exists(d):
                raise Stop(f"{dst} is taken already")
            new = [p for p in new_folders(root, dst) if p not in made]
            if new:
                made.extend(new)
                jr.save()  # noted before the move: a power cut after it still knows the folders
            move(s, d)
        elif not exists(d):
            raise Stop(f"{src} is gone and {dst} is not there")
        jr.data[key].append(k)
        jr.save()


def new_folders(root, rel):
    """The folders ('/' between them) a move to rel makes: its parents that do not exist yet, the outermost first."""
    out, parent = [], rel.rsplit("/", 1)[0] if "/" in rel else ""
    while parent and not exists(within(root, parent)):
        out.insert(0, parent)
        parent = parent.rsplit("/", 1)[0] if "/" in parent else ""
    return out


def within(root, rel):
    """The path of rel ('/' between folders) under root; Stop when it would leave root (a path of a card of a package
    is data from someone else: nothing outside the workspace is ever moved or removed)."""
    why = P.bad_path(rel)
    p = os.path.join(root, *rel.split("/"))
    if why or not P.inside(p, root):
        raise Stop(f"{rel}: refused, a path that leaves {root} ({why or 'outside'})")
    return p


def two_phase(renames):
    """(phase one, phase two) of renames [(old, new)]: every file to a temporary name first, so a swap works."""
    one = [(old, f"{old}.ax-renumber-{k}") for k, (old, _) in enumerate(renames)]
    two = [(f"{old}.ax-renumber-{k}", new) for k, (old, new) in enumerate(renames)]
    return one, two


# ---------- the small files of the index ----------

SMALL = (
    "cards",
    "codes.json",
    "packages.json",
    "manifest.tsv",
    "ocr_quality.tsv",
    "intake_events.tsv",
    "journal.md",
    "CATALOG.md",
    "sources_to_update.md",
)


def backup(w, ident):
    """The small files of the index and the settings into .assistant_x\\backups\\<time>-before-<id>.zip."""
    folder = w.data / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{datetime.datetime.now():%Y%m%d-%H%M%S}-before-{ident}.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name in SMALL:
            p = w.index / name
            if p.is_dir():
                for f in sorted(p.glob("*.json")):
                    z.write(f, f"index/{name}/{f.name}")
            elif p.is_file():
                z.write(p, f"index/{name}")
        for f in (w.config, w.root / "questions.md", w.root / "eval_baseline.json"):
            if f.is_file():
                z.write(f, f.name)
    return str(path)


def restore(w, path, made=None):
    """The small files of a backup back in place. made: the names of the cards the transaction put in place (placed or
    renamed to); of these, the ones the backup has not are removed — a card anyone else made since stays. None: every
    card the backup has not (the cards folder as it was)."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        cards = {n.split("/")[-1] for n in names if n.startswith("index/cards/")}
        for p in w.cards.glob("*.json"):
            if p.name not in cards and not p.name.startswith("_") and (made is None or p.name in made):
                p.unlink()
        for name in names:
            dst = w.index / name[len("index/") :] if name.startswith("index/") else w.root / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(z.read(name))
        for name in SMALL:
            p = w.index / name
            if p.is_file() and f"index/{name}" not in names:
                p.unlink()


# ---------- the settings of an empty workspace ----------


def adopt(w, profile, languages):
    """An empty workspace takes the profile and the card languages of the package (assistant_x.toml rewritten in
    these two places only, its comments kept)."""
    from assistant_x.core import lang

    profile = profile or settings.PROFILE
    if profile not in settings.profiles() or any(x != "en" and x not in lang.available() for x in languages):
        raise Stop(f"the package names a profile or languages this program has not: {profile!r}, {languages!r}")
    text = w.config.read_text(encoding="utf-8") if w.config.is_file() else ""
    line = f"profile = {settings.toml_value(profile)}"  # escaped: a value never becomes TOML of its own
    text = (
        re.sub(r"(?m)^\s*profile\s*=.*$", lambda _: line, text, count=1)
        if re.search(r"(?m)^\s*profile\s*=", text)
        else line + "\n" + text
    )
    order = (
        [x for x in languages if x != "en"] + ["en"]
        if "en" in languages and languages != ["en"]
        else [x for x in languages if x != "en" or languages == ["en"]]
    )
    langs = f"languages = {settings.toml_value(order)}"
    m = re.search(r"(?m)^\[documents\]\s*$", text)
    if not m:
        text = text.rstrip("\n") + f"\n\n[documents]\n{langs}\n"
    else:
        rest = text[m.end() :]
        nxt = re.search(r"(?m)^\[", rest)
        block = rest[: nxt.start()] if nxt else rest
        if re.search(r"(?m)^\s*languages\s*=", block):
            block = re.sub(r"(?m)^\s*languages\s*=.*$", lambda _: langs, block, count=1)
        else:
            block = f"\n{langs}" + block
        text = text[: m.end()] + block + (rest[nxt.start() :] if nxt else "")
    w.config.write_text(text, encoding="utf-8", newline="\n")


# ---------- running the commands of the base ----------


def run_main(main, prog, args):
    """main() of a command as if it were run (sys.argv); its exit code, None for a normal end."""
    argv = sys.argv
    sys.argv = [prog, *args]
    try:
        return main()
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (print(e.code) or 1)
    finally:
        sys.argv = argv


def base_is_current(cfg):
    """True when the base in use can be updated (its schema and chunk version are of this program)."""
    from assistant_x.core.common import BASE_SCHEMA, CHUNK_VERSION, connect, meta

    if not os.path.exists(cfg["db"]):
        return True
    con = connect(cfg["db"], readonly=True)
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='docs'").fetchone():
            return True
        return (meta(con, "base_schema") or "1") == BASE_SCHEMA and meta(con, "chunk_version", "1") == CHUNK_VERSION
    finally:
        con.close()


# ---------- the plan ----------


def make_plan(report, answers, pcards, own):
    """{mapping, renumbered, package_mapping, skip, replace, merged, adopt, choose} of an install from the report of
    inspect: the merges by the rule (a package document that loses is not installed: skip; a library document that
    loses goes aside: replace); when the library keeps its numbering, a package document that wins takes the code of
    the library document it replaces (the same shelf)."""
    codes = report["codes"]
    merged = [m for m in report["matches"] if m.get("keep")]
    skip = sorted({m["package"] for m in merged if m["keep"] == "library"})
    replace = sorted({m["library"] for m in merged if m["keep"] == "package"})
    takeover = {}  # the library keeps its numbering: a package document that wins takes the code it replaces
    if codes["keeper"] == "own":
        for m in merged:
            if m["keep"] == "package" and m["package"][0] == m["library"][0]:
                takeover[m["package"]] = m["library"]
    # a skipped package document, or a library document it replaces, frees its code: no collision there (unless a
    # package document takes that code over: then the package document of the same code still needs a new one)
    taken = set(takeover.values())
    mapping = {
        k: v
        for k, v in codes["mapping"].items()
        if k not in skip and (k not in replace or (k in taken and takeover.get(k) != k))
    }
    renumbered = codes["renumbered"] if mapping else ""
    package_mapping = dict(mapping) if renumbered == "package" else {}
    package_mapping.update({k: v for k, v in (codes.get("retired") or {}).items() if k not in skip})
    package_mapping.update(takeover)
    package_mapping = {k: v for k, v in package_mapping.items() if k != v}
    return {
        "mapping": mapping,
        "renumbered": renumbered,
        "keeper": codes["keeper"],
        "package_mapping": package_mapping,
        "skip": skip,
        "replace": replace,
        "merged": merged,
        "adopt": report["compatibility"].get("adopt"),
        "choose": bool(mapping) and not codes["renumbered"],
    }


def other_package(jr, identity):
    """Why the package given is not the one the interrupted transaction of the journal started with (its manifest and
    checksums, package.identity), or '': --resume and --rollback take the very same package."""
    had = (jr.data or {}).get("identity")
    if had and had != identity:
        return (
            f"This is not the package the interrupted {jr.data.get('kind', 'install')} started with "
            f"({jr.data.get('package')}, version {jr.data.get('version')}): give that very file to --resume or "
            "--rollback; nothing changed."
        )
    return ""


def staging(w, ident):
    """The work folder of an install: short, so the deep paths of the library fit under it."""
    import hashlib

    return w.data / "w" / hashlib.sha256(ident.encode()).hexdigest()[:8]


# ---------- the install ----------


def install(
    path, confirm=False, keep=None, answers=None, own_apart=False, resume=False, rollback=False, config=None, say=print
):
    """Install the package at path; 0 when it is installed (or only planned without confirm), 1 when it cannot."""
    from assistant_x.core import lock
    from assistant_x.core.common import clear_maintenance, load_config

    w, raw = settings.load(config)
    cfg = load_config(config)
    with P.Package(path) as pkg:
        man, identity = pkg.manifest, pkg.identity()
    ident, version = man["id"], man["version"]
    stage = staging(w, ident)
    jr = Journal(stage / JOURNAL)
    other = other_package(jr, identity)
    if other:
        say(other)
        return 1
    if rollback:
        if not jr.data:
            say("Nothing to undo: no install of this package was interrupted.")
            return 1
        with lock.heavy_task("base install"), lock.hold(w.work, "base install"):
            return undo(w, cfg, jr, stage, say)
    if jr.data and jr.data.get("kind", "install") != "install":
        say(
            f"An {jr.data['kind']} of {ident} was interrupted: finish it first (assistant-x base {jr.data['kind']} … "
            "--resume, or --rollback)."
        )
        return 1
    if jr.data and not resume:
        say(
            f"An install of {ident} was interrupted (started {jr.data['started']}, done: "
            f"{', '.join(jr.data['steps']) or 'nothing'}): assistant-x base install PACKAGE --resume, or --rollback"
        )
        return 1
    if resume and not jr.data:
        say("Nothing to resume: no install of this package was interrupted.")
        return 1
    if keep is None and (answers or {}).get("codes") in ("own", "package"):
        keep = answers["codes"]  # the answer to the question of the codes is the --keep of the install
    if not jr.data:
        installed = registry.get(w.index, ident)
        if installed and installed.get("version") == version:
            say(f"The package {ident} {version} is installed already: nothing to do.")
            return 0
        report = I.inspect(cfg, raw, path, work=str(w.work), keep=keep)
        if not confirm:
            say(I.text(report))
            say("Nothing changed. To install: the same command with --confirm (answers to the questions: --answers).")
            return 0 if report["ok"] else 1
        if not report["ok"]:
            say(I.text(report))
            return 1
        if make_plan(report, answers, None, None)["choose"]:
            c = report["codes"]
            say(
                f"The codes of the package and of the library collide in {len(c['mapping'])} documents and this is not a "
                "reference package: choose --keep package (the package keeps its codes, the colliding documents of the "
                "library get new codes) or --keep own (the package goes after the numbering of the library, its "
                "colliding documents get new codes). Nothing changed."
            )
            return 1
        with P.Package(path) as pkg:
            problems = check_entries(pkg)
        if problems:
            say("The package is refused, nothing changed:")
            for p in problems[:30]:
                say(f"  {p}")
            return 1
    else:
        report = jr.data["report"]
    date = jr.data["date"] if jr.data else datetime.date.today().isoformat()
    try:
        with lock.heavy_task("base install"), lock.hold(w.work, "base install"):
            from assistant_x.intake.build import code_lock, CODES_LOCK

            lock_f = code_lock(w.index)
            if lock_f is None:
                say(f"Another process holds {w.index / CODES_LOCK}: run the install again when it has ended.")
                return 1
            try:
                if not jr.data:
                    stage.mkdir(parents=True, exist_ok=True)
                    jr.start(
                        date,
                        kind="install",
                        package=os.path.abspath(path),
                        id=ident,
                        version=version,
                        report=report,
                        identity=identity,
                    )
                run(w, cfg, raw, path, jr, stage, answers, own_apart, date, say)
            finally:
                lock_f.close()
                clear_maintenance(cfg["index_dir"])  # stopped or ended: the server must not wait for this process
    except Stop as e:
        say(f"The install stopped: {e.code}")
        if jr.data:
            say("What is done stays noted: assistant-x base install PACKAGE --resume to go on, --rollback to undo.")
        return 1
    return 0


def run(w, cfg, raw, path, jr, stage, answers, own_apart, date, say):
    from assistant_x.core.common import clear_maintenance, mark_index_stale, set_maintenance

    report, root = jr.data["report"], str(w.root)
    idx_rel, lib_rel = _rel(w.index, root), _rel(w.library, root)
    ident, version = jr.data["id"], jr.data["version"]
    pkg_dir = stage / "pkg"

    def step(name):
        return not jr.done(name)

    if step("marker"):
        set_maintenance(cfg["index_dir"], f"install of the base package {ident} {version}")
        mark_index_stale(cfg, date)
        jr.mark("marker")
    if step("backup"):
        jr.data["backup"] = backup(w, ident)
        jr.mark("backup")
    if step("extract"):
        if pkg_dir.exists():
            shutil.rmtree(pkg_dir)  # a half extraction of an interrupted run: the work folder is ours
        with P.Package(path) as pkg:
            jr.data["extracted"] = extract(pkg, str(pkg_dir))
        jr.mark("extract")
    pcards = {c: C.load(p) for c, p in C.paths(pkg_dir / "cards").items()}
    if step("plan"):
        own = {c: C.load(p) for c, p in C.paths(w.cards).items()}
        plan = make_plan(report, answers, pcards, own)
        own_moves = []
        if plan["renumbered"] == "own":
            for code in sorted(plan["mapping"]):
                for old, new in C.renames(own[code], plan["mapping"], index=idx_rel):
                    if exists(os.path.join(root, *old.split("/"))):
                        own_moves.append((old, new))
        aside = f"inbox/_to_delete/merged_{date}"
        out_moves = []  # the documents that lost a merge: of the library, and of the package (from its work folder)
        for code in plan["replace"]:
            card = own[code]
            files = [f"{idx_rel}/cards/{code}.json"] + [x for _, e in _entries(card) for x in _files(e, idx_rel)]
            out_moves += [(f, f"{aside}/{f}") for f in dict.fromkeys(files) if exists(os.path.join(root, *f.split("/")))]
        src_rel = _rel(pkg_dir, root)
        for code in plan["skip"]:
            card = pcards[code]
            files = [f"cards/{code}.json"] + [re.sub(r"^index/", "", x) for _, e in _entries(card) for x in _files(e)]
            out_moves += [
                (f"{src_rel}/{f}", f"{aside}/package {ident}/{f}")
                for f in dict.fromkeys(files)
                if exists(os.path.join(str(pkg_dir), *f.split("/")))
            ]
        jr.data["plan"], jr.data["own_moves"], jr.data["out_moves"] = plan, own_moves, out_moves
        jr.mark("plan")
    plan = jr.data["plan"]
    mapping = plan["mapping"]
    if step("aside"):
        run_moves(jr, "aside_done", jr.data["out_moves"], root)
        jr.mark("aside")
    one, two = two_phase([tuple(m) for m in jr.data["own_moves"]])
    if step("renames one"):
        run_moves(jr, "one_done", one, root)
        jr.mark("renames one")
    if step("renames two"):
        run_moves(jr, "two_done", two, root)
        jr.mark("renames two")
    if step("cards"):
        if plan["renumbered"] == "own":
            renumber_tables(w, mapping, date)
        if own_apart:
            for code, p in C.paths(w.cards).items():
                card = C.load(p)
                if not (card.get("intake") or {}).get("package") and not card["intake"].get("personal"):
                    card["intake"]["personal"] = True
                    C.dump(card, p)
        jr.mark("cards")
    if step("package"):  # the package side renumbered, inside the work folder (nothing holds it)
        prepare_package(pkg_dir, pcards, plan.get("package_mapping") or {}, set(plan["skip"]), ident, version)
        jr.mark("package")
    if step("place"):
        placed, src_rel = [], _rel(pkg_dir, root)
        for dp, _, fns in os.walk(lp(pkg_dir)):
            for f in fns:
                rel = os.path.relpath(os.path.join(dp, f), lp(pkg_dir)).replace(os.sep, "/")
                if rel.startswith(("cards/", "texts/")):
                    placed.append((f"{src_rel}/{rel}", f"{idx_rel}/{rel}"))
                elif rel.startswith("library/"):
                    placed.append((f"{src_rel}/{rel}", lib_rel + rel[len("library") :]))
        jr.data["placed"] = sorted(placed)
        jr.save()
        run_moves(jr, "placed_done", [tuple(m) for m in jr.data["placed"]], root)
        jr.mark("place")
    if step("tables"):
        tables(w, cfg, raw, pkg_dir, jr, date)
        jr.mark("tables")
    if step("build"):
        jr.data["full"] = build_only(config_path(w))
        jr.mark("build")
    if step("vectors"):
        jr.data["vectors"] = package_vectors(w, pkg_dir, ident)
        jr.mark("vectors")
    if step("base"):
        jr.data["base"] = build_base(config_path(w), say, full=jr.data["full"])
        jr.mark("base")
    clear_maintenance(cfg["index_dir"])
    write_report(w, jr, say)
    shutil.rmtree(stage)  # the work folder of this install: extracted package and journal
    say(f"Installed {ident} {version}: {jr.data['base'].get('documents', '?')} documents in the library.")


def config_path(w):
    return str(w.config)


def _rel(path, root):
    return os.path.relpath(str(path), root).replace(os.sep, "/")


def _entries(card):
    file = card.get("file") or {}
    return [(card["code"], file)] + [(p["code"], p) for p in file.get("parts") or []]


def _files(entry, index="index"):
    """The files of a document or a part, relative to the workspace (the text in the index folder given)."""
    code = entry.get("code") or ""
    text = re.sub(r"^index/", f"{index}/", entry.get("text") or "")
    out = [x for x in (entry.get("library"), entry.get("pdf_copy")) if x]
    if text:
        out += [text, re.sub(r"\.(md|txt)$", "", text) + ".pages.json"]
    return out + ([f"{index}/texts/{code}.md", f"{index}/texts/{code}.pages.json"] if code and not text else [])


def renumber_tables(w, mapping, date):
    """The cards of the renumbered documents of the library rewritten (they were renamed already), the tables, the
    control questions, the fingerprint caches; the events and the marks."""
    from assistant_x.core import journal
    from assistant_x.intake import manifest

    for old, new in mapping.items():
        p = w.cards / f"{new}.json"
        card = C.load(p)
        if card["code"] == old:
            C.dump(C.remap(card, mapping)[0], p)
    man = manifest.manifest_path(w.root)
    if man.exists():
        manifest.save(R.manifest_rows(manifest.load(man), mapping), man)
    p = w.index / "ocr_quality.tsv"
    if p.exists():
        p.write_text(R.tsv_codes(p.read_text(encoding="utf-8"), mapping), encoding="utf-8", newline="\n")
    q = w.root / "questions.md"
    if q.exists():
        text, odd = R.questions_text(q.read_text(encoding="utf-8"), mapping)
        q.write_text(text, encoding="utf-8", newline="\n")
    b = w.root / "eval_baseline.json"
    if b.exists():
        b.write_text(
            json.dumps(
                R.any_json(json.loads(b.read_text(encoding="utf-8")), mapping), ensure_ascii=False, indent=1, sort_keys=True
            ),
            encoding="utf-8",
        )
    for f in R.fingerprint_files([str(w.fingerprints)], list(mapping) + list(mapping.values())):
        os.remove(f)
    journal.append_events(w.index / "intake_events.tsv", R.events(date, mapping))
    C.raise_high_water(w.index, mapping.values())


def prepare_package(pkg_dir, pcards, mapping, skip, ident, version):
    """The package in its work folder as it goes into the library: the skipped documents out, the renumbered ones
    under their new codes (cards rewritten, files renamed), every card naming the package."""
    root = str(pkg_dir)

    def here(path):  # a path of a card ("index/texts/...", "library/...") in the package folder
        return re.sub(r"^index/", "", path)

    for code in skip:
        card = pcards.pop(code)
        for f in [f"cards/{code}.json"] + [here(x) for _, e in _entries(card) for x in _files(e)]:
            p = within(root, f)
            if os.path.exists(lp(p)):
                os.remove(lp(p))
    renames = []
    for code, card in pcards.items():
        for old, new in C.renames(card, mapping):
            old, new = here(old), here(new)
            if os.path.exists(lp(os.path.join(root, *old.split("/")))):
                renames.append((old, new))
    one, two = two_phase(renames)
    for src, dst in one + two:
        txn_move(within(root, src), within(root, dst))
    for code, card in pcards.items():
        new = I.as_installed(C.remap(card, mapping)[0], code, {"id": ident, "version": version})
        C.dump(new, Path(root) / "cards" / f"{new['code']}.json")
    p = Path(root) / "ocr_quality.tsv"
    if p.exists():  # the scores of the documents that go in, under their codes here
        lines = p.read_text(encoding="utf-8").splitlines()
        rows = [lines[0]] + [ln for ln in lines[1:] if C.main_code(ln.split("\t")[0]) not in skip]
        p.write_text(R.tsv_codes("\n".join(rows) + "\n", mapping), encoding="utf-8", newline="\n")
    (Path(root) / "mapping.json").write_text(json.dumps({"mapping": mapping, "skip": sorted(skip)}), encoding="utf-8")


def tables(w, cfg, raw, pkg_dir, jr, date):
    """The tables of the index after the documents of the package are in place."""
    from assistant_x.core import journal
    from assistant_x.intake import manifest
    from assistant_x.intake.tools import ocr_score
    from assistant_x.search import catalog

    plan = jr.data["plan"]
    ident, version = jr.data["id"], jr.data["version"]
    if plan.get("adopt"):
        adopt(w, plan["adopt"]["profile"], plan["adopt"]["card_languages"])
        from assistant_x.core import workspace as ws_mod

        ws_mod.reset()
    p = pkg_dir / "ocr_quality.tsv"
    if p.exists():
        rows = ocr_score.read_tsv(w.index / ocr_score.TSV_NAME)
        rows.update(ocr_score.read_tsv(p))
        ocr_score.write_tsv(w.index / ocr_score.TSV_NAME, rows)
    codes = {c: C.load(p) for c, p in C.paths(w.cards).items()}
    mine = {c: card for c, card in codes.items() if ((card.get("intake") or {}).get("package") or {}).get("id") == ident}
    pm = plan.get("package_mapping") or {}
    events = [
        [
            date,
            "—",
            "—",
            "—",
            code,
            (card.get("file") or {}).get("library", "—").replace("/", "\\"),
            f"done: installed from package {ident} {version}"
            + (
                f" (its code there {card['intake']['package']['code']})" if card["intake"]["package"]["code"] != code else ""
            ),
        ]
        for code, card in sorted(mine.items())
    ]
    if pm:
        events += R.events(date, pm, why=f"renumbered in package {ident}")
    journal.append_events(w.index / "intake_events.tsv", events)
    C.raise_high_water(w.index, codes)
    registry.put(
        w.index,
        {
            "id": ident,
            "version": version,
            "name": jr.data["report"]["package"].get("name") or {},
            "installed": date,
            "documents": len(mine),
            "manifest_sha": _sha((pkg_dir / P.MANIFEST).read_bytes()),
        },
    )
    for m in plan.get("merged") or []:  # the one that lost a merge, aside: never deleted
        lost, kept = (m["library"], m["package"]) if m["keep"] == "package" else (m["package"], m["library"])
        where = "of the library" if m["keep"] == "package" else f"of package {ident}"
        journal.append_events(
            w.index / "intake_events.tsv",
            [
                [
                    date,
                    "—",
                    "—",
                    "—",
                    lost,
                    f"inbox\\_to_delete\\merged_{date}\\",
                    f"to delete: merged ({m['kind']}), the document {where} lost to {kept}: {m['why']}",
                ]
            ],
        )
    catalog.write(w.index, date, profile=settings.load(str(w.config))[1])
    manifest.main(["--root", str(w.root)])
    journal.sync(w.index)


def _sha(data):
    import hashlib

    return hashlib.sha256(data).hexdigest()


def package_vectors(w, pkg_dir, ident):
    """The checked vectors of the package into the vector cache (base/vectors.install), for its documents here."""
    from assistant_x.base import vectors as V

    codes = [
        c for c, p in C.paths(w.cards).items() if ((C.load(p).get("intake") or {}).get("package") or {}).get("id") == ident
    ]
    return V.install(str(w.config), str(pkg_dir), ident, codes)


def build_only(config):
    """assistant-x build of the workspace (--full when the base is of another schema); Stop when it fails: no embed
    and no vectors on a base that did not build. Returns whether it was full."""
    from assistant_x.core.common import load_config
    from assistant_x.search import build_index

    full = not base_is_current(load_config(config))
    rc = run_main(build_index.main, "build_index.py", ["--config", config] + (["--full"] if full else []))
    if rc not in (None, 0):  # the transaction stops, its journal kept
        raise Stop(
            f"assistant-x build ended with {rc} (assistant-x check shows the errors): solve them, then --resume, "
            "or --rollback"
        )
    return full


def build_base(config, say, full=None):
    """build (unless done already: full given), embed and check of the workspace; {documents, embedded, checked,
    notes}."""
    from assistant_x.core.common import load_config
    from assistant_x.search import check_index, embed

    if full is None:
        full = build_only(config)
    notes = []
    rc = run_main(embed.main, "embed.py", ["--config", config])
    embedded = rc in (None, 0)
    if not embedded:
        notes.append(
            "the embeddings are not complete (no model here, or no video card): the search goes by words "
            "for the new fragments until assistant-x embed has run"
        )
    errors = check_index.run(load_config(config), quiet=True)
    if errors:
        notes.append(f"assistant-x check finds {errors} errors")
    return {
        "documents": len(C.paths(load_config(config)["cards_dir"])),
        "full": full,
        "embedded": embedded,
        "check_errors": errors,
        "notes": notes,
    }


def write_report(w, jr, say):
    d = jr.data
    plan, base = d["plan"], d.get("base") or {}
    lines = [
        f"# Install of the base package {d['id']} {d['version']}",
        "",
        f"Date: {d['date']}. Package: {d['package']}. Backup of the index: {d.get('backup')}.",
        "",
        f"Codes: {d['report']['codes']['why']}.",
    ]
    if plan["mapping"]:
        side = "this library" if plan["renumbered"] == "own" else "the package"
        lines += ["", f"New codes of {side}:", ""] + [f"- {a} -> {b}" for a, b in sorted(plan["mapping"].items())]
    codes = d["report"]["codes"]
    if codes.get("retired"):
        lines += [
            "",
            "Package codes once given here to documents since removed (a number never comes back), new codes:",
            "",
        ] + [f"- {a} -> {b}" for a, b in sorted(codes["retired"].items())]
    if codes.get("reused"):
        lines += [
            "",
            "Codes once given here and reused by the reference numbering of the package: " + ", ".join(codes["reused"]),
        ]
    merged = plan.get("merged") or []
    if merged:
        lines += ["", "Merged by the rule (the other one to inbox\\_to_delete\\merged_<date>, never deleted):", ""]
        lines += [
            f"- {m['kind']}: kept {m['package'] if m['keep'] == 'package' else m['library']} "
            f"({'package' if m['keep'] == 'package' else 'library'}), moved "
            f"{m['library'] if m['keep'] == 'package' else m['package']} — {m['why']}"
            for m in merged
        ]
    alike = [m for m in d["report"]["matches"] if not m.get("keep")]
    if alike:
        lines += ["", "Alike but kept separate: " + ", ".join(f"{m['package']} ~ {m['library']}" for m in alike)]
    if plan.get("adopt"):
        lines += [
            "",
            f"The workspace took the profile {plan['adopt']['profile']} and the card languages "
            f"{', '.join(plan['adopt']['card_languages'])} of the package.",
        ]
    vec = d.get("vectors") or {}
    lines += [
        "",
        f"Vectors from the package: {vec.get('added', 0)} of {vec.get('offered', 0)}"
        + (f" (check by encoding again: {vec['verified']})" if vec.get("verified") else "")
        + (f"; {vec['note']}" if vec.get("note") else "")
        + ". Base: "
        f"{'built anew' if base.get('full') else 'updated'}, "
        f"{'every fragment embedded' if base.get('embedded') else 'embeddings to complete'}, "
        f"check errors {base.get('check_errors', '?')}.",
    ]
    lines += [f"- {n}" for n in base.get("notes") or []]
    w.reports.mkdir(parents=True, exist_ok=True)
    path = w.reports / f"base_install_{d['id']}_{datetime.datetime.now():%Y%m%d-%H%M%S}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    for n in base.get("notes") or []:
        say(f"Note: {n}")
    say(f"Report: {path}")


def undo(w, cfg, jr, stage, say):
    """Undo an interrupted install: the moves back in the reverse order, the small files of the backup back, the
    marker gone, the work folder emptied. The base is marked behind (assistant-x build brings it level)."""
    from assistant_x.core.common import clear_maintenance, mark_index_stale

    root = str(w.root)
    d = jr.data
    plan = d.get("plan") or {}
    one, two = two_phase([tuple(m) for m in d.get("own_moves") or []])
    placed = [tuple(m) for m in d.get("placed") or []]  # the sources name the work folder already
    for key, moves in (
        ("placed_done", placed),
        ("two_done", two),
        ("one_done", one),
        ("aside_done", [tuple(m) for m in d.get("out_moves") or []]),
    ):
        for k in sorted(d.get(key) or [], reverse=True):
            src, dst = moves[k]
            s, t = within(root, src), within(root, dst)
            if exists(t) and not exists(s):
                move(t, s)
    if d.get("backup") and os.path.exists(d["backup"]):
        made = {t.rsplit("/", 1)[-1] for _, t in list(placed) + list(two) if "/cards/" in f"/{t}"}
        restore(w, d["backup"], made)
    for f in R.fingerprint_files(
        [str(w.fingerprints)], list(plan.get("mapping") or {}) + list((plan.get("mapping") or {}).values())
    ):
        os.remove(f)
    for rel in sorted(d.get("made_dirs") or [], key=lambda x: x.count("/"), reverse=True):  # those the moves made
        p = within(root, rel)
        if os.path.isdir(lp(p)) and not is_link(p) and not os.listdir(lp(p)):
            os.rmdir(lp(p))
    clear_maintenance(cfg["index_dir"])
    mark_index_stale(cfg, datetime.date.today().isoformat())
    shutil.rmtree(stage)
    say(f"The install of {d['id']} {d['version']} is undone; run assistant-x build to bring the search base level.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="assistant-x base install")
    ap.add_argument("package")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--keep", choices=("own", "package"))
    ap.add_argument("--answers")
    ap.add_argument("--own-apart", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--config")
    a = ap.parse_args(argv)
    answers = json.loads(Path(a.answers).read_text(encoding="utf-8")) if a.answers else None
    try:
        return install(
            a.package,
            confirm=a.confirm,
            keep=a.keep,
            answers=answers,
            own_apart=a.own_apart,
            resume=a.resume,
            rollback=a.rollback,
            config=a.config,
        )
    except P.PackageError as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    sys.exit(main())
