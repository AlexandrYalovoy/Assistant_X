# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reviewing a batch (what Claude reads to write meta.jsonl): the summary, the status, the list of files to
describe, the digest of headings, the kit folders of standards grouped into parts."""

import collections, json, re
from pathlib import Path

from assistant_x.core import lang
from assistant_x.core.formats import PAGE_SPLIT_RX
from assistant_x.intake import config as intake_cfg
from assistant_x.intake.state import State
from assistant_x.intake.batch import say, win, work_dir
from assistant_x.intake.prepare import KIT, KIT_RX, KIT_WORDS


# hidden text worth a look: words aimed at an AI (English and Russian ones). The rest (CAD and PDF service layers,
# white text on scans) is a number.
SUSPECT = re.compile(rf"(?i)\b({lang.alt('suspect_words')})")


def hidden_line(work, hidden):
    """The "Hidden text" line of the summary: documents whose hidden fragments look like instructions, with the fragment;
    the others only counted (in 243 documents it was nearly all service layers)."""
    shown = []
    for r in hidden:
        try:
            rep = json.loads((Path(work) / "log" / f"{r['tid']}.hidden.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        hits = [it["text"] for items in rep.get("found", {}).values() for it in items if SUSPECT.search(it.get("text", ""))]
        if hits:
            first = re.sub(r"\s+", " ", hits[0])[:120]
            shown.append(f'{r["tid"]} "{first}"' + (f" and {len(hits) - 1} more" if len(hits) > 1 else ""))
    line = f"- Hidden text found: {len(hidden)} docs"
    if shown:
        line += f"; looking like instructions for an AI — {len(shown)}: " + "; ".join(shown[:20]) + " (have a look yourself)"
    elif hidden:
        line += " (service layers and invisible text of scans, nothing like instructions for an AI)"
    return line


def summary(cfg, work, state, prep_counts, problems, seconds, quality=None):
    from assistant_x.intake import quality_report

    rows = state.all()
    c = collections.Counter(r["status"] for r in rows)
    dups = [r for r in rows if r["status"] == "dup"]
    sha = sum("SHA-256" in (r.get("why") or "") for r in dups)
    skipped = [r for r in rows if r["status"] == "skipped"]
    no_lo = sum("LibreOffice" in (r.get("why") or "") for r in skipped)
    errors = [r for r in rows if r["status"] == "error"]
    hidden = [r for r in rows if r.get("hidden")]
    L = [
        f"# Intake summary {work.name}",
        "",
        f"- Work folder: {work}",
        f"- Files in the batch: {len(rows)}; done (text obtained) {c['done']}, duplicates {c['dup']} "
        f"(by SHA-256 {sha}, by content {len(dups) - sha}), skipped {c['skipped']} (no LibreOffice {no_lo}), "
        f"errors {c['error']}, still queued {c['queued'] + c['running']}"
        + (f", moved into the library {c['applied']}" if c["applied"] else ""),
        f"- Preparing the folder: archives unpacked {prep_counts.get('archives', 0)} (files from them {prep_counts.get('archive_files', 0)}), "
        f"not unpacked {prep_counts.get('archive_failed', 0)}; letters {prep_counts.get('letters', 0)} (their "
        f"attachments taken out {prep_counts.get('letter_files', 0)}) to delete, archives with a password "
        f"{prep_counts.get('archive_password', 0)}, "
        f"macOS service files {prep_counts.get('macos', 0)}, personal papers (by the name of the file) "
        f"{prep_counts.get('personal', 0)} — not opened",
        hidden_line(work, hidden),
        f"- Programs: LibreOffice {'present' if cfg.soffice else 'MISSING (DOC/DOCX are skipped)'}; "
        f"Tesseract {'present' if intake_cfg.can_ocr(cfg) else 'MISSING (scans without OCR, marked)'}",
        f"- {quality_report.summary_line(quality)}" if quality else "- Quality: no documents done",
        f"- Time: {seconds / 60:.1f} min",
        "",
        "Next (Claude): check meta_draft.jsonl and write meta.jsonl (a line per file), "
        "then `assistant-x intake build` and `assistant-x intake apply --dry-run`, `assistant-x intake apply`.",
    ]
    for title, items in (("Errors", errors), ("Skipped", skipped), ("Duplicates", dups)):
        if items:
            L += ["", f"## {title} ({len(items)})", ""]
            L += [
                f"- {r['tid']} {win(r['rel'])} — {r.get('why') or ''}" + (f" → {r['dup_of']}" if r.get("dup_of") else "")
                for r in items[:200]
            ]
    if problems:
        L += ["", "## Preparing the folder: what failed", ""] + [f"- {p}" for p in problems]
    text = "\n".join(L) + "\n"
    (work / "summary.md").write_text(text, encoding="utf-8")
    return text


def status_data(work, state, started=None, now=None):
    """The state of a batch for the status: done / in work (tid, stage, pages done of the conversion) / waiting /
    errors, and an estimate of the time left from the pages done so far (None until it can be told)."""
    import time

    now = now or time.time()
    rows = state.all()
    final = ("done", "dup", "error", "skipped", "applied")
    done = [r for r in rows if r["status"] in final]
    running = []
    for r in rows:
        if r["status"] != "running":
            continue
        p = {"done": 0, "total": 0}
        for f in (Path(work) / "cache").glob(f"{r['tid']}.*progress.json"):  # the file, and its OCR ranges
            try:
                x = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            p["done"] += int(x.get("done") or 0)
            p["total"] += int(x.get("total") or 0)
        item = {"tid": r["tid"], "rel": r["rel"], "stage": r.get("stage") or "prep", "active": bool(r.get("active"))}
        if r.get("stage") in ("convert", "convert_shard") and p.get("total"):
            item["progress"] = [int(p.get("done") or 0), int(p["total"])]
        if r.get("pages"):
            item["pages"] = r["pages"]
        running.append(item)
    queued = [r["tid"] for r in rows if r["status"] == "queued"]
    errors = [
        {"tid": r["tid"], "rel": r["rel"], "status": r["status"], "why": r.get("why")}
        for r in rows
        if r["status"] in ("error", "skipped")
    ]
    # the time left: the pages done so far over the time spent, for the pages still to do (a file not prepared yet
    # counts as the mean pages of the known ones)
    eta = None
    pages_of = [r.get("pages") or 0 for r in rows]
    known = [p for p in pages_of if p]
    mean = sum(known) / len(known) if known else 0
    did = sum(r.get("pages") or 0 for r in done if r["status"] != "skipped")
    did += sum((x.get("progress") or [0])[0] for x in running)
    left = sum((r.get("pages") or mean) for r in rows if r["status"] in ("queued", "running")) - sum(
        (x.get("progress") or [0])[0] for x in running
    )
    if started and did and now > started:
        eta = round(left / (did / (now - started))) if left > 0 else 0
    return {
        "work": str(work),
        "total": len(rows),
        "done": len(done),
        "counts": state.counts(),
        "running": running,
        "queued": queued,
        "errors": errors,
        "eta_seconds": eta,
    }


def cmd_status(cfg, a):
    work = work_dir(cfg, a.work)
    state = State(work / "state.sqlite")
    if getattr(a, "json", False):
        started = state.get_meta("started", None)
        say(json.dumps(status_data(work, state, started), ensure_ascii=False))
        return 0
    say(f"{work}: {state.counts()}")
    for r in state.all("error", "skipped"):
        say(f"  {r['tid']} [{r['status']}] {win(r['rel'])} — {r.get('why')}")
    return 0


def cmd_todo(cfg, a):
    work = work_dir(cfg, a.work)
    from assistant_x.intake import meta_schema

    meta = meta_schema.load(work / "meta.jsonl")[0] if (work / "meta.jsonl").exists() else {}
    rows = [r for r in State(work / "state.sqlite").all("done", "skipped", "error") if r["tid"] not in meta]
    say(len(rows))
    if not getattr(a, "by_folder", False):
        say(" ".join(r["tid"] for r in rows))
        return 0
    groups = collections.defaultdict(list)  # a folder is often one document with its parts, or one kind of paper
    for r in rows:
        groups["/".join(r["rel"].split("/")[:-1]) or "."].append(r["tid"])
    for folder, tids in sorted(groups.items(), key=lambda x: (-len(x[1]), x[0])):
        say(f"{len(tids):4}  {win(folder)}  {' '.join(tids[:12])}{' …' if len(tids) > 12 else ''}")
    return 0


def drafts(work):
    p = Path(work) / "meta_draft.jsonl"
    return {d["tid"]: d for d in map(json.loads, p.read_text(encoding="utf-8").splitlines())} if p.exists() else {}


def cmd_brief(cfg, a):
    """One line a file (digest is pages of text a file, too much for 2000 files): tid, pages, OCR score, the
    draft's section, designation and title, and the place — enough to write most lines of meta.jsonl."""
    work = work_dir(cfg, a.work)
    rows = {r["tid"]: r for r in State(work / "state.sqlite").all()}
    dr = drafts(work)
    tids = a.tids or sorted(t for t, r in rows.items() if r["status"] == "done")
    for t in tids:
        r, d = rows.get(t), dr.get(t, {})
        if r is None:
            continue
        score = r.get("ocr_score")
        flag = " ".join(
            x
            for x in (
                f"OCR {score:.0f}" if score is not None else "",
                "drawing" if r.get("drawing") else "",
                f"like {r['pair'][0][1]}" if r.get("pair") else "",
                f"like {r['suspect']}?" if r.get("suspect") else "",
                d.get("drop") and "drop?",
            )
            if x
        )
        title = d.get("title") or ""
        title = " / ".join(title.values()) if isinstance(title, dict) else str(title)
        say(
            f"{t} {r['status'][:4]} {r.get('pages') or '?'}p {d.get('sec', '?')} {d.get('doc_type', '?')} "
            f"{d.get('code_hint', '')} | {title[:80]} | {win(r['rel'])[-70:]}" + (f" | {flag}" if flag else "")
        )
    return 0


