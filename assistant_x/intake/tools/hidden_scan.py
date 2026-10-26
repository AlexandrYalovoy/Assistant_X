# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hidden text in the whole library: tools/hidden.py over every PDF of library, one process per file
(a time and memory limit each, low priority), continues where it stopped.
Result: intake/reports/hidden_text_<DATE>.tsv (a row per PDF), progress and the summary in the .log beside it;
the last line of a finished pass is "DONE …".

    python -m assistant_x.intake.tools.hidden_scan                 run or continue the pass (in the background: pythonw)
    python -m assistant_x.intake.tools.hidden_scan --new           a new pass over the PDFs added since the last finished one
                                                         (under the machine lock; AX_PRIORITY=idle for spare time only)
    python -m assistant_x.intake.tools.hidden_scan --status        how far the latest pass is
    python -m assistant_x.intake.tools.hidden_scan --apply [--dry-run] [--force]
        after a finished pass: file.hidden_text in the card of every document where some was found
        (build_index.py turns it into the "Source quality" warning)
"""

import argparse, datetime, json, os, re, sys, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from assistant_x.core import formats
from assistant_x.intake import config as intake_cfg
from assistant_x.intake.limits import run

HEADER = ["path", "code", "pages", "hidden", "hidden_pages", "reasons", "example", "result"]
CODE_RX = re.compile(r"^([A-Z]-\d{5}(?:-\d{2,3})?)_")
DONE = "DONE"  # the last line of a finished pass


def code_of(rel):
    parts = re.split(r"[\\/]", rel)
    for name in (parts[-1], *reversed(parts[:-1])):
        m = CODE_RX.match(name)
        if m:
            return m.group(1)
    return ""


def pdfs(cfg):
    top = intake_cfg.lp(cfg.library)
    out = []
    for dp, dns, fns in os.walk(top):
        dns.sort()
        for f in sorted(fns):
            if f.lower().endswith(".pdf"):
                p = os.path.join(dp, f)
                out.append((p, "library\\" + formats.place_of(os.path.relpath(p, top))))  # the form of the cards
    return out


def latest(reports):
    files = sorted(reports.glob("hidden_text_*.tsv"), key=lambda p: p.stem[-10:])
    return files[-1] if files else None


def finished(tsv):
    log = tsv.with_suffix(".log")
    last = (log.read_text(encoding="utf-8").strip().splitlines() or [""])[-1] if log.exists() else ""
    return DONE in last


def done_paths(tsv):
    if not tsv.exists():
        return set()
    return {ln.split("\t")[0] for ln in tsv.read_text(encoding="utf-8").splitlines()[1:] if ln.strip()}


def check_one(full, rel, cfg, tmp):
    rep = Path(tmp) / f"{threading.get_ident()}.json"
    if rep.exists():
        rep.unlink()
    rc, why = run(
        [sys.executable, "-X", "utf8", "-I", "-m", "assistant_x.intake.tools.hidden", full, "--json", rep],
        timeout=900,
        memory_mb=cfg.worker_memory_mb,
        env=intake_cfg.tool_env(cfg),
        low_priority=True,
    )
    try:
        r = json.loads(rep.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [rel, code_of(rel), "", "", "", "", "", why or f"error (code {rc})"]
    reasons = {}
    sample = ""
    for items in r.get("found", {}).values():
        for it in items:
            reasons[it["why"]] = reasons.get(it["why"], 0) + 1
            sample = sample or re.sub(r"\s+", " ", it["text"])[:150]
    return [
        rel,
        code_of(rel),
        r.get("pages", ""),
        r.get("hidden", 0),
        ",".join(map(str, r.get("hidden_pages", [])[:30])),
        "; ".join(f"{k}: {v}" for k, v in reasons.items()),
        sample,
        "ok",
    ]


def scan(cfg, workers, new_only=False):
    """new_only: a new pass starts from the rows of the latest finished one and checks only the PDFs it had not seen
    (the documents added since), instead of the whole library again."""
    reports = cfg.reports
    reports.mkdir(parents=True, exist_ok=True)
    tsv = latest(reports)
    if tsv is None or finished(tsv):
        old = tsv
        tsv = reports / f"hidden_text_{datetime.date.today().isoformat()}.tsv"
        if new_only and old is not None and old != tsv and not tsv.exists():
            have = {p for _, p in pdfs(cfg)}
            rows = [ln for ln in old.read_text(encoding="utf-8").splitlines()[1:] if ln.split("\t")[0] in have]
            tsv.write_text("\n".join(["\t".join(HEADER)] + rows) + "\n", encoding="utf-8", newline="\n")
            with open(tsv.with_suffix(".log"), "a", encoding="utf-8") as L:
                L.write(
                    f"{datetime.datetime.now():%Y-%m-%d %H:%M} taken from {old.name}: {len(rows)} PDF, checking only the new ones\n"
                )
    log = tsv.with_suffix(".log")
    seen = done_paths(tsv)
    todo = [(f, r) for f, r in pdfs(cfg) if r not in seen]
    total = len(seen) + len(todo)
    lock = threading.Lock()
    if not tsv.exists():
        tsv.write_text("\t".join(HEADER) + "\n", encoding="utf-8", newline="\n")
    t0, n = time.time(), len(seen)
    with (
        open(log, "a", encoding="utf-8") as L,
        open(tsv, "a", encoding="utf-8", newline="\n") as T,
        tempfile.TemporaryDirectory() as tmp,
    ):
        L.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M} start: PDF in all {total}, checked already {len(seen)}\n")
        L.flush()

        def one(item):
            nonlocal n
            row = check_one(item[0], item[1], cfg, tmp)
            with lock:
                T.write("\t".join(re.sub(r"[\t\r\n]+", " ", str(x)) for x in row) + "\n")
                T.flush()
                n += 1
                if row[3] or row[7] != "ok" or n % 50 == 0:
                    L.write(
                        f"{n}/{total} {time.time() - t0:.0f} s  {row[1] or row[0][-60:]}  hidden {row[3] or 0}  {row[7]}\n"
                    )
                    L.flush()

        with ThreadPoolExecutor(workers) as ex:
            list(ex.map(one, todo))
        rows = [ln.split("\t") for ln in tsv.read_text(encoding="utf-8").splitlines()[1:] if ln.strip()]
        hid = [r for r in rows if r[3] not in ("", "0")]
        bad = [r for r in rows if r[7] != "ok"]
        L.write(
            f"{DONE} {datetime.datetime.now():%Y-%m-%d %H:%M}: PDF checked {len(rows)}, with hidden text {len(hid)} "
            f"(documents {len({r[1] for r in hid if r[1]})}), not checked (time, memory, error) {len(bad)}\n"
        )
    return tsv


def status(cfg):
    tsv = latest(cfg.reports)
    if tsv is None:
        print("The hidden text check has not run yet.")
        return
    rows = [ln.split("\t") for ln in tsv.read_text(encoding="utf-8").splitlines()[1:] if ln.strip()]
    total = len(pdfs(cfg))
    hid = [r for r in rows if r[3] not in ("", "0")]
    print(
        f"{tsv}: checked {len(rows)} of {total} PDF, with hidden text {len(hid)}"
        + (" — the pass is finished" if finished(tsv) else " — running or interrupted (start it again, it goes on)")
    )
    for r in hid[:20]:
        print(f"  {r[1] or r[0]}: {r[3]} fragments, pages {r[4]}; {r[5]}")


def apply(cfg, dry=False, force=False):
    tsv = latest(cfg.reports)
    if tsv is None or not (finished(tsv) or force):
        sys.exit('No full pass yet: wait for the line "DONE" in the .log (or --force).')
    rows = [ln.split("\t") for ln in tsv.read_text(encoding="utf-8").splitlines()[1:] if ln.strip()]
    from assistant_x.core import card as C

    by_doc = {}
    for r in rows:
        if r[3] not in ("", "0") and r[1]:
            by_doc.setdefault(C.main_code(r[1]), []).append(r)
    date = tsv.stem.rsplit("_", 1)[-1]
    changed = 0
    for code, items in sorted(by_doc.items()):
        path = cfg.index / "cards" / f"{code}.json"
        if not path.exists():
            print(f"{code}: no card, skipped")
            continue
        card = C.load(path)
        if card["file"].get("hidden_text"):
            continue
        card["file"]["hidden_text"] = [
            {
                "code": r[1],
                "fragments": int(r[3]),
                "pages": [int(x) for x in re.findall(r"\d+", r[4]) if int(x) > 0],
                "note": f"a check of the whole library {date}; the search text was not changed, check the document",
            }
            for r in items
        ]
        print(f"{code}: " + "; ".join(f"{r[1]}: {r[3]} fragments, PDF pages {r[4]}" for r in items))
        if not dry:
            C.dump(card, path)
        changed += 1
    print(f"Cards {'that would change' if dry else 'changed'}: {changed}. Next: assistant-x build")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Hidden text in the whole library")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--apply", action="store_true", help="mark the cards (after a full pass)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="--apply on an unfinished pass")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--new", action="store_true", help="a new pass: only the PDFs that were not in the last finished one")
    ap.add_argument("--wait", action="store_true", help="if another heavy task is running, wait for it (otherwise code 3)")
    a = ap.parse_args(argv)
    cfg = intake_cfg.load()
    if a.status:
        return status(cfg)
    if a.apply:
        return apply(cfg, a.dry_run, a.force)
    from assistant_x.intake import balance
    from assistant_x.core import lock as machine_lock

    try:
        with machine_lock.heavy_task("hidden text check", wait=a.wait):
            balance.apply_self(cfg.priority, cfg.affinity)  # AX_PRIORITY=idle: only the spare time of the PC
            print(f"Result: {scan(cfg, a.workers, a.new)}")
    except machine_lock.Busy:
        return machine_lock.BUSY


if __name__ == "__main__":
    main()
