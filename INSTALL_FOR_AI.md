# Install Assistant X — instructions for an AI agent

<!-- Made by assistant-x gen-docs from assistant_x/templates/docs/INSTALL_FOR_AI.md: edit that file. -->

You are an agent (Codex, Claude Code, DeepSeek Harness or another one that runs commands) and the user asked you to
install or connect **Assistant X**: a local library of the user's documents (PDF, DOC/DOCX, PPTX, scans) with search by
words and by meaning, served to AI apps over MCP. Follow these steps in order. Run every command only after the user
agreed to it; say in one line what each one does. These instructions are of version 0.4; always install the
**latest release**: https://github.com/AlexandrYalovoy/Assistant_X/releases/latest.

## 1. Tell the user what will happen, and ask

- Downloads: the source of the release (≈ 5 MB), the Python packages (≈ 1 GB; ≈ 3.5 GB with the CUDA build of torch
  for an NVIDIA video card), the models of the search by meaning (≈ 4.5 GB, optional: without them the search is by
  words only).
- Folders: the program and the models in `%LOCALAPPDATA%\AssistantX` (Linux: `~/.cache/AssistantX`); the user's data in
  one workspace folder, `Documents\Assistant X` by default. Ask whether another folder is wanted, and the profile:
  `general` (any field, the default) or `oil-gas-ru` (a Russian oil-and-gas process engineer).
- Privacy: the library and its search stay on the PC; the pages the model reads to answer go to the provider of the
  model of the app (with a local model in LM Studio nothing leaves the PC).

## 2. Python 3.11

`py -3.11 -V` (Windows) or `python3.11 -V` (Linux). Missing: on Windows `winget install -e --id Python.Python.3.11`
(after the user's yes), on Linux the package of the system.

## 3. The latest release

Read the tag of the latest release (`vX.Y`) from https://github.com/AlexandrYalovoy/Assistant_X/releases/latest (or the GitHub API
`https://api.github.com/repos/AlexandrYalovoy/Assistant_X/releases/latest`, field `tag_name`). Download the source
`https://github.com/AlexandrYalovoy/Assistant_X/archive/refs/tags/<tag>.zip` and extract it to `%LOCALAPPDATA%\AssistantX\src\<tag>` (Linux:
`~/.cache/AssistantX/src/<tag>`): the program is installed from that folder and keeps using it, so do not put it into
Downloads or a temporary folder.

## 4. Install

In that folder:

```
py -3.11 -m assistant_x.setup.install --online --yes --json [--workspace "D:\My library"] [--profile oil-gas-ru]
```

(`python3.11` on Linux.) It makes the environment `%LOCALAPPDATA%\AssistantX\venv`, installs the packages, makes the
workspace, connects every app it finds and checks itself; it asks nothing (`--yes`). Its last line is one JSON object:
`ok`, `version`, `python`, `command` (the `assistant-x` program), `workspace`, `device`, `apps` (connected),
`problems`, `next`. Tell the user the `problems` in plain words. Run it again after a failure: what is done is not done
again. `--dry-run` shows what it would do.

## 5. The models (optional, ≈ 4.5 GB)

After the user's yes: `<command> download-models` (the `command` of the JSON). Without the models the search is by
words only.

## 6. Connect the apps and check

`<command> connect auto` connects every app found on this PC (`claude_desktop`, `claude_code`, `codex`, `dsh`, `lmstudio`); `<command> connect APP` one app. The
installer did it already; run it again when an app was installed later. Then `<command> connect --check`: the
handshake and a search through the entry of every app. Each app needs a restart (Claude Desktop: the icon by the clock
→ Quit), except DeepSeek Harness and LM Studio, which reload their settings. Claude Desktop also needs its skill
uploaded by the user: `<command> skill`, then zip the folder it names and upload it in Settings → Capabilities →
Skills.

## 7. A base package (when the user has one, an `.axbase` file)

`<command> base inspect FILE` shows what it holds and the questions; show them to the user. Only after their explicit
yes: `<command> base install FILE --confirm` (with `--keep own|package` when the inspect asked who keeps the codes).

## 8. Tell the user how to use it

- In any connected app: start a message with `AX:` or ask to "connect to the library"; the answers cite
  `[code, p. printed, PDF N]`.
- Their own documents: put them into the `inbox` folder of the workspace and ask "AX: sort my documents".
- Something fails: `<command> doctor`, `<command> connect --check`, `<command> debug-report`.

## What the tools are

