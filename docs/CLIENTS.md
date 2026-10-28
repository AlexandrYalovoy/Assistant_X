# The apps of Assistant X

<!-- Made by assistant-x gen-docs from assistant_x/templates/docs/CLIENTS.md: edit that file. -->

Assistant X serves its library to any app that speaks MCP. `assistant-x connect APP|auto` writes the entry; every
entry starts the same stdio bridge, which talks to one library service of the workspace on 127.0.0.1.

```
app ──stdio──> assistant-x mcp (the bridge) ──HTTP, token──> assistant-x service ──> the library, the models (once)
app ──stdio──> assistant-x mcp ─────────────────────────────┘
```

- **The bridge** (`python -m assistant_x.server.bridge`): imports nothing heavy, answers the handshake at once, starts
  the service hidden when it is not running (and again when it is gone), reads the token of the machine folder itself:
  the settings of the apps hold no secret.
- **The service** (`assistant-x service`): one per workspace, the models loaded once (on the video card when there is
  one), every request with the bearer token, only the Host and Origin of 127.0.0.1 and localhost; it exits after 30
  minutes without a request, so a local model gets the video memory back.
- **The tool sets**: `all` (every tool: the intake, base packages) or `reader` (`library_guide`, `search_library`, `read_pages`, `book_map`, `page_image`, `verify_quote`, `document_info`, `list_documents`). `--compact`: one-sentence
  descriptions, 4 search results at most, answers cut at 6 000 characters with a note how to get the rest.
- **The rules for the model**: the instructions of the server at the handshake, the skill where the app has a skills
  folder, and the tool `library_guide` for every app (an app that passes no instructions, a chat without skills):
  "connect to the library" or the key "AX:" makes the model call it first.

| App | `connect` name | Settings written | Tool set | Skill |
| --- | --- | --- | --- | --- |
| Claude Desktop | `claude_desktop` | `%APPDATA%\Claude\claude_desktop_config.json` (and the Microsoft Store folder), `mcpServers` | all | a zip the user uploads (`assistant-x skill`) |
| Claude Code | `claude_code` | `claude mcp add-json -s user` (`~/.claude.json`) | all | `~/.claude/skills/assistant-x` |
| Codex and the ChatGPT desktop app | `codex` | `~/.codex/config.toml` (`CODEX_HOME`), `[mcp_servers.assistant-x]`, `startup_timeout_sec = 60` | all | `~/.agents/skills/assistant-x` |
| DeepSeek Harness | `dsh` | `~/.dsh/cordis.patch.yml` (`DSH_HOME`): an `insert` patch of `@deepseek-ai/dsh-mcp-client`, `serverName: assistant-x` | reader | `~/.dsh/skills/assistant-x` |
| LM Studio | `lmstudio` | `~/.lmstudio/mcp.json`, `mcpServers` | reader, compact | none: `library_guide`; `assistant-x skill --app guide` writes a system prompt for a preset |

`--full` gives an app every tool without the compact answers, `--reader` only the reading tools, `--compact` the short
answers. A copy of a settings file is kept beside it before a change (`<name>.backup-<date>`, the newest three), the
entries and comments of others stay, a second `connect` changes nothing, and a file that cannot be read is left alone:
the command prints the entry to add by hand. `assistant-x disconnect APP` takes the entry and the skill out (a skill
edited by hand stays).

`assistant-x connect --list` shows the apps (found, connected, tool set); `assistant-x connect --check [APP]` starts
the entry of every connected app as the app does, makes the handshake, lists the tools and searches once.

## Where the text goes

The library and its search run on the PC. The pages a model reads to answer go to the maker of that model: Anthropic
for Claude, OpenAI for Codex and ChatGPT, DeepSeek for DeepSeek models; nothing leaves the PC with a local model in
LM Studio (or in DeepSeek Harness and Codex pointed at LM Studio).

## Codex and ChatGPT

The Codex CLI, its IDE extension and the ChatGPT desktop app read the same `~/.codex/config.toml`: `assistant-x connect
codex` serves all of them. On the Free plan of ChatGPT Codex runs in the desktop app only (the CLI and the IDE
extension need a paid plan), and its sign-in may ask for a phone number. Codex keeps the tools of a server behind its
search of tools: the instructions of the server and the skill tell the model to search for them. With a small local
model through LM Studio (`codex --oss`) Codex takes most of the context itself and some chat templates refuse its
system messages: in a test with a 9B model it never reached the library; the cloud models of the app do not have
these limits.

## Not possible

The web sites chatgpt.com and chat.deepseek.com cannot start a program on the PC, so they cannot reach the library.

## The tools (0.5.1)

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