def cmd_pack(cfg, a):
    """ "A package by folder": the done files of one folder of inbox are one document — the main file (the
    longest text, or --main) and its parts. Shows the lines; --write appends them to meta.jsonl (the main one still
    needs its own line: sec, title, en…)."""
    from assistant_x.intake import meta_schema

    work = work_dir(cfg, a.work)
    meta = meta_schema.load(work / "meta.jsonl")[0] if (work / "meta.jsonl").exists() else {}
    folder = a.folder.replace("\\", "/").strip("/")
    if folder.lower().startswith("inbox/"):
        folder = folder.split("/", 1)[1]
    items = [r for r in State(work / "state.sqlite").all("done") if r["rel"].startswith(folder + "/")]
    if not items:
        say(f"The folder {win(folder)} has no processed files")
        return 1
    main = a.main or max(items, key=lambda r: (r.get("chars") or 0, -int(r["tid"][1:])))["tid"]
    lines = [
        {"tid": r["tid"], "part": main, "what": re.sub(r"[^\w-]+", "-", Path(r["rel"]).stem)[:40].strip("-") or "Part"}
        for r in sorted(items, key=lambda r: r["tid"])
        if r["tid"] != main and r["tid"] not in meta
    ]
    say(f"Main file: {main} {win(next(r['rel'] for r in items if r['tid'] == main))}; parts: {len(lines)}")
    for ln in lines:
        say("  " + json.dumps(ln, ensure_ascii=False))
    if a.write and lines:
        with open(work / "meta.jsonl", "a", encoding="utf-8") as f:
            for ln in lines:
                f.write(json.dumps(ln, ensure_ascii=False) + "\n")
        say(f"Written to meta.jsonl: {len(lines)}; write the line of the main file ({main}) yourself")
    return 0


