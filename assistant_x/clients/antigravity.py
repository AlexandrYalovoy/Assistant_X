# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Antigravity (the agent IDE of Google): mcpServers of ~/.gemini/antigravity/mcp_config.json, the file its MCP store
opens with "Manage MCP Servers → View raw config"; refreshed there after the file is saved. No skills: the model
learns the rules from the tool library_guide. All the tools."""

from assistant_x import clients as K

NAME, TITLE = "antigravity", "Antigravity"
TOOLSET, COMPACT = "one", False
SETTINGS = "`~/.gemini/antigravity/mcp_config.json`, `mcpServers`"
SKILL = "none: `library_guide`"


def folder():
    return K.home() / ".gemini" / "antigravity"


def found():
    return folder().is_dir()


def configs():
    return [str(folder() / "mcp_config.json")]


def read():
    return K.json_entry(configs()[0])


def connect(e, dry):
    return K.json_app_connect(configs()[0], e, dry)


def disconnect(dry):
    return K.json_app_disconnect(configs()[0], dry)


def skill_dir():
    return None
