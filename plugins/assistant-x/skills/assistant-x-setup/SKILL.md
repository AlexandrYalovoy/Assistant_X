---
name: "assistant-x-setup"
description: "Install and connect Assistant X, the local library of the user's documents (PDF, scans, standards, books) with search and page citations. Use it when the user asks to install, set up, connect or update Assistant X or their document library, or gives a base package (.axbase)."
---

# Install and connect Assistant X

<!-- Made by assistant-x gen-docs from assistant_x/templates/docs/setup-SKILL.md (version 0.5.2). -->

Assistant X keeps the user's documents as searchable texts on their PC and serves them over MCP. This plugin brings
only this guide: the program itself is installed from its latest release, and `assistant-x connect` then writes the
MCP entry and the library skill of this app.

1. Read the instructions of the latest release and follow them step by step, with the user's yes before every
   command: https://github.com/AlexandrYalovoy/Assistant_X/blob/main/INSTALL_FOR_AI.md (the tag of https://github.com/AlexandrYalovoy/Assistant_X/releases/latest gives the version; install that one, never
   `main`).
2. When the program is there already (`assistant-x --version` answers, or `%USERPROFILE%\.assistant_x\venv`), run
   `assistant-x doctor --json` first and follow the `fix` of every item it lists (ask the user before a download or a
   change of their settings), then `assistant-x connect auto` and `assistant-x connect --check --json`; an app that is
   not `"ok"` has its own `problem.fix`. Run the checks again until they are clean.
3. Tell the user to restart this app; then a message starting with `AX:` (or "connect to the library") switches the
   library on.
