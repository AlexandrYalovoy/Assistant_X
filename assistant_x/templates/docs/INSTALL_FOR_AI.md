# Install Assistant X — instructions for an AI agent

<!-- Made by assistant-x gen-docs from assistant_x/templates/docs/INSTALL_FOR_AI.md: edit that file. -->

You are an agent (Codex, Claude Code, DeepSeek Harness or another one that runs commands) and the user asked you to
install or connect **Assistant X**: a local library of the user's documents (PDF, DOC/DOCX, PPTX, scans) with search by
words and by meaning, served to AI apps over MCP. Follow these steps in order. Run every command only after the user
agreed to it; say in one line what each one does. These instructions are of version {{version}}; always install the
**latest release**: {{latest}}.

## 1. Tell the user what will happen, and ask

- Downloads: the source of the release (≈ 5 MB), the Python packages (≈ 1 GB; ≈ 3.5 GB with the CUDA build of torch
  for an NVIDIA video card), the models of the search by meaning (≈ 4.5 GB, optional: without them the search is by
  words only).
- Folders: the program and the models in `%USERPROFILE%\.assistant_x` (Linux: `~/.cache/AssistantX`; an install before
  0.5.1 in `%LOCALAPPDATA%\AssistantX` is taken over by itself); the user's data in one workspace folder,
  `Documents\Assistant X` by default. Ask whether another folder is wanted, and the profile:
  `general` (any field, the default) or `oil-gas-ru` (a Russian oil-and-gas process engineer).
- Privacy: the library and its search stay on the PC; the pages the model reads to answer go to the provider of the
  model of the app (with a local model in LM Studio nothing leaves the PC).

## 2. Python 3.11

`py -3.11 -V` (Windows) or `python3.11 -V` (Linux). Missing: on Windows `winget install -e --id Python.Python.3.11`
(after the user's yes), on Linux the package of the system.

## 3. The latest release

Read the tag of the latest release (`vX.Y`) from {{latest}} (or the GitHub API
`https://api.github.com/repos/AlexandrYalovoy/Assistant_X/releases/latest`, field `tag_name`). Download the source
`{{repo}}/archive/refs/tags/<tag>.zip` and extract it to `%USERPROFILE%\.assistant_x\src\<tag>` (Linux:
`~/.cache/AssistantX/src/<tag>`): the program is installed from that folder and keeps using it, so do not put it into
Downloads or a temporary folder.

## 4. Install

In that folder:

```
py -3.11 -m assistant_x.setup.install --online --yes --json [--workspace "D:\My library"] [--profile oil-gas-ru]
```

(`python3.11` on Linux.) It makes the environment `%USERPROFILE%\.assistant_x\venv`, installs the packages, makes the
workspace, connects every app it finds and checks itself; it asks nothing (`--yes`). Its last line is one JSON object:
`ok`, `version`, `python`, `command` (the `assistant-x` program), `workspace`, `device`, `apps` (connected),
`problems`, `next`. Tell the user the `problems` in plain words. Run it again after a failure: what is done is not done
again. `--dry-run` shows what it would do.

## 5. The models (optional, ≈ 4.5 GB)

After the user's yes: `<command> download-models` (the `command` of the JSON). Without the models the search is by
words only.

## 6. Connect the apps and check

`<command> connect auto` connects every app found on this PC ({{apps}}); `<command> connect APP` one app. The
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

## 9. When something fails: repair it yourself

Run `<command> doctor --json` and `<command> connect --check --json`. Each prints one JSON document; every failure in
it has a stable `code`, a `message` and a `fix`: the command to run (ask the user before any download or change of
their settings), then run both checks again. `ok: true` and every app `"ok": true` mean done. The codes:

{{troubleshooting}}

## What the tools are

{{tools_table}}

The reading tools ({{reader_tools}}) are the set of DeepSeek Harness and LM Studio by default; every tool that
changes the library asks for the user's yes to a plan first.

## The commands

{{commands_table}}