| Tool | What it does | Set | Changes the library |
| --- | --- | --- | --- |
| `library_guide` | Call this first when the user asks to work with the library (connect to the library or the knowledge base, the key "AX:"): the rules of the answers (search, read, cite the code and the page, check quotes) and the shelves of this library. | reader | no |
| `search_library` | Find fragments of the library for a question (words + meaning). | reader | no |
| `read_pages` | Text of pages of a document or of its part (code E-00006-02; PDF page numbers), at most 15 pages at a time: exactly as the text of the library has it. | reader | no |
| `book_map` | Map of a document: the table of contents with PDF page ranges; with page — the part of the contents around that page and which tables, figures, formulas and appendices lie in its section. | reader | no |
| `page_image` | Image of a page of the original (PDF page number) to check figures, tables, formulas and charts. | reader | no |
| `verify_quote` | Check a quote before citing it word for word, or a number taken from a table: is the text on that PDF page of the document (or the page before or after it)? | reader | no |
| `document_info` | The card of a document: designation, title, authors, year, type and shelf, scope, summary, topics, keywords, terms, tables, references, other versions, page numbering. | reader | no |
| `list_documents` | List of the documents of the library with filters; text searches the titles, designations and topics. | reader | no |
| `intake_list` | What lies in inbox (the user's own documents to sort) and whether an intake is running now. | all | no |
| `intake_run` | Start the intake of inbox in the background: unpacking, DOC/DOCX to PDF, OCR of scans, texts, card drafts. | all | writes its own work files |
| `intake_status` | Progress of the intake, of the transfer into the library and of the base recalculation, and the next step, in a short answer. | all | no |
| `intake_card` | Card drafts of the processed files (T0001…): pages, OCR score, section, designation, title; with tids — also the headings and the start of the text. | all | no |
| `intake_save_meta` | Save lines of the meta.jsonl of the batch (cards, parts, duplicates, rejected) and check them. | all | writes its own work files |
| `intake_apply` | Build the cards and move the documents into the library. | all | yes, after the user's yes to a plan |
| `library_remove` | Take documents out of the library (a document that got in by mistake): nothing is deleted, the originals, the cards and the texts go to inbox\_to_delete\removed_<code>_<date>, the codes stay reserved and the base by words is rebuilt. | all | yes, after the user's yes to a plan |
| `intake_reindex` | Finish the search base for new documents. | all | writes its own work files |
| `base_export` | The library as a base package file (out: a path ending in .axbase). | all | writes its own work files |
| `base_inspect` | What installing a base package (an .axbase file or its unpacked folder) would do: problems, warnings, who keeps the codes, the documents the library has already, and the questions for the user. | all | no |
| `base_install` | Install a base package. | all | yes, after the user's yes to a plan |
| `base_update` | A new version of an installed base package. | all | yes, after the user's yes to a plan |
| `base_remove` | An installed base package out of the library: its documents go to inbox\_to_delete (never deleted), the user's own stay. | all | yes, after the user's yes to a plan |
| `base_status` | How far the check and the install of a base package are, the questions of the check, the report of the install. | all | no |
| `base_list` | The base packages installed in this library (version, date, documents) and the user's own documents. | all | no |

The reading tools (`library_guide`, `search_library`, `read_pages`, `book_map`, `page_image`, `verify_quote`, `document_info`, `list_documents`) are the set of DeepSeek Harness and LM Studio by default; every tool that
changes the library asks for the user's yes to a plan first.

## The commands

| Command | What it does |
| --- | --- |
| `init [FOLDER]` | make a workspace |
| `doctor` | where everything is and what is missing |
| `intake` | the intake of inbox: run, build, apply, status, ... |
| `build` | build the search base from index |
| `embed` | embeddings of the new fragments |
| `mcp` | the stdio bridge an app starts: it talks to the library service |
| `service` | the library service: one MCP server on 127.0.0.1 for every app |
| `serve` | the MCP server in the process of the app (stdio; --http) |
| `search` | a query from the command line |
| `check` | check the cards (the schema, the profile) and the texts |
| `report` | the state of the library |
| `eval` | the control questions of the workspace |
| `query-log` | what the apps asked and how long it took |
| `debug-report` | a report to pass on when something fails |
| `install` | the Python environment and the connection to the apps |
| `setup-intake` | LibreOffice, Tesseract, 7-Zip and DjVuLibre for the intake |
| `download-models` | the embedding and reranking models from HuggingFace |
| `prepare-media` | the packages of an offline installation (build PC) |
| `lock` | who holds the machine lock; a command under it |
| `skill` | write the skill of the profile of the workspace (SKILL.md) |
| `connect` | connect the apps of this PC: claude_desktop, claude_code, codex, dsh, lmstudio |
| `disconnect` | take the library out of the settings of an app |
| `update` | connect every connected app again, its skill refreshed |
| `gen-docs` | make INSTALL_FOR_AI.md, AGENTS.md, docs/CLIENTS.md, the plugin |
| `base` | base packages: export, inspect, install, update, remove |
| `remove` | take documents of the library aside (inbox\_to_delete), codes reserved |
