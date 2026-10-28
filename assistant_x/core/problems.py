# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The known failures of a setup, one table for every place that reports one: assistant-x doctor --json, assistant-x
connect --check --json, library_guide, and the troubleshooting section of the docs (setup/gen_docs.py). Every item has
a stable code, a message and the fix: the exact command to run (or the step to take), so an agent (Codex, Claude Code,
DeepSeek Harness, LM Studio) can repair the setup by itself. Light: the standard library only.

    item(code, **values)   {"code", "message", "fix"} with the {placeholders} of the fix filled in
    markdown()             the table of the docs"""

# code -> (message, fix); the fix names {workspace}, {app}, {log}, {folder} where they are known
PROBLEMS = {
    "workspace-missing": ("The workspace of the library is not made yet.", 'assistant-x init "{workspace}"'),
    "folder-missing": ("A folder of the workspace is missing.", 'assistant-x init "{workspace}"'),
    "base-missing": ("The library has cards but no search base.", "assistant-x build"),
    "model-missing": (
        "No embedding model: the search is by words only.",
        "assistant-x download-models (about 4.5 GB: ask the user first)",
    ),
    "vectors-missing": ("Fragments without meaning vectors are found by words only.", "assistant-x embed"),
    "older-folder": (
        "An older folder of the PC (before 0.5.1, or the private copy of Claude Desktop from the Microsoft Store) may "
        "still be used by an app connected before.",
        "assistant-x connect auto",
    ),
    "app-not-connected": ("The app has no entry of Assistant X.", "assistant-x connect {app}"),
    "app-check-failed": (
        "The entry of the app does not answer the handshake, the tool list or a search.",
        "assistant-x connect --check {app} --json; if it fails again: assistant-x debug-report",
    ),
    "search-words-only": (
        "The search of the app answers by words only (no model or no vectors).",
        "assistant-x doctor --json (it names the missing model or vectors)",
    ),
    "service-not-started": (
        "The library service did not start.",
        "read the end of the service log {log}; then assistant-x doctor --json",
    ),
    "gpu-memory-low": (
        "The video card has little free memory: the search models and a local language model slow each other down.",
        'in assistant_x.toml under [search] set device = "cpu" (the library then leaves the video card to the local '
        "model), or load the local model with fewer parallel slots",
    ),
    "skill-outdated": (
        "The skill uploaded to Claude Desktop is older than the program.",
        "assistant-x skill; zip the folder {folder} and upload it in Claude (Settings, Capabilities, Skills)",
    ),
    "tools-hidden": (
        "The app keeps the tools of the server behind its search of tools (Codex).",
        'search the tools for "assistant-x library_guide search_library"; the server has no resources',
    ),
    "sign-in-limits": (
        "The plan or the sign-in of the app limits it: on the Free plan of ChatGPT, Codex runs in the desktop app only, "
        "and its sign-in may ask for a phone number.",
        "use the ChatGPT desktop app, or connect another app: assistant-x connect auto",
    ),
}


class _Blank(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def item(code, **values):
    """The item of a known failure; KeyError for an unknown code (a typo must not pass unnoticed)."""
    message, fix = PROBLEMS[code]
    return {"code": code, "message": message, "fix": fix.format_map(_Blank(values))}


def markdown():
    """The troubleshooting table of the docs: every code, what it means, what fixes it."""
    rows = ["| Code | What it means | Fix |", "| --- | --- | --- |"]
    for code, (message, fix) in PROBLEMS.items():
        rows.append(f"| `{code}` | {message} | {fix.replace('|', '/')} |")
    return "\n".join(rows)
