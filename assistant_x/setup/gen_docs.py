# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The documents for people and agents that follow the code: made from the registry of the apps (assistant_x/clients),
the tools of the server, the commands of the command line and the version only, so they change with it.

    assistant-x gen-docs [--check]     write them (--check: exit 1 when a committed one differs, change nothing)

    INSTALL_FOR_AI.md      what an agent (Codex, Claude Code, DeepSeek Harness) does when told "connect this tool"
    AGENTS.md              the section between the assistant-x markers (the rest of the file is the people's)
    docs/CLIENTS.md        the apps, their settings files, tool sets and skills
    INSTALL_FOR_AI.ru.md, docs/CLIENTS.ru.md    their Russian twins: the templates *.ru.md, the strings of the tables
                           in templates/docs/ru.json (one per app, tool, command and known failure: a missing one fails)

tests/test_gen_docs.py fails when a committed file differs from what this makes; hooks/pre-commit runs it."""

import argparse, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # the folder of the code (pyproject.toml)
TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "docs"
REPO = "https://github.com/AlexandrYalovoy/Assistant_X"
BEGIN, END = "<!-- assistant-x:begin (made by assistant-x gen-docs) -->", "<!-- assistant-x:end -->"


def tools():
    """[(name, title, first sentence, read only, destructive)] of the server."""
    import anyio

    from assistant_x.server import mcp_server, toolsets

    listed = anyio.run(mcp_server.mcp.list_tools)
    return [
        (
            t.name,
            t.title,
            toolsets.first_sentence(t.description),
            bool(t.annotations.read_only_hint),
            bool(t.annotations.destructive_hint),
        )
        for t in listed
    ]


def ru():
    """The Russian strings of the tables (templates/docs/ru.json)."""
    import json

    return json.loads((TEMPLATES / "ru.json").read_text(encoding="utf-8"))


def _rule(header):
    return "| " + " | ".join("---" for _ in header.strip("|").split("|")) + " |"


def apps_table(lang="en"):
    from assistant_x import clients

    r = ru() if lang == "ru" else None
    head = r["headers"]["apps"] if r else "| App | `connect` name | Settings written | Tool set | Skill |"
    rows = [head, _rule(head)]
    for name in clients.APPS:
        a = clients.app(name)
        s = r["apps"][name] if r else {"TITLE": a.TITLE, "SETTINGS": a.SETTINGS, "SKILL": a.SKILL}
        ts = a.TOOLSET + ((", " + r["toolsets"]["compact"] if r else ", compact") if a.COMPACT else "")
        rows.append(f"| {s['TITLE']} | `{a.NAME}` | {s['SETTINGS']} | {ts} | {s['SKILL']} |")
    return "\n".join(rows)


def tools_table(lang="en"):
    from assistant_x.server import toolsets

    r = ru() if lang == "ru" else None
    head = r["headers"]["tools"] if r else "| Tool | What it does | Set | Changes the library |"
    rows = [head, _rule(head)]
    words = (
        r["change"]
        if r
        else {"no": "no", "destructive": "yes, after the user's yes to a plan", "work": "writes its own work files"}
    )
    for name, _title, about, read, destructive in tools():
        change = words["no"] if read else words["destructive"] if destructive else words["work"]
        about = r["tools"][name] if r else about
        rows.append(f"| `{name}` | {about} | {'reader' if name in toolsets.READER else 'all'} | {change} |")
    return "\n".join(rows)


def commands_table(lang="en"):
    from assistant_x.cli import main as cli

    r = ru() if lang == "ru" else None
    head = r["headers"]["commands"] if r else "| Command | What it does |"
    say = (lambda k, en: r["commands"][k]) if r else (lambda k, en: en)
    rows = [head, _rule(head), f"| `init [FOLDER]` | {say('init', 'make a workspace')} |"]
    rows.append(
        f"| `doctor [--json]` | {say('doctor', 'where everything is and what is missing (`--json`: codes and fixes)')} |"
    )
    rows += [f"| `{k}` | {say(k, v[1])} |" for k, v in cli.COMMANDS.items()]
    return "\n".join(rows)


def problems_table(lang="en"):
    from assistant_x.core import problems

    if lang != "ru":
        return problems.markdown()
    r = ru()
    rows = [r["headers"]["problems"], _rule(r["headers"]["problems"])]
    for code in problems.PROBLEMS:
        message, fix = r["problems"][code]
        rows.append(f"| `{code}` | {message} | {fix.replace('|', '/')} |")
    return "\n".join(rows)


def values(lang="en"):
    from assistant_x import __version__
    from assistant_x.server import toolsets

    return {
        "version": __version__,
        "repo": REPO,
        "latest": f"{REPO}/releases/latest",
        "apps_table": apps_table(lang),
        "tools_table": tools_table(lang),
        "commands_table": commands_table(lang),
        "troubleshooting": problems_table(lang),
        "reader_tools": ", ".join(f"`{t}`" for t in toolsets.READER),
        "apps": ", ".join(f"`{n}`" for n in __import__("assistant_x.clients", fromlist=["APPS"]).APPS),
    }


def render(name, v=None):
    v = v or values()
    text = (TEMPLATES / name).read_text(encoding="utf-8")
    text = re.sub(r"\{\{(\w+)\}\}", lambda m: v[m.group(1)], text)
    return text


def agents_md(old, v):
    """AGENTS.md with its section made again (added at the end when the markers are missing)."""
    section = f"{BEGIN}\n{render('AGENTS-section.md', v).strip()}\n{END}"
    if BEGIN in old and END in old:
        return old[: old.index(BEGIN)] + section + old[old.index(END) + len(END) :]
    return (old.rstrip() + "\n\n" if old.strip() else "# Agents\n\n") + section + "\n"


DESCRIPTION = (
    "Your own library of documents (PDF, scans, standards, books) on your PC: search by words and meaning, answers "
    "citing the code and the page. The plugin installs and connects Assistant X."
)


def as_json(obj):
    import json

    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def plugin_files(v):
    """The plugin of Codex (and the ChatGPT desktop app) and of Claude Code, with the marketplaces of this repository:
    `codex plugin marketplace add AlexandrYalovoy/Assistant_X`, `/plugin marketplace add AlexandrYalovoy/Assistant_X`."""
    meta = {
        "name": "assistant-x",
        "version": v["version"],
        "description": DESCRIPTION,
        "author": {"name": "Alexandr Yalovoy"},
        "homepage": REPO,
        "repository": REPO,
        "license": "AGPL-3.0-or-later",
        "keywords": ["documents", "library", "rag", "mcp", "search", "citations"],
    }
    portable = {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        **meta,
        "extensions": {
            "com.openai": {
                "onboardingSkill": "./skills/assistant-x-setup/SKILL.md",
                "interface": {"displayName": "Assistant X"},
            }
        },
    }
    plugin = ROOT / "plugins" / "assistant-x"
    return {
        plugin / "plugin.json": as_json(portable),
        plugin / ".claude-plugin" / "plugin.json": as_json(meta),
        plugin / "skills" / "assistant-x-setup" / "SKILL.md": render("setup-SKILL.md", v),
        ROOT / ".claude-plugin" / "marketplace.json": as_json(
            {
                "name": "assistant-x",
                "owner": {"name": "Alexandr Yalovoy"},
                "description": "Assistant X: your own library of documents for your AI apps.",
                "plugins": [{"name": "assistant-x", "source": "./plugins/assistant-x", "description": DESCRIPTION}],
            }
        ),
        ROOT / ".agents" / "plugins" / "marketplace.json": as_json(
            {
                "name": "assistant-x",
                "plugins": [
                    {
                        "name": "assistant-x",
                        "source": {"source": "local", "path": "./plugins/assistant-x"},
                        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                        "category": "Productivity",
                    }
                ],
            }
        ),
    }


def targets():
    """{path: text} of every file this makes."""
    v, v_ru = values(), values("ru")
    agents = ROOT / "AGENTS.md"
    old = agents.read_text(encoding="utf-8") if agents.exists() else ""
    return {
        ROOT / "INSTALL_FOR_AI.md": render("INSTALL_FOR_AI.md", v),
        ROOT / "INSTALL_FOR_AI.ru.md": render("INSTALL_FOR_AI.ru.md", v_ru),
        agents: agents_md(old, v),
        ROOT / "docs" / "CLIENTS.md": render("CLIENTS.md", v),
        ROOT / "docs" / "CLIENTS.ru.md": render("CLIENTS.ru.md", v_ru),
        **plugin_files(v),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="assistant-x gen-docs", description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when a file differs; change nothing")
    a = ap.parse_args(argv)
    stale = []
    for path, text in targets().items():
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if old == text:
            continue
        stale.append(path)
        if not a.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"written {path.relative_to(ROOT)}")
    if a.check and stale:
        print("out of date (assistant-x gen-docs): " + ", ".join(str(p.relative_to(ROOT)) for p in stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
