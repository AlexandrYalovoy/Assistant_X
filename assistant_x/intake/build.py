# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Catalogue material of an intake batch from meta.jsonl + state.sqlite.
meta.jsonl is checked first (meta_schema.py): with errors nothing is built and no codes are given.
Writes <work>/out/: cards/<code>.json (the doc block from meta.jsonl, the file block from the pipeline), texts/*.md,
events.tsv (rows of intake_events.tsv), ocr.tsv (rows of ocr_quality.tsv: the recognition score of each text),
moves.json, pdfcopies.json, versions.json (the new versions: replaced codes and the codes whose cards name each other;
versions.py). The catalog and the sources to update are made from the cards by the apply (search/catalog.py).
Codes: the letter of the shelf and five digits (N-00012), the next free one of the shelf; <work>/codes.json keeps
tid -> code once given. The documents of the user go into the same shelves and folders as any others (an installed
base package too); a card is marked personal only when the user asks to keep an addition apart (--personal).
Usage: assistant-x intake build [--work DIR] [--personal]"""

import json, os, re
from pathlib import Path

from assistant_x.core import card as C
from assistant_x.intake import meta_schema
from assistant_x.core.formats import EVENT_DONE, EVENT_DUP, EVENT_REJECTED, EVENT_DELETE, PAGES_SUFFIX, file_kind, pages_path

DOC_EXT = ("doc", "docx", "rtf", "odt")
SLIDE_EXT = ("ppt", "pptx", "pps", "ppsx", "odp")
SHA_RX = re.compile(r"[0-9a-f]{64}")


def clean(x, n=60):
    x = re.sub(r"[^A-Za-z0-9-]+", "-", str(x).replace(".", "-")).strip("-")
    return re.sub(r"-{2,}", "-", x)[:n].strip("-")


def ext_of(rel):
    return rel.rsplit(".", 1)[-1].lower()


def win(rel):
    return rel.replace("/", "\\")


def posix(place):
    """'library\\01_Standards\\x.pdf' -> 'library/01_Standards/x.pdf': the paths of a card."""
    return place.replace("\\", "/")


def file_format(r):
    """The format block of a card from the state of a file: its kind, pages, recognized pages and score (0-1)."""
    x, n = ext_of(r["rel"]), r.get("pages")
    o, no = r.get("ocr_pages") or 0, r.get("no_ocr_pages") or 0
    fk = file_kind(r["rel"])
    if x in DOC_EXT:
        kind = "doc"
    elif x in SLIDE_EXT:
        kind = "presentation"
    elif fk in ("ebook", "text", "spreadsheet"):
        kind = fk
    elif no:
        kind = "pdf_no_ocr"
    elif o == 0:
        kind = "pdf_text"
    elif o >= 0.5 * (n or 1):
        kind = "pdf_scan"
    else:
        kind = "pdf_mixed"
    out = {"kind": kind, "pages": n if isinstance(n, int) else None}
    if o:
        out["ocr_pages"] = int(o)
    if no:
        out["no_ocr_pages"] = int(no)
    if r.get("ocr_score") is not None:
        out["ocr_score"] = round(min(max(float(r["ocr_score"]) / 100, 0.0), 1.0), 3)
    return out


def file_facts(r):
    """The facts of a file of the state that every card or part of a card carries."""
    sha = str(r.get("sha256") or "")
    return {
        "source_name": r["rel"].rsplit("/", 1)[-1],
        "sha256": sha if SHA_RX.fullmatch(sha) else "",
        "size": r["size"] if isinstance(r.get("size"), int) else None,
        "format": file_format(r),
    }


def clear_dir(d):
    """Empty a folder of our own output (files, then empty folders; no rmtree)."""
    if not d.exists():
        return
    for dp, dns, fns in os.walk(d, topdown=False):
        for f in fns:
            os.remove(os.path.join(dp, f))
        for x in dns:
            os.rmdir(os.path.join(dp, x))


CODES_LOCK = "codes.lock"  # in index/: one process at a time reads the numbers in use and gives new ones


def code_lock(index, wait=120):
    """The open lock file of the code numbers (index/codes.lock) once this process holds it; waits up to wait s."""
    import time
    from assistant_x.core import lock

    Path(index).mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    while True:
        f = lock.exclusive(str(Path(index) / CODES_LOCK))
        if f or time.time() - t0 > wait:
            return f
        time.sleep(0.5)


def used_numbers(cards_dir, codes):
    """{letter: the highest number given} over the cards of the library, the codes of this batch and the marks of
    index/codes.json (a number of a removed document never comes back)."""
    used = C.high_water(Path(cards_dir).parent)
    for code in list(C.paths(cards_dir)) + list(codes.values()):
        m = C.CODE_RX.match(code)
        if m:
            used[m["letter"]] = max(used.get(m["letter"], 0), int(m["num"]))
    return used


def base_open(cfg):
    """Why the intake must wait: a base package transaction of the workspace was interrupted (its --resume or
    --rollback restores the cards of that moment, so nothing may be built or applied in between), or ''."""
    from assistant_x.base import registry
    from assistant_x.core import config as settings

    pending = registry.open_transactions(settings.load(cfg.path)[0].data)
    if not pending:
        return ""
    return (
        "A base package " + "; ".join(pending) + " was interrupted: finish it first (assistant-x base install|update|"
        "remove … --resume, or --rollback); the intake builds and applies nothing until then."
    )


def build(cfg, work, date=None, personal=False):
    import datetime
    from assistant_x.core import config as settings
    from assistant_x.intake import config as intake_cfg
    from assistant_x.intake.tools import ocr_score
    from assistant_x.intake.state import State

    date = date or datetime.date.today().isoformat()
    base = base_open(cfg)
    if base:
        print(base)
        return 1
    work = Path(work)
    out = work / "out"
    cards_dir = cfg.index / "cards"
    state = State(work / "state.sqlite")
    by = {r["tid"]: r for r in state.all()}
    if not (work / "meta.jsonl").exists():
        print(f"No {work / 'meta.jsonl'}: write the metadata (draft: meta_draft.jsonl).")
        return 1
    rules = meta_schema.profile_rules(cfg)
    shelves = {s["letter"]: s for s in settings.sections(cfg)}
    meta, errors, warnings = meta_schema.check_batch(cfg, work)  # the very check of check-meta
    for w in warnings:
        print(f"warning: {w}")
    for t, m in meta.items():
        if m.get("sec") and t in by and by[t]["status"] not in ("done",):
            errors.append(
                f"{t}: a document (sec) with the status {by[t]['status']}: only processed files go into the "
                "library (a wrong duplicate: assistant-x intake requeue {t}, then assistant-x intake run)"
            )
    # a new version that replaces a document of the library takes its code; the old one must be there and be one file
    in_library = C.paths(cards_dir)
    old_place = {}
    for t, m in meta.items():
        for k in ("replaces", "other_version"):
            c = m.get(k)
            if not c:
                continue
            if c not in in_library:
                errors.append(f"{t}: {k} {c}: no such document in the library (no card index/cards/{c}.json)")
                continue
            if k == "replaces":
                old = C.load(in_library[c]).get("file") or {}
                if old.get("parts"):
                    errors.append(
                        f"{t}: replaces {c}, a document of several files: keep both (other_version) or replace it by hand"
                    )
                place = old.get("library") or ""
                if not place.startswith("library/"):
                    errors.append(f"{t}: replaces {c}: its card names no file in the library ({place or 'empty'})")
                old_place[c] = win(place)
    taken_by = [m["replaces"] for m in meta.values() if m.get("replaces")]
    errors += [f"two files replace {c}" for c in sorted({c for c in taken_by if taken_by.count(c) > 1})]
    if errors:
        print("Build stopped, errors in meta.jsonl:")
        for e in errors:
            print(f"  {e}")
        return 1
    codes_p = work / "codes.json"
    lock_f = code_lock(cfg.index)  # the numbers in use and the new ones: one batch at a time
    if lock_f is None:
        print(
            f"Build stopped: another process holds {cfg.index / CODES_LOCK} (an intake build or a base install); "
            "run the build again when it has ended."
        )
        return 1
    try:
        codes = json.loads(codes_p.read_text(encoding="utf-8")) if codes_p.exists() else {}
        used = used_numbers(cards_dir, codes)
        mains = sorted(t for t, m in meta.items() if m.get("sec"))
        for t in mains:
            if meta[t].get("replaces"):
                codes[t] = meta[t]["replaces"]
            elif t not in codes:
                sec = meta[t]["sec"]
                used[sec] = used.get(sec, 0) + 1
                if used[sec] >= 10**C.DIGITS:
                    print(f"Build stopped: section {sec} has run out of codes.")
                    return 1
                codes[t] = C.new_code(sec, used[sec])
        codes_p.write_text(json.dumps(codes, indent=0), encoding="utf-8")
        C.raise_high_water(cfg.index, codes.values())
    finally:
        lock_f.close()
    parts = {}
    for t, m in meta.items():
        if m.get("part"):
            parts.setdefault(m["part"], []).append(t)
    quality = json.loads((work / "quality.json").read_text(encoding="utf-8")) if (work / "quality.json").exists() else {}
    # the user's documents go into the library as any others; marked personal only when the user asked to keep this
    # addition apart (assistant-x intake build --personal, or [intake] personal = true for every batch)
    personal = bool(personal or cfg.get("personal", False))

    def md_path(t):
        p = work / "md" / f"{t}.md"
        return p if p.exists() else work / "mdtmp" / t / f"{t}.dup.md"

    clear_dir(out)
    (out / "cards").mkdir(parents=True, exist_ok=True)
    (out / "build.json").write_text(json.dumps({"date": date, "personal": personal}), encoding="utf-8")
    (out / "texts").mkdir(parents=True, exist_ok=True)
    events, moves, pdfs, ocr_rows, cards = [], [], [], {}, {}
    versions = {"replaced": [], "linked": []}
    for t in mains:
        c = meta[t].get("replaces")
        if c:  # the old original first: its place may be the name of the new one
            dst = f"inbox\\_to_delete\\replaced_{date}\\{old_place[c].rsplit(chr(92), 1)[-1]}"
            moves.append({"src": old_place[c], "dst": dst, "replaced": c})
            events.append([date, old_place[c], "—", "—", c, dst, f"{EVENT_DELETE}: replaced by a new version"])
            versions["replaced"].append(c)
        m, code, r = meta[t], codes[t], by[t]
        folder = shelves[m["sec"]]["folder"]
        yr = str(m["year"]) if m.get("year") and m.get("doc_type") != "standard" else ""  # a standard: in its designation
        au, en = clean(m.get("au", ""), 40), clean(m["en"], 55)
        stem = "_".join(x for x in (code, au, en, yr) if x)
        pl = sorted(parts.get(t, []))
        if pl:
            items = [(t, f"{code}-01_{en}")] + [
                (p, f"{code}-{i + 2:02d}_{clean(meta[p].get('what', 'Part'), 50)}") for i, p in enumerate(pl)
            ]
            base = f"library\\{folder}\\{code}_{en}"
        else:
            items, base = [(t, stem)], f"library\\{folder}"
        files = []
        for k, (tt, name) in enumerate(items):
            rr = by[tt]
            x = ext_of(rr["rel"])
            fn = f"{name}.{x}"
            moves.append({"tid": tt, "src": "inbox\\" + win(rr["rel"]), "dst": f"{base}\\{fn}"})
            conv = work / "pdf" / f"{tt}.pdf"
            copy = ""
            if x != "pdf" and conv.exists() and conv.stat().st_size < 30e6:
                copy = f"{base}\\{name}.pdf"
                pdfs.append({"src": str(conv), "dst": copy})
            sub = code if k == 0 else C.part_code(code, k + 1)
            mp = md_path(tt)
            has_text = mp.exists() and (k == 0 or mp.stat().st_size > 1500)
            if has_text:
                (out / "texts" / f"{sub}.md").write_text(mp.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
                if os.path.exists(pages_path(mp)):  # assemble_md: the source, score, label and flags of every page
                    (out / "texts" / f"{sub}{PAGES_SUFFIX}").write_bytes(Path(pages_path(mp)).read_bytes())
                det = work / "ocr" / f"{tt}.json"  # the recognition score of intake_work.convert
                if det.exists():
                    ocr_rows[sub] = ocr_score.row_of(sub, json.loads(det.read_text(encoding="utf-8")), "intake", date)
            entry = {
                "code": sub,
                "library": posix(f"{base}\\{fn}"),
                "text": f"index/texts/{sub}.md" if has_text else "",
                "pdf_copy": posix(copy),
                **file_facts(rr),
            }
            if k:
                entry["what"] = str(meta[tt].get("what") or "")
            files.append((entry, rr))
            events.append(
                [
                    date,
                    "inbox\\" + win(rr["rel"]),
                    rr.get("size") or "—",
                    rr.get("sha") or "—",
                    sub,
                    f"{base}\\{fn}",
                    EVENT_DONE + (": a new version, the old one to delete" if m.get("replaces") else ""),
                ]
            )
        doc = meta_schema.doc_of(m)
        if m.get("other_version"):
            doc["other_versions"] = sorted(set(doc.get("other_versions") or []) | {m["other_version"]})
            versions["linked"].append({"code": code, "other": m["other_version"]})
        issues = [
            {"what": i["what"], "need": i.get("need") or "", "priority": i["priority"], "noted": date}
            for i in m.get("issues") or []
        ]
        if not m.get("quality_ok"):  # the problems the quality report found (a poor scan, empty pages)
            for entry, rr in files:
                for what, need, prio in quality.get(rr["tid"], {}).get("problems", []):
                    issues.append(
                        {
                            "what": what,
                            "need": need,
                            "priority": prio,
                            "noted": date,
                            **({"code": entry["code"]} if entry["code"] != code else {}),
                        }
                    )
        # tools/hidden.py found text a reader does not see; it was cut out of the search text, the original is unchanged
        hidden = [
            {
                "code": e["code"],
                "fragments": int(rr["hidden"]),
                "pages": [p for p in rr.get("hidden_pages") or [] if isinstance(p, int) and p > 0],
            }
            for e, rr in files
            if rr.get("hidden")
        ]
        main = dict(files[0][0])
        del main["code"]
        file = {**main, "hidden_text": hidden, "issues": issues, "parts": [e for e, _ in files[1:]]}
        cards[code] = C.complete(
            {
                "schema": C.SCHEMA_VERSION,
                "code": code,
                "section": m["sec"],
                "doc_type": m["doc_type"],
                "doc": doc,
                "file": file,
                "intake": {"batch": work.name, "date": date, "personal": personal},
            }
        )
    bad = [
        f"{code}: {e}"
        for code, cd in cards.items()
        for e in C.validate(cd, rules["languages"], rules["sections"], rules["topics"])
    ]
    if bad:
        print("Build stopped, the cards do not pass the schema:")
        for e in bad:
            print(f"  {e}")
        return 1
    for code, cd in cards.items():
        C.dump(cd, out / "cards" / f"{code}.json")

    def code_of(x):
        if x in codes:
            return codes[x]
        if x in meta and meta[x].get("part"):
            return code_of(meta[x]["part"])
        if x in meta and meta[x].get("dupof"):
            return code_of(meta[x]["dupof"])
        return x

    from assistant_x.core import lang

    programs = {
        e.lower().lstrip(".")
        for e in cfg.get("program_ext") or (*intake_cfg.PROGRAM_EXT, *lang.profile_words().get("program_ext", []))
    }
    for t, r in sorted(by.items()):
        m = meta.get(t, {})
        src = "inbox\\" + win(r["rel"])
        ext = r["rel"].rsplit(".", 1)[-1].lower() if "." in r["rel"] else ""
        if not m and r["status"] == "skipped" and ext in programs:  # a model or a case of an engineering program
            moves.append({"tid": t, "src": src, "dst": "inbox\\_rejected\\programs\\" + win(r["rel"])})
            events.append(
                [
                    date,
                    src,
                    r.get("size") or "—",
                    r.get("sha") or "—",
                    "—",
                    "inbox\\_rejected\\programs\\",
                    f"{EVENT_REJECTED}: a program file .{ext}",
                ]
            )
            meta[t] = {"drop": f"a program file .{ext}"}  # not "left" below
            continue
        if m.get("drop"):
            moves.append({"tid": t, "src": src, "dst": "inbox\\_rejected\\" + win(r["rel"])})
            events.append(
                [
                    date,
                    src,
                    r.get("size") or "—",
                    r.get("sha") or "—",
                    "—",
                    "inbox\\_rejected\\" + win(r["rel"].rsplit("/", 1)[0] if "/" in r["rel"] else "") + "\\",
                    f"{EVENT_REJECTED}: {m['drop']}",
                ]
            )
            continue
        d = m.get("dupof") or (r.get("dup_of") if r["status"] == "dup" and not m.get("sec") and not m.get("part") else None)
        if not d:
            continue
        c = code_of(d)
        # every duplicate leaves inbox (~300 SHA copies inside a batch used to stay there): with the code of
        # the original when it has one, else with the original's file of this batch
        if not C.is_code(c) and c in by:
            c = f"{c}, {win(by[c]['rel'])}"
        why = m.get("why") or r.get("why") or "same content"
        moves.append({"tid": t, "src": src, "dst": "inbox\\_duplicates\\" + win(r["rel"])})
        events.append(
            [
                date,
                src,
                r.get("size") or "—",
                r.get("sha") or "—",
                "—",
                "inbox\\_duplicates\\" + (win(r["rel"].rsplit("/", 1)[0]) + "\\" if "/" in r["rel"] else ""),
                f"{EVENT_DUP} {c} ({why})" if C.is_code(c) else f"{EVENT_DUP}: {why} ({c})",
            ]
        )
    with open(out / "events.tsv", "w", encoding="utf-8", newline="\n") as f:
        for e in events:
            f.write("\t".join(re.sub(r"[\t\r\n]+", " ", str(x)) for x in e) + "\n")
    ocr_score.write_tsv(out / "ocr.tsv", ocr_rows)
    (out / "moves.json").write_text(json.dumps(moves, ensure_ascii=False, indent=0), encoding="utf-8")
    (out / "pdfcopies.json").write_text(json.dumps(pdfs, ensure_ascii=False, indent=0), encoding="utf-8")
    (out / "versions.json").write_text(json.dumps(versions, ensure_ascii=False, indent=0), encoding="utf-8")
    left = [r for t, r in by.items() if r["status"] in ("done", "skipped", "error") and t not in meta]
    n_issues = sum(len(cd["file"]["issues"]) for cd in cards.values())
    print(
        f"Cards {len(cards)}, events {len(events)}, issues of the sources {n_issues}, moves {len(moves)}, "
        f"PDF copies {len(pdfs)}"
        + (f", new versions replacing {', '.join(versions['replaced'])}" if versions["replaced"] else "")
        + (f", other versions linked {len(versions['linked'])}" if versions["linked"] else "")
        + "."
    )
    if left:
        print(f"Without a line in meta.jsonl (they stay in inbox): {len(left)} — " + ", ".join(r["tid"] for r in left[:20]))
    print(f"Next: assistant-x intake apply --dry-run (folder {out})")
    return 0
