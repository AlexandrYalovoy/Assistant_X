English | [Русский](INSTALL_REFERENCE.ru.md)

# Install Assistant X — the reference for an agent

<!-- Made by assistant-x gen-docs from assistant_x/templates/docs/INSTALL_REFERENCE.md: edit that file. -->

The install itself is [INSTALL_FOR_AI.md](../INSTALL_FOR_AI.md): one command in the background and its status. This
page is for what goes beyond it (version {{version}}): the steps one by one, the codes of the checks, the update, the
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
- The apps: `<command> connect auto` connects every app found on this PC ({{apps}}); `<command> connect APP` one
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

{{troubleshooting}}

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

{{tools_table}}

Every app gets the one tool `library` by default: it carries every command of the table by its name and
arguments (`library(action="search_library", args={"query": "..."})`), so the app asks once or keeps one rule to
allow it; LM Studio gets the commands of the reference mode. `--full` gives every tool apart, `--reader` the reading
tools apart ({{reader_tools}}). Every command that changes the library asks for the user's yes to a plan first.

## The commands

{{commands_table}}
