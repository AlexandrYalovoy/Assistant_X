# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""assistant-x base inspect: what installing a base package into this workspace would do, changing nothing.

    assistant-x base inspect PACKAGE [--keep own|package] [--json OUT.json] [--no-verify]

The report (also as JSON, for Claude: the questions to put to the user are in "questions"):
  problems        what stops the install: another card schema or text format, damaged files, cards that do not pass
                  the languages, shelves and topics of this workspace, an intake batch built but not applied, paths
                  over 255 characters without long paths in Windows, too little disk space
  warnings        what the user should know: Claude holds the library (its files are released during the install), a
                  workspace in OneDrive, a package made by a newer version, the package installed already
  compatibility   the format, card schema, text format and chunk version; profile, card languages and topics of the
                  package against the workspace (an empty workspace takes the ones of the package)
  matches         package documents that look like documents of the library and what happens to them, by rule
                  (classify): the same file or the same content — one stays; another edition — the newer stays; the
                  rest stays separate. No question: the report of the install lists every pair.
  codes           who keeps the codes when they collide: the user's choice, "package" or "own" (code_plan); a
                  reference package recommends "package"; an empty workspace takes the package's codes as they are
  disk, embed     the space the install needs and the time of the embeddings it has to compute
"""

import argparse, json, os, re, shutil, sys

from assistant_x.base import package as P, registry, vectors as package_vectors
from assistant_x.core import card as C
from assistant_x.core import config as settings
from assistant_x.core.formats import TEXT_FORMAT

MAX_PATH = 255  # a path longer than this needs long paths enabled in Windows (MAX_PATH 260)
STAGING = os.path.join(".assistant_x", "w", "12345678")  # the extraction folder of an install (stage 4)
CPU_S = 0.8  # seconds per fragment of bge-m3 on a processor, as embed.CPU_S
CHARS_PER_FRAGMENT = 900  # common.CHUNK_TARGET: a text gives about one fragment per this many characters


def _version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v or "0")))


def long_paths_enabled():
    """Does Windows take paths over 260 characters (LongPathsEnabled)? True elsewhere."""
    if os.name != "nt":
        return True
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as k:
            return bool(winreg.QueryValueEx(k, "LongPathsEnabled")[0])
    except OSError:
        return False


def onedrive(root):
    """The OneDrive folder root is in, or ''."""
    r = os.path.normcase(os.path.abspath(root))
    for k in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        d = os.environ.get(k)
        if d and (r + os.sep).startswith(os.path.normcase(os.path.abspath(d)) + os.sep):
            return d
    return ""


def pending_batches(work):
    """The intake batches of the work folder built but not applied, or whose apply was interrupted; and the intake
    lock when its owner is alive."""
    from assistant_x.core import lock

    out = []
    if not os.path.isdir(work):
        return out
    for name in sorted(os.listdir(work)):
        o = os.path.join(work, name, "out")
        if os.path.exists(os.path.join(o, "applied.json")):
            continue
        if os.path.exists(os.path.join(o, "apply.journal.json")):
            out.append(f"{name}: an apply was interrupted (assistant-x intake apply --resume)")
        elif os.path.exists(os.path.join(o, "moves.json")):
            out.append(f"{name}: built and not applied (assistant-x intake apply, or delete the batch)")
    owner = lock.read(os.path.join(work, lock.NAME))
    if owner and owner.get("pid") and lock.alive(int(owner["pid"]), owner.get("ts")):
        out.append(f"an intake is running: {owner.get('command', '?')} (process {owner['pid']})")
    return out


def server_running():
    """Does a search server of Assistant X hold its models lock (Claude Desktop or Claude Code is open)?"""
    from assistant_x.core import lock

    try:
        f = lock.exclusive(lock.server_lock_path())
    except OSError:
        return False
    if f is None:
        return True
    f.close()  # closing frees the byte lock taken just now
    return False


def package_cards(pkg):
    """{code: card} of the package (a card that does not read: under its file name with the error)."""
    out, bad = {}, {}
    for name in pkg.names():
        m = re.fullmatch(r"cards/([A-Z]-\d{5})\.json", name)
        if not m:
            continue
        try:
            out[m[1]] = C.migrate(json.loads(pkg.read(name).decode("utf-8")))
        except (ValueError, C.CardError) as e:
            bad[m[1]] = str(e)
    return out, bad


def as_installed(card, code, man):
    """The card as the install writes it (install.prepare_package): intake.package names this package and keeps the
    code the document has in it; inspect validates this form, so a bad value fails here, not at the build."""
    out = json.loads(json.dumps(card))
    intake = out.get("intake") if isinstance(out.get("intake"), dict) else {}
    pkg = intake.get("package") if isinstance(intake.get("package"), dict) else {}
    intake["package"] = dict(pkg, id=man.get("id"), version=man.get("version"), code=pkg.get("code") or code)
    out["intake"] = intake
    return out


def unsafe_paths(card):
    """[problems] of the paths of a card of a package: every file it names must be under library/ (the original, its
    PDF copy) or index/texts/ (the text), with no '..', drive, colon or device name — a package is data from someone
    else, and these paths are moved and removed by the install."""
    out = []
    file = card.get("file") if isinstance(card.get("file"), dict) else {}
    entries = [file] + [p for p in file.get("parts") or [] if isinstance(p, dict)]
    for e in entries:
        for key, top in (("library", "library/"), ("pdf_copy", "library/"), ("text", "index/texts/")):
            v = e.get(key)
            if v in (None, ""):
                continue
            why = P.bad_path(v) if isinstance(v, str) else "not a string"
            if not why and not v.startswith(top):
                why = f"not under {top}"
            if why:
                out.append(f"{key} {v!r}: {why}")
    return out


def lineage(index, ident):
    """The codes this package's own documents had here under their package code (intake_events.tsv: "installed from
    package <id>" with no "its code there"): a number of these may come back for the same package document."""
    from assistant_x.core import journal

    out = set()
    for r in journal.read_events(os.path.join(index, "intake_events.tsv")):
        if f"installed from package {ident} " in r[6] and "its code there" not in r[6]:
            out.add(r[4])
    return out


