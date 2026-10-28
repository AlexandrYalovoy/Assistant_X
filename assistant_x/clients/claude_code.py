# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Claude Code: the entry of the user scope through its own command line (`claude mcp add-json -s user`, kept in
~/.claude.json, which is read here and never written); the skill goes to ~/.claude/skills/assistant-x."""

import json, shutil
from pathlib import Path

from assistant_x import clients as K
from assistant_x.core import proc

NAME, TITLE = "claude_code", "Claude Code"
TOOLSET, COMPACT = "all", False


def exe():
    return shutil.which("claude")


def found():
    return bool(exe())


def configs():
    return [str(K.home() / ".claude.json")]


def read():
    p = Path(configs()[0])
    try:
        return (json.loads(p.read_text(encoding="utf-8")).get("mcpServers") or {}).get(K.SERVER)
    except (OSError, ValueError, AttributeError):
        return None


def claude(*args):
    """(exit code, output) of the claude command line."""
    try:
        r = proc.run([exe(), *args], capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    except (OSError, proc.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, (r.stdout + r.stderr).strip()


def connect(e, dry):
    where = "claude mcp (user scope)"
    if not exe():
        return [(where, "Claude Code is not installed")]
    old = read()
    want = {"type": "stdio", "command": e["command"], "args": e["args"], "env": e["env"]}
    if old and all(old.get(k) == want[k] for k in ("command", "args", "env")):
        return [(where, "unchanged")]
    if dry:
        return [(where, "would write")]
    if old:
        claude("mcp", "remove", K.SERVER, "-s", "user")
    code, out = claude("mcp", "add-json", K.SERVER, json.dumps(want), "-s", "user")
    return [(where, "written" if code == 0 else f"refused by claude ({out[:300]}); add by hand:\n{K.by_hand(e)}")]


def disconnect(dry):
    where = "claude mcp (user scope)"
    if not exe() or not read():
        return [(where, "not connected")]
    if dry:
        return [(where, "would write")]
    code, out = claude("mcp", "remove", K.SERVER, "-s", "user")
    return [(where, "written" if code == 0 else f"refused by claude ({out[:300]})")]


def skill_dir():
    return K.home() / ".claude" / "skills" / K.SERVER
