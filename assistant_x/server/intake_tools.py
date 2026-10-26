# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Intake of the user's own documents from the Claude chat: commands of the assistant-x server (mcp_server.py) on top
of the intake (assistant_x.intake.pipeline). Long steps (the intake, the base recalculation) run in the background, as a separate process
with low priority: the command answers at once, the progress shows in intake_status. Heavy steps take the machine lock
themselves (core/lock.py, journal heavy.log): busy — code 3 and who holds it. Without a video card the
embeddings are not computed on the processor silently: embed.py (gpu_guard) answers with a time estimate, and the
command returns a question for the user to Claude; "yes" — intake_reindex(cpu=True)."""

import collections, datetime, json, os, re, secrets, subprocess, sys, time

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
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
BELOW_NORMAL = 0x00004000 if os.name == "nt" else 0
# a background job outlives the server: no console of the server, a process group of its own, and out of the job
# object of the client (Claude closes the server with its whole job) where the job object allows it
DETACHED = 0x00000008 | 0x00000200 if os.name == "nt" else 0  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
BREAKAWAY = 0x01000000 if os.name == "nt" else 0  # CREATE_BREAKAWAY_FROM_JOB
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
        p = subprocess.run(
            [*INTAKE, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_env(),
            cwd=_cwd(),
            creationflags=NO_WINDOW,
        )
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
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
    """The wrapper started detached from the server; (process, out of the client's job object)."""
    opts = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=_cwd(), env=env)
    if os.name != "nt":
        return subprocess.Popen(cmd, start_new_session=True, **opts), True
    try:
        p = subprocess.Popen(cmd, creationflags=DETACHED | BREAKAWAY | BELOW_NORMAL, **opts)
    except PermissionError:  # the job object of the client forbids a breakaway: the job ends if the client ends it
        return subprocess.Popen(cmd, creationflags=DETACHED | BELOW_NORMAL, **opts), False
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
    p, apart = _popen(
        [sys.executable, "-m", "assistant_x.server.jobrun", log, done, "--", *cmd], _env(**env, **{jobrun.JOB_ID: ident})
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
    except subprocess.TimeoutExpired:
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
    for kind in ("run", "reindex", "base_export", "base_inspect", "base_install", "base_update", "base_remove"):
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
    files, size, exts, tops = 0, 0, {}, []
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
    for kind, what in (("run", "an intake"), ("reindex", "a base recalculation")):
        job = _job(kind)
        if _alive(job):
            out.append(f"Running now: {what} ({_ago(job)}): see intake_status.")
    return "\n".join(out)


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


def status():
    out = []
    for kind, what in (("run", "Intake"), ("reindex", "Base recalculation")):
        job = _job(kind)
        if not job:
            continue
        alive = _alive(job)
        tail = _tail(kind, 15 if alive else 25)
        out.append(f"## {what}: {state_text(kind, job)} (started {_ago(job)} ago)\n{tail}")
        if kind == "reindex" and not alive and "--cpu" in tail:
            out.append(CPU_QUESTION)
    from assistant_x.server import base_tools

    journals = base_tools.open_journals()
    if journals:
        out.append("## Interrupted base change\n" + "\n".join(journals))
    gap = vector_note()
    if gap and not _alive(_job("reindex")):
        out.append("## Search base\n" + gap)
    rc, text = _intake("status")
    out.append("## Batch\n" + (text if rc == 0 else "no batches yet"))
    work = _last_work()
    if work and not _alive(_job("run")):
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


def save_meta(lines):
    """Append the lines to meta.jsonl of the last batch and check the whole file (assistant-x intake check-meta)."""
    work = _last_work()
    if not work:
        return "No batches: run intake_run first."
    rows = []
    for x in lines:
        try:
            rows.append(x if isinstance(x, dict) else json.loads(x))
        except ValueError as e:
            return f"A line is not JSON ({e}): {str(x)[:200]}"
    bad = [r for r in rows if not isinstance(r, dict) or not r.get("tid")]
    if bad:
        return f"A line has no tid: {json.dumps(bad[0], ensure_ascii=False)[:200]}"
    with open(os.path.join(work, "meta.jsonl"), "a", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    rc, text = _intake("check-meta")
    rc2, todo = _intake("todo")
    return f"Lines written: {len(rows)}.\n{text}\n\nStill without a line:\n{_cut(todo, 3000)}"


def apply(confirm=False, personal=False, token=None, ask=None):
    """build, then apply --dry-run (confirm=False: the plan to show the user, with a confirmation token) or apply
    (confirm=True with that token, server/confirm.py) and the reindex. personal: mark the documents of the batch
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
    debuglog.log_change("intake_apply", args, "started" if confirm else "plan")
    if _alive(_job("run")):
        return "The intake is still running: wait until it ends (intake_status)."
    rc, built = _intake("build", *(["--personal"] if personal else []), timeout=3600)
    if rc:
        return "The build failed" + (" (the machine lock is busy)" if rc == BUSY else "") + f":\n{_cut(built, 8000)}"
    rc, plan = _intake("apply", *([] if confirm else ["--dry-run"]), timeout=3600)
    if rc or not confirm:
        return (
            _cut(built, 4000)
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
    return _cut(plan, 6000) + "\n\n" + reindex(cpu=False)


def reindex(cpu=False):
    """build_index.py, then embed.py for the new fragments, in the background. Without a video card embed.py does not
    start on the processor by itself: the answer carries its estimate and the question for the user."""
    if _alive(_job("reindex")):
        return f"A base recalculation is already running ({_ago(_job('reindex'))}): intake_status."
    script = (
        "import subprocess, sys\n"
        "py = sys.executable\n"
        "rc = subprocess.call([py, '-m', 'assistant_x.search.build_index'])\n"
        "if rc: sys.exit(rc)\n"
        "sys.exit(subprocess.call([py, '-m', 'assistant_x.search.embed'] + sys.argv[1:]))\n"
    )
    started, text = _start("reindex", [sys.executable, "-c", script] + (["--cpu"] if cpu else []))
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