# what the digest shows of a text by the genre of its draft: the parts and their characters (one table of sizes)
SCOPE, ABSTRACT, CONTENTS, SPECS = (
    (("title", 600), ("scope", 900)),
    (("title", 600), ("abstract", 900)),
    (("title", 600), ("contents", 1200)),
    (("title", 400), ("characteristics", 1200)),
)
DIGEST = {
    "standard": SCOPE,
    "guideline": SCOPE,
    "regulation": SCOPE,
    "article": ABSTRACT,
    "thesis": ABSTRACT,
    "serial_issue": CONTENTS,
    "proceedings": CONTENTS,
    "book": CONTENTS,
    "textbook": CONTENTS,
    "handbook": CONTENTS,
    "datasheet": SPECS,
    "manual": SPECS,
}
DIGEST_DEFAULT = (("start", 450),)


def flat(text):
    text = re.sub(r"<br>|\|", " ", text)
    return re.sub(r"[ \t]+", " ", re.sub(r"-{3,}|\n+", " ", text)).strip()


def digest_part(kind, pages, size):
    """A part of a text for the digest: start (the first two pages), title (the first page), contents (the contents
    pages, core/textmap.toc_pages), scope / abstract / characteristics (from the heading of that name: digest_heads of
    the language packs, on to the next page); "" when the text has none."""
    from assistant_x.core import textmap

    if kind == "start":
        return flat(" ".join(p for _, p in pages[:2]))[:size].rstrip()
    if kind == "title":
        return flat(pages[0][1])[:size].rstrip() if pages else ""
    if kind == "contents":
        spans = textmap.toc_pages([(int(n), p) for n, p in pages])
        return flat(" ".join(pages[x][1] for i, j in spans[:1] for x in range(i, j)))[:size].rstrip()
    words = lang.lists("digest_heads").get(kind) or []
    rx = re.compile("(?i)(" + "|".join(re.escape(w) for w in words) + ")") if words else None
    for k, (_, p) in enumerate(pages):
        m = rx.search(p) if rx else None
        if m:
            return flat(p[m.start() :] + " " + (pages[k + 1][1] if k + 1 < len(pages) else ""))[:size].rstrip()
    return ""


