# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tool sets of the library server and the compact mode for small local models: which tools an app gets and how
long their answers may be. Light (standard library only): the stdio bridge (server/bridge.py) uses it on every message.

    reader  the tools that read the library (READER): the default of DeepSeek Harness and LM Studio
    all     every tool, the intake and the base packages too: the default of Claude and Codex

compact: the first sentence of every tool description, and the answers of the reading tools cut at COMPACT_CHARS
characters with a note how to get the rest: one answer with a quote fits a context of 16 000 tokens."""

import re

READER = (
    "library_guide",
    "search_library",
    "read_pages",
    "book_map",
    "page_image",
    "verify_quote",
    "document_info",
    "list_documents",
)
TOOLSETS = ("reader", "all")
# the compact mode is the reference mode of a small local model (LM Studio): it finds and quotes, nothing else; the
# other tools are hidden, their descriptions would only take its context
REFERENCE = ("library_guide", "search_library", "read_pages")
HIDDEN_ARGS = ("quotes", "reference", "context")  # set by the bridge in the compact mode, not shown to the model
COMPACT_CHARS = 12000  # about 3 500-4 000 tokens of an answer: 15 quote lines of a search fit
COMPACT_K = 3  # search_library results in the compact mode, at most: the best of the library
COMPACT_NORMS = 3  # and the best of shelf N (standards, company documents) after them
CUT_NOTE = (
    "\n\n[Cut at {n} characters (compact mode). Ask for less: fewer results (k), fewer pages, or one document (codes).]"
)


def allowed(name, toolset, compact=False):
    """Is the tool name in the set ("reader" | "all"), and in the compact mode one of the reference mode?"""
    return (toolset == "all" or name in READER) and (not compact or name in REFERENCE)


def check(toolset):
    """The set, or SystemExit with the choices."""
    if toolset not in TOOLSETS:
        raise SystemExit(f"--tools takes {' or '.join(TOOLSETS)}, not {toolset!r}")
    return toolset


def first_sentence(text):
    """The first sentence of a description (up to the first full stop followed by a space or the end)."""
    text = " ".join((text or "").split())
    m = re.search(r"(?<=[.!?])\s", text)
    return text[: m.start()] if m else text


def fit(text, limit=None):
    """text cut at limit characters (default COMPACT_CHARS; at a line end where one is near), with CUT_NOTE."""
    limit = limit or COMPACT_CHARS
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", int(limit * 0.8), limit)
    return text[: cut if cut > 0 else limit] + CUT_NOTE.format(n=limit)


def compact_tools(tools):
    """A tools/list result's tools (dicts) with short descriptions; the argument descriptions dropped."""
    out = []
    for t in tools:
        t = dict(t)
        t["description"] = first_sentence(t.get("description"))
        schema = t.get("inputSchema")
        if isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
            props = {
                k: {x: y for x, y in v.items() if x != "description"}
                for k, v in schema["properties"].items()
                if k not in HIDDEN_ARGS
            }
            t["inputSchema"] = dict(schema, properties=props)
        out.append(t)
    return out


def compact_arguments(name, args):
    """The arguments of a call in the compact mode: search_library asks for COMPACT_K results at most and, unless the
    model chose shelves or documents itself, COMPACT_NORMS of shelf N after them, every hit as a line ready to quote;
    library_guide gives the rules of the reference mode."""
    if name == "search_library" and isinstance(args, dict):
        args = dict(args, k=min(int(args.get("k") or COMPACT_K), COMPACT_K), quotes=True)
        if not args.get("sections") and not args.get("codes"):
            args["norms"] = COMPACT_NORMS
    elif name == "library_guide":
        args = dict(args or {}, reference=True)
    return args


WEAK_MARK = "Weak match ("  # the note of search_library when the reranker is not sure (mcp_server.WEAK_MATCH)
WEAK_LIMIT = 3  # weak searches in a row after which the compact bridge stops a small model searching on
WEAK_STOP = (
    "STOP. The library has no document on this topic. Do not search again. Answer the user now, in the user's "
    'language: "The library has no documents on this question", and suggest rephrasing the question. Do not answer '
    "from general knowledge."
)


FORM_HINT = (
    "Reference mode, answer in the user's language: 1) one line: what was found; 2) ALL the lines below that are "
    "about the question, up to 15 (do not stop at the first few; never a line off the question), copied exactly, "
    "grouped by the level of the documents, the highest first: «quote» — [code, …, PDF N], title; 3) Sources: code, "
    "title. No explanation, no calculation, no "
    'advice, nothing from yourself. If no line is about the question, answer only "The library has no documents on '
    "this question\" in the user's language."
)


def with_form(content):
    """The content of a search_library or read_pages answer with FORM_HINT before it: a small local model that got
    no system prompt (LM Studio without the preset) sees the form of the answer at every result."""
    return [{"type": "text", "text": FORM_HINT}] + list(content)


SEARCH_LIMIT = 3  # searches of one question after which the reference mode tells a small model to answer
QUESTION_GAP = 120  # seconds without a call: the next call starts a new question
ANSWER_NOW = (
    "Searched {n} times: answer the user now with the lines you already have (copied exactly, with their references), "
    'or, if none is about the question, "The library has no documents on this question". Do not search again.'
)


def first_search(state, query, now):
    """((first query, now), context) for one more search_library of the compact bridge: the first search of a question
    (after QUESTION_GAP without a call a new question begins) goes with every later one as its context, so the key
    norms of its topic come first though the small model rewords the next searches; no context for the first one."""
    first, last = state
    if first is None or last is None or now - last > QUESTION_GAP:
        return (query, now), None
    return (first, now), (first if first != query else None)


def search_budget(state, name, content, now):
    """(state, content) after one more answer of a tool in the reference mode; state is (searches, time of the last
    call). A pause of QUESTION_GAP starts a new question; from the SEARCH_LIMIT-th search on, ANSWER_NOW comes before
    the result (a small model with no system prompt searched six times and read pages, and never answered)."""
    count, last = state
    if last is None or now - last > QUESTION_GAP:
        count = 0
    if name == "search_library":
        count += 1
    if count >= SEARCH_LIMIT and name in ("search_library", "read_pages"):
        content = [{"type": "text", "text": ANSWER_NOW.format(n=count)}] + list(content)
    return (count, now), content


def weak_guard(count, content):
    """(the count of weak searches in a row, the content to give) after one more search_library answer: a search with
    the weak-match note counts, any other resets; at WEAK_LIMIT in a row the fragments give way to WEAK_STOP (a small
    model told twice that the library may lack the subject searched twelve times and never answered)."""
    text = "\n".join(c.get("text") or "" for c in content if isinstance(c, dict) and c.get("type") == "text")
    count = count + 1 if WEAK_MARK in text[:2000] else 0
    if count >= WEAK_LIMIT:
        return count, [{"type": "text", "text": WEAK_STOP}]
    return count, content


def compact_content(content):
    """The content blocks of a tool result with every text block fitted."""
    return [
        dict(c, text=fit(c["text"])) if c.get("type") == "text" and isinstance(c.get("text"), str) else c for c in content
    ]
