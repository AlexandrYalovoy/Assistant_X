# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""LM Studio: mcpServers of ~/.lmstudio/mcp.json (the notation of Cursor); LM Studio reloads its servers when the file
is saved. No skills: the model learns the rules from the tool library_guide (and an optional preset). The reading tools
and the compact answers by default: the models of LM Studio are small and local."""

from assistant_x import clients as K

NAME, TITLE = "lmstudio", "LM Studio"
TOOLSET, COMPACT = "reader", True


def folder():
    return K.home() / ".lmstudio"


def found():
    return folder().is_dir()


def configs():
    return [str(folder() / "mcp.json")]


def read():
    return K.json_entry(configs()[0])


def connect(e, dry):
    path = configs()[0]
    try:
        return [(path, K.json_connect(path, e, dry))]
    except K.Refused as why:
        return [(path, f"left alone: {why}; add by hand:\n{K.by_hand(e)}")]


def disconnect(dry):
    path = configs()[0]
    try:
        return [(path, K.json_disconnect(path, dry))]
    except K.Refused as why:
        return [(path, f"left alone: {why}")]


def skill_dir():
    return None
