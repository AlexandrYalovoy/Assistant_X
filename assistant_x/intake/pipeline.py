# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Intake of inbox on this PC: one command from the folder to the texts and the summary, then the metadata (Claude),
the build and the apply.

    assistant-x intake run [--dry-run] [--workers N] [--work DIR]
        preparing the folder (archives unpacked beside them, letters and Excel to _to_delete), SHA duplicates, PDF from
        DOC/DOCX, hidden text, duplicates by content, Markdown, quality report, metadata draft, summary.
        A second run on the same day goes on from where it stopped.
    assistant-x intake status | todo | digest T0001 … | groups [--write] | draft | quality | requeue T0001 …
    assistant-x intake check-meta      check meta.jsonl (meta_schema.py)
    assistant-x intake build           cards, texts, catalog rows, events, moves (build.py)
    assistant-x intake apply [--dry-run]  move into library, index, manifest, journal (apply.py)
    assistant-x intake journal         build index\\journal.md (core/journal.py)
    assistant-x intake reflag [--dry-run] [CODE ...]  page flags and text notes of the cards made again from the texts
                                       of the library, no OCR (text_notes.py)

The work folder of a batch: intake/work/<DATE> (state.sqlite, md/, meta_draft.jsonl, summary.md, intake_quality.md);
paths and programs: assistant_x.toml (intake/config.py). The parts: batch.py (shared helpers), prepare.py, process.py,
review.py; this module holds the commands."""

import argparse, collections, sys, time

from assistant_x.intake import config as intake_cfg
from assistant_x.core import lock as intake_lock
from assistant_x.core import journal
from assistant_x.intake.state import State
from assistant_x.intake.batch import say, work_dir
from assistant_x.intake.prepare import prepare, walk
from assistant_x.intake.process import Batch, register
from assistant_x.intake.review import cmd_brief, cmd_digest, cmd_groups, cmd_pack, cmd_status, cmd_todo, summary
from assistant_x.intake.review import hidden_line  # noqa: F401 — re-exported for the callers
from assistant_x.intake.tools import unpack  # noqa: F401 — re-exported for the callers


def cmd_run(cfg, a):
    work = work_dir(cfg, a.work, new=not getattr(a, "resume", False))  # --resume: the latest batch, its done files stay
    if not cfg.inbox.is_dir():
        sys.exit(f"No folder {cfg.inbox}")
    t0 = time.time()
    work.mkdir(parents=True, exist_ok=True)
    state = State(work / "state.sqlite")
    state.reset_running()
    say(f"Intake {cfg.inbox} → {work}")
    if a.dry_run:
        say("Trial run: nothing is moved or unpacked.")
        prepare(cfg, state, dry=True)
        files = [rel for _, rel in walk(cfg.inbox)]
        say(f"Files to process: {len(files)} (without the letters, Excel and archives that go to _to_delete)")
        return 0
    from assistant_x.core import common

    need = common.folder_bytes(*(full for full, _ in walk(cfg.inbox)))
    low = common.free_space_problem(work, need, cfg.disk)
    if low:
        sys.exit(low)
    counts, events, problems = prepare(cfg, state)
    old = collections.Counter(state.get_meta("prepare", {}))
    old.update(counts)
    state.set_meta("prepare", dict(old))
    state.set_meta("problems", state.get_meta("problems", []) + problems)
    n = register(cfg, state)
    say(f"New files: {n}; preparation: {dict(counts) or 'nothing to do'}")
    workers = cfg.workers if a.workers is None else a.workers
    state.set_meta("started", time.time())  # the estimate of the time left counts from here (intake status)
    Batch(cfg, work, state, workers).run()
    from assistant_x.intake import metadraft
    from assistant_x.intake import quality_report

    q = quality_report.report(work, state) if state.all("done") else None
    metadraft.write_drafts(work, state, index=cfg.index, profile=cfg)
    if events:
        journal.sync(cfg.index)
    text = summary(cfg, work, state, state.get_meta("prepare", {}), state.get_meta("problems", []), time.time() - t0, q)
    say("\n" + text)
    return 0


def cmd_requeue(cfg, a):
    """Back to the queue without the duplicate check (a wrong duplicate verdict) or after fixing a file."""
    work = work_dir(cfg, a.work)
    state = State(work / "state.sqlite")
    for t in a.tids:
        if state.get(t) is None:
            say(f"{t}: not in the batch")
            continue
        state.update(t, status="queued", nodup=True, dup_of=None, why="returned to the queue by hand")
        say(f"{t}: queued; next assistant-x intake run --work {work}")
    return 0


def cmd_draft(cfg, a):
    from assistant_x.intake import metadraft

    work = work_dir(cfg, a.work)
    n = metadraft.write_drafts(work, State(work / "state.sqlite"), index=cfg.index, profile=cfg)
    say(f"Metadata draft: {n} lines in {work / 'meta_draft.jsonl'}")
    return 0


def cmd_quality(cfg, a):
    from assistant_x.intake import quality_report

    work = work_dir(cfg, a.work)
    say(quality_report.summary_line(quality_report.report(work, State(work / "state.sqlite"))))
    return 0


def cmd_check_meta(cfg, a):
    from assistant_x.intake import meta_schema

    meta, errors, warnings = meta_schema.check_batch(cfg, work_dir(cfg, a.work), a.meta)
    for e in errors:
        say(e)
    for w in warnings:
        say(f"warning: {w}")
    say(f"meta.jsonl: files {len(meta)}, errors {len(errors)}")
    return 1 if errors else 0


def cmd_build(cfg, a):
    from assistant_x.intake import build as intake_build

    return intake_build.build(cfg, work_dir(cfg, a.work), personal=a.personal)


def cmd_apply(cfg, a):
    from assistant_x.intake import apply as intake_apply

    return intake_apply.apply(cfg, work_dir(cfg, a.work), dry=a.dry_run, resume=a.resume)


def cmd_journal(cfg, a):
    return journal.main(["--index", str(cfg.index)] + (["--check"] if a.check else []))


def cmd_ocr(cfg, a):
    from assistant_x.intake import ocr_quality

    return getattr(ocr_quality, "cmd_" + a.cmd.replace("-", "_"))(cfg, a)


def cmd_reflag(cfg, a):
    from assistant_x.intake import text_notes

    text_notes.reflag(cfg, a.codes, a.dry_run, say=say)
    return 0


LOCKED = ("run", "requeue", "build", "apply", "redo", "reflag")
HEAVY = ("run", "build", "apply", "redo")  # also take the machine lock (core/lock.py) and the priority of assistant_x.toml


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="assistant-x intake",
        description="Intake of inbox on the PC",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--config", help="another assistant_x.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    commands = {
        "run": cmd_run,
        "status": cmd_status,
        "todo": cmd_todo,
        "digest": cmd_digest,
        "groups": cmd_groups,
        "brief": cmd_brief,
        "pack": cmd_pack,
        "requeue": cmd_requeue,
        "draft": cmd_draft,
        "quality": cmd_quality,
        "check-meta": cmd_check_meta,
        "build": cmd_build,
        "apply": cmd_apply,
        "journal": cmd_journal,
        "vocab": cmd_ocr,
        "ocr-score": cmd_ocr,
        "sample": cmd_ocr,
        "redo": cmd_ocr,
        "reflag": cmd_reflag,
    }
    for name in commands:
        p = sub.add_parser(name)
        p.add_argument("--work", help="the work folder of the batch (default: today's for run, the latest for the others)")
        if name in ("run", "apply"):
            p.add_argument("--dry-run", action="store_true", help="show what would be done, change nothing")
        if name == "run":
            p.add_argument("--workers", type=int, help="at most this many processes (0: everything in this process)")
            p.add_argument("--resume", action="store_true", help="continue the latest batch: done files are skipped")
        if name == "apply":
            p.add_argument("--resume", action="store_true", help="continue an interrupted apply (its journal)")
        if name == "build":
            p.add_argument(
                "--personal",
                action="store_true",
                help="mark the documents of this batch personal (only when the user asks to keep them apart)",
            )
        if name in HEAVY:
            p.add_argument(
                "--wait", action="store_true", help="if another heavy task is running, wait for it (otherwise exit code 3)"
            )
        if name in ("digest", "requeue", "brief"):
            p.add_argument("tids", nargs="*")
        if name == "status":
            p.add_argument("--json", action="store_true", help="the state as JSON (intake_status renders it)")
        if name == "check-meta":
            p.add_argument("--meta", help="check this file of lines instead of the meta.jsonl of the batch")
        if name == "todo":
            p.add_argument("--by-folder", action="store_true", help="by folder: how many files have no meta line and which")
        if name == "pack":
            p.add_argument("folder", help="a folder inside inbox: all its processed files are one document")
            p.add_argument("--main", help="tid of the main file (default: the longest text)")
            p.add_argument("--write", action="store_true", help="append the lines of the parts to meta.jsonl")
        if name == "groups":
            p.add_argument("--write", action="store_true")
        if name == "journal":
            p.add_argument("--check", action="store_true")
        if name == "reflag":
            p.add_argument("codes", nargs="*", help="codes (default: every card of the library)")
            p.add_argument("--dry-run", action="store_true", help="count what would change, write nothing")
        if name in ("ocr-score", "redo"):
            p.add_argument("codes", nargs="*", help="codes (default: all the texts of index\\texts)")
        if name == "ocr-score":
            p.add_argument("--all", action="store_true", help="score again the rows scored with the OCR confidence too")
            p.add_argument("--report", help="write a Markdown report: the distribution and the worst documents")
        if name == "sample":
            p.add_argument("n", type=int)
            p.add_argument("--out", help="the folder of the sample (default debug/ocr_quality/sample)")
            p.add_argument("--seed", type=int, default=1)
        if name == "redo":
            p.add_argument(
                "--worst", type=int, help="also the N worst documents of ocr_quality.tsv with a score below the threshold"
            )
            p.add_argument("--below", type=float, help="the threshold for --worst (default: common.QUALITY ocr_note)")
            p.add_argument("--dry-run", action="store_true", help="recognize and score, do not replace the text")
            p.add_argument("--reuse", help="a redo folder of an earlier (stopped) run: the texts it finished are taken")
    a = ap.parse_args(argv)
    cfg = intake_cfg.load(a.config)
    if a.cmd not in LOCKED:
        return commands[a.cmd](cfg, a)
    if a.cmd not in HEAVY or getattr(a, "dry_run", False) and a.cmd in ("apply", "run"):  # a trial run is light
        with intake_lock.hold(cfg.work, a.cmd):  # a second run, requeue, build or apply at the same time is refused
            return commands[a.cmd](cfg, a)
    from assistant_x.intake import balance
    from assistant_x.core import lock as machine_lock

    try:
        with machine_lock.heavy_task(f"intake {a.cmd}", wait=a.wait, say=say):
            balance.apply_self(cfg.priority, cfg.affinity)  # the workers, soffice and tesseract inherit it
            say(f"Priority: {cfg.priority}, low disk priority")
            with intake_lock.hold(cfg.work, a.cmd):
                return commands[a.cmd](cfg, a)
    except machine_lock.Busy:
        return machine_lock.BUSY


if __name__ == "__main__":
    sys.exit(main())
