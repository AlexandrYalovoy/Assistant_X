# Assistant X

Your own knowledge base with an expert on top: Assistant X keeps your documents (PDF, DOC/DOCX, PPTX, scans) as
searchable texts on your computer and lets your AI assistant read, cross-check and cite them page by page through
an MCP server: Claude (Desktop and Code), Codex and the ChatGPT desktop app, DeepSeek Harness, LM Studio with any local
model, and any other MCP client. Search by words and by meaning, page images of the originals, tables of contents of
books, a quality warning for weak scans. The library and its search run locally; what reaches the model is only what
it reads from the library to answer (with a local model in LM Studio nothing leaves the PC).

Version 0.5.3, a prototype (what comes next: [`ROADMAP.md`](ROADMAP.md)). The default profile `general` suits a library of any
field; `oil-gas-ru` adds the synonyms of a Russian oil-and-gas process engineer. License: GNU AGPL-3.0-or-later; the data folders also CC-BY-4.0 (see License below).

**Author:** Alexandr Yalovoy.

## Get the program

**The shortest way: ask your agent.** Tell Codex, Claude Code or DeepSeek Harness: "Install Assistant X for me:
https://github.com/AlexandrYalovoy/Assistant_X" — the agent follows [`INSTALL_FOR_AI.md`](INSTALL_FOR_AI.md) (the
latest release, the connection of your apps, a check), and you confirm its commands. Codex and the ChatGPT desktop app
also take the plugin of this repository: `codex plugin marketplace add AlexandrYalovoy/Assistant_X`; Claude Code:
`/plugin marketplace add AlexandrYalovoy/Assistant_X`.

- **The repository:** https://github.com/AlexandrYalovoy/Assistant_X (issues and pull requests there); a mirror on
  GitFlic: https://gitflic.ru/project/alexandryalovoy/assistant_x. Clone it with
  `git clone https://github.com/AlexandrYalovoy/Assistant_X.git`, or download the ZIP of the code from the page.
- **A release:** https://github.com/AlexandrYalovoy/Assistant_X/releases — the source of the version, the wheel
  `assistant_x-<version>-py3-none-any.whl` and the notes of the version (CHANGELOG).