def code_plan(own, pkg_codes, high, keep=None, codes="default", lineage=()):
    """Who keeps the codes when the codes of the package and of the library collide — the user's choice:
    "package" (keep the codes of the package: the colliding documents of the library get new codes) or "own" (append
    the package after the numbering of the library: the colliding documents of the package get new codes). The new
    codes are the next free numbers above both sides and the marks of index/codes.json (mapping). A reference package
    (codes "reference": its codes are the same for everyone who installs it) recommends "package" and takes it when no
    one chose; a default one recommends nothing, and then keeper stays None: the install asks for --keep. An empty
    workspace takes the codes of the package, no choice. Facts only, for Claude to put to the user in their language.

    A number never comes back (core/card.py, index/codes.json): a package code at or below the mark of its letter
    that no document here has now was given to a document since removed, and an old citation of it must not name
    another document. Such a code is "retired": the package document gets a new code (retired: package code -> new
    code), whoever keeps the codes; unless the package is a reference one and its numbering is kept (the reuse is then
    listed in "reused" for the report), or this package's own document had that code here before (lineage)."""
    reference = codes == "reference"
    collide = sorted(set(own) & set(pkg_codes))
    used = dict(high)
    for code in list(own) + list(pkg_codes):
        m = C.CODE_RX.match(code)
        used[m["letter"]] = max(used.get(m["letter"], 0), int(m["num"]))
    lineage = set(lineage)
    retired_codes = sorted(
        c
        for c in pkg_codes
        if c not in own and c not in lineage and int(C.CODE_RX.match(c)["num"]) <= int(high.get(c[0], 0))
    )
    facts = {
        "own_documents": len(own),
        "package_documents": len(pkg_codes),
        "collisions": len(collide),
        "package_codes": codes,
    }

    def retire(keeper):
        if reference and keeper == "package":
            return {}, retired_codes
        out = {}
        for code in retired_codes:
            used[code[0]] += 1
            out[code] = C.new_code(code[0], used[code[0]])
        return out, []

    if not own:
        retired, reused = retire("package")
        return {
            "keeper": "package",
            "renumbered": "",
            "mapping": {},
            "recommended": None,
            "options": {},
            "why": "empty workspace: the package keeps its codes",
            "retired": retired,
            "reused": reused,
            **facts,
        }
    mapping = {}
    for code in collide:
        letter = code[0]
        used[letter] += 1
        mapping[code] = C.new_code(letter, used[letter])
    recommended = "package" if reference else None
    if keep in ("own", "package"):
        keeper, why = keep, f"chosen: keep {keep}"
    elif not mapping:
        keeper, why = "package", "no collision"
    elif reference:
        keeper, why = "package", "reference package: its codes are kept unless the user chooses own"
    else:
        keeper, why = None, "default package: the user chooses (keep package or own)"
    retired, reused = retire(keeper)
    options = (
        {
            "package": {"renumbered": "own", "codes_changed": len(mapping)},
            "own": {"renumbered": "package", "codes_changed": len(mapping)},
        }
        if mapping
        else {}
    )
    return {
        "keeper": keeper,
        "renumbered": ("package" if keeper == "own" else "own") if mapping and keeper else "",
        "mapping": mapping,
        "why": why,
        "recommended": recommended,
        "options": options,
        "retired": retired,
        "reused": reused,
        **facts,
    }


