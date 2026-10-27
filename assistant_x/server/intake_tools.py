# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Intake of the user's own documents from the Claude chat: commands of the assistant-x server (mcp_server.py) on top
of the intake (assistant_x.intake.pipeline). Long steps (the intake, the base recalculation) run in the background, as a separate process
with low priority: the command answers at once, the progress shows in intake_status. Heavy steps take the machine lock
themselves (core/lock.py, journal heavy.log): busy — code 3 and who holds it. Without a video card the
embeddings are not computed on the processor silently: embed.py (gpu_guard) answers with a time estimate, and the
command returns a question for the user to Claude; "yes" — intake_reindex(cpu=True)."""

import collections, datetime, json, os, re, secrets, sys, time

from assistant_x.core import proc

from assistant_x.core import workspace
from assistant_x.intake.config import SERVICE  # the service folders of inbox: one list


class _Paths:
    """The folders of the workspace in use, found each time they are asked (not at import); a folder set on it (a test)
    stays."""

    def __getattr__(self, name):
        if name not in ("ROOT", "INBOX", "WORK"):
            raise AttributeError(name)
        w = workspace.current()
        return {"ROOT": str(w.root), "INBOX": str(w.inbox), "WORK": str(w.work)}[name]


P = _Paths()


def __getattr__(name):  # intake_tools.INBOX and the others for the callers
    if name in ("ROOT", "INBOX", "WORK"):
        return getattr(P, name)
    raise AttributeError(name)


INTAKE = [sys.executable, "-m", "assistant_x.intake.pipeline"]
JOBS = None  # pid and output of the background jobs started from the chat (jobs_dir), unless set


def jobs_dir():
    return JOBS or os.path.join(P.WORK, "_claude")


BUSY = 3  # machine_lock.BUSY, gpu_guard.BUSY: not started, the output says why
TAIL = 40
QUICK = 8  # seconds _start waits: a job that ends by then (lock busy, nothing to do) answers at once


def _cwd():
    return P.ROOT if os.path.isdir(P.ROOT) else None


def _env(**extra):
    from assistant_x.core import env as ax_env  # the libraries of the models kept quiet (core/env.QUIET)

    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", AX_NOPAUSE="1", AX_NO_OPEN="1")
    return {**ax_env.quiet(env), **extra}


def _intake(*args, timeout=600):
    """(code, output) of the intake command args, waited for."""
    try:
        p = proc.run(
            [*INTAKE, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_env(),
            cwd=_cwd(),
            hidden=True,
        )
        return p.returncode, (p.stdout + p.stderr).strip()
    except proc.TimeoutExpired:
        return 1, f"intake {' '.join(args)}: longer than {timeout} s"


def _cut(text, n=12000):
    return text if len(text) <= n else text[: n // 3] + f"\n… ({len(text) - n} characters skipped) …\n" + text[-2 * n // 3 :]


# ---------- background jobs ----------


def _job(kind):
    try:
        with open(os.path.join(jobs_dir(), f"{kind}.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _alive(job):
    if not job:
        return False
    try:
        import psutil

        p = psutil.Process(job["pid"])
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE and abs(p.create_time() - job["created"]) < 2
    except Exception:  # noqa: BLE001 — gone, or psutil missing
        return False


def _tail(kind, n=TAIL):
    try:
        with open(os.path.join(jobs_dir(), f"{kind}.log"), encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return ""
    return "\n".join([x for x in lines if not NOISE.search(x)][-n:])


# lines of a log that tell Claude nothing: progress bars, Python warnings and the source line they quote
NOISE = re.compile(r"\d+%\|[^|]*\||\bit/s\]|^\s*warnings\.warn\(|(?:User|Future|Deprecation|Runtime)Warning:")


def _exit_path(kind):
    return os.path.join(jobs_dir(), f"{kind}.exit.json")


def in_my_job(pid):
    """Windows: True when process pid is in the job object of this process (the innermost one, the client's); False
    when it is not, or when this process is in no job object."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    class Ids(ctypes.Structure):  # JOBOBJECT_BASIC_PROCESS_ID_LIST with room for 4096 processes
        _fields_ = [("assigned", wintypes.DWORD), ("listed", wintypes.DWORD), ("ids", ctypes.c_size_t * 4096)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.QueryInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    )
    ids = Ids()
    if not k32.QueryInformationJobObject(None, 3, ctypes.byref(ids), ctypes.sizeof(ids), None):  # no job: nothing to leave
        return False
    return pid in ids.ids[: ids.listed]


def _popen(cmd, env):
    """The wrapper started detached from the server; (process, out of the client's job object). A background job
    outlives the server: a hidden console of its own that every descendant inherits (never a window, M-008), a process
    group of its own, and out of the job object of the client (Claude closes the server with its whole job) where the
    job object allows it (core/proc.popen)."""
    opts = dict(stdin=proc.DEVNULL, stdout=proc.DEVNULL, stderr=proc.DEVNULL, cwd=_cwd(), env=env)
    p = proc.popen(cmd, detach=True, creationflags=proc.BELOW_NORMAL, **opts)
    if os.name != "nt" or not p.broke_away:
        return p, p.broke_away
    return p, not in_my_job(p.pid)  # a breakaway can succeed and leave it in the job (nested job objects): asked


def _start(kind, cmd, **env):
    """Start cmd in the background (no window, below normal priority, detached from the server) through the wrapper
    jobrun.py: output to work/_claude/<kind>.log, the exit code to <kind>.exit.json. Returns (started, text): a quick
    exit (lock busy, nothing to do) is reported at once."""
    os.makedirs(jobs_dir(), exist_ok=True)
    log, done = os.path.join(jobs_dir(), f"{kind}.log"), _exit_path(kind)
    with open(log, "w", encoding="utf-8") as f:
        f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {' '.join(cmd[1:])}\n")
    if os.path.exists(done):
        os.remove(done)
    from assistant_x.server import jobrun

    ident = secrets.token_hex(8)
    # the base interpreter of the venv starts the wrapper: no redirector process in between (core/proc.python)
    p, apart = _popen(
        [proc.python(), "-m", "assistant_x.server.jobrun", log, done, "--", *cmd],
        proc.python_env(_env(**env, **{jobrun.JOB_ID: ident})),
    )
    import psutil

    job = {
        "id": ident,
        "pid": p.pid,
        "created": psutil.Process(p.pid).create_time(),
        "cmd": cmd[1:],
        "started": time.time(),
        "detached": apart,
    }
    with open(os.path.join(jobs_dir(), f"{kind}.json"), "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False)
    try:
        rc = p.wait(timeout=QUICK)
    except proc.TimeoutExpired:
        return True, ""
    return False, f"Ended at once (code {rc}):\n{_tail(kind)}"


def _exit_code(kind, job):
    """The exit code the wrapper wrote for this job, None when it wrote none."""
    try:
        with open(_exit_path(kind), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data.get("code") if job and data.get("job") == job.get("id") else None


AGAIN = {  # what Claude calls when a job stopped before the end
    "run": "intake_run(resume=True)",
    "apply": "intake_apply() (the plan again; an apply stopped halfway is resumed)",
    "reindex": "intake_reindex()",
    "base_install": "base_install(path, resume=True) (or rollback=True to undo)",
    "base_update": "base_update(path, resume=True) (or rollback=True to undo)",
    "base_remove": "base_remove(id, resume=True) (or rollback=True to undo)",
}


def state(kind, job=None):
    """(state, code) of the background job of kind: "running", "finished" (code 0), "failed" (its code), "stopped"
    (its process is gone without an exit code: closed with the computer or killed), or (None, None) without a job."""
    job = job if job is not None else _job(kind)
    if not job:
        return None, None
    if _alive(job):
        return "running", None
    code = _exit_code(kind, job)
    if code is None:
        return "stopped", None
    return ("finished" if code == 0 else "failed"), code


def state_text(kind, job=None):
    """The state of a job in words, for the status and the start notice."""
    job = job if job is not None else _job(kind)
    s, code = state(kind, job)
    if s == "running" and job and job.get("detached") is False:
        return "running (in the job object of Claude: closing Claude stops it)"
    if s == "failed":
        return f"failed (exit code {code})"
    if s == "stopped":
        again = AGAIN.get(kind, "start it again")
        return f"stopped before the end (no exit code: the process was ended); go on with {again}"
    return s or ""


def interrupted():
    """Lines about the background jobs that failed or were stopped before the end (for the status and the first
    answer of the server)."""
    out = []
    for kind in ("run", "apply", "reindex", "base_export", "base_inspect", "base_install", "base_update", "base_remove"):
        job = _job(kind)
        if state(kind, job)[0] in ("failed", "stopped"):
            out.append(f"Background job {kind} (started {_ago(job)} ago): {state_text(kind, job)}.")
    return out


def _ago(job):
    return f"{(time.time() - job['started']) / 60:.0f} min" if job else "?"


# ---------- the tools ----------


def inbox_list():
    """What lies in inbox waiting for the intake, and whether an intake runs now."""
    if not os.path.isdir(P.INBOX):
        os.makedirs(P.INBOX, exist_ok=True)
    files, size, exts, tops, names = 0, 0, {}, [], []
    for name in sorted(os.listdir(P.INBOX)):
        if name in SERVICE or name.lower() == "_readme.md":
            continue
        tops.append(name + ("\\" if os.path.isdir(os.path.join(P.INBOX, name)) else ""))
    for dp, dns, fns in os.walk(P.INBOX):
        dns[:] = [d for d in dns if not (dp == P.INBOX and d in SERVICE)]
        for fn in fns:
            if dp == P.INBOX and fn.lower() == "_readme.md":
                continue
            files += 1
            names.append(os.path.relpath(os.path.join(dp, fn), P.INBOX))
            size += os.path.getsize(os.path.join(dp, fn))
            ext = os.path.splitext(fn)[1].lower() or "no extension"
            exts[ext] = exts.get(ext, 0) + 1
    out = [f"Folder for the intake: {P.INBOX}"]
    if not files:
        out.append("Empty: ask the user to put documents into this folder.")
    else:
        out.append(
            f"Files {files}, {size / 2**20:.0f} MB: "
            + ", ".join(f"{e} {n}" for e, n in sorted(exts.items(), key=lambda x: -x[1]))
        )
        out.append("Top level: " + "; ".join(tops[:40]) + (" …" if len(tops) > 40 else ""))
        out.append(
            "Time estimate: a page of a text PDF 0.2–1 s, a scan 2.5–9 s. Hundreds of files are better sorted "
            "overnight: intake_run(night=True)."
        )
        hint = profile_hint(names)
        if hint:
            out.append(hint)
    for kind, what in (("run", "an intake"), ("reindex", "a base recalculation")):
        job = _job(kind)
        if _alive(job):
            out.append(f"Running now: {what} ({_ago(job)}): see intake_status.")
    return "\n".join(out)


HINT_SHARE = 0.4  # the share of the files whose names have the words of a profile from which intake_list suggests it
HINT_FILES = 5


def profile_hint(names):
    """A line for Claude when the workspace uses a profile without hint words (the general one) and most of the
    files have the words of another profile ("hint" of its profile.json): the user may want that profile."""
    import re

    from assistant_x.core import config

    try:
        raw = config.load()[1]
    except SystemExit:
        return ""
    current = raw.get("profile") or config.PROFILE
    if config.profile_info(raw).get("hint") or len(names) < HINT_FILES:
        return ""
    for name in config.profiles():
        words = config.profile_info({"profile": name}).get("hint") or []
        if name == current or not words:
            continue
        rx = re.compile("|".join(re.escape(w) for w in words), re.I)
        share = sum(bool(rx.search(n)) for n in names) / len(names)
        if share >= HINT_SHARE:
            info = config.profile_info({"profile": name})
            return (
                f"Profile: {share:.0%} of the files look like documents of the profile {name} ({info.get('name')}); "
                f"this workspace uses {current}. That profile adds its synonyms and designations to the search: ask "
                f'the user whether to set profile = "{name}" in assistant_x.toml (before the intake).'
            )
    return ""


def run(night=False, resume=False):
    job = _job("run")
    if _alive(job):
        return f"An intake is already running ({_ago(job)}). Progress: intake_status."
    cmd = [*INTAKE, "run"] + (["--resume"] if resume else [])
    started, text = _start("run", cmd, **({"AX_PROFILE": "night"} if night else {}))
    if not started:
        return text
    return (
        "The intake started in the background"
        + (
            " in night mode (it takes more of the processor)"
            if night
            else ": while the user is at the computer it takes about half of the processor"
        )
        + ". Progress and result — intake_status (every few minutes, not more often). When it ends: read the summary, "
        "then intake_card for the card drafts."
    )


def apply_progress_path():
    """The progress file of the transfer job (build, apply, then the recalculation: intake/apply_job.py)."""
    return os.path.join(jobs_dir(), "apply.progress.json")


def progress_path():
    """The progress file of the base recalculation (search/reindex.py writes it)."""
    return os.path.join(jobs_dir(), "reindex.progress.json")


def _minutes(seconds):
    m = round(seconds / 60)
    return "less than a minute" if m < 1 else f"about {m} min" if m < 90 else f"about {m / 60:.1f} h"


STAGE_WORDS = {"prep": "preparation", "convert": "conversion", "convert_shard": "OCR in page ranges"}


def batch_words(data):
    """The state of a batch (intake status --json) in words: "34 of 41 done; in work T0002 (conversion 390/1136 pages)…;
    about 40 min left"."""
    head = f"{data['done']} of {data['total']} files done"
    if data.get("ocr_seconds"):
        head += f" (OCR {data['ocr_seconds']} s)"
    work = []
    for x in data["running"]:
        if not x.get("active"):
            continue
        what = STAGE_WORDS.get(x["stage"], x["stage"])
        if x.get("progress"):
            what += f" {x['progress'][0]}/{x['progress'][1]} pages"
        elif x.get("pages"):
            what += f", {x['pages']} pages"
        if x.get("ocr_seconds"):
            what += f", OCR {x['ocr_seconds']} s"
        work.append(f"{x['tid']} ({what})")
    waiting = sum(not x.get("active") for x in data["running"]) + len(data["queued"])
    parts = [head]
    if work:
        parts.append("in work " + ", ".join(work))
    if waiting:
        parts.append(f"waiting {waiting}")
    if data["errors"]:
        parts.append(f"errors and skipped {len(data['errors'])}")
    if data.get("eta_seconds") is not None and (work or waiting):
        parts.append(_minutes(data["eta_seconds"]) + " left")
    lines = ["; ".join(parts) + "."]
    lines += [f"  {e['tid']} [{e['status']}] {e['rel']} — {e.get('why')}" for e in data["errors"][:30]]
    return "\n".join(lines)


def next_step(work, data, running, reindexing):
    """What Claude does next, by the state of the batch."""
    if _alive(_job("apply")):
        return "Next (Claude): wait — the transfer into the library runs (intake_status shows its stage)."
    if running:
        return (
            "Next (Claude): wait (intake_status every few minutes); the drafts of the files that are done are in "
            "meta_draft.jsonl already — their cards may be written now (intake_card, intake_save_meta)."
        )
    if os.path.exists(os.path.join(work, "out", "applied.json")):
        return "Done: the batch is in the library" + ("; the base is being recalculated." if reindexing else ".")
    rc, todo = _intake("todo")
    left = int(todo.split()[0]) if rc == 0 and todo.split() and todo.split()[0].isdigit() else None
    if left:
        return f"Next (Claude): write the cards of {left} files (intake_card, then intake_save_meta)."
    return "Next (Claude): intake_apply() — the plan for the user (every file has its line in meta.jsonl)."


STAGE_NAMES = {
    "build": "the cards and the plan (build)",
    "apply": "moving the files into the library (apply)",
    "build_index": "the search base by words",
    "embed": "the meaning vectors",
}


def reindex_words(job, path=None):
    """The step of the base recalculation (or of the transfer: path) from its progress file."""
    from assistant_x.search import reindex as rx

    p = rx.read_progress(path or progress_path())
    if not p:
        return ""
    stage = STAGE_NAMES.get(p.get("stage"), p.get("stage"))
    n = f": {p['done']} of {p['total']}" if p.get("total") else ""
    return f"Step: {stage}{n}."


def status():
    out = []
    for kind, what in (("run", "Intake"), ("apply", "Transfer to the library"), ("reindex", "Base recalculation")):
        job = _job(kind)
        if not job:
            continue
        alive = _alive(job)
        tail = _tail(kind, 8 if alive else 25)
        head = f"## {what}: {state_text(kind, job)} (started {_ago(job)} ago)"
        if kind in ("reindex", "apply"):
            step = reindex_words(job, apply_progress_path() if kind == "apply" else None) if alive else ""
            out.append(head + (f"\n{step}" if step else "") + f"\n{tail}")
        else:
            out.append(head + (f"\n{tail}" if not alive else ""))
        if kind in ("reindex", "apply") and not alive and "--cpu" in tail:
            out.append(CPU_QUESTION)
    from assistant_x.server import base_tools

    journals = base_tools.open_journals()
    if journals:
        out.append("## Interrupted base change\n" + "\n".join(journals))
    gap = vector_note()
    if gap and not _alive(_job("reindex")):
        out.append("## Search base\n" + gap)
    rc, text = _intake("status", "--json")
    data = None
    if rc == 0:
        try:
            data = json.loads(text.strip().splitlines()[-1])
        except (ValueError, IndexError):
            data = None
    out.append("## Batch\n" + (batch_words(data) if data else text if rc == 0 else "no batches yet"))
    work = _last_work()
    running = _alive(_job("run"))
    if work and data:
        out.append(next_step(work, data, running, _alive(_job("reindex")) or _alive(_job("apply"))))
    if work and not running:
        for name in ("summary.md", "intake_quality.md"):
            p = os.path.join(work, name)
            if os.path.exists(p):
                out.append(f"## {name}\n" + _cut(open(p, encoding="utf-8").read(), 6000))
        rc, todo = _intake("todo")
        out.append("## Without a card (todo)\n" + _cut(todo, 3000))
    return _cut("\n\n".join(out), 16000)


def vector_note():
    """The line about the fragments of the base without a meaning vector ("" when none or no base)."""
    from assistant_x.core import common

    try:
        return common.vector_gap_note(*common.base_vector_gap(common.load_config()["db"]))
    except Exception:  # noqa: BLE001 — a note only: no workspace, no base
        return ""


def _last_work():
    days = (
        sorted(d for d in os.listdir(P.WORK) if re.fullmatch(r"\d{4}-\d{2}-\d{2}(_\d+)?", d))
        if os.path.isdir(P.WORK)
        else []
    )
    return os.path.join(P.WORK, days[-1]) if days else None


def card(tids=None):
    """Brief of the files and the draft metadata Claude turns into meta.jsonl lines."""
    work = _last_work()
    if not work:
        return "No batches: run intake_run first."
    rc, brief = _intake("brief", *(tids or []))
    drafts = []
    p = os.path.join(work, "meta_draft.jsonl")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not tids or d.get("tid") in tids:
                drafts.append(line.strip())
    done = os.path.join(work, "meta.jsonl")
    have = sum(1 for _ in open(done, encoding="utf-8")) if os.path.exists(done) else 0
    head = (
        f"Batch {os.path.basename(work)}; lines in meta.jsonl so far: {have}.\n"
        "Check the draft of every file against its text (intake_card with tids shows the start of the text and the "
        "headings) and save the result with intake_save_meta: document {tid, sec, doc_type, en, au, title, "
        "designation, authors, year, publisher, edition, lang, scope, summary, topics, keywords, terms, questions, "
        "toc, tables, references, units, serial, note, issues}, part {tid, part, what}, duplicate {tid, dupof, why}, "
        "rejected {tid, drop}.\n" + classification()
    )
    if tids:
        rc2, digest = _intake("digest", *tids)
        brief += "\n\n" + digest
    return _cut(head + "\n\n## brief\n" + brief + "\n\n## Drafts (meta_draft.jsonl)\n" + "\n".join(drafts), 20000)


def classification():
    """What Claude needs to classify and describe a document: the shelves with what goes on them,
    the genres, the languages every searchable text needs, the topics the library uses already."""
    from assistant_x.core import card as C
    from assistant_x.core import config

    try:
        w, raw = config.load()
    except SystemExit:
        return ""
    langs = config.card_languages(raw)
    out = [
        f"Searchable texts (title, designation, keywords, terms[].name, toc[].title, tables[].title, units[].title) "
        f"are maps in these languages: {', '.join(langs)}; scope, summary, questions, note in English.",
        "Shelves (sec): the shelf of the genre (doc_type) below; another one only when the text clearly belongs "
        "there, X/Other with a note when unsure:",
    ]
    for sh in config.sections(raw):
        out.append(f"  {sh['letter']} {' / '.join(sh['name'].values())}: {sh['about']} Types: {', '.join(sh['doc_types'])}.")
    out.append("doc_type, one of: " + ", ".join(C.doc_types()) + ".")
    controlled = config.topics(raw)
    if controlled:
        out.append("topics, from the list of the profile: " + ", ".join(sorted(controlled)) + ".")
    else:
        used = collections.Counter()
        for p in C.paths(w.cards).values():
            try:
                used.update(C.load(p)["doc"].get("topics") or [])
            except (C.CardError, KeyError):
                continue
        out.append(
            "topics: 1-8 English ids (lower_case_with_underscores); reuse those of the library: "
            + (", ".join(t for t, _ in used.most_common(80)) or "none yet")
            + "."
        )
    return "\n".join(out)


def inside(path, folder):
    """True when path (resolved, links followed) lies inside folder."""
    try:
        p, f = os.path.realpath(path), os.path.realpath(folder)
        return os.path.commonpath([os.path.normcase(p), os.path.normcase(f)]) == os.path.normcase(f)
    except ValueError:  # another disk
        return False


def _rows(lines):
    """(rows, error) of lines given as dicts or JSON strings."""
    rows = []
    for x in lines:
        if isinstance(x, str) and not x.strip():
            continue
        try:
            rows.append(x if isinstance(x, dict) else json.loads(x))
        except ValueError as e:
            return None, f"A line is not JSON ({e}): {str(x)[:200]}"
    bad = [r for r in rows if not isinstance(r, dict) or not r.get("tid")]
    if bad:
        return None, f"A line has no tid: {json.dumps(bad[0], ensure_ascii=False)[:200]}"
    return rows, ""


def save_meta(lines=None, path=None, check_only=False):
    """Append the lines to meta.jsonl of the last batch and check the whole file (assistant-x intake check-meta).
    lines: the lines in the call; path: a file of lines Claude wrote with the client's file tools, inside the batch
    folder only (the meta.jsonl of the batch itself is checked as it is); check_only: check the file with the lines
    added, write nothing."""
    work = _last_work()
    if not work:
        return "No batches: run intake_run first."
    meta = os.path.join(work, "meta.jsonl")
    own = False
    if path:
        if not inside(path, work):
            return f"The file must lie in the folder of the batch {work}: {path}"
        own = os.path.normcase(os.path.realpath(path)) == os.path.normcase(os.path.realpath(meta))
        try:
            with open(path, encoding="utf-8") as f:
                given = f.read().splitlines()
        except OSError as e:
            return f"The file cannot be read: {e}"
        lines = ([] if own else given) + list(lines or [])
    rows, why = _rows(lines or [])
    if why:
        return why
    if not rows and not own:
        return "No lines: give lines, or path= of a file of lines in the folder of the batch."
    if check_only:
        trial = os.path.join(work, "meta.check.jsonl")
        with open(trial, "w", encoding="utf-8", newline="\n") as out:
            if os.path.exists(meta):
                with open(meta, encoding="utf-8") as f:
                    out.write(f.read().rstrip("\n") + "\n" if os.path.getsize(meta) else "")
            for r in rows:
                out.write(json.dumps(r, ensure_ascii=False) + "\n")
        try:
            rc, text = _intake("check-meta", "--meta", trial)
        finally:
            os.remove(trial)
        return f"Checked only, nothing written ({len(rows)} lines with meta.jsonl).\n{text}"
    if rows:
        with open(meta, "a", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    rc, text = _intake("check-meta")
    rc2, todo = _intake("todo")
    head = f"Lines written: {len(rows)}." if rows else "meta.jsonl of the batch checked as it is."
    return f"{head}\n{text}\n\nStill without a line:\n{_cut(todo, 3000)}"


def auto_apply_on():
    """[intake] auto_apply = true in assistant_x.local.toml of the workspace: this PC, written by the user. Never from
    assistant_x.toml (it may come with a copied workspace or a package) nor from a document."""
    import tomllib

    from assistant_x.intake import config as intake_cfg

    try:
        with open(intake_cfg.local_path(), "rb") as f:
            return (tomllib.load(f).get("intake") or {}).get("auto_apply") is True
    except (OSError, ValueError):
        return False


def always_ask(work):
    """Why this batch needs the user's yes even with auto_apply ([] when it does not): a new version that replaces or
    links a document of the library, a duplicate of a document of the library, a file rejected, hidden text addressed
    to an AI."""
    from assistant_x.core import card as C
    from assistant_x.core.suspect import addressed_to_ai
    from assistant_x.intake import meta_schema
    from assistant_x.intake.state import State

    meta, _ = (
        meta_schema.load(os.path.join(work, "meta.jsonl")) if os.path.exists(os.path.join(work, "meta.jsonl")) else ({}, [])
    )
    out = []
    for tid, m in sorted(meta.items()):
        if m.get("replaces"):
            out.append(f"{tid} replaces {m['replaces']} of the library")
        if m.get("other_version"):
            out.append(f"{tid} is another version of {m['other_version']} of the library")
        if m.get("dupof") and C.is_code(str(m["dupof"])):
            out.append(f"{tid} is a duplicate of {m['dupof']} of the library")
        if m.get("drop"):
            out.append(f"{tid} is rejected ({str(m['drop'])[:80]})")
    st = os.path.join(work, "state.sqlite")
    rows = State(st).all() if os.path.exists(st) else []
    for r in rows:
        m = meta.get(r["tid"], {})
        if r["status"] == "dup" and r.get("dup_of") and C.is_code(str(r["dup_of"])) and not (m.get("sec") or m.get("part")):
            if not m.get("dupof"):
                out.append(f"{r['tid']} is a duplicate of {r['dup_of']} of the library")
        hidden = os.path.join(work, "log", f"{r['tid']}.hidden.json")
        if r.get("hidden") and os.path.exists(hidden):
            try:
                with open(hidden, encoding="utf-8") as f:
                    found = json.load(f).get("found") or {}
            except (OSError, ValueError):
                found = {}
            text = " ".join(str(s.get("text") or "") for spans in found.values() for s in spans if isinstance(s, dict))
            if addressed_to_ai(text):
                out.append(f"{r['tid']} holds hidden text addressed to an AI")
    return out


AUTO = "Applied automatically (auto_apply = true in assistant_x.local.toml): the check of meta.jsonl found no error"


def apply(confirm=False, personal=False, token=None, ask=None):
    """build, then apply --dry-run (confirm=False: the plan to show the user, with a confirmation token); confirm=True
    with that token (server/confirm.py): build, apply and the reindex as one background job (start_apply), the answer at
    once and the stage in intake_status. personal: mark the documents of the batch
    personal (only when the user asks to keep this addition apart). ask(question): the client asks the user itself
    (confirm.ask_user) where it can; a "no" changes nothing."""
    from assistant_x.core import debuglog
    from assistant_x.server import confirm as K

    args = {"confirm": confirm, "personal": personal}
    if confirm:
        why = K.check("intake_apply", P.ROOT, token)
        if why:
            debuglog.log_change("intake_apply", args, "refused: no valid token")
            return why
        if ask and ask("Assistant X: move the documents of the batch into the library, as in the plan shown?") is False:
            debuglog.log_change("intake_apply", args, "declined by the user")
            return K.DECLINED
    if _alive(_job("run")):
        return "The intake is still running: wait until it ends (intake_status)."
    if _alive(_job("apply")):
        return f"The transfer is already running (started {_ago(_job('apply'))} ago): intake_status shows its stage."
    note = ""
    if not confirm and auto_apply_on():
        work = _last_work()
        reasons = always_ask(work) if work else ["no batch"]
        rc, checked = _intake("check-meta")
        if rc == 0 and not reasons:
            return _auto_apply(args, personal)
        note = "auto_apply is on, but this plan needs the user's yes: " + (
            "; ".join(reasons) if reasons else "the check of meta.jsonl found errors:\n" + _cut(checked, 3000)
        )
    debuglog.log_change("intake_apply", args, "started" if confirm else "plan")
    if confirm:
        return start_apply(personal)
    rc, built = _intake("build", *(["--personal"] if personal else []), timeout=3600)
    if rc:
        return "The build failed" + (" (the machine lock is busy)" if rc == BUSY else "") + f":\n{_cut(built, 8000)}"
    rc, plan = _intake("apply", "--dry-run", timeout=3600)
    return (
        (note + "\n\n" if note else "")
        + _cut(built, 4000)
        + "\n\n"
        + _cut(plan, 8000)
        + (
            ""
            if rc
            else K.instruction(
                "intake_apply",
                P.ROOT,
                'intake_apply(confirm=True, token="TOKEN")'
                if not personal
                else 'intake_apply(confirm=True, personal=True, token="TOKEN")',
            )
        )
    )


def batch_documents(work):
    """How many documents the transfer moves: the lines of meta.jsonl that give a shelf (the parts and the dropped
    files aside)."""
    from assistant_x.intake import meta_schema

    path = os.path.join(work or "", "meta.jsonl")
    meta = meta_schema.load(path)[0] if work and os.path.exists(path) else {}
    return sum(bool(m.get("sec")) and not m.get("drop") for m in meta.values())


def start_apply(personal=False, auto=False):
    """The transfer in the background (intake/apply_job.py: build, apply, the recalculation); the answer at once."""
    prog = apply_progress_path()
    if os.path.exists(prog):
        os.remove(prog)
    cmd = [sys.executable, "-m", "assistant_x.intake.apply_job", *(["--personal"] if personal else [])]
    started, text = _start("apply", cmd, AX_PROGRESS=prog)
    if not started:
        return f"The transfer did not start: {text}"
    n = batch_documents(_last_work())
    return (
        (f"{AUTO}. " if auto else "")
        + f"The transfer started in the background: {n} documents; intake_status shows the stage; the base is "
        "recalculated after it."
    )


def _auto_apply(args, personal):
    """build, apply and the reindex without a token, in the background: auto_apply is on, the check found no error and
    nothing in the plan needs the user (always_ask). changes.log notes it as automatic."""
    from assistant_x.core import debuglog

    debuglog.log_change("intake_apply", {**args, "auto": True}, "started (auto_apply)")
    return start_apply(personal, auto=True)


def up_to_date(cfg):
    """The words "The base is up to date: …" when nothing is to recalculate (no fragment without a vector, no text or
    card newer than the base), else ""."""
    from assistant_x.search import reindex as rx

    if not os.path.exists(cfg["db"]) or pending_fragments(cfg):
        return ""
    since = max(os.path.getmtime(p) for p in (cfg["db"], cfg["db"] + "-wal") if os.path.exists(p))
    cards = cfg.get("cards_dir") or ""
    for name in os.listdir(cards) if os.path.isdir(cards) else ():
        if name.endswith(".json") and os.path.getmtime(os.path.join(cards, name)) > since:
            return ""
    last = rx.read_last(cfg) or {}
    total = last.get("fragments") or rx.counts(cfg["db"])[0]
    when = (last.get("finished") or datetime.datetime.fromtimestamp(since).isoformat(timespec="seconds")).replace("T", " ")
    rate = (
        f", {last['per_second']:g}/s" + (f" on {last['device']}" if last.get("device") else "")
        if last.get("per_second")
        else ""
    )
    return f"The base is up to date: last recalculation {when}, {total} fragments{rate}. intake_reindex(force=True) runs it anyway."


def reindex(cpu=False, force=False):
    """build_index.py, then embed.py for the new fragments, in the background; nothing when the base is up to date
    (force=True runs it anyway). Without a video card embed.py does not start on the processor by itself: the answer
    carries its estimate and the question for the user."""
    if _alive(_job("reindex")):
        return f"A base recalculation is already running ({_ago(_job('reindex'))}): intake_status."
    if _alive(_job("apply")):
        return "The transfer into the library is running: the base is recalculated after it (intake_status)."
    if not force:
        from assistant_x.core.common import load_config

        try:
            fresh = up_to_date(load_config())
        except Exception:  # noqa: BLE001 — no workspace or base: the recalculation says why
            fresh = ""
        if fresh:
            return fresh
    prog = progress_path()
    if os.path.exists(prog):
        os.remove(prog)
    cmd = [sys.executable, "-m", "assistant_x.search.reindex"] + (["--cpu"] if cpu else [])
    started, text = _start("reindex", cmd, AX_PROGRESS=prog)
    if started:
        est = embed_estimate(cpu)
        return (
            "The base recalculation started in the background: new documents are found by words right after "
            "build_index, by meaning after embed"
            + (" on the processor (low priority)" if cpu else "")
            + ". "
            + (est + " " if est else "")
            + "Progress — intake_status."
        )
    if "--cpu" in text:
        return "The user has to decide: " + text.split("\n", 1)[-1].strip() + "\n" + CPU_QUESTION
    return text


def pending_fragments(cfg):
    """About how many fragments embed.py will compute: those of the base without a vector, and a fragment per page of
    every text newer than the base (build_index makes their fragments first)."""
    from assistant_x.core.common import connect
    from assistant_x.core.formats import PAGE_RX

    n, since = 0, 0.0
    if os.path.exists(cfg["db"]):
        con = connect(cfg["db"], readonly=True)
        n = con.execute("SELECT count(*) FROM chunks WHERE vec_row IS NULL").fetchone()[0]
        con.close()
        since = max(os.path.getmtime(p) for p in (cfg["db"], cfg["db"] + "-wal") if os.path.exists(p))
    texts = cfg.get("texts_dir") or ""
    for name in os.listdir(texts) if os.path.isdir(texts) else ():
        path = os.path.join(texts, name)
        if name.endswith(".md") and os.path.getmtime(path) > since:
            with open(path, encoding="utf-8", errors="replace") as f:
                n += max(1, len(PAGE_RX.findall(f.read())))
    return n


def embed_estimate(cpu=False):
    """ "Embeddings: about 12 min (900 fragments, on the video card, the speed measured on this PC)." for the reindex,
    or "" when nothing is to compute or no speed is known (a video card never measured here)."""
    from assistant_x.core import gpu_guard
    from assistant_x.core.common import load_config

    try:
        n = pending_fragments(load_config())
    except Exception:  # noqa: BLE001 — an estimate only: no base, no workspace
        return ""
    if not n:
        return ""
    kind = "cpu" if cpu else next((k for k in ("cuda", "dml") if gpu_guard.measured("fragments", k)), None)
    if kind is None:
        return ""
    from assistant_x.search.embed import CPU_S

    s = gpu_guard.estimate(n, "fragments", kind, cpu_s=CPU_S)
    how = "the speed measured on this PC" if gpu_guard.measured("fragments", kind) else "not measured on this PC yet"
    where = "on the processor" if kind == "cpu" else "on the video card"
    return f"Embeddings: {gpu_guard.duration(s)} ({n} fragments, {where}, {how})."


CPU_QUESTION = (
    "The embeddings of the new fragments are not computed: there is no video card or it has too little memory "
    '(the estimate is above). Ask the user: "Compute on the processor now, at low priority?" Yes — '
    "intake_reindex(cpu=True); no — the new documents are found by words only for now, they can be computed later."
)
