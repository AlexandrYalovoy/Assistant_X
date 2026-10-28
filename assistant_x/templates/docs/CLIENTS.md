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
- **The tool sets**: `all` (every tool: the intake, base packages) or `reader` ({{reader_tools}}). `--compact`: one-sentence
  descriptions, 4 search results at most, answers cut at 6 000 characters with a note how to get the rest.
- **The rules for the model**: the instructions of the server at the handshake, the skill where the app has a skills
  folder, and the tool `library_guide` for every app (an app that passes no instructions, a chat without skills):
  "connect to the library" or the key "AX:" makes the model call it first.

{{apps_table}}

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

## Not possible

The web sites chatgpt.com and chat.deepseek.com cannot start a program on the PC, so they cannot reach the library.

## The tools ({{version}})

{{tools_table}}
