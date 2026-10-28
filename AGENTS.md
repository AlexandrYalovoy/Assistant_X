# Agents

<!-- assistant-x:begin (made by assistant-x gen-docs) -->
## For agents that work on this repository or install it

- The user asks you to install or connect Assistant X: follow [INSTALL_FOR_AI.md](INSTALL_FOR_AI.md) (version
  0.5.3); install the latest release (https://github.com/AlexandrYalovoy/Assistant_X/releases/latest), never `main`.
- The apps and their settings files: [docs/CLIENTS.md](docs/CLIENTS.md); `assistant-x connect APP|auto` writes the
  entry, `assistant-x connect --check` checks it.
- Something does not work: `assistant-x doctor --json` and `assistant-x connect --check --json` give every known
  failure a stable `code` and a `fix` (the command to run; ask the user before a download or a change of their
  settings); run them again after each fix. The codes: [docs/CLIENTS.md](docs/CLIENTS.md#when-something-does-not-work).
- The tools of the server `assistant-x` not in your list (Codex keeps them behind its search of tools): search the
  tools for "assistant-x library_guide search_library".
- Working on the code: everything in the repository is in US English; the Python code has no Cyrillic (a test checks
  it); `scripts/check.ps1` runs ruff, `ruff format --check` and the tests (`python scripts/check.py` the same where
  PowerShell scripts may not run; `--log FOLDER` keeps a full record). `INSTALL_FOR_AI.md`, this section and
  `docs/CLIENTS.md` are made by `assistant-x gen-docs` from `assistant_x/templates/docs/`: edit the templates, then run
  it (`hooks/pre-commit` does; a test fails when they differ).
<!-- assistant-x:end -->
