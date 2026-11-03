# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Kimi (Moonshot AI): the Kimi CLI (`kimi`, ~/.kimi/mcp.json) and Kimi Code (~/.kimi-code/mcp.json, or the folder of
KIMI_CODE_HOME), each the mcpServers of the MCP clients (command, args, env); Kimi Code also takes startupTimeoutMs and
toolTimeoutMs for the long first answer. The rules of the library go into the AGENTS.md of the folder, the instructions
Kimi reads in every session, as a block between two marker comments (as for Gemini CLI). Both apps when both are
there. All the tools: the Kimi models carry the intake too.

The formats were checked against the documentation of Moonshot AI (2026-11-03):
https://moonshotai.github.io/kimi-cli/en/customization/mcp.html and
https://moonshotai.github.io/kimi-code/en/customization/mcp; not checked against a running Kimi on this PC."""

import os
import re
from pathlib import Path

from assistant_x import clients as K
from assistant_x.clients import gemini

NAME, TITLE = "kimi", "Kimi CLI / Kimi Code"
TOOLSET, COMPACT = "all", False
SETTINGS = "`~/.kimi/mcp.json` and `~/.kimi-code/mcp.json` (`KIMI_CODE_HOME`), `mcpServers`; the rules in `AGENTS.md`"
SKILL = "a block of the short rules in `AGENTS.md` of the folder"
BEGIN = "<!-- >>> assistant-x (assistant-x connect kimi; assistant-x disconnect kimi removes it) -->\n"
END = gemini.END


def cli_folder():
    return K.home() / ".kimi"


def code_folder():
    given = os.environ.get("KIMI_CODE_HOME")
    return Path(given) if given else K.home() / ".kimi-code"


def folders():
    """The folders of the Kimi apps of this PC (the Kimi CLI, Kimi Code), the ones that exist."""
    return [d for d in (cli_folder(), code_folder()) if d.is_dir()]


def found():
    return bool(folders())


def configs():
    return [str(d / "mcp.json") for d in (folders() or [code_folder()])]


def read():
    for path in configs():
        got = K.json_entry(path)
        if got:
            return got
    return None


def extra(folder):
    """The keys of the entry an app takes besides command, args and env: the timeouts of Kimi Code, in milliseconds."""
    if folder == code_folder():
        return {"startupTimeoutMs": K.STARTUP_TIMEOUT * 1000, "toolTimeoutMs": K.TOOL_TIMEOUT * 1000}
    return None


def rules(text, block):
    """The text of AGENTS.md with our block in place of the old one (or at the end), or without it (block None)."""
    rx = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    text = rx.sub("", text)
    if block is None:
        return text.rstrip("\n") + "\n" if text.strip() else ""
    return (text.rstrip("\n") + "\n\n" if text.strip() else "") + BEGIN + block.rstrip("\n") + "\n" + END


def connect(e, dry):
    out = []
    for d in folders() or [code_folder()]:
        path = str(d / "mcp.json")
        try:
            out.append((path, K.json_connect(path, e, dry, extra=extra(d))))
        except K.Refused as why:
            out.append((path, f"left alone: {why}; add by hand:\n{K.by_hand(e)}"))
            continue
        p = d / "AGENTS.md"
        old = p.read_text(encoding="utf-8-sig") if p.exists() else ""
        out.append((str(p), K.put(p, rules(old, gemini.guide()), dry)))
    return out


def disconnect(dry):
    out = []
    for d in folders():
        path = str(d / "mcp.json")
        try:
            out.append((path, K.json_disconnect(path, dry)))
        except K.Refused as why:
            out.append((path, f"left alone: {why}"))
        p = d / "AGENTS.md"
        if p.exists() and BEGIN in p.read_text(encoding="utf-8-sig"):
            out.append((str(p), K.put(p, rules(p.read_text(encoding="utf-8-sig"), None), dry)))
    return out


def skill_dir():
    return None
