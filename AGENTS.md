# Agents

<!-- assistant-x:begin (made by assistant-x gen-docs) -->
## For agents that work on this repository or install it

- The user asks you to install or connect Assistant X: follow [INSTALL_FOR_AI.md](INSTALL_FOR_AI.md) (version
  0.5); install the latest release (https://github.com/AlexandrYalovoy/Assistant_X/releases/latest), never `main`.
- The apps and their settings files: [docs/CLIENTS.md](docs/CLIENTS.md); `assistant-x connect APP|auto` writes the
  entry, `assistant-x connect --check` checks it.
- Working on the code: everything in the repository is in US English; the Python code has no Cyrillic (a test checks
  it); `scripts/check.ps1` runs ruff, `ruff format --check` and the tests. `INSTALL_FOR_AI.md`, this section and
  `docs/CLIENTS.md` are made by `assistant-x gen-docs` from `assistant_x/templates/docs/`: edit the templates, then run
  it (`hooks/pre-commit` does; a test fails when they differ).
<!-- assistant-x:end -->