def cmd_digest(cfg, a):
    """Headings and first lines of processed documents: what Claude reads to write meta.jsonl. The parts shown follow
    the genre of the draft (DIGEST): a standard its title page and scope, an article its abstract, a datasheet its
    characteristics, a book its title page and contents."""
    work = work_dir(cfg, a.work)
    state = State(work / "state.sqlite")
    rows = {r["tid"]: r for r in state.all()}
    tids = a.tids or sorted(t for t, r in rows.items() if r["status"] == "done")
    dr = drafts(work)
    H = re.compile(
        rf"^(#{{1,4}} .{{3,100}}|\*\*\d+(\.\d+)*\.? [^*]{{3,90}}\*\*|\d+(\.\d+)?\.? [{lang.chars('upper_basic')}][^.\n]{{3,80}})$"
    )
    for t in tids:
        r = rows[t]
        md_p = work / "md" / f"{t}.md"
        md = md_p.read_text(encoding="utf-8") if md_p.exists() else ""
        parts = PAGE_SPLIT_RX.split(md)[1:]
        pages = list(zip(parts[0::2], parts[1::2]))
        heads, seen = [], set()
        for n, p in pages:
            for line in p.split("\n"):
                line = line.strip()
                if H.match(line) and not re.search(r"\.{4,}|…{2,}", line):
                    h = re.sub(r"[#*]", "", line).strip()[:70]
                    if h.lower() not in seen:
                        seen.add(h.lower())
                        heads.append(f"{n}:{h}")
        parts = []
        for kind, size in DIGEST.get(dr.get(t, {}).get("doc_type"), DIGEST_DEFAULT):
            text = digest_part(kind, pages, size)
            if text:
                parts.append(f"{'T' if kind in ('start', 'title') else kind}: {text}")
        if not parts:
            parts = [f"T: {digest_part('start', pages, 450)}"]
        q = f"letters={r.get('letters')} ocr={r.get('ocr_pages')} fb={r.get('fallback')} fffd={r.get('fffd')} hidden={r.get('hidden')}"
        say(
            f"### {t} [{r['status']}] {win(r['rel'])}\n{r.get('pages')}p {(r.get('size') or 0) // 1024}KB {q} "
            f"sim={r.get('similar')}\nH: {' | '.join(heads[:10])}\n" + "\n".join(parts) + "\n"
        )
    return 0


