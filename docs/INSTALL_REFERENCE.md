English | [Русский](INSTALL_REFERENCE.ru.md)

# Install Assistant X — the reference for an agent

<!-- Made by assistant-x gen-docs from assistant_x/templates/docs/INSTALL_REFERENCE.md: edit that file. -->

The install itself is [INSTALL_FOR_AI.md](../INSTALL_FOR_AI.md): one command in the background and its status. This
page is for what goes beyond it (version 0.6): the steps one by one, the codes of the checks, the update, the
tools of the server. Read only the section you need.

## The steps one by one

Without `--background` the same command runs in the foreground and ends with one JSON object: `ok`, `version`,
`python`, `python_source`, `command` (the `assistant-x` program), `workspace`, `device`, `apps` (connected),
`doctor`, `problems`, `next`. `--dry-run` shows what it would do.

```
Setup.bat --online --yes --json [--base FILE] [--keep own|package] [--models] [--workspace DIR] [--machine-dir DIR] [--profile NAME]
```

Each step alone, with the `command` of the JSON:

- The models (≈ 4.5 GB): `<command> download-models`. Without them the search is by words only.
- The apps: `<command> connect auto` connects every app found on this PC (`claude_desktop`, `claude_code`, `codex`, `dsh`, `lmstudio`, `gemini`, `antigravity`, `cursor`, `cline`, `kimi`); `<command> connect APP` one
  app; `<command> connect --check` the handshake and a search through the entry of every app.
- A base package: `<command> base inspect FILE` shows what it holds and its questions; after the user's yes
  `<command> base install FILE --confirm` (`--keep own|package` when the inspect asked who keeps the codes;
  `--or-resume` continues an install that was interrupted; `--cpu` computes the fragments without a vector on the
  processor however many: without it up to 5000, about an hour, when there is no video card).
- A person without an agent double-clicks `Setup.bat` (it offers a `.axbase` beside it) or `Install-Base.bat` later.

## When something fails

Run `<command> doctor --json` and `<command> connect --check --json`. Each prints one JSON document; every failure in
it has a stable `code`, a `message` and a `fix`: the command to run (ask the user before any download or change of
their settings), then run both checks again. `ok: true` and every app `"ok": true` mean done. The codes:

| Code | What it means | Fix |
| --- | --- | --- |
| `workspace-missing` | The workspace of the library is not made yet. | assistant-x init "{workspace}" |
| `folder-missing` | A folder of the workspace is missing. | assistant-x init "{workspace}" |
| `base-missing` | The library has cards but no search base. | assistant-x build |
| `model-missing` | No embedding model: the search is by words only. | assistant-x download-models (about 4.5 GB: ask the user first) |
| `vectors-missing` | Fragments without meaning vectors are found by words only. | assistant-x embed |
| `older-folder` | An older folder of the PC (before 0.5.1, or the private copy of Claude Desktop from the Microsoft Store) may still be used by an app connected before. | assistant-x connect auto |
| `app-not-connected` | The app has no entry of Assistant X. | assistant-x connect {app} |
| `models-in-app-package` | The models of the PC lie in the folder of an app from the Microsoft Store: removing or resetting that app deletes them. | close the apps of the library for a minute (the library service then stops), then run any assistant-x command: it moves the models into the folder of the PC |
| `app-in-process` | The app starts a library server of its own (an entry made before 0.5): it holds the models and the video card apart from the shared service of the other apps. | assistant-x connect {app}, then restart the app |
| `app-check-failed` | The entry of the app does not answer the handshake, the tool list or a search. | assistant-x connect --check {app} --json; if it fails again: assistant-x debug-report |
| `search-words-only` | The search of the app answers by words only (no model or no vectors). | assistant-x doctor --json (it names the missing model or vectors) |
| `service-not-started` | The library service did not start. | read the end of the service log {log}; then assistant-x doctor --json |
| `service-light` | The library service searches on the processor without the reranker: another server of the library holds the video card, so the answers are less accurate. | close the apps of the library for a minute (the library service then stops) and open one again; if it stays: assistant-x doctor --json and assistant-x debug-report |
| `gpu-memory-low` | The video card has little free memory: the search models and a local language model slow each other down. | in assistant_x.toml under [search] set device = "cpu" (the library then leaves the video card to the local model), or load the local model with fewer parallel slots |
| `skill-outdated` | The skill uploaded to Claude Desktop is older than the program. | assistant-x skill; zip the folder {folder} and upload it in Claude (Settings, Capabilities, Skills) |
| `tools-hidden` | The app keeps the tools of the server behind its search of tools (Codex). | search the tools for "assistant-x library library_guide search_library"; the server has no resources |
| `sign-in-limits` | The plan or the sign-in of the app limits it: on the Free plan of ChatGPT, Codex runs in the desktop app only, and its sign-in may ask for a phone number. | use the ChatGPT desktop app, or connect another app: assistant-x connect auto |

## Update ("update my assistant" and a link to GitHub or GitFlic)

Ask the user first: the update downloads the wheel of the latest release (a few MB) and installs it beside the
version in use. Then run

```
<command> update --from https://github.com/OWNER/REPO --dry-run
<command> update --from https://github.com/OWNER/REPO
```

(or `https://gitflic.ru/project/OWNER/REPO`). It takes only the latest release with a tag, never a draft, a
pre-release or the last commit of a branch; it checks the wheel against the `SHA256SUMS` of the release and refuses
a release without it; it installs the program into a new environment `venv-<version>` of the machine folder beside
the old one, connects the apps again with the new python and runs `doctor --json` there. When a step fails it
connects the apps back to the old version and removes the new environment. The library, the workspace and its
settings are never touched. Tell the user to restart the apps; the old environment stays for a return.

## What the tools are