- **An offline medium** (Windows, no internet needed on the PC): a folder made by `assistant-x prepare-media` on a PC
  with internet — [`Setup.bat`](Setup.bat), the program in `app\` (its complete source), the packages, the models and the programs
  of the intake. Copy it to the PC and double-click [`Setup.bat`](Setup.bat).

## What is in the repository

| Path | What it is |
| --- | --- |
| [`assistant_x/`](assistant_x) | the Python package: `core` (workspace, settings, language packs, locks, file formats, text and base helpers), `search` (base builder, embeddings, retrieval, reports), `intake` (the intake of new documents and its tools), `server` (the MCP server `assistant-x`), `setup` (installer, debug report, media), `cli` (the command `assistant-x`), `lang` (language packs: data), `profiles` (domain profiles: data), `templates` |
| [`pyproject.toml`](pyproject.toml) | the package `assistant-x`: dependencies and extras `dense`, `intake`, `dml`, `export`, `dev` |
| [`Setup.bat`](Setup.bat), [`intake.bat`](intake.bat), [`assistant-x.bat`](assistant-x.bat) | double-click: install; the intake of `inbox`; any command (`assistant-x.bat help`) |
| [`scripts/`](scripts) | thin .bat files: debug report, library report, query log, intake installation, media |
| [`assistant_x/templates/skill/`](assistant_x/templates/skill) | the skill `assistant-x` (switched on by "AX:") from one core: SKILL.md for Claude and for the agents (Codex, DeepSeek Harness), the short rules of the tool `library_guide`; `assistant-x skill` writes it for the profile of the workspace |
| [`assistant_x/clients/`](assistant_x/clients) | the apps `assistant-x connect` knows: where each keeps its MCP servers and skills |
| [`INSTALL_FOR_AI.md`](INSTALL_FOR_AI.md), [`AGENTS.md`](AGENTS.md), [`plugins/`](plugins) | the instructions for an agent that installs Assistant X, the notes for agents, the plugin of Codex and Claude Code (with [`.agents/plugins`](.agents/plugins) and [`.claude-plugin`](.claude-plugin)): made by `assistant-x gen-docs` from [`assistant_x/templates/docs/`](assistant_x/templates/docs) |
| [`assistant_x/schemas/`](assistant_x/schemas) | the JSON Schema of the document cards (`card-1.json`) |
| [`tests/`](tests) | the tests ([`tests/base`](tests/base), [`tests/search`](tests/search), [`tests/intake`](tests/intake), [`tests/corpus`](tests/corpus), and the top of `tests`: see Tests) |
| [`docs/`](docs) | the guides: the search ([`SEARCH.md`](docs/SEARCH.md)), the intake ([`INTAKE.md`](docs/INTAKE.md)), base packages ([`PACKAGES.md`](docs/PACKAGES.md)), the apps ([`CLIENTS.md`](docs/CLIENTS.md)), the glossary ([`GLOSSARY.md`](docs/GLOSSARY.md)) |
| [`ROADMAP.md`](ROADMAP.md), [`CHANGELOG.md`](CHANGELOG.md) | what comes next, what changed |
| [`LICENSE`](LICENSE), [`LICENSES/`](LICENSES), [`NOTICE`](NOTICE), [`CLA.md`](CLA.md), [`CONTRIBUTING.md`](CONTRIBUTING.md), [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) | the licenses, the notices of the author and of the third-party components, the contributor agreement, how to contribute, the code of conduct |
| [`SECURITY.md`](SECURITY.md) | how to report a vulnerability privately, and what the product guarantees about untrusted documents and packages |

## Profiles and languages

The code is English only; what it knows about documents is data. **Language packs** ([`assistant_x/lang/ru`](assistant_x/lang/ru),
[`assistant_x/lang/en`](assistant_x/lang/en)) hold the letters, stemmers, stop words and the words that match documents: headings, references
to tables and figures, designations of standards, title pages, personal papers, hidden instructions. Every pack is used
by default (`[documents] languages` in `assistant_x.toml`), so Russian and English documents are read the same way in
any workspace, and every card has its searchable texts in English and Russian. The shelves of the library (the
letters of the codes) are the same everywhere: N Standards, L Literature, P Projects and reports, E Equipment documents, R Regulations and law, J Journals and
papers, X Other ([`assistant_x/schemas/shelves.json`](assistant_x/schemas/shelves.json)). A **domain profile**
(`assistant_x/profiles/<name>`) adds only the knowledge of one field: `general` (the default) has none, `oil-gas-ru`
brings Russian oil-and-gas synonyms and the role of a process engineer in the skill (`assistant-x init --profile
oil-gas-ru`).

## Your workspace (not in the repository)

All your data lives in one folder, `Documents\Assistant X` by default (`assistant-x init [FOLDER]` makes it; another
one: `AX_WORKSPACE` or `--workspace`): `assistant_x.toml` (the settings), `inbox/` (new documents), `library/` (the
originals by shelves, `01_Standards … 99_Other`), `index/` (`cards/<code>.json` — the JSON cards,
the one source of truth about every document; `texts/<code>.md` with pages `=== page N ===`; `CATALOG.md` and
`sources_to_update.md` made from the cards; `intake_events.tsv` and the generated `journal.md`, `manifest.tsv`,
`ocr_quality.tsv`), `reports/`, and `.assistant_x/` (the base, the batches of the intake, the debug journals; the models are of
the PC, in `%USERPROFILE%\.assistant_x\models`). Keep your own copy of `library` and `index`: they are your data. The code folder is never written to.

## Requirements

- **System:** Windows 10 or 11 (x64), or Linux (x86_64; see "Linux and macOS" below).
- **Python 3.11** (the tested version; Setup.bat installs it on Windows when it is missing).
- **Disk:** about 6 GB for the models (≈ 4.5 GB) and the packages (≈ 1 GB), plus the room of your library.
- **Memory:** 8 GB of RAM recommended (the models and the intake of scans take several GB).
- **Video card:** optional. NVIDIA (CUDA), AMD or Intel with its own memory (DirectML) make the search by meaning
  faster; without one it runs on the processor.
- **An app with MCP:** Claude Desktop or Claude Code; Codex (CLI, IDE) or the ChatGPT desktop app; DeepSeek
  Harness; LM Studio with a model that can call tools; or any MCP client (stdio, or streamable HTTP with
  `assistant-x serve --http`). The library also works from the command line alone ("Without an app" below).
- **Where your text goes:** the search runs on your PC, but the pages the model reads to answer go to the provider of
  that model (Anthropic, OpenAI, DeepSeek). For confidential documents use a local model in LM Studio.

## Getting started (Windows)

1. [`Setup.bat`](Setup.bat) — finds or installs Python, installs the packages and the program, makes the workspace
   `Documents\Assistant X` with the profile `general`, connects the library to every app it finds (Claude Desktop,
   Claude Code, Codex, DeepSeek Harness, LM Studio: `assistant-x connect auto`), writes the skills and runs a
   self-test. From a medium (`assistant-x prepare-media --out E:\` on a PC with internet:
   [`Setup.bat`](Setup.bat), `app\`, `packages\`, `models\` with `MODELS.json`, `programs\`) everything of the program goes to
   `%USERPROFILE%\.assistant_x` — `app\<version>`, the environment `venv`, the models (checked against `MODELS.json`),
   the programs of the intake — and the workspace holds your data only; `Setup.bat --base E:\base\x.axbase` installs
   a base package right after. Another folder or the oil-and-gas profile: `Setup.bat --workspace "D:\My library"
   --profile oil-gas-ru`. From a folder of the code (a development checkout) it uses `.venv` beside it; then
   `assistant-x.bat download-models` downloads the models (≈ 4.5 GB) into `%USERPROFILE%\.assistant_x\models`;
   without them the search is by words. The PC folder `%USERPROFILE%\.assistant_x` (program, models, programs of the
   intake, locks, tokens) can be moved: set `AX_MACHINE_DIR` to another folder before [`Setup.bat`](Setup.bat) and keep it set.
2. [`scripts\install_intake.bat`](scripts/install_intake.bat) (`assistant-x setup-intake`) — LibreOffice, Tesseract (the languages of the packs: rus+eng by default), 7-Zip and DjVuLibre for the
   intake, without administrator rights.
3. Claude Desktop only: zip the folder `skill` of the workspace (it holds `SKILL.md`) and upload it in Claude →
   Settings → Capabilities → Skills, then restart Claude Desktop (the icon by the clock → Quit, then open it again).
   Codex, Claude Code and DeepSeek Harness got their skill from `connect`; in LM Studio any model learns the rules from
   the tool `library_guide`.
4. Put documents into `inbox` of the workspace and write to your assistant "AX: sort my documents" (or double-click
   [`intake.bat`](intake.bat) and let the assistant write the cards afterwards).
5. Ask, starting the message with "AX:" (or "connect to the library"). The answers cite `[code, p. printed, PDF N]`.
   `assistant-x.bat doctor` shows where everything is and what is missing, `assistant-x connect --check` whether every
   app reaches the library.

## Commands at a glance

`assistant-x <command>` ([`assistant-x.bat`](assistant-x.bat) on Windows; `assistant-x help` lists them all; `--workspace DIR` anywhere
chooses another workspace):

| Command | What it does |
| --- | --- |
| `init [FOLDER]`, `doctor` | make a workspace; show where everything is and what is missing |
| `intake run`, `intake status`, `intake check-meta`, `intake build`, `intake apply [--dry-run]` | the intake of `inbox` ([docs/INTAKE.md](docs/INTAKE.md)) |
| `remove CODE [--why TEXT] [--dry-run]` | a document of the library taken aside (`inbox\_to_delete`), its code reserved ([docs/INTAKE.md](docs/INTAKE.md)) |
| `build [--full]`, `embed [--cpu]` | the search base from the cards and texts; the meaning vectors of the new fragments |
| `search "question"` | a query from the command line |
| `base export`, `base inspect`, `base install`, `base update`, `base remove` | base packages: a library passed between people ([docs/PACKAGES.md](docs/PACKAGES.md)) |
| `connect APP\|auto`, `connect --list`, `connect --check`, `disconnect APP` | connect the apps of this PC ([docs/CLIENTS.md](docs/CLIENTS.md)) |
| `update` | connect every connected app again (after a new version: its entry and its skill) |
| `install --yes --json` | the installation without questions, a JSON summary at the end (for an agent) |
| `mcp [--tools reader] [--compact]`, `service` | the stdio bridge every app starts; the library service it talks to (both started by themselves) |
| `serve [--http]` | the MCP server in the process of the app (the fallback), or over HTTP for other clients |
| `setup-intake`, `download-models`, `skill` | the programs of the intake; the models; the skill |
| `report`, `query-log`, `debug-report` | the state of the library; what the apps asked; a report to pass on when something fails |

### Without an app

The intake runs from the command line too: `assistant-x intake run` makes the texts and `meta_draft.jsonl` in
`.assistant_x\work\<date>`; write `meta.jsonl` there by hand from the draft (one JSON line per file: [docs/INTAKE.md](docs/INTAKE.md),
"Cards"), check it with `assistant-x intake check-meta`, then `assistant-x intake build`, `assistant-x intake apply
--dry-run`, `assistant-x intake apply`, `assistant-x build` and `assistant-x embed`.

## Troubleshooting

- **"Found by words only"** or "N of M fragments have no meaning vectors": the embeddings are missing or still
  loading. Wait 10–20 s after the start of the library; otherwise run `assistant-x embed` (or ask the assistant for
  `intake_reindex`), and `assistant-x doctor` names a missing model (`assistant-x download-models`).
- **A base install, update or removal was interrupted** (the PC switched off): `assistant-x base install PACKAGE
  --resume` goes on, `--rollback` undoes it (the same for `update` and `remove`); the assistant reports it in its
  status.
- **An app does not see the library**: `assistant-x connect --check` makes the handshake and a search through the
  entry of every app and says which part fails; `assistant-x connect APP` writes the entry again.
- **The intake apply was interrupted**: `assistant-x intake apply --resume`.
- **"the machine lock is busy"**: another heavy task runs (`assistant-x lock` says which); wait, or add `--wait`.
- **Anything else**: `assistant-x debug-report` makes a file to pass on to whoever helps you (read it first: it
  names the folders and the last questions).

## Install with pip (any system)

Python 3.11 (the tested version; newer versions are not tested yet). In a folder of the code (a clone of the repository):

```
python -m venv .venv
.venv/bin/python -m pip install -c assistant_x/setup/constraints.txt -e ".[dense,intake]"
.venv/bin/assistant-x init
.venv/bin/assistant-x download-models
```

(on Windows `.venv\Scripts\…`). `constraints.txt` holds the versions of the release: the same packages as an
installation by Setup.bat. `[dense]` brings the search by meaning (torch; on Windows the torch of PyPI is CPU-only,
so for an NVIDIA card install the CUDA build from download.pytorch.org first — without it the card is not used and
`embed` asks about the processor), `[intake]` the intake of your own documents; without them the search goes by words.
`assistant-x init` makes the workspace (`--profile oil-gas-ru` for the oil and gas profile), `assistant-x doctor` shows
what is missing. Then `assistant-x connect auto` connects the apps (below).

### Linux and macOS

The program runs there too (the PC folder is `~/.cache/AssistantX`, or `AX_MACHINE_DIR`); Setup.bat
and the offline medium are for Windows only. The programs of the intake come from the system: `apt install
libreoffice tesseract-ocr tesseract-ocr-rus p7zip-full djvulibre-bin` (Debian, Ubuntu) or `brew install libreoffice
tesseract tesseract-lang p7zip djvulibre` (macOS); `assistant-x setup-intake --no-install` finds them and writes their
paths into `assistant_x.local.toml`. The tests (all but the slow ones) run in CI on Linux and Windows with Python 3.11
([`.github/workflows/tests.yml`](.github/workflows/tests.yml)); macOS and newer Python versions are not tested yet.

### Connect your apps

`assistant-x connect auto` (Setup.bat runs it) writes the entry of the library into every app it finds; `assistant-x
connect APP` one app (`claude_desktop`, `claude_code`, `codex`, `dsh`, `lmstudio`), `--full` gives an app every tool,
`assistant-x disconnect APP` takes it out. A copy of the settings file is kept beside it, the entries of others stay.
Every entry starts the same light bridge, `<python> -m assistant_x.server.bridge`, which talks to one library service
on 127.0.0.1: the models are loaded once for all the apps. By hand (any MCP client that starts a program):

```json
{
  "mcpServers": {
    "assistant-x": {
      "command": "C:\\Users\\you\\.assistant_x\\venv\\Scripts\\pythonw.exe",
      "args": ["-m", "assistant_x.server.bridge", "--tools", "reader"],
      "env": {"AX_WORKSPACE": "C:\\Users\\you\\Documents\\Assistant X", "PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1"}
    }
  }
}
```

**Add to LM Studio** without the command line: `assistant-x connect lmstudio --link` prints a link
(`lmstudio://add_mcp?...`, the entry of this PC); opened, LM Studio asks to add the server. The installer's summary
gives it too.

