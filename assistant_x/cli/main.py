# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The command line: assistant-x <command> [arguments of the command].

    assistant-x init [FOLDER] [--profile oil-gas-ru] [--personal]   make a workspace (default: Documents\\Assistant X,
                                     profile general); a second run only adds what is missing
    assistant-x intake run|build|apply|status|...   the intake of inbox (assistant_x.intake.pipeline)
    assistant-x build [--full]       build the search base from index (assistant_x.search.build_index)
    assistant-x embed [--wait|--cpu] embeddings of the new fragments (assistant_x.search.embed)
    assistant-x mcp [--tools reader|all] [--compact]  the stdio bridge an app starts (assistant_x.server.bridge): it
                                     starts the library service of the workspace and talks to it
    assistant-x service              the library service: one MCP server on 127.0.0.1 for every app of the PC
    assistant-x serve [--http]       the MCP server in the process of the app (assistant_x.server.mcp_server); --http:
                                     local clients with the bearer token of mcp_http_token.txt in the PC folder
    assistant-x doctor               where everything is and what is missing
    assistant-x base export|inspect|install|update|remove  base packages (assistant_x.base)
    assistant-x remove CODE [CODE …] [--why TEXT] [--dry-run]  documents of the library aside (inbox\\_to_delete)
    assistant-x search, check, report, eval, query-log, debug-report, install, lock

