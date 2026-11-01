# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""LM Studio: mcpServers of ~/.lmstudio/mcp.json (the notation of Cursor); LM Studio reloads its servers when the file
is saved. No skills: the rules reach the model through the tool library_guide and the preset "Assistant X" written
beside the servers (config-presets: the guide as the system prompt, thinking off so that it cannot eat the answer; the
user picks it once in the chat). The reading tools and the compact answers by default: the models of LM Studio are
small and local."""

import json

from assistant_x import clients as K

NAME, TITLE = "lmstudio", "LM Studio"
TOOLSET, COMPACT = "reader", True
SETTINGS = "`~/.lmstudio/mcp.json`, `mcpServers`"
SKILL = "the preset `~/.lmstudio/config-presets/Assistant X.preset.json` (the guide as the system prompt)"
PRESET = "Assistant X.preset.json"


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
        out = [(path, K.json_connect(path, e, dry))]
    except K.Refused as why:
        out = [(path, f"left alone: {why}; add by hand:\n{K.by_hand(e)}")]
    return out + [write_preset(dry)]


def disconnect(dry):
    path = configs()[0]
    try:
        out = [(path, K.json_disconnect(path, dry))]
    except K.Refused as why:
        out = [(path, f"left alone: {why}")]
    ours = preset_path()
    if ours.exists():
        if not dry:
            ours.unlink()
        out.append((str(ours), "removed"))
    return out


def preset_path():
    return folder() / "config-presets" / PRESET


def preset():
    """The preset of LM Studio (the format of its config-presets): the guide of the library as the system prompt and
    the thinking of the model off (a small model thinking at length leaves no tokens for the answer)."""
    from assistant_x.setup import skill

    return {
        "identifier": "@local:assistant-x",
        "name": "Assistant X",
        "changed": False,
        "operation": {
            "fields": [
                {"key": "llm.prediction.systemPrompt", "value": skill.guide()},
                {"key": "llm.prediction.reasoning.enableThinking", "value": False},
            ]
        },
        "load": {"fields": []},
    }


def write_preset(dry):
    """(path, what happened) for our preset file; no other file of LM Studio is written."""
    path = preset_path()
    text = json.dumps(preset(), ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return (str(path), "unchanged")
    if not dry:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return (str(path), "preset written: pick «Assistant X» in a chat of LM Studio")


def skill_dir():
    return None


def link(e):
    """The "Add to LM Studio" link of an entry: lmstudio://add_mcp with the name and the entry as base64 JSON; opened,
    it asks the user to add the server (for a PC where the entry was not written by connect)."""
    import base64, json, urllib.parse

    config = base64.b64encode(json.dumps(e, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return f"lmstudio://add_mcp?name={K.SERVER}&config={urllib.parse.quote(config, safe='')}"
