# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cursor: mcpServers of ~/.cursor/mcp.json, the servers of every project (any model of Cursor uses them, Grok too).
No skills: the model learns the rules from the tool library_guide. All the tools."""

from assistant_x import clients as K

NAME, TITLE = "cursor", "Cursor"
TOOLSET, COMPACT = "all", False
SETTINGS = "`~/.cursor/mcp.json`, `mcpServers`"
SKILL = "none: `library_guide`"


def folder():
    return K.home() / ".cursor"


def found():
    return folder().is_dir()


def configs():
    return [str(folder() / "mcp.json")]


def read():
    return K.json_entry(configs()[0])


def connect(e, dry):
    return K.json_app_connect(configs()[0], e, dry)


def disconnect(dry):
    return K.json_app_disconnect(configs()[0], dry)


def skill_dir():
    return None
