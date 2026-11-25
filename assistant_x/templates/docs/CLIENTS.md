English | [Русский](CLIENTS.ru.md)

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
- **The tool sets**: `one_reader` (one `library` schema, reading and export only, the short guide; the default of
  every cloud agent), `one` (the same schema with every command, explicitly selected for library changes), `all`
  (every tool apart) or `reader` ({{reader_tools}}). `--compact`: one-sentence
  descriptions, 4 search results at most, answers cut at 6 000 characters with a note how to get the rest.
- **The rules for the model**: the instructions of the server at the handshake, the skill where the app has a skills
  folder, and the tool `library_guide` for every app (an app that passes no instructions, a chat without skills):
  "connect to the library" or the key "AX:" makes the model call it first.

{{apps_table}}

The legacy `--full` (every tool apart) and `--reader` (the reading tools apart) remain. An explicit
`assistant-x connect APP --tools one_reader|one|reader|all` is kept by `assistant-x update`; without an explicit choice,
the current default applies. `--compact` gives short answers. A copy of a settings file is kept beside it before a change
(`<name>.backup-<date>`, the newest three), the entries and comments of others stay, a second `connect` changes nothing,
and a file that cannot be read is left alone: the command prints the entry to add by hand. `assistant-x disconnect APP`
takes the entry and the skill out (a skill edited by hand stays).

`assistant-x connect --list` shows the apps (found, connected, tool set); `assistant-x connect --check [APP]` starts
the entry of every connected app as the app does, makes the handshake, lists the tools and searches once.

## Where the text goes

The library and its search run on the PC. What the tools give a model goes to the maker of that model (Anthropic
for Claude, OpenAI for Codex and ChatGPT, DeepSeek for DeepSeek models, Google for Gemini CLI and Antigravity,
Moonshot AI for Kimi, the provider chosen in Cursor or Cline): the question, the search hits (fragments, quotes, codes
and titles), the pages it reads, cards, the list of documents, page images, and during the intake the drafts of the
cards with the start of the text of the new files. Nothing leaves the PC with a local model in LM Studio (or in
DeepSeek Harness and Codex pointed at LM Studio).

## Kimi Work

Kimi Work can install the program itself from a repository link: the agent follows
[`INSTALL_FOR_AI.md`](../INSTALL_FOR_AI.md), then creates or updates the personal-plugin source, validates it and
registers it through the official Kimi mechanism. The user opens **Personal** and clicks **＋**; no client restart is
needed. Updates edit only the source, bump its local version and register it again, after which the user clicks
**Update**. The installed copy is never edited directly. Personal paths and settings are never published.

The plugin uses one `library` tool: `one_reader` for ordinary reading, or full `one` in the plugin source for an
explicitly requested library change, with a plan and the user's confirmation. `assistant-x connect kimi` configures Kimi
CLI / Kimi Code; it does not install or update the Work plugin, which is a separate action.

On 25 November 2026, fast and deep answers in Kimi Work were live-tested on the real library. Kimi CLI / Kimi Code and
Kimi Chat have not been live-tested separately; they must not be called tested merely because Work works. When MCP is
unavailable but the agent can run a terminal command, one fallback `assistant-x context "question" --mode
fast|balanced|deep` is enough, without inspecting the source or writing a custom client. The modes and measurements:
[`COST.md`](COST.md).

## Codex and ChatGPT

The Codex CLI, its IDE extension and the ChatGPT desktop app read the same `~/.codex/config.toml`: `assistant-x connect
codex` serves all of them. On the Free plan of ChatGPT Codex runs in the desktop app only (the CLI and the IDE
extension need a paid plan), and its sign-in may ask for a phone number. Codex keeps the tools of a server behind its
search of tools: the instructions of the server and the skill tell the model to search for them. With a small local
model through LM Studio (`codex --oss`) Codex takes most of the context itself (16 000 tokens of a 16 384 context, 68 000
input tokens a turn at 32 768) and some chat templates refuse its system messages: Qwen3.5 in LM Studio answers
"System message must be at the beginning" (its template raises on a system message that is not the first one); in a
test with a 9B model, its template patched, Codex still never reached the library. The cloud models of the app do not
have these limits; LM Studio's own chat with the same model works (`assistant-x connect lmstudio`).

## When something does not work

`assistant-x doctor --json` and `assistant-x connect --check --json` name every known failure by a stable code with
the command that fixes it (the same table, core/problems.py):

{{troubleshooting}}

## Not possible

The web sites chatgpt.com and chat.deepseek.com cannot start a program on the PC, so they cannot reach the library.

## The tools ({{version}})

{{tools_table}}