def cmd_groups(cfg, a):
    """Group the kit folders of national standards (KIT: the document file, its scan images, additional documents, as
    the registry distributes them); --write adds part lines to meta.jsonl."""
    from assistant_x.intake import meta_schema

    work = work_dir(cfg, a.work)
    state = State(work / "state.sqlite")
    mp = work / "meta.jsonl"
    meta = meta_schema.load(mp)[0] if mp.exists() else {}
    G = {}
    for e in state.all():
        m = KIT_RX.match(e["rel"])
        if m:
            G.setdefault(m.group(1), []).append((e["tid"], m.group(2), e["rel"].rsplit("/", 1)[1], e))
    out = []
    for g, items in sorted(G.items(), key=lambda x: min(i[0] for i in x[1])):
        items.sort(key=lambda i: i[0])
        done = all(e["status"] in ("done", "dup", "error", "skipped") for *_, e in items)
        cand = [
            i
            for i in items
            if i[1] == KIT["file"] and i[3]["status"] == "done" and not re.search(f"(?i){KIT_WORDS['not_main']}", i[2])
        ] or [i for i in items if i[3]["status"] == "done"]
        main = max(cand, key=lambda i: i[3].get("chars") or 0)[0] if cand else None
        say(f"{'DONE' if done else 'wait'} main={main} {g.rsplit('/', 1)[-1][:70]}")
        for t, k, n, e in items:
            say(f"   {t} {e['status']:7} {k[:6]} {e.get('pages')}p {e.get('chars')}ch {n[:60]}")
        if done and main and a.write:
            for t, k, n, e in items:
                if t != main and t not in meta and e["status"] == "done":
                    # a signed title or an approval sheet scanned on 1-2 pages and a plan of measures are not parts
                    # of the norm: dropped (the skill's rule for administrative pages), not dozens of tiny parts
                    if k == KIT["scan"] and (e.get("pages") or 9) <= 2:
                        out.append(
                            {
                                "tid": t,
                                "drop": "administrative pages only: a scan image of the title or of the approval sheet",
                            }
                        )
                        continue
                    if re.search(f"(?i){KIT_WORDS['plan_of_measures']}", n):
                        out.append({"tid": t, "drop": "administrative pages only: an implementation plan"})
                        continue
                    what = {KIT["scan"]: "Scan", KIT["supplement"]: "Supplement"}.get(k, "File")
                    lab = (
                        "Approval-Sheet"
                        if re.match(f"(?i){KIT_WORDS['approval']}", n)
                        else "Signed-Title"
                        if re.search(f"(?i){KIT_WORDS['signed_title']}", n) and (e.get("pages") or 9) <= 2
                        else "Implementation-Plan"
                        if re.search(f"(?i){KIT_WORDS['plan']}", n)
                        else "Explanatory-Note"
                        if re.search(f"(?i){KIT_WORDS['explanatory']}", n)
                        else "Change-Register"
                        if re.search(f"(?i){KIT_WORDS['register']}", n)
                        else what
                    )
                    out.append({"tid": t, "part": main, "what": lab})
    if out:
        with open(mp, "a", encoding="utf-8") as f:
            for o in out:
                f.write(json.dumps(o, ensure_ascii=False) + "\n")
        say(f"written to meta.jsonl: parts {sum('part' in o for o in out)}, rejected {sum('drop' in o for o in out)}")
    return 0