def year_of(card):
    """The year of the edition of a document: the year at the end of its designation (GOST 1510-84: 1984; the edition
    of a standard), else doc.year, else None."""
    from assistant_x.intake import versions

    doc = card.get("doc") or {}
    for d in C.all_texts(doc.get("designation")):
        m = versions.YEAR_TAIL.search(d)
        if m:
            y = int(re.sub(r"\D", "", m.group(0)))
            return y if y > 999 else (1900 + y if y > 30 else 2000 + y)
    return doc["year"] if isinstance(doc.get("year"), int) else None


def classify(pcard, lcard, share, pscore, lscore):
    """What happens to a package document and a library document that look alike (no question:
    the user is told in the report): {kind, keep: "package" | "library" | None, why}.
      same_file      the same sha256 of the original: the one of the library stays
      same_content   the same text (dupcheck share >= THRESHOLDS["same"]) and the same designation without its year
                     (or neither has one): the higher recognition score stays, a tie keeps the library's
      newer_edition  the same designation without its year, another edition: the newer one stays (an unknown or equal
                     year keeps the library's)
      separate       anything less (a similar title, a partial overlap): both stay, nothing moves"""
    from assistant_x.intake import versions
    from assistant_x.intake.tools import dupcheck

    psha, lsha = (pcard.get("file") or {}).get("sha256"), (lcard.get("file") or {}).get("sha256")
    if psha and psha == lsha:
        return {"kind": "same_file", "keep": "library", "why": "the same file (sha256)"}
    pd, ld = (
        C.all_texts((pcard.get("doc") or {}).get("designation")),
        C.all_texts((lcard.get("doc") or {}).get("designation")),
    )
    same_key = (not pd and not ld) or any(versions.key(x) == versions.key(y) for x in pd for y in ld if versions.key(x))
    same_norm = any(versions.norm(x) == versions.norm(y) for x in pd for y in ld)
    if share is not None and share >= dupcheck.THRESHOLDS["same"] and same_key:
        ps, ls = pscore if pscore is not None else -1, lscore if lscore is not None else -1
        keep = "package" if ps > ls else "library"
        return {
            "kind": "same_content",
            "keep": keep,
            "why": f"the same text ({share:.0%} of the phrases), recognition score {pscore} in the package, "
            f"{lscore} in the library",
        }
    if pd and ld and same_key and not same_norm:
        py, ly = year_of(pcard), year_of(lcard)
        keep = "package" if py and ly and py > ly else "library"
        return {
            "kind": "newer_edition",
            "keep": keep,
            "why": f"another edition: {pd[0]} ({py}) in the package, {ld[0]} ({ly}) in the library",
        }
    return {"kind": "separate", "keep": None, "why": "alike, but not the same document: both stay"}


