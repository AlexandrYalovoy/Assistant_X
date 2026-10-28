# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The documents for people and agents that follow the code: made from the registry of the apps (assistant_x/clients),
the tools of the server, the commands of the command line and the version only, so they change with it.

    assistant-x gen-docs [--check]     write them (--check: exit 1 when a committed one differs, change nothing)

    INSTALL_FOR_AI.md      what an agent (Codex, Claude Code, DeepSeek Harness) does when told "connect this tool"
    AGENTS.md              the section between the assistant-x markers (the rest of the file is the people's)
    docs/CLIENTS.md        the apps, their settings files, tool sets and skills

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


def apps_table():
    from assistant_x import clients

    rows = ["| App | `connect` name | Settings written | Tool set | Skill |", "| --- | --- | --- | --- | --- |"]
    for name in clients.APPS:
        a = clients.app(name)
        ts = a.TOOLSET + (", compact" if a.COMPACT else "")
        rows.append(f"| {a.TITLE} | `{a.NAME}` | {a.SETTINGS} | {ts} | {a.SKILL} |")
    return "\n".join(rows)


def tools_table():
    from assistant_x.server import toolsets

    rows = ["| Tool | What it does | Set | Changes the library |", "| --- | --- | --- | --- |"]
    for name, _title, about, read, destructive in tools():
        change = "no" if read else "yes, after the user's yes to a plan" if destructive else "writes its own work files"
        rows.append(f"| `{name}` | {about} | {'reader' if name in toolsets.READER else 'all'} | {change} |")
    return "\n".join(rows)


def commands_table():
    from assistant_x.cli import main as cli

    rows = ["| Command | What it does |", "| --- | --- |", "| `init [FOLDER]` | make a workspace |"]
    rows.append("| `doctor [--json]` | where everything is and what is missing (`--json`: codes and fixes) |")
    rows += [f"| `{k}` | {v[1]} |" for k, v in cli.COMMANDS.items()]
    return "\n".join(rows)


def values():
    from assistant_x import __version__
    from assistant_x.server import toolsets

    return {
        "version": __version__,
        "repo": REPO,
        "latest": f"{REPO}/releases/latest",
        "apps_table": apps_table(),
        "tools_table": tools_table(),
        "commands_table": commands_table(),
        "troubleshooting": __import__("assistant_x.core.problems", fromlist=["markdown"]).markdown(),
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
    v = values()
    agents = ROOT / "AGENTS.md"
    old = agents.read_text(encoding="utf-8") if agents.exists() else ""
    return {
        ROOT / "INSTALL_FOR_AI.md": render("INSTALL_FOR_AI.md", v),
        agents: agents_md(old, v),
        ROOT / "docs" / "CLIENTS.md": render("CLIENTS.md", v),
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
