# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Gemini CLI: mcpServers of ~/.gemini/settings.json (the user settings of every project), with a timeout for the long
first answer; the rules of the library go into ~/.gemini/GEMINI.md, the context file Gemini CLI reads in every
session, as a block between two marker comments, so the user's own lines stay and disconnect takes out exactly what
connect put in. All the tools: the Gemini models carry the intake too."""

import re

from assistant_x import clients as K

NAME, TITLE = "gemini", "Gemini CLI"
TOOLSET, COMPACT = "all", False
SETTINGS = "`~/.gemini/settings.json`, `mcpServers` (`timeout`); the rules in `~/.gemini/GEMINI.md`"
SKILL = "a block of the short rules in `~/.gemini/GEMINI.md`"
BEGIN = "<!-- >>> assistant-x (assistant-x connect gemini; assistant-x disconnect gemini removes it) -->\n"
END = "<!-- <<< assistant-x -->\n"


def folder():
    return K.home() / ".gemini"


def found():
    return folder().is_dir()


def configs():
    return [str(folder() / "settings.json")]


def rules_path():
    return folder() / "GEMINI.md"


def read():
    return K.json_entry(configs()[0])


def rules(text, block):
    """The text of GEMINI.md with our block in place of the old one (or at the end), or without it (block None)."""
    rx = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    text = rx.sub("", text)
    if block is None:
        return text.rstrip("\n") + "\n" if text.strip() else ""
    return (text.rstrip("\n") + "\n\n" if text.strip() else "") + BEGIN + block.rstrip("\n") + "\n" + END


def guide():
    from assistant_x.setup import skill

    head = (
        f"# The document library of the user (the MCP server {K.SERVER})\n\n"
        'Use it when a message starts with "AX:" or asks for the library, the documents or the standards; call its '
        "tool library_guide once when the work with the library starts.\n\n"
    )
    return head + skill.guide()


def connect(e, dry):
    path, out = configs()[0], []
    try:
        out.append((path, K.json_connect(path, e, dry, extra={"timeout": K.TOOL_TIMEOUT * 1000, "trust": False})))
    except K.Refused as why:
        return [(path, f"left alone: {why}; add by hand:\n{K.by_hand(e)}")]
    p = rules_path()
    old = p.read_text(encoding="utf-8-sig") if p.exists() else ""
    out.append((str(p), K.put(p, rules(old, guide()), dry)))
    return out


def disconnect(dry):
    path, out = configs()[0], []
    try:
        out.append((path, K.json_disconnect(path, dry)))
    except K.Refused as why:
        out.append((path, f"left alone: {why}"))
    p = rules_path()
    if p.exists() and BEGIN in p.read_text(encoding="utf-8-sig"):
        out.append((str(p), K.put(p, rules(p.read_text(encoding="utf-8-sig"), None), dry)))
    return out


def skill_dir():
    return None
