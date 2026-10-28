# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""LM Studio: mcpServers of ~/.lmstudio/mcp.json (the notation of Cursor); LM Studio reloads its servers when the file
is saved. No skills: the model learns the rules from the tool library_guide (and an optional preset). The reading tools
and the compact answers by default: the models of LM Studio are small and local."""

from assistant_x import clients as K

NAME, TITLE = "lmstudio", "LM Studio"
TOOLSET, COMPACT = "reader", True
SETTINGS = "`~/.lmstudio/mcp.json`, `mcpServers`"
SKILL = "none: `library_guide`; `assistant-x skill --app guide` writes a system prompt for a preset"


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


def link(e):
    """The "Add to LM Studio" link of an entry: lmstudio://add_mcp with the name and the entry as base64 JSON; opened,
    it asks the user to add the server (for a PC where the entry was not written by connect)."""
    import base64, json, urllib.parse

    config = base64.b64encode(json.dumps(e, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return f"lmstudio://add_mcp?name={K.SERVER}&config={urllib.parse.quote(config, safe='')}"