class ShingleIndex:
    """The fingerprints of the library texts (dupcheck: sampled shingle hashes) as an inverted index, shingle ->
    codes: the texts that share enough shingles with a package text are found without comparing it with every
    library text (10 000 x 10 000 set intersections took hours). A shingle of more than COMMON texts (boilerplate) is
    not listed; it still counts for every text when the candidates are bounded, so no pair is missed, and the share of
    a candidate is computed exactly."""

    COMMON = 50

    def __init__(self, fps):
        self.fps, posting = fps, {}
        for code, fp in fps.items():
            for s in fp:
                posting.setdefault(s, []).append(code)
        self.common = {s for s, codes in posting.items() if len(codes) > self.COMMON}
        self.posting = {s: codes for s, codes in posting.items() if s not in self.common}

    def best(self, fp, skip=(), least=0.0):
        """(share, code) of the library text that shares the most of fp (share = |fp & its| / |fp|), among those not in
        skip, when it reaches least; (0, None) otherwise."""
        import collections

        if not fp:
            return 0, None
        counts = collections.Counter(c for s in fp if s in self.posting for c in self.posting[s])
        need = least * len(fp) - len(fp & self.common)  # a text below this many rare shingles cannot reach least
        cands = [c for c, n in counts.items() if n >= need] if need > 0 else list(self.fps)
        return max(((len(fp & self.fps[c]) / len(fp), c) for c in cands if c not in skip), default=(0, None))


def matches(cfg, pkg, pcards, own):
    """Package documents that look like documents of the library, with what happens to them (classify): [{kind,
    package, library, keep, why}], one per package document; a library document is the pair of one package document
    at most."""
    from assistant_x.core.common import read_ocr_scores
    from assistant_x.intake import versions
    from assistant_x.intake.tools import dupcheck
    from assistant_x.intake.tools import ocr_score

    out, done, used = [], set(), set()
    lscores = read_ocr_scores(os.path.join(os.path.dirname(cfg["cards_dir"]), "ocr_quality.tsv"))
    names = set(pkg.names())
    pscores = {}
    if "ocr_quality.tsv" in names:
        import tempfile

        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "ocr_quality.tsv")
            with open(p, "wb") as f:
                f.write(pkg.read("ocr_quality.tsv"))
            pscores = {k: float(v["score"]) for k, v in ocr_score.read_tsv(p).items() if v.get("score") not in (None, "")}
    texts = cfg["texts_dir"]
    lib_fp = {}
    if own and os.path.isdir(texts):
        for name in sorted(os.listdir(texts)):
            if name.endswith(".md") and not name.startswith("_") and C.main_code(name[:-3]) == name[:-3]:
                lib_fp[name[:-3]] = dupcheck.library_fingerprint(os.path.join(texts, name))

    def share_with(code, lcode):
        name = f"texts/{code}.md"
        if name not in names or lcode not in lib_fp:
            return None
        fp = dupcheck.fingerprint(pkg.read(name).decode("utf-8"))
        return len(fp & lib_fp[lcode]) / len(fp) if len(fp) >= 30 else None

    def add(code, lcode, share=None):
        r = classify(pcards[code], own[lcode], share, pscores.get(code), lscores.get(lcode))
        out.append(dict(r, package=code, library=lcode))
        done.add(code)
        if r["keep"]:
            used.add(lcode)

    by_sha = {}
    for code, card in own.items():
        sha = (card.get("file") or {}).get("sha256")
        if sha:
            by_sha.setdefault(sha, code)
    for code, card in sorted(pcards.items()):
        sha = (card.get("file") or {}).get("sha256")
        if sha and sha in by_sha and by_sha[sha] not in used:
            add(code, by_sha[sha])
    by_key = {}
    for lcode, card in sorted(own.items()):
        for d in C.all_texts((card.get("doc") or {}).get("designation")):
            if versions.key(d):
                by_key.setdefault(versions.key(d), lcode)
    for code, card in sorted(pcards.items()):
        if code in done:
            continue
        hits = [
            by_key[versions.key(d)]
            for d in C.all_texts((card.get("doc") or {}).get("designation"))
            if versions.key(d) in by_key and by_key[versions.key(d)] not in used
        ]
        if hits:
            add(code, hits[0], share_with(code, hits[0]))
    shingles = ShingleIndex(lib_fp) if lib_fp else None
    for code in sorted(pcards):  # the same text without a designation, or a partial overlap
        if code in done or f"texts/{code}.md" not in names or not lib_fp:
            continue
        fp = dupcheck.fingerprint(pkg.read(f"texts/{code}.md").decode("utf-8"))
        if len(fp) < 30:
            continue
        share, best = shingles.best(fp, used, dupcheck.THRESHOLDS["dup"])
        if best and share >= dupcheck.THRESHOLDS["dup"]:
            add(code, best, share)
    lib_docs = versions.library(os.path.dirname(cfg["cards_dir"]))
    for code, card in sorted(pcards.items()):  # a very similar title: reported, both stay
        if code in done:
            continue
        doc = card.get("doc") or {}
        hit = versions.find(None, " ".join(C.all_texts(doc.get("title"))), lib_docs)
        if hit:
            out.append({"kind": "separate", "keep": None, "package": code, "library": hit[0], "why": hit[2]})
            done.add(code)
    return out


