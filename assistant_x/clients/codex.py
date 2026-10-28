# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Codex (the CLI, the IDE extension) and the ChatGPT desktop app: they share ~/.codex/config.toml (CODEX_HOME moves
it). The entry is the table [mcp_servers.assistant-x] with its [mcp_servers.assistant-x.env], written as text: the
other tables and every comment of the file stay as they are. startup_timeout_sec is raised (Codex waits 10 s by
default); the skill goes to ~/.agents/skills/assistant-x."""

import os, re, tomllib
from pathlib import Path

from assistant_x import clients as K

NAME, TITLE = "codex", "Codex and the ChatGPT desktop app"
TOOLSET, COMPACT = "all", False
TABLE = f"mcp_servers.{K.SERVER}"
HEADER = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(?:#.*)?$")


def folder():
    return Path(os.environ.get("CODEX_HOME") or K.home() / ".codex")


def found():
    import shutil

    return folder().is_dir() or bool(shutil.which("codex"))


def configs():
    return [str(folder() / "config.toml")]


def parse(text):
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise K.Refused(f"config.toml cannot be read ({e})") from e


def read():
    p = Path(configs()[0])
    if not p.exists():
        return None
    try:
        conf = parse(p.read_text(encoding="utf-8-sig"))
    except K.Refused:
        return None
    return (conf.get("mcp_servers") or {}).get(K.SERVER)


def name_of(header):
    """The dotted name of a table header, quotes and spaces around the dots taken off."""
    return ".".join(part.strip().strip("\"'") for part in header.split("."))


def ours(name):
    return name == TABLE or name.startswith(TABLE + ".")


def split(text):
    """(the text without our tables, the index where they stood or None)."""
    lines = text.splitlines(keepends=True)
    keep, at, inside = [], None, False
    for line in lines:
        m = HEADER.match(line)
        if m:
            inside = ours(name_of(m.group(1)))
            if inside and at is None:
                at = len(keep)
        if not inside:
            keep.append(line)
    return keep, at


def value(v):
    """A TOML value: a literal string where it can be (Windows paths keep their backslashes), else a basic one."""
    if isinstance(v, str):
        if "'" not in v and "\n" not in v:
            return f"'{v}'"
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return "[" + ", ".join(value(x) for x in v) + "]"


def block(e):
    from assistant_x.server import toolsets

    lines = [
        "# Assistant X: the library of documents (assistant-x connect codex; assistant-x disconnect codex removes it)\n",
        f"[{TABLE}]\n",
        f"command = {value(e['command'])}\n",
        f"args = {value(e['args'])}\n",
        f"startup_timeout_sec = {K.STARTUP_TIMEOUT}\n",
        f"tool_timeout_sec = {K.TOOL_TIMEOUT}\n",
    ]
    if "--tools" in e["args"]:
        lines.append(f"enabled_tools = {value(list(toolsets.READER))}\n")
    lines.append(f"\n[{TABLE}.env]\n")
    lines += [f"{k} = {value(v)}\n" for k, v in e["env"].items()]
    return lines


def without_our_comment(keep, at):
    """Our comment line just above our tables goes with them."""
    if at and keep[at - 1].startswith("# Assistant X: the library of documents"):
        del keep[at - 1]
        at -= 1
    return keep, at


def connect(e, dry):
    path = Path(configs()[0])
    text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    try:
        conf = parse(text)
        keep, at = without_our_comment(*split(text))
        if at is None and K.SERVER in (conf.get("mcp_servers") or {}):
            raise K.Refused("it has an inline entry assistant-x of mcp_servers")
    except K.Refused as why:
        return [(str(path), f"left alone: {why}; add by hand:\n{''.join(block(e))}")]
    new = block(e)
    if at is None:  # at the end, after a blank line
        if keep and not keep[-1].endswith("\n"):
            keep[-1] += "\n"
        at = len(keep)
        if keep and keep[-1].strip():
            new = ["\n"] + new
    elif at < len(keep):
        new = new + ["\n"]
    out = "".join(keep[:at] + new + keep[at:])
    if parse(out).get("mcp_servers", {}).get(K.SERVER, {}).get("command") != e["command"]:
        raise AssertionError("the TOML written does not read back")  # never expected: the tests cover it
    return [(str(path), K.put(path, out, dry))]


def disconnect(dry):
    path = Path(configs()[0])
    if not path.exists():
        return [(str(path), "not connected")]
    text = path.read_text(encoding="utf-8-sig")
    keep, at = without_our_comment(*split(text))
    if at is None:
        return [(str(path), "not connected")]
    while at < len(keep) and at and not keep[at - 1].strip() and not keep[at].strip():
        del keep[at]  # no double blank line where the tables were
    out = "".join(keep).rstrip("\n") + ("\n" if "".join(keep).strip() else "")
    return [(str(path), K.put(path, out, dry))]


def skill_dir():
    return K.home() / ".agents" / "skills" / K.SERVER
