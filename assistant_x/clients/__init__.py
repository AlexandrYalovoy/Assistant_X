# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The apps Assistant X connects to, one module each: where the app keeps its MCP servers and its skills, how to add,
read and remove the entry of the library. Every entry starts the same stdio bridge (assistant-x mcp,
server/bridge.py) with the workspace in its environment; the reading tools only for DeepSeek Harness and LM Studio
unless --full.

    claude_desktop  claude_desktop_config.json (mcpServers)          Claude Desktop
    claude_code     `claude mcp add-json -s user` (~/.claude.json)   Claude Code
    codex           ~/.codex/config.toml [mcp_servers.assistant-x]   Codex CLI and IDE, the ChatGPT desktop app
    dsh             ~/.dsh/cordis.patch.yml (an insert entry)        DeepSeek Harness
    lmstudio        ~/.lmstudio/mcp.json (mcpServers)                LM Studio

A file is changed only when the entry differs: a copy of it first (<name>.backup-<date>, the newest BACKUPS_KEPT
kept), the entries and comments of others kept, a file that cannot be read left alone with the entry to add by hand."""

import datetime, importlib, json, os, shutil, sys
from pathlib import Path

SERVER = "assistant-x"
APPS = ("claude_desktop", "claude_code", "codex", "dsh", "lmstudio")
BACKUPS_KEPT = 3
TOOL_TIMEOUT = 900  # s: an answer of the library (a cold start loads the models)
STARTUP_TIMEOUT = 60  # s: the bridge answers the handshake at once; the tool list waits for the service


def app(name):
    """The module of an app."""
    if name not in APPS:
        raise SystemExit(f"Unknown app {name!r}; the apps: {', '.join(APPS)}")
    return importlib.import_module(f"assistant_x.clients.{name}")


def home():
    return Path.home()


def windowless(py):
    """pythonw.exe beside python.exe on Windows: a program without a console never opens a window, whichever app
    starts it (M-008)."""
    p = Path(py)
    if os.name == "nt" and p.name.lower() == "python.exe" and p.with_name("pythonw.exe").is_file():
        return str(p.with_name("pythonw.exe"))
    return str(py)


def entry(python=None, toolset="all", compact=False, root=None):
    """{command, args, env} of the bridge: the same for every app."""
    from assistant_x.core import workspace

    args = ["-m", "assistant_x.server.bridge"]
    if toolset != "all":
        args += ["--tools", toolset]
    if compact:
        args.append("--compact")
    env = {"AX_WORKSPACE": str(root or workspace.find()), "PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1"}
    return {"command": windowless(python or sys.executable), "args": args, "env": env}


# ---------- files ----------


def backup(path):
    """A copy of path beside it (<stem>.backup-<date>_<time><suffix>), the newest BACKUPS_KEPT kept; its path."""
    p = Path(path)
    dst = p.with_name(f"{p.stem}.backup-{datetime.datetime.now():%Y-%m-%d_%H%M%S}{p.suffix}")
    shutil.copy2(p, dst)
    prune(p)
    return str(dst)


def prune(path, keep=BACKUPS_KEPT):
    p = Path(path)
    prefix = f"{p.stem}.backup-"
    old = sorted(f.name for f in p.parent.iterdir() if f.name.startswith(prefix) and f.name.endswith(p.suffix))
    for f in old[:-keep] if keep else old:
        (p.parent / f).unlink()


def put(path, text, dry):
    """Write text into path (atomically, after a backup of the old file); 'written' | 'would write' | 'unchanged'."""
    p = Path(path)
    old = p.read_text(encoding="utf-8-sig") if p.exists() else None
    if old == text:
        return "unchanged"
    if dry:
        return "would write"
    p.parent.mkdir(parents=True, exist_ok=True)
    if old is not None:
        backup(p)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="")
    os.replace(tmp, p)
    return "written"


class Refused(Exception):
    """The settings file cannot be read or holds an entry of ours that is not ours to change: left alone."""


# ---------- JSON settings (Claude Desktop, LM Studio: the mcpServers of Cursor) ----------


def json_read(path):
    """The settings as a dict ({} for no file), Refused when it is not a JSON object."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        conf = json.loads(p.read_text(encoding="utf-8-sig") or "{}")
    except ValueError as e:
        raise Refused(f"the settings file cannot be read ({e})") from e
    if not isinstance(conf, dict) or not isinstance(conf.get("mcpServers", {}), dict):
        raise Refused("the settings file is not a JSON object with mcpServers")
    return conf


def json_entry(path):
    try:
        return (json_read(path).get("mcpServers") or {}).get(SERVER)
    except Refused:
        return None


def json_text(conf):
    return json.dumps(conf, ensure_ascii=False, indent=2) + "\n"


def json_connect(path, e, dry):
    conf = json_read(path)
    servers = conf.setdefault("mcpServers", {})
    old = servers.get(SERVER) or {}
    new = dict(old, command=e["command"], args=e["args"], env=dict(old.get("env") or {}, **e["env"]))
    if old == new and Path(path).exists():
        return "unchanged"
    servers[SERVER] = new
    return put(path, json_text(conf), dry)


def json_disconnect(path, dry):
    if not Path(path).exists():
        return "not connected"
    conf = json_read(path)
    if SERVER not in (conf.get("mcpServers") or {}):
        return "not connected"
    del conf["mcpServers"][SERVER]
    return put(path, json_text(conf), dry)


def by_hand(e, fmt="json"):
    """The entry to add by hand into a file that was left alone."""
    if fmt == "json":
        return json.dumps({"mcpServers": {SERVER: e}}, ensure_ascii=False, indent=2)
    return fmt


# ---------- the connections of this PC (assistant-x update, the service refreshes the skills) ----------


def connections_path():
    from assistant_x.core import workspace

    return workspace.machine_dir() / "connections.json"


def connections():
    """{app: {toolset, compact, python, workspace, version, time}} of the apps connect wrote, {} when none."""
    try:
        data = json.loads(connections_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def remember(name, settings=None):
    """Record (settings) or forget (None) the connection of an app."""
    data = connections()
    if settings is None:
        data.pop(name, None)
    else:
        data[name] = settings
    p = connections_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)