def questions(report):
    """The questions for the user as data, for Claude to put in the user's language: [{id, kind, options, default,
    recommended, …facts}] (no sentences for the user here). Only who keeps the codes is asked: duplicates and
    editions are merged by the rule (classify) and told in the report."""
    out = []
    codes = report["codes"]
    if codes["mapping"]:
        out.append(
            {
                "id": "codes",
                "kind": "codes",
                "options": ["package", "own"],
                "default": codes["keeper"],
                "recommended": codes["recommended"],
                "package_codes": codes["package_codes"],
                "own_documents": codes["own_documents"],
                "package_documents": codes["package_documents"],
                "collisions": sorted(codes["mapping"]),
                "new_codes": codes["mapping"],
                "consequences": {
                    "package": f"{len(codes['mapping'])} documents of the library get new codes",
                    "own": f"{len(codes['mapping'])} documents of the package get new codes",
                },
            }
        )
    return out


def inspect(cfg, raw, path, work=None, keep=None, verify=True):
    """The report of a package (see the module); changes nothing. work: the work folder of the intake of the
    workspace (default <workspace>/.assistant_x/work)."""
    from assistant_x import __version__
    from assistant_x.core.common import CHUNK_VERSION, disk_limits
    from assistant_x.search import vector_cache

    problems, warnings = [], []
    with P.Package(path) as pkg:
        man = pkg.manifest
        req = man.get("requires") or {}
        if req.get("card_schema") != C.SCHEMA_VERSION:
            problems.append(f"card schema {req.get('card_schema')}: this program reads {C.SCHEMA_VERSION}")
        if str(req.get("text_format")) != TEXT_FORMAT:
            problems.append(f"text format {req.get('text_format')}: this program reads {TEXT_FORMAT}")
        if _version_tuple(req.get("app")) > _version_tuple(__version__):
            warnings.append(
                f"made by Assistant X {req.get('app')}, this is {__version__}: update the program if the install fails"
            )
        problems += [f"package entry {p}" for p in P.check_entries(pkg)]  # what the install refuses, said now
        if verify:
            bad = pkg.verify()
            problems += [f"package file {b}" for b in bad[:20]] + ([f"… and {len(bad) - 20} more"] if len(bad) > 20 else [])
            if any(b.startswith("damaged: ") for b in bad):  # its files do not read: nothing more to look at
                return damaged(man, path, problems, warnings, len(C.paths(cfg["cards_dir"])))
        pcards, unreadable = package_cards(pkg)
        problems += [f"card {c} of the package does not read: {e}" for c, e in sorted(unreadable.items())]
        for code, card in sorted(pcards.items()):
            problems += [f"unsafe path in the package card {code}: {x}" for x in unsafe_paths(card)]
        listed = {d["code"] for d in man.get("docs") or []}
        if listed and listed != set(pcards):
            problems.append(f"axbase.json lists {len(listed)} documents, the package has {len(pcards)} cards")
        own = {c: C.load(p) for c, p in C.paths(cfg["cards_dir"]).items()}
        empty = not own
        ws_langs, ws_topics = settings.card_languages(raw), settings.topics(raw)
        pkg_langs = list(man.get("card_languages") or ["en"])
        letters = [s["letter"] for s in settings.sections(raw)]
        compat = {
            "format": man.get("format"),
            "card_schema": req.get("card_schema"),
            "text_format": req.get("text_format"),
            "chunk_version": {"package": man.get("chunk_version"), "this program": CHUNK_VERSION},
            "profile": {"package": man.get("profile"), "workspace": raw.get("profile") or settings.PROFILE},
            "card_languages": {"package": pkg_langs, "workspace": ws_langs},
            "topics_controlled": {"package": bool(man.get("topics_controlled")), "workspace": bool(ws_topics)},
            "adopt": None,
        }
        if empty:  # the workspace takes the profile and the card languages of the package (the install writes them)
            compat["adopt"] = {"profile": man.get("profile"), "card_languages": pkg_langs}
            langs, topics = pkg_langs, None
        else:
            missing = [x for x in ws_langs if x not in pkg_langs]
            if missing:
                problems.append(
                    f"the cards of the package have no texts in {', '.join(missing)}, which this workspace "
                    f"reads documents in ([documents] languages of assistant_x.toml); the package has "
                    f"{', '.join(pkg_langs)}"
                )
            if man.get("profile") and man.get("profile") != compat["profile"]["workspace"]:
                warnings.append(
                    f"the package was made with the profile {man.get('profile')}, this workspace has "
                    f"{compat['profile']['workspace']} (the shelves are the same; its synonyms are not used)"
                )
            langs, topics = ws_langs, ws_topics
        failing = {}
        for code, card in sorted(pcards.items()):
            errs = C.validate(as_installed(card, code, man), langs, letters, topics)
            if card.get("code") != code:
                errs.append(f"the card file {code}.json has the code {card.get('code')}")
            if errs:
                failing[code] = errs[:3]
        for code, errs in list(failing.items())[:20]:
            problems.append(f"card {code} does not pass this workspace: {'; '.join(errs)}")
        if len(failing) > 20:
            problems.append(f"… and {len(failing) - 20} more cards")
        compat["cards_failing"] = len(failing)
        installed = registry.get(os.path.dirname(cfg["cards_dir"]), man.get("id"))
        if installed:
            warnings.append(
                f"the package {man.get('id')} {installed.get('version')} is installed already"
                + (
                    " (the same version: installing it again changes nothing)"
                    if installed.get("version") == man.get("version")
                    else f": for {man.get('version')} use assistant-x base update"
                )
            )
        found = matches(cfg, pkg, pcards, own)
        index = os.path.dirname(cfg["cards_dir"])
        plan = code_plan(
            own, set(pcards), C.high_water(index), keep, man.get("codes") or "default", lineage(index, man.get("id"))
        )
        root = cfg["workspace"]
        names = [n for n in pkg.names() if n.startswith("library/")]
        side = dict(plan["mapping"] if plan["renumbered"] == "package" else {}, **plan["retired"])
        longest = max((len(os.path.join(root, *C.map_path(n, side).split("/"))) for n in names), default=0)
        stage = max((len(os.path.join(root, STAGING, *n.split("/"))) for n in names), default=0)
        paths = {"longest": longest, "staging": stage, "long_paths_enabled": long_paths_enabled()}
        if longest > MAX_PATH and not paths["long_paths_enabled"]:
            problems.append(
                f"the longest path of a document would be {longest} characters (over {MAX_PATH}) and long "
                "paths are off in Windows: enable LongPathsEnabled, or use a workspace in a shorter folder"
            )
        od = onedrive(root)
        if od:
            warnings.append(
                f"the workspace is in OneDrive ({od}): thousands of files moved at once are synced at once; "
                "better pause the sync during the install"
            )
        problems += [f"intake batch {b}" for b in pending_batches(work or os.path.join(root, ".assistant_x", "work"))]
        if server_running():
            warnings.append(
                "An app holds the library now (its search server runs): the install has it release the "
                "files it moves (an install started from the chat goes on when the app is closed)"
            )
        size = {n: pkg.size(n) for n in pkg.names()}
        text_bytes = sum(v for n, v in size.items() if n.startswith("texts/"))
        own_texts = (
            sum(
                os.path.getsize(os.path.join(cfg["texts_dir"], f)) for f in os.listdir(cfg["texts_dir"]) if f.endswith(".md")
            )
            if os.path.isdir(cfg["texts_dir"])
            else 0
        )
        problems += [f"package vectors: {x}" for x in package_vectors.problems(pkg, man, cfg)]
        emb = man.get("embed") or None
        fp = vector_cache.fingerprint(cfg)
        usable = bool(emb and emb.get("fingerprint") == fp)
        fragments = int(text_bytes / 2 / CHARS_PER_FRAGMENT) + 3 * len(pcards)  # UTF-8 text: ~2 bytes a character
        todo = 0 if usable else fragments
        from assistant_x.core import gpu_guard

        embed = {
            "package_fingerprint": (emb or {}).get("fingerprint"),
            "workspace_fingerprint": fp,
            "vectors_usable": usable,
            "package_vectors": (emb or {}).get("rows", 0),
            "fragments_to_compute": todo,
            "seconds_cpu": gpu_guard.estimate(todo, "fragments", "cpu", CPU_S) if todo else 0,
            "seconds_gpu": gpu_guard.estimate(todo, "fragments", "cuda", CPU_S) if todo else 0,
        }
        if emb and not usable:
            warnings.append(
                f"the vectors of the package were made by another state of the model ({emb.get('model')}, "
                f"fingerprint {emb.get('fingerprint')}, here {fp}): about {todo} fragments to embed"
            )
        dim = int((emb or {}).get("dim") or 1024)
        need = (
            sum(size.values())
            + int(1.3 * (text_bytes + own_texts))
            + todo * dim * 2
            + sum(v for n, v in size.items() if n.startswith("cards/"))
        )
        lim = disk_limits()
        probe = root if os.path.exists(root) else os.path.dirname(root)
        free = shutil.disk_usage(probe).free
        disk = {"need_bytes": need, "free_bytes": free, "min_free_gb": lim["min_free_gb"]}
        if free < need + lim["min_free_gb"] * 1024**3:
            problems.append(
                f"not enough disk space: {free / 1024**3:.1f} GB free, the install needs about "
                f"{need / 1024**3:.1f} GB and {lim['min_free_gb']:g} GB should stay free"
            )
        report = {
            "package": {
                k: man.get(k)
                for k in ("id", "version", "name", "about", "created", "documents", "bytes", "shelves", "codes")
            },
            "path": os.path.abspath(path),
            "problems": problems,
            "warnings": warnings,
            "compatibility": compat,
            "library": {"documents": len(own)},
            "matches": found,
            "codes": plan,
            "paths": paths,
            "disk": disk,
            "embed": embed,
        }
        report["questions"] = questions(report)
        report["ok"] = not problems
        return report


