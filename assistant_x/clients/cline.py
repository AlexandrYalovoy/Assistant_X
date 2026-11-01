# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cline, the agent extension of VS Code: mcpServers of cline_mcp_settings.json in the global storage of the extension
(saoudrizwan.claude-dev) of every VS Code found (Code, Code - Insiders, VSCodium), with the timeout of a long first
answer and the tools not approved in advance; Cline reloads the file when it is saved. No skills: the model learns
the rules from the tool library_guide. All the tools (any model of Cline, Grok too)."""

import os
from pathlib import Path

from assistant_x import clients as K

NAME, TITLE = "cline", "Cline (VS Code)"
TOOLSET, COMPACT = "all", False
SETTINGS = (
    r"`%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json`, `mcpServers` "
    "(`timeout`, `disabled`, `autoApprove`)"
)
SKILL = "none: `library_guide`"
EXTENSION = Path("User") / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"
EDITORS = ("Code", "Code - Insiders", "VSCodium")


def bases():
    """The settings folders of the VS Code builds of this system (whether they exist or not)."""
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA") or K.home() / "AppData" / "Roaming")
    elif os.uname().sysname == "Darwin":
        root = K.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or K.home() / ".config")
    return [root / e for e in EDITORS]


def configs():
    """The settings file of Cline in every VS Code that has the extension, else in the usual one (written in advance)."""
    have = [str(b / EXTENSION) for b in bases() if (b / EXTENSION).parent.parent.is_dir()]
    return have or [str(bases()[0] / EXTENSION)]


def found():
    return any((b / EXTENSION).parent.parent.is_dir() for b in bases())


def read():
    return next((x for x in (K.json_entry(p) for p in configs()) if x), None)


def connect(e, dry):
    out = []
    for p in configs():
        out += K.json_app_connect(p, e, dry, extra={"timeout": K.TOOL_TIMEOUT, "disabled": False, "autoApprove": []})
    return out


def disconnect(dry):
    out = []
    for p in configs():
        out += K.json_app_disconnect(p, dry)
    return out


def skill_dir():
    return None
