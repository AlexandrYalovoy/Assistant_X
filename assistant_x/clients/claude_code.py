# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Claude Code: the entry of the user scope through its own command line (`claude mcp add-json -s user`, kept in
~/.claude.json, which is read here and never written); the skill goes to ~/.claude/skills/assistant-x. The reading
tools are allowed in advance in permissions.allow of ~/.claude/settings.json (the Code tab of Claude Desktop reads it
too), so the user is not asked before every page; the tools that change the library stay on the user's yes."""

import json, shutil
from pathlib import Path

from assistant_x import clients as K
from assistant_x.core import proc
from assistant_x.server import toolsets

NAME, TITLE = "claude_code", "Claude Code"
TOOLSET, COMPACT = "all", False
SETTINGS = "`claude mcp add-json -s user` (`~/.claude.json`)"
SKILL = "`~/.claude/skills/assistant-x`"


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


def settings():
    return K.home() / ".claude" / "settings.json"


def allowed_tools():
    """The permission rules of the reading tools ("mcp__assistant-x__search_library", ...)."""
    return [f"mcp__{K.SERVER}__{name}" for name in toolsets.READER]


def allow(dry, add=True):
    """(path, status) of the reading tools added to (or taken out of) permissions.allow of ~/.claude/settings.json;
    the other keys and rules stay. A file that is not a JSON object is left alone."""
    p = settings()
    try:
        conf = json.loads(p.read_text(encoding="utf-8-sig") or "{}") if p.exists() else {}
    except (OSError, ValueError) as why:
        return (str(p), f"left alone: the settings file cannot be read ({why})")
    perms = conf.get("permissions", {}) if isinstance(conf, dict) else None
    rules = perms.get("allow", []) if isinstance(perms, dict) else None
    if not isinstance(rules, list):
        return (str(p), "left alone: the settings file is not a JSON object with permissions.allow")
    ours = allowed_tools()
    new = rules + [r for r in ours if r not in rules] if add else [r for r in rules if r not in ours]
    if new == rules:
        return (str(p), "unchanged")
    conf.setdefault("permissions", {})["allow"] = new
    return (str(p), K.put(p, K.json_text(conf), dry))


def connect(e, dry):
    where = "claude mcp (user scope)"
    if not exe():
        return [(where, "Claude Code is not installed")]
    old = read()
    want = {"type": "stdio", "command": e["command"], "args": e["args"], "env": e["env"]}
    if old and all(old.get(k) == want[k] for k in ("command", "args", "env")):
        return [(where, "unchanged"), allow(dry)]
    if dry:
        return [(where, "would write"), allow(dry)]
    if old:
        claude("mcp", "remove", K.SERVER, "-s", "user")
    code, out = claude("mcp", "add-json", K.SERVER, json.dumps(want), "-s", "user")
    if code != 0:
        return [(where, f"refused by claude ({out[:300]}); add by hand:\n{K.by_hand(e)}")]
    return [(where, "written"), allow(dry)]


def disconnect(dry):
    where = "claude mcp (user scope)"
    if not exe() or not read():
        return [(where, "not connected")]
    if dry:
        return [(where, "would write"), allow(dry, add=False)]
    code, out = claude("mcp", "remove", K.SERVER, "-s", "user")
    return [(where, "written" if code == 0 else f"refused by claude ({out[:300]})"), allow(dry, add=False)]


def skill_dir():
    return K.home() / ".claude" / "skills" / K.SERVER
