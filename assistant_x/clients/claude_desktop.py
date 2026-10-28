# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Claude Desktop: mcpServers of claude_desktop_config.json in every settings folder of the app (the build of
claude.ai/download and the Microsoft Store one). Its skill is a zip the user uploads (assistant-x skill): no folder."""

import glob, os

from assistant_x import clients as K

NAME, TITLE = "claude_desktop", "Claude Desktop"
TOOLSET, COMPACT = "all", False
SETTINGS = r"`%APPDATA%\Claude\claude_desktop_config.json` (and the Microsoft Store folder), `mcpServers`"
SKILL = "a zip the user uploads (`assistant-x skill`)"
FILE = "claude_desktop_config.json"


def dirs():
    """([settings folders], installed): the folders that exist, else the one of the usual build (written in advance)."""
    if os.name == "nt":  # the Microsoft Store build keeps settings inside its package folder
        all_ = [os.path.join(os.environ.get("APPDATA", ""), "Claude")] + glob.glob(
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages", "Claude_*", "LocalCache", "Roaming", "Claude")
        )
    else:
        all_ = [os.path.expanduser("~/Library/Application Support/Claude"), os.path.expanduser("~/.config/Claude")]
    found = [d for d in all_ if os.path.isdir(d)]
    return found or all_[:1], bool(found)


def found():
    return dirs()[1]


def configs():
    return [os.path.join(d, FILE) for d in dirs()[0]]


def read():
    return next((e for e in map(K.json_entry, configs()) if e), None)


def connect(e, dry):
    out = []
    for path in configs():
        try:
            out.append((path, K.json_connect(path, e, dry)))
        except K.Refused as why:
            out.append((path, f"left alone: {why}; add by hand:\n{K.by_hand(e)}"))
    return out


def disconnect(dry):
    out = []
    for path in configs():
        try:
            out.append((path, K.json_disconnect(path, dry)))
        except K.Refused as why:
            out.append((path, f"left alone: {why}"))
    return out


def skill_dir():
    return None  # uploaded as a zip in Settings → Capabilities → Skills
