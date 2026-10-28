# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""DeepSeek Harness (dsh): an `insert` patch with an entry of @deepseek-ai/dsh-mcp-client in ~/.dsh/cordis.patch.yml,
the user patch layer of every profile of the PC (DSH_HOME moves the folder). The file is a YAML array of patches: the
entry goes in as a block between two marker comments, so the patches and comments of others stay and disconnect takes
out exactly what connect put in. dsh reloads an edited entry by itself; its tools are mcp__assistant-x__*. The skill
goes to ~/.dsh/skills/assistant-x (watched, no restart). The reading tools by default."""

import os, re
from pathlib import Path

from assistant_x import clients as K

NAME, TITLE = "dsh", "DeepSeek Harness"
TOOLSET, COMPACT = "reader", False
BEGIN = "# >>> assistant-x (assistant-x connect dsh; assistant-x disconnect dsh removes it)\n"
END = "# <<< assistant-x\n"
HEAD = "# The user patch layer of every dsh profile: a YAML array of loader patches.\n"


def folder():
    return Path(os.environ.get("DSH_HOME") or K.home() / ".dsh")


def found():
    return folder().is_dir()


def configs():
    return [str(folder() / "cordis.patch.yml")]


def q(v):
    """A YAML scalar in single quotes (a backslash stays a backslash)."""
    return "'" + str(v).replace("'", "''") + "'"


def block(e):
    lines = [
        BEGIN,
        "- insert:\n",
        f"    - id: mcp-{K.SERVER}\n",
        "      name: '@deepseek-ai/dsh-mcp-client'\n",
        "      config:\n",
        f"        serverName: {K.SERVER}\n",
        "        transport: stdio\n",
        f"        command: {q(e['command'])}\n",
        f"        args: [{', '.join(q(a) for a in e['args'])}]\n",
        "        env:\n",
        *[f"          {k}: {q(v)}\n" for k, v in e["env"].items()],
        f"        toolCallTimeoutMs: {K.TOOL_TIMEOUT * 1000}\n",
        END,
    ]
    return "".join(lines)


def split(text):
    """(before, ours or None, after) of the file text."""
    if BEGIN not in text:
        return text, None, ""
    a = text.index(BEGIN)
    b = text.find(END, a)
    if b < 0:
        raise K.Refused("the block of assistant-x has no end marker")
    return text[:a], text[a : b + len(END)], text[b + len(END) :]


def body(text):
    """The text without comments and blank lines."""
    return "\n".join(line for line in (re.sub(r"(^|\s)#.*$", "", x).rstrip() for x in text.splitlines()) if line.strip())


def read():
    p = Path(configs()[0])
    if not p.exists():
        return None
    _, ours, _ = split(p.read_text(encoding="utf-8-sig"))
    if not ours:
        return None
    cmd = re.search(rf"^\s+command: {QUOTED}$", ours, re.M)
    args = re.search(r"^\s+args: \[(.*)\]$", ours, re.M)
    return {
        "command": unq(cmd.group(1)) if cmd else None,
        "args": [unq(x) for x in re.findall(QUOTED, args.group(1))] if args else [],
        "env": {k: unq(v) for k, v in re.findall(rf"^ {{10}}(\w+): {QUOTED}$", ours, re.M)},
    }


QUOTED = r"'((?:[^']|'')*)'"


def unq(s):
    return s.replace("''", "'")


def connect(e, dry):
    path = Path(configs()[0])
    text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    try:
        before, ours, after = split(text)
        rest = body(before + after)
        if "serverName: assistant-x" in before + after:
            raise K.Refused("it has an entry with serverName assistant-x that assistant-x did not write")
        if rest and rest.strip() != "[]" and not rest.lstrip().startswith("-"):
            raise K.Refused("it is not a YAML array of patches")
    except K.Refused as why:
        return [(str(path), f"left alone: {why}; add by hand:\n{block(e)}")]
    if ours is None:
        if body(text).strip() == "[]":  # an empty flow array: the block takes its place
            before = re.sub(r"^\s*\[\]\s*$\n?", "", text, count=1, flags=re.M)
        elif not text:
            before = HEAD
        else:
            before = text if text.endswith("\n") else text + "\n"
        after = ""
    out = before + block(e) + after
    return [(str(path), K.put(path, out, dry))]


def disconnect(dry):
    path = Path(configs()[0])
    if not path.exists():
        return [(str(path), "not connected")]
    text = path.read_text(encoding="utf-8-sig")
    try:
        before, ours, after = split(text)
    except K.Refused as why:
        return [(str(path), f"left alone: {why}")]
    if ours is None:
        return [(str(path), "not connected")]
    out = before + after
    if not body(out):
        out = out + "[]\n"  # an array still, with no patch
    return [(str(path), K.put(path, out, dry))]


def skill_dir():
    return folder() / "skills" / K.SERVER
