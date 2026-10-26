# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Base packages from the Claude chat: commands of the assistant-x server (mcp_server.py) on top of assistant-x base
(assistant_x.base). Inspect and install run in the background like the intake (intake_tools.py: a separate process
with low priority, its output in work/_claude/<kind>.log); base_status shows how far they are.

    export(out, ...)       the library as a package (the user chose "reference" or "default" codes first)
    inspect(path, keep)    the report and the questions for the user (a big package: checked in the background)
    install(path, ...)     confirm=False: the same as inspect, and a confirmation token; confirm=True with that token:
                           the install with the user's answers (server/confirm.py: two steps for every change)
    status()               the inspect and the install of the chat: running or done, the report, the questions
    listing()              the packages installed and the documents of each, and the user's own"""

import json, os, sys

from assistant_x.core import debuglog
from assistant_x.server import confirm as K, intake_tools as T

BASE = [sys.executable, "-m", "assistant_x.base.cli"]
# the values Claude passes go after "--" (a path or an id) or glued to their option ("--id=…"): a value that starts
# with "-" ("--rollback", "--help") is never taken for an option of the command
REPORT = "base_inspect.report.json"  # beside base_inspect.json, the job itself


def _report_path():
    return os.path.join(T.jobs_dir(), REPORT)


def _report():
    try:
        with open(_report_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def questions_text(report):
    """The questions of an inspect report as data for Claude (it puts them to the user in the user's language, with
    the consequences of every option): one JSON object per line, the ids for base_install(answers=...)."""
    qs = report.get("questions") or []
    if not qs:
        return "QUESTIONS: none (every document of the package is new here; no codes collide)."
    lines = [
        "QUESTIONS (data; ask the user in their language, then base_install(path, confirm=True, answers={id: option})):"
    ]
    for q in qs:
        lines.append(json.dumps(q, ensure_ascii=False, sort_keys=True))
    return "\n".join(lines)


def busy():
    for kind in ("base_export", "base_inspect", "base_install", "base_update", "base_remove"):
        job = T._job(kind)
        if T._alive(job):
            return f"A base package {kind.split('_')[1]} is running already ({T._ago(job)}): see base_status."
    return ""


def inspect(path, keep=None):
    b = busy()
    if b:
        return b
    if not os.path.exists(path):
        return f"No package {path}: ask the user for the path of the .axbase file (or of the unpacked folder)."
    if os.path.exists(_report_path()):
        os.remove(_report_path())
    cmd = [*BASE, "inspect", f"--json={_report_path()}"] + ([f"--keep={keep}"] if keep else []) + ["--", path]
    started, text = T._start("base_inspect", cmd)
    if started:
        return "The package is being checked in the background (its checksums are read): base_status in a minute."
    report = _report()
    if not report:
        return text
    return T._cut(f"{text}\n\n{questions_text(report)}", 12000)


def export(out, ident, version, codes="default", name_en=None, name_ru=None, include_personal=False):
    """The library as a base package, in the background (base_status shows the end)."""
    b = busy()
    if b:
        return b
    if codes not in ("default", "reference"):
        return 'codes: "reference" or "default" (ask the user which one first)'
    cmd = [*BASE, "export", f"--id={ident}", f"--version={version}", f"--codes={codes}"]
    cmd += ([f"--name-en={name_en}"] if name_en else []) + ([f"--name-ru={name_ru}"] if name_ru else [])
    cmd += (["--include-personal"] if include_personal else []) + ["--", out]
    started, text = T._start("base_export", cmd)
    if not started:
        return text
    return "The export started in the background: base_status in a few minutes."


def install(
    path, confirm=False, answers=None, keep=None, own_apart=False, resume=False, rollback=False, token=None, ask=None
):
    args = {
        "path": path,
        "confirm": confirm,
        "answers": answers,
        "keep": keep,
        "own_apart": own_apart,
        "resume": resume,
        "rollback": rollback,
    }
    if not confirm and not resume and not rollback:
        debuglog.log_change("base_install", args, "plan")
        out = inspect(path, keep)
        return (
            out + K.instruction("base_install", path, f'base_install("{path}", confirm=True, answers={{…}}, token="TOKEN")')
            if os.path.exists(path)
            else out
        )
    if confirm and not resume and not rollback:
        why = K.check("base_install", path, token)
        if why:
            debuglog.log_change("base_install", args, "refused: no valid token")
            return why
        if ask and ask(f"Assistant X: install the base package {path} into the library, as in the plan shown?") is False:
            debuglog.log_change("base_install", args, "declined by the user")
            return K.DECLINED
    b = busy()
    if b:
        return b
    cmd = [*BASE, "install"]
    if resume:
        cmd.append("--resume")
    elif rollback:
        cmd.append("--rollback")
    else:
        cmd.append("--confirm")
        if keep:
            cmd.append(f"--keep={keep}")
        if own_apart:
            cmd.append("--own-apart")
        if answers:
            os.makedirs(T.jobs_dir(), exist_ok=True)
            p = os.path.join(T.jobs_dir(), "base_answers.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(answers, f, ensure_ascii=False)
            cmd.append(f"--answers={p}")
    cmd += ["--", path]
    started, text = T._start("base_install", cmd)
    debuglog.log_change("base_install", args, "started" if started else f"ended at once (code {T.state('base_install')[1]})")
    if not started:
        return text
    return (
        "The install started in the background: the originals move, then the search base is updated and the "
        "embeddings computed. Progress — base_status (every few minutes). The search answers meanwhile; page images "
        "come back when it ends."
    )


def update(path, confirm=False, resume=False, rollback=False, token=None, ask=None):
    """A new version of an installed package: the plan (confirm=False, with a confirmation token), or the update in
    the background (confirm=True with that token)."""
    return _run_change("base_update", "update", path, confirm, resume, rollback, token, ask)


def remove(ident, confirm=False, resume=False, rollback=False, token=None, ask=None):
    """An installed package out of the library: the plan (confirm=False, with a confirmation token), or the removal in
    the background (confirm=True with that token)."""
    return _run_change("base_remove", "remove", ident, confirm, resume, rollback, token, ask)


def _run_change(kind, command, what, confirm, resume, rollback, token=None, ask=None):
    args = {"what": what, "confirm": confirm, "resume": resume, "rollback": rollback}
    if confirm and not resume and not rollback:
        why = K.check(kind, what, token)
        if why:
            debuglog.log_change(kind, args, "refused: no valid token")
            return why
        if ask and ask(f"Assistant X: {command} the base package {what}, as in the plan shown?") is False:
            debuglog.log_change(kind, args, "declined by the user")
            return K.DECLINED
    b = busy()
    if b:
        return b
    cmd = (
        [*BASE, command]
        + (["--resume"] if resume else ["--rollback"] if rollback else ["--confirm"] if confirm else [])
        + ["--", what]
    )
    plan = not (confirm or resume or rollback)
    started, text = T._start(kind, cmd)
    debuglog.log_change(kind, args, "plan" if plan else "started" if started else f"ended at once (code {T.state(kind)[1]})")
    if not started:  # ended at once: a plan that ended well (a small package: the usual case) gets its token
        return text + (K.instruction(kind, what, _confirm_call(command, what)) if plan and T.state(kind)[1] == 0 else "")
    if plan:
        return (
            f"The plan of the {command} is being made in the background: base_status in a minute shows it."
            + K.instruction(kind, what, _confirm_call(command, what))
        )
    return f"The {command} started in the background: base_status in a few minutes."


def _installed(package):
    """Is this version of the package (the "package" of an inspect report) installed here already?"""
    from assistant_x.base import registry
    from assistant_x.core import workspace

    entry = registry.get(workspace.current().index, package.get("id"))
    return bool(entry) and entry.get("version") == package.get("version")


def _confirm_call(command, what):
    return f'base_{command}("{what}", confirm=True, token="TOKEN")'


def _plan_of(job):
    """The path or the id of a plan job (update or remove without --confirm, --resume, --rollback), else None."""
    cmd = (job or {}).get("cmd") or []
    if "--" not in cmd:
        return None
    i = cmd.index("--")
    return None if {"--confirm", "--resume", "--rollback"} & set(cmd[:i]) else (cmd[i + 1 :] or [None])[0]


def status():
    out = []
    for kind, what in (
        ("base_export", "Export of the library"),
        ("base_inspect", "Check of a package"),
        ("base_install", "Install of a package"),
        ("base_update", "Update of a package"),
        ("base_remove", "Removal of a package"),
    ):
        job = T._job(kind)
        if not job:
            continue
        alive = T._alive(job)
        out.append(f"## {what}: {T.state_text(kind, job)} (started {T._ago(job)} ago)\n{T._tail(kind, 15 if alive else 30)}")
        what = _plan_of(job) if kind in ("base_update", "base_remove") else None
        if what and T.state(kind, job) == ("finished", 0):  # the plan is shown now: a fresh token for it
            out.append(K.instruction(kind, what, _confirm_call(kind.split("_")[1], what)).strip())
        if kind == "base_inspect" and not alive and _report():
            out.append(questions_text(_report()))
            path = _report().get("path")
            # the plan is shown now: a fresh token for the install of this package, unless it is installed already
            if path and _report().get("ok") and not _installed(_report().get("package") or {}):
                out.append(
                    K.instruction(
                        "base_install", path, f'base_install("{path}", confirm=True, answers={{…}}, token="TOKEN")'
                    ).strip()
                )
    journals = open_journals()
    if journals:
        out.append("## Interrupted\n" + "\n".join(journals))
    gap = T.vector_note()
    if out and gap and not any(T._alive(T._job(k)) for k in ("base_install", "base_update", "base_remove")):
        out.append("## Search base\n" + gap)
    if not out:
        return "No base package was exported, checked or installed from this chat."
    reports = os.path.join(T.P.ROOT, "reports")
    done = (
        sorted(
            (f for f in os.listdir(reports) if f.startswith(("base_install_", "base_update_", "base_remove_"))),
            key=lambda f: os.path.getmtime(os.path.join(reports, f)),
        )
        if os.path.isdir(reports)
        else []
    )
    if done and not any(T._alive(T._job(k)) for k in ("base_install", "base_update", "base_remove")):
        out.append("## " + done[-1] + "\n" + T._cut(open(os.path.join(reports, done[-1]), encoding="utf-8").read(), 5000))
    return T._cut("\n\n".join(out), 16000)


def open_journals():
    """Lines about the base transactions (install, update, remove) whose journal is open while no job of the server
    runs them: interrupted, to go on with (resume) or to undo (rollback)."""
    from assistant_x.base import install as B
    from assistant_x.core import workspace

    if any(T._alive(T._job(k)) for k in ("base_install", "base_update", "base_remove")):
        return []
    out = []
    for p in sorted((workspace.current().data / "w").glob(f"*/{B.JOURNAL}")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        kind = data.get("kind", "install")
        what = data.get("id") if kind == "remove" else data.get("package")
        out.append(
            f"A base {kind} of {data.get('id')} was interrupted (started {data.get('started')}, done: "
            f"{', '.join(data.get('steps') or []) or 'nothing'}): the library is half-changed. Tell the user; with "
            f'their yes base_{kind}("{what}", resume=True) goes on, rollback=True undoes it.'
        )
    return out


def listing():
    from assistant_x.base import registry
    from assistant_x.core import card as C, workspace

    w = workspace.current()
    counts, own, personal = {}, 0, 0
    for _, p in C.paths(w.cards).items():
        try:
            card = C.load(p)
        except C.CardError:
            continue
        pkg = ((card.get("intake") or {}).get("package") or {}).get("id")
        if pkg:
            counts[pkg] = counts.get(pkg, 0) + 1
        else:
            own += 1
            personal += bool((card.get("intake") or {}).get("personal"))
    lines = []
    for p in registry.load(w.index):
        name = (p.get("name") or {}).get("en") or ""
        lines.append(
            f"{p['id']} {p['version']}" + (f" ({name})" if name else "") + f": installed {p.get('installed')}, "
            f"{counts.get(p['id'], 0)} documents in the library"
        )
    lines.append(f"The user's own documents: {own}" + (f" ({personal} of them personal)" if personal else ""))
    if not registry.load(w.index):
        lines.insert(0, "No base package is installed.")
    return "\n".join(lines)