After a new version, `assistant-x update` writes the entries again; the skills of the apps are refreshed by the library
service at its first start (a skill edited by hand is kept), and Claude Desktop says once that its uploaded skill is
outdated.

`--tools reader` gives the 8 reading tools (search, pages, contents, page image, quote check, card, list, the guide);
without it every tool (the intake, base packages). `--compact` shortens the descriptions and the answers for small local
models. The apps and their files: [docs/CLIENTS.md](docs/CLIENTS.md). Clients that speak MCP over HTTP only:
`assistant-x serve --http [--port 8765]` (every request needs the bearer token of `mcp_http_token.txt` in the PC folder:
[SECURITY.md](SECURITY.md)).

## Tests

No models and no real library are needed (a mini library is built on the fly in a temporary workspace):

```
.venv\Scripts\python.exe -m pytest -q tests
```

The folders: `tests\base` (base packages: export, inspect, install, update, hostile packages), `tests\search` (the
search, the index, the server, the installer), `tests\intake` (the intake), `tests\corpus` (the recognition of a
corpus against its baseline) and the tests at the top of `tests` (cards, language packs, profiles, the medium, an
English library). [`scripts\check.ps1`](scripts/check.ps1) runs ruff and every test (`-Fast`: without the slow ones). The slow tests (the
whole intake with LibreOffice and OCR, the corpus) carry `@pytest.mark.slow`: `pytest -m slow tests`.
[`hooks/pre-commit`](hooks/pre-commit) runs ruff and `pytest -m "not slow" tests` before a commit (copy it to `.git/hooks/`).