Every command works on the workspace found by core/workspace.py: --workspace DIR anywhere on the line (or
AX_WORKSPACE) chooses another.
"""

import os, runpy, sys
from pathlib import Path

COMMANDS = {  # command -> (module run as __main__, one line of help)
    "intake": ("assistant_x.intake.pipeline", "the intake of inbox: run, build, apply, status, ..."),
    "build": ("assistant_x.search.build_index", "build the search base from index"),
    "embed": ("assistant_x.search.embed", "embeddings of the new fragments"),
    "mcp": ("assistant_x.server.bridge", "the stdio bridge an app starts: it talks to the library service"),
    "service": ("assistant_x.server.service", "the library service: one MCP server on 127.0.0.1 for every app"),
    "serve": ("assistant_x.server.mcp_server", "the MCP server in the process of the app (stdio; --http)"),
    "search": ("assistant_x.search.retrieval", "a query from the command line"),
    "check": ("assistant_x.search.check_index", "check the cards (the schema, the profile) and the texts"),
    "report": ("assistant_x.search.library_report", "the state of the library"),
    "eval": ("assistant_x.search.eval", "the control questions of the workspace"),
    "query-log": ("assistant_x.search.query_log", "what the apps asked and how long it took"),
    "debug-report": ("assistant_x.setup.debug_report", "a report to pass on when something fails"),
    "install": ("assistant_x.setup.install", "the Python environment and the connection to the apps"),
    "setup-intake": ("assistant_x.setup.setup_intake", "LibreOffice, Tesseract, 7-Zip and DjVuLibre for the intake"),
    "download-models": ("assistant_x.setup.download_models", "the embedding and reranking models from HuggingFace"),
    "prepare-media": ("assistant_x.setup.prepare_media", "the packages of an offline installation (build PC)"),
    "lock": ("assistant_x.core.lock", "who holds the machine lock; a command under it"),
    "skill": ("assistant_x.setup.skill", "write the Claude skill of the profile of the workspace (SKILL.md)"),
    "base": ("assistant_x.base.cli", "base packages: export, inspect, install, update, remove"),
    "remove": ("assistant_x.intake.remove", "take documents of the library aside (inbox\\_to_delete), codes reserved"),
}
MODEL_COMMANDS = ("search", "embed", "eval")  # they load the models: torch and transformers kept quiet


def usage():
    lines = [
        __doc__.split("\n\n", 1)[0],
        "",
        "Commands:",
        "  init [FOLDER] [--profile NAME]   make a workspace",
        "  doctor           where everything is and what is missing",
    ]
    lines += [f"  {k:<16} {v[1]}" for k, v in COMMANDS.items()]
    return "\n".join(lines)


HELP = {  # the commands whose module has no argparse of its own: their help, shown without running anything
    "init": (
        "usage: assistant-x init [FOLDER] [--profile NAME] [--personal]\n\n"
        "Make a workspace in FOLDER (default: Documents\\Assistant X, or AX_WORKSPACE / --workspace), or complete one:\n"
        "folders, settings, the files of an empty index. Nothing existing is changed.\n\n"
        "  --profile NAME   the domain profile of a new workspace (general, oil-gas-ru)\n"
        "  --personal       every batch of the intake is marked personal (personal = true in the settings)"
    ),
    "doctor": (
        "usage: assistant-x doctor\n\n"
        "Where everything of the workspace is and what is missing; exit code 1 when the workspace is broken or not made."
    ),
    "serve": (
        "usage: assistant-x serve [--tools reader|all] [--compact] [--http [--port N]]\n\n"
        "The MCP server of the library in the process of the app (the apps start assistant-x mcp, the bridge to the\n"
        "library service; serve is the fallback). Without options: stdio.\n"
        "  --tools      reader: only the 8 reading tools; all (default): every tool\n"
        "  --compact    short descriptions and answers for small local models\n"
        "  --http       streamable HTTP on 127.0.0.1 (http://127.0.0.1:N/mcp), every request with the bearer token\n"
        "               of mcp_http_token.txt in the PC folder\n"
        "  --port N     the port of --http (default 8765)"
    ),
    "lock": (
        "usage: assistant-x lock                                   who holds the machine lock\n"
        "       assistant-x lock [--wait] [TASK] -- COMMAND [ARGS]  run COMMAND under the machine lock\n\n"
        "One heavy task on the PC at a time (intake, build, embed, eval). Busy: exit code 3 (--wait: wait for it)."
    ),
}


def wants_help(argv):
    """-h or --help among the arguments of a command (before a "--": what follows belongs to another program)."""
    head = argv[: argv.index("--")] if "--" in argv else argv
    return any(a in ("-h", "--help") for a in head)


INBOX_README = (
    "Put new documents here (PDF, DOC/DOCX, PPTX, scans, archives), then run the intake: intake.bat, or\n"
    'assistant-x intake run, or ask Claude "AX: sort my documents". The folders _duplicates, _to_delete and\n'
    "_rejected are where the intake puts what does not go into the library.\n"
)


def _option(argv, name):
    """(value of --name VALUE or None, argv without it)."""
    if name not in argv:
        return None, argv
    i = argv.index(name)
    return (argv[i + 1] if i + 1 < len(argv) else ""), argv[:i] + argv[i + 2 :]


def init(argv):
    """Make a workspace, or complete one: folders, settings, the files of an empty index. Nothing existing is changed."""
    from assistant_x.core import config, index_files, workspace
    from assistant_x.intake import config as intake_cfg

    profile, argv = _option(argv, "--profile")
    personal = "--personal" in argv
    argv = [a for a in argv if a != "--personal"]
    unknown = [a for a in argv if a.startswith("-")]
    if unknown or len(argv) > 1:
        print(f"init: unexpected {' '.join(unknown or argv[1:])}\n\n{HELP['init']}", file=sys.stderr)
        return 2
    if profile is not None and profile not in config.profiles():
        print(f"No profile {profile!r}; the profiles: {', '.join(config.profiles())}", file=sys.stderr)
        return 2
    root = Path(argv[0]).expanduser() if argv else workspace.default_root()
    w = workspace.Workspace(root)
    had = w.exists()
    w.ensure()
    made = [w.inbox / d for d in intake_cfg.SERVICE if not (w.inbox / d).is_dir()]
    for d in made:
        d.mkdir(parents=True)
    if not (w.inbox / "_README.md").exists():
        (w.inbox / "_README.md").write_text(INBOX_README, encoding="utf-8", newline="\n")
        made.append(w.inbox / "_README.md")
    made += index_files.ensure(w.index)
    if not had:
        templates = Path(__file__).resolve().parent.parent / "templates"
        text = (templates / workspace.CONFIG).read_text(encoding="utf-8")
        text = text.replace('profile = "general"', f'profile = "{profile or config.PROFILE}"', 1)
        if personal:
            text = text.replace("# personal = false", "personal = true", 1)
        w.config.write_text(text, encoding="utf-8", newline="\n")
        made.append(w.config)
    elif profile or personal:
        print(f"{w.config} exists already: the profile and --personal are set there, not changed here", file=sys.stderr)
    print(f"Workspace: {w.root}" + (" (it was there; completed)" if had else ""))
    for p in made:
        print(f"  made {p.relative_to(w.root)}")
    if had and not made:
        print("  nothing was missing")
    print(f"Put your documents into {w.inbox}, then: assistant-x intake run")
    return 0


def state_of(w):
    """('none' | 'empty' | 'ready' | 'broken', [problems], [remarks]) of a workspace. A remark (no embedding model:
    the search by words still works) does not make it broken."""
    from assistant_x.core import card as C, common
    from assistant_x.core.common import load_config

    if not w.exists():
        return "none", [], []
    problems, remarks = [], []
    for name in ("inbox", "library", "index"):
        if not getattr(w, name).is_dir():
            problems.append(f"no folder {getattr(w, name)} (assistant-x init makes it)")
    docs = len(C.paths(w.cards))
    if not w.cards.is_dir():
        problems.append(f"no folder {w.cards} (assistant-x init makes it)")
    cfg = load_config()
    base = os.path.exists(cfg["db"])
    if docs and not base:
        problems.append(f"the library has {docs} cards but there is no search base: assistant-x build")
    gap = common.vector_gap_note(*common.base_vector_gap(cfg["db"])) if base else ""
    if gap:
        remarks.append(gap.replace("intake_reindex() (or assistant-x embed)", "assistant-x embed"))
    if not os.path.isdir(cfg.get("embed_model") or ""):
        remarks.append(
            f"no embedding model {cfg.get('embed_model')}: the search is by words only (assistant-x download-models)"
        )
    if problems:
        return "broken", problems, remarks
    return ("ready" if docs else "empty"), [], remarks


def doctor(argv):
    """Where everything is and what is missing: an empty workspace is fine, a broken one is listed (exit code 1)."""
    from assistant_x.core import config, lang, lock, workspace
    from assistant_x.core.common import load_config

    w = workspace.current()
    state, problems, remarks = state_of(w)
    if state == "none":
        print(f'Workspace: {w.root} — not made yet: assistant-x init "{w.root}"')
        return 1
    print(f"Workspace: {w.root} (settings {w.config})")
    for name in ("inbox", "library", "index", "db", "models", "work", "reports", "debug"):
        p = getattr(w, name)
        print(f"  {name:<8} {p}{'' if p.exists() else '  (missing)'}")
    cfg = load_config()
    for k, what in (("db", "search base"), ("embed_model", "embedding model"), ("synonyms", "synonyms")):
        ok = bool(cfg.get(k)) and os.path.exists(cfg[k])
        if k == "synonyms" and not cfg.get(k):  # the profile has none (general): nothing is missing
            print(f"  {what:<16} none in this profile")
            continue
        print(f"  {what:<16} {'present' if ok else 'MISSING'} ({cfg.get(k) or '-'})")
    raw = config.load()[1]
    print(f"  domain profile   {raw['profile']} ({config.profile_info(raw).get('name', '')})")
    print(f"  languages        {', '.join(lang.active())}")
    h = lock.holder()
    print(f"  machine lock     {lock.lock_path()} ({'held by ' + lock.who(h) if h else 'free'})")
    for r in remarks:
        print(f"Remark: {r}")
    if state == "empty":
        print(f"The workspace is empty and in order: put documents into {w.inbox}, then assistant-x intake run.")
        return 0
    if state == "ready":
        print("The workspace is in order.")
        return 0
    print("Problems:")
    for p in problems:
        print(f"  - {p}")
    return 1


def safe_output():
    """A console or a pipe in a legacy code page (cp1251, cp866) cannot show every character of the messages ("→",
    "—"): such a character is replaced instead of stopping the command."""
    for s in (sys.stdout, sys.stderr):
        if s and (getattr(s, "encoding", "") or "").lower().replace("-", "") != "utf8":
            try:
                s.reconfigure(errors="replace")
            except (AttributeError, ValueError):
                pass


def take_workspace(argv):
    """(argv without --workspace DIR / --workspace=DIR, DIR or None): the option is taken anywhere before a "--", so
    `assistant-x search … --workspace D:\\Lib` works like `assistant-x --workspace D:\\Lib search …`."""
    out, given, i = [], None, 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            out += argv[i:]
            break
        if a == "--workspace" and i + 1 < len(argv):
            given, i = argv[i + 1], i + 2
            continue
        if a.startswith("--workspace="):
            given, i = a.split("=", 1)[1], i + 1
            continue
        out.append(a)
        i += 1
    return out, given


def main(argv=None):
    safe_output()
    argv, given = take_workspace(list(sys.argv[1:] if argv is None else argv))
    if given:
        os.environ["AX_WORKSPACE"] = str(Path(given).resolve())
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage())
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd in HELP and wants_help(rest):  # help only: no workspace made, no server started, no lock taken
        print(HELP[cmd])
        return 0
    if cmd == "init":
        return init(rest)
    if cmd == "doctor":
        return doctor(rest)
    if cmd == "--version":
        from assistant_x import __version__

        print(__version__)
        return 0
    if cmd not in COMMANDS:
        print(f"Unknown command {cmd!r}.\n\n{usage()}", file=sys.stderr)
        return 2
    if cmd in MODEL_COMMANDS:  # before the libraries of the models are imported: no progress bars or warnings
        from assistant_x.core import env

        env.quiet_here()
    sys.argv = [f"assistant-x {cmd}", *rest]
    try:
        runpy.run_module(COMMANDS[cmd][0], run_name="__main__", alter_sys=True)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) or e.code is None else (print(e.code, file=sys.stderr) or 1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