| Tool | What it does | Set | Changes the library |
| --- | --- | --- | --- |
| `library_guide` | Call this first when the user asks to work with the library (connect to the library or the knowledge base, the key "AX:"): the rules of the answers (search, read, cite the code and the page, check quotes) and the shelves of this library. | reader | no |
| `search_library` | Find fragments of the library for a question (words + meaning); every fact taken from them is cited as its "Cite:" line shows. | reader | no |
| `read_pages` | Text of pages of a document or of its part (code E-00006-02; PDF page numbers), at most 15 pages at a time: exactly as the text of the library has it, its "Cite:" references on top. | reader | no |
| `book_map` | Map of a document: the table of contents with PDF page ranges; with page — the part of the contents around that page and which tables, figures, formulas and appendices lie in its section. | reader | no |
| `page_image` | Image of a page of the original (PDF page number) to check figures, tables, formulas and charts, or to show the user the page of a reference. | reader | no |
| `export_references` | Copy the files of the documents cited into a folder of the user and make there one PDF of the pages cited, a page a sheet, each with its reference and title on top and its quote marked in yellow. | reader | no: writes copies into a folder the user names |
| `verify_quote` | Check a quote before citing it word for word, or a number taken from a table: is the text on that PDF page of the document (or the page before or after it)? | reader | no |
| `document_info` | The card of a document: designation, title, authors, year, type and shelf, scope, summary, topics, keywords, terms, tables, references, other versions, page numbering. | reader | no |
| `list_documents` | List of the documents of the library with filters; text searches the titles, designations and topics. | reader | no |
| `intake_list` | What lies in inbox (the user's own documents to sort) and whether an intake is running now. | all | no |
| `intake_run` | Start the intake of inbox in the background: unpacking, DOC/DOCX to PDF, OCR of scans, texts, card drafts. | all | writes its own work files |
| `intake_status` | Progress of the intake, of the transfer into the library and of the base recalculation, and the next step, in a short answer. | all | no |
| `intake_card` | Card drafts of the processed files (T0001…): pages, OCR score, section, designation, title; with tids — also the headings and the start of the text. | all | no |
| `intake_save_meta` | Save lines of the meta.jsonl of the batch (cards, parts, duplicates, rejected) and check them. | all | writes its own work files |
| `intake_apply` | Build the cards and move the documents into the library. | all | yes, after the user's yes to a plan |
| `library_hierarchy` | The hierarchy of the documents the answers follow (which kind rules over which; a higher level wins a conflict): without levels, the levels in force and where they come from. | all | writes its own work files |
| `library_remove` | Take documents out of the library (a document that got in by mistake): nothing is deleted, the originals, the cards and the texts go to inbox\_to_delete\removed_<code>_<date>, the codes stay reserved and the base by words is rebuilt. | all | yes, after the user's yes to a plan |
| `intake_reindex` | Finish the search base for new documents. | all | writes its own work files |
| `library` | Every command of the library in one tool: action is the name of a command as the guide names it (library_guide, search_library, read_pages, book_map, page_image, verify_quote, document_info, list_documents, export_references, library_hierarchy, the intake_* and base_* commands, library_remove), args its arguments by name, as in library(action="search_library", args={"query": "gas velocity in a field pipeline"}). | one | as the command it carries |
| `base_export` | The library as a base package file (out: a path ending in .axbase). | all | writes its own work files |
| `base_inspect` | What installing a base package (an .axbase file or its unpacked folder) would do: problems, warnings, who keeps the codes, the documents the library has already, and the questions for the user. | all | no |
| `base_install` | Install a base package. | all | yes, after the user's yes to a plan |
| `base_update` | A new version of an installed base package. | all | yes, after the user's yes to a plan |
| `base_remove` | An installed base package out of the library: its documents go to inbox\_to_delete (never deleted), the user's own stay. | all | yes, after the user's yes to a plan |
| `base_status` | How far the check and the install of a base package are, the questions of the check, the report of the install. | all | no |
| `base_list` | The base packages installed in this library (version, date, documents) and the user's own documents. | all | no |

Every app gets the one tool `library` by default: it carries every command of the table by its name and
arguments (`library(action="search_library", args={"query": "..."})`), so the app asks once or keeps one rule to
allow it; LM Studio gets the commands of the reference mode. `--full` gives every tool apart, `--reader` the reading
tools apart (`library_guide`, `search_library`, `read_pages`, `book_map`, `page_image`, `verify_quote`, `document_info`, `list_documents`, `export_references`). Every command that changes the library asks for the user's yes to a plan first.

## The commands

| Command | What it does |
| --- | --- |
| `init [FOLDER]` | make a workspace |
| `doctor [--json]` | where everything is and what is missing (`--json`: codes and fixes) |
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
| `status` | the state of an installation running in the background (--json: one line) |
| `setup-intake` | LibreOffice, Tesseract, 7-Zip and DjVuLibre for the intake |
| `download-models` | the embedding and reranking models from HuggingFace |
| `prepare-media` | the packages of an offline installation (build PC) |
| `lock` | who holds the machine lock; a command under it |
| `skill` | write the skill of the profile of the workspace (SKILL.md) |
| `connect` | connect the apps of this PC: claude_desktop, claude_code, codex, dsh, lmstudio, gemini, antigravity, cursor, cline, kimi |
| `disconnect` | take the library out of the settings of an app |
| `update` | connect every connected app again, its skill refreshed; --from URL: a newer release |
| `gen-docs` | make INSTALL_FOR_AI.md, AGENTS.md, docs/CLIENTS.md, the plugin |
| `base` | base packages: export, inspect, install, update, remove |
| `remove` | take documents of the library aside (inbox\_to_delete), codes reserved |
| `key-norms` | the key norms of the design topics: searched, verified, written |