def damaged(man, path, problems, warnings, own):
    """The report of a package whose files do not read whole (a damaged or cut download): its problems only."""
    return {
        "package": {
            k: man.get(k) for k in ("id", "version", "name", "about", "created", "documents", "bytes", "shelves", "codes")
        },
        "path": os.path.abspath(path),
        "problems": problems + ["the package file is damaged: get it again (download or copy it anew)"],
        "warnings": warnings,
        "compatibility": {"adopt": None},
        "library": {"documents": own},
        "matches": [],
        "codes": {"why": "not compared (the package is damaged)", "mapping": {}, "renumbered": None},
        "paths": {"longest": 0},
        "disk": {"need_bytes": 0, "free_bytes": 0, "min_free_gb": 0},
        "embed": {"vectors_usable": False, "fragments_to_compute": 0},
        "questions": [],
        "ok": False,
    }


def text(report):
    """The report in words."""
    p = report["package"]
    out = [
        f"Package {p['id']} {p['version']} ({(p.get('name') or {}).get('en') or ''}): {p['documents']} documents, "
        f"{(p.get('bytes') or 0) / 1024**2:.0f} MB; this library: {report['library']['documents']} documents."
    ]
    c = report["codes"]
    out.append(
        f"Codes ({c.get('package_codes', 'default')} package): {c['why']}; collisions {len(c['mapping'])}"
        + (
            f", {len(c['mapping'])} documents of the {c['renumbered']} side get new codes"
            if c["renumbered"]
            else (" — choose --keep package or --keep own" if c["mapping"] else "")
        )
    )
    if c.get("retired"):
        out.append(
            "Codes once given here to documents since removed (a number never comes back): the package "
            "documents get new ones: " + ", ".join(f"{a} -> {b}" for a, b in sorted(c["retired"].items()))
        )
    if c.get("reused"):
        out.append(
            "The reference numbering reuses codes once given here to documents since removed (an old citation "
            "of them now names the package document): " + ", ".join(c["reused"])
        )
    if report["compatibility"].get("adopt"):
        a = report["compatibility"]["adopt"]
        out.append(
            f"The empty workspace takes the profile {a['profile']} and the card languages "
            f"{', '.join(a['card_languages'])} of the package."
        )
    merged = [m for m in report["matches"] if m["keep"]]
    if merged:
        out.append(
            f"Merged by the rule (one stays, the other to inbox\\_to_delete\\merged_<date>): {len(merged)} — "
            + ", ".join(f"{m['package']}/{m['library']} {m['kind']}, keeps the {m['keep']}'s" for m in merged[:10])
            + (" …" if len(merged) > 10 else "")
        )
    alike = [m for m in report["matches"] if not m["keep"]]
    if alike:
        out.append(f"Alike but separate (both stay): {len(alike)}")
    e = report["embed"]
    out.append(
        "Embeddings: "
        + ("from the package" if e["vectors_usable"] else f"about {e['fragments_to_compute']} fragments to compute")
    )
    out.append(
        f"Disk: about {report['disk']['need_bytes'] / 1024**3:.1f} GB needed, "
        f"{report['disk']['free_bytes'] / 1024**3:.1f} GB free; longest path {report['paths']['longest']}."
    )
    for w in report["warnings"]:
        out.append(f"Warning: {w}")
    for x in report["problems"]:
        out.append(f"PROBLEM: {x}")
    out.append("The install may start." if report["ok"] else "The install cannot start: solve the problems above.")
    return "\n".join(out)


def main(argv=None):
    from assistant_x.core.common import load_config

    ap = argparse.ArgumentParser(prog="assistant-x base inspect")
    ap.add_argument("package")
    ap.add_argument("--keep", choices=("own", "package"))
    ap.add_argument("--json")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--config")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    w, raw = settings.load(a.config)
    try:
        report = inspect(cfg, raw, a.package, work=str(w.work), keep=a.keep, verify=not a.no_verify)
    except P.PackageError as e:
        raise SystemExit(str(e))
    print(text(report))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