## License

- **The code** is free software under the GNU AGPL-3.0-or-later ([`LICENSE`](LICENSE)). You may use it for yourself or inside
  your company, change it and pass it on. Whoever passes on copies, changed or not, gives the source code with them
  under the same license; whoever runs a changed version as a network service for other people offers those people
  its source code.
- **The data** in [`assistant_x/lang`](assistant_x/lang), [`assistant_x/profiles`](assistant_x/profiles) and [`assistant_x/schemas`](assistant_x/schemas) (language packs, domain
  profiles, the card schema and the shelves) is also available under CC-BY-4.0 ([`LICENSES/CC-BY-4.0.txt`](LICENSES/CC-BY-4.0.txt)): it may be
  used in any project, open or closed, with credit to "Assistant X by Alexandr Yalovoy" and a link to the license.
- **Your documents**, cards, texts and base are yours: the licenses of the program do not apply to them.
- **Third-party components** (PyMuPDF, Tesseract, LibreOffice, 7-Zip, the models) keep their own licenses: [`NOTICE`](NOTICE).
- **Contributions** are accepted under the Contributor License Agreement ([`CLA.md`](CLA.md), see [`CONTRIBUTING.md`](CONTRIBUTING.md)).

## Security

Report a vulnerability privately (GitHub → Security → Report a vulnerability), never with its details in a public issue
(without access to that form: an issue titled "private contact request", nothing more): [`SECURITY.md`](SECURITY.md) says how,
and what Assistant X guarantees about the documents and base packages it reads.

## Disclaimer

The author is not responsible for the documents and libraries that users load into the assistant. The rights to those
documents belong to their right holders; users are responsible for checking that they may load and use what they load.
This is in addition to the no-warranty clause of the GNU AGPL.

## AI-assisted development

Assistant X was developed with Claude Desktop and Claude Code using Claude Opus 5.5 and Claude Fable 5.1.
