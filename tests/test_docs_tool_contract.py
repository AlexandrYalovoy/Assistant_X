# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The calls the documents and the skills show match the live schema of the server: every tool they name exists,
every argument they give it is one of its parameters (an agent that installed 0.6 wrote its own check with an old
name of a field and lost calls on it). The documents of people (docs, README, INSTALL_FOR_AI and their Russian
twins), the files for models (AGENTS.md, the skill templates, the plugins) and the instructions of the server."""

import glob, json, os, re

import anyio
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXTS = (
    ["AGENTS.md", "INSTALL_FOR_AI.md", "INSTALL_FOR_AI.ru.md", "README.md", "README.ru.md"]
    + glob.glob("docs/*.md", root_dir=ROOT)
    + glob.glob("assistant_x/templates/**/*.md", root_dir=ROOT, recursive=True)
    + glob.glob("assistant_x/profiles/**/*.md", root_dir=ROOT, recursive=True)
    + glob.glob("plugins/**/*.md", root_dir=ROOT, recursive=True)
    + ["assistant_x/server/mcp_server.py"]
)


@pytest.fixture(scope="module")
def schema():
    from assistant_x.server import mcp_server

    return {
        t.name: set((t.input_schema or {}).get("properties") or {}) - {"ctx"} for t in anyio.run(mcp_server.mcp.list_tools)
    }


def balanced(text, i, open_="(", close=")"):
    """text[i:] from an opening bracket to its closing one (strings in quotes skipped), or ''."""
    depth, q = 0, None
    for j in range(i, min(len(text), i + 2000)):
        c = text[j]
        if q:
            q = None if c == q and text[j - 1] != "\\" else q
        elif c in "\"'":
            q = c
        elif c == open_:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return text[i : j + 1]
    return ""


def keys_of(args):
    """The names of the arguments of a call: name=… of a Python call, "name": of a JSON object (the outer level)."""
    inner = args[1:-1]
    out, depth, q = set(), 0, None
    for k, c in enumerate(inner):
        if q:
            q = None if c == q and inner[k - 1] != "\\" else q
            continue
        if c in "\"'":
            q = c
            if depth == 0 and args[0] == "{":
                m = re.match(r'"(\w+)"\s*:', inner[k:])
                if m:
                    out.add(m[1])
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth == 0 and args[0] == "(":
            m = (
                re.match(r"(?<![\w.])(\w+)\s*=(?!=)", inner[k:])
                if not (k and (inner[k - 1].isalnum() or inner[k - 1] == "_"))
                else None
            )
            if m:
                out.add(m[1])
    return out


def calls(text, tools):
    """(tool, {argument names}, where) of every call of a tool the text shows."""
    names = "|".join(sorted(tools, key=len, reverse=True))
    for m in re.finditer(rf"(?<![\w.-])(?<!def )({names})\(", text):  # search_library(query=…); no def, no a.b(
        args = balanced(text, m.end() - 1)
        if args:
            yield m[1], keys_of(args), m.start()
    for m in re.finditer(r'action\s*=\s*"(\w+)"', text):  # library(action="read_pages", args={...})
        rest = text[m.end() : m.end() + 400]
        a = re.match(r"\s*,\s*args\s*=\s*\{", rest)
        yield "@" + m[1], keys_of(balanced(rest, rest.index("{"), "{", "}")) if a else set(), m.start()
    for m in re.finditer(r'"name"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:\s*\{', text):  # JSON-RPC tools/call
        yield m[1], keys_of(balanced(text, m.end() - 1, "{", "}")), m.start()
    for m in re.finditer(r'(?:call_tool|call)\(\s*"(\w+)"\s*,\s*', text):  # call("verify_quote", code=…) / call_tool
        args = balanced(text, m.start() + text[m.start() :].index("("))
        if text[m.end() : m.end() + 1] == "{":
            yield m[1], keys_of(balanced(text, m.end(), "{", "}")), m.start()
        elif args:
            yield m[1], {k for k in keys_of(args)}, m.start()


def test_every_call_in_the_documents_matches_the_live_schema(schema):
    bad = []
    seen = 0
    for rel in TEXTS:
        text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        for tool, keys, at in calls(text, schema):
            line = text.count("\n", 0, at) + 1
            seen += 1
            name = tool.lstrip("@")
            if name not in schema:
                if tool.startswith("@"):
                    bad.append(f"{rel}:{line}: library(action={name!r}) names no command")
                continue
            wrong = keys - schema[name]
            if wrong:
                bad.append(f"{rel}:{line}: {name}({', '.join(sorted(wrong))}=…): not a parameter of {name}")
    assert seen > 40  # the calls are found at all
    assert not bad, "\n".join(bad)


def test_the_parser_of_the_calls_finds_a_stale_name(schema):
    text = 'read_pages(code="N-00001", start=3, end_page=4); library(action="search_library", args={"q": "x"})'
    got = {(t, frozenset(k)) for t, k, _ in calls(text, schema)}
    assert ("read_pages", frozenset({"code", "start", "end_page"})) in got
    assert ("@search_library", frozenset({"q"})) in got
    assert json.dumps(sorted(schema["read_pages"])) == json.dumps(["code", "end_page", "start_page"])
