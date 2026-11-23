# Agents

<!-- assistant-x:begin (made by assistant-x gen-docs) -->
## For agents that work on this repository or install it

- The user asks you to install or connect Assistant X: follow [INSTALL_FOR_AI.md](INSTALL_FOR_AI.md) (version
  0.6.1): one command in the background and its status, its token budget first; install the latest release
  (https://github.com/AlexandrYalovoy/Assistant_X/releases/latest), never `main`. The rest (the steps one by one, the codes, the tools):
  [docs/INSTALL_REFERENCE.md](docs/INSTALL_REFERENCE.md).
- The apps and their settings files: [docs/CLIENTS.md](docs/CLIENTS.md); `assistant-x connect APP|auto` writes the
  entry, `assistant-x connect --check` checks it.
- Something does not work: `assistant-x doctor --json` and `assistant-x connect --check --json` give every known
  failure a stable `code` and a `fix` (the command to run; ask the user before a download or a change of their
  settings); run them again after each fix. The codes: [docs/CLIENTS.md](docs/CLIENTS.md#when-something-does-not-work).
- The tools of the server `assistant-x` not in your list (Codex keeps them behind its search of tools): search the
  tools for "assistant-x library library_guide search_library". The server shows one tool, `library`: every command goes through it,
  `library(action="search_library", args={"query": "..."})`.
- Working on the code: everything in the repository is in US English; the Python code has no Cyrillic (a test checks
  it); `scripts/check.ps1` runs ruff, `ruff format --check` and the tests (`python scripts/check.py` the same where
  PowerShell scripts may not run; `--log FOLDER` keeps a full record). `INSTALL_FOR_AI.md`, this section and
  `docs/CLIENTS.md` are made by `assistant-x gen-docs` from `assistant_x/templates/docs/`: edit the templates, then run
  it (`hooks/pre-commit` does; a test fails when they differ).
<!-- assistant-x:end -->

## Development map for agents

- Read `README.md` for the product contract and `docs/` for the subsystem in question. `core` owns paths, settings,
  cards and transactions; `intake` reads documents; `search` builds and queries the base; `server` exposes MCP;
  `clients` writes application settings; `setup` installs and updates the program.
- Use the project `.venv`. Run `python scripts/check.py --fast` during development and `python
  scripts/release_check.py` on a release commit. Do not edit generated documents directly: edit
  `assistant_x/templates/docs/`, then run `assistant-x gen-docs` and its `--check`.
- Keep the user's library outside the repository. Read-only MCP work uses `--tools one_reader` (one schema) or
  `--tools reader`; `assistant-x context "question" --mode fast|balanced|deep` is the bounded one-command fallback.
  `AX: быстро` selects fast, `AX: глубоко` selects deep, and an unqualified AX question uses balanced. Changing
  documents or packages always needs the plan and confirmation flow. Do not bypass a busy machine lock.
- Every code change needs a focused test. Human-facing documents have Russian twins; code, comments, tests and commit
  messages use US English. Do not publish, tag, push or update an installed application without the maintainer's word.
