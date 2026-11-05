English | [Русский](INSTALL_FOR_AI.ru.md)

# Install Assistant X — instructions for an AI agent

<!-- Made by assistant-x gen-docs from assistant_x/templates/docs/INSTALL_FOR_AI.md: edit that file. -->

You are an agent (Codex, Claude Code, DeepSeek Harness or another one that runs commands) and the user asked you to
install or connect **Assistant X**: a local library of the user's documents with search by words and by meaning,
served to AI apps over MCP. These instructions are of version {{version}}; always install the **latest release**:
{{latest}}.

## Token budget: read this first

The program with a base package of tens of GB takes hours to install. Done by hand it took an agent 199 model calls
and its whole plan limit; done this way it takes 10–20:

- Run the **one command** of step 3. It installs everything in the background and returns at once.
- Poll the status with the command it printed, every `poll_s` seconds (5–10 minutes): wait in one shell command
  (`timeout /t 600 /nobreak >nul`, `sleep 600`), never in many short waits.
- Do **not** read the source code, the logs or other documents, and do not print long outputs: every command here
  prints one JSON line. Only on an error: the status with `--tail 20`.
- One message to the user per stage (when `stage` changes), not per poll.
- Do not repair by hand what the installer does (Python, paths, vectors): on a failure its `error.fix` says what to
  do, and the same command again continues where it stopped.

## 1. Ask the user once

One message, then wait for the yes:

- Downloads: the release (≈ 5 MB), the Python packages (≈ 1 GB; ≈ 3.5 GB with CUDA for an NVIDIA card), the models
  of the search by meaning (≈ 4.5 GB, `--models`; without them the search is by words only).
- Folders: the program and the models in `%USERPROFILE%\.assistant_x` (another disk: `--machine-dir D:\AssistantX`);
  the documents in `Documents\Assistant X` (another folder: `--workspace "D:\My library"`). The profile: `general` or
  `oil-gas-ru` (a Russian oil-and-gas process engineer, `--profile oil-gas-ru`).
- A base package (`.axbase`), when the user has one: it is checked whole, then installed (`--base FILE`); it needs
  about twice its size free on the disk of the documents. Its yes is the consent to the install.
- Privacy: the library stays on the PC; the pages the model reads to answer go to the provider of the app's model.

## 2. The latest release

Read the tag of the latest release (`vX.Y.Z`) from {{latest}} (or the GitHub API
`https://api.github.com/repos/AlexandrYalovoy/Assistant_X/releases/latest`, field `tag_name`). From the assets of that
release download `assistant_x-<version>-src.zip` and `SHA256SUMS.txt` (`{{repo}}/releases/download/<tag>/<file>`;
`<version>` is the tag without `v`) and check the archive before anything else: its SHA-256 (`Get-FileHash -Algorithm
SHA256 FILE` on Windows, `sha256sum FILE` on Linux) must be the one `SHA256SUMS.txt` names; when it differs, stop and
tell the user. Extract it to `%USERPROFILE%\.assistant_x\src\<tag>` (Linux: `~/.cache/AssistantX/src/<tag>`), not to
Downloads or a temporary folder: the program keeps using it.

## 3. The one command

In that folder (Windows):

```
Setup.bat --online --yes --json --background --models [--base "E:\base.axbase"] [--workspace "D:\My library"] [--machine-dir "D:\AssistantX"] [--profile oil-gas-ru]
```

On Linux: `python3.11 -m assistant_x.setup.install` with the same options. Setup.bat finds a Python 3.11 on the PC or
installs one for the user from python.org (no winget). The answer is one JSON line: `started`, `status` (the command
that polls), `poll_s`, `python_source`, `outlives_the_agent` (`false`: the installation ends with your session, keep
it open until the end). It runs: environment, packages, models, intake, connect (every app found), self-test, base
(check, install, the vectors on the video card or the processor), doctor.

## 4. Poll until the end

Run the `status` command of step 3 (after the install also `<command> status --json`). One line: `state`
(`running`, `done`, `failed`), `stage`, `percent`, `eta_min`, `poll_s`, `error` (`code`, `message`, `fix`). Running:
wait `poll_s` seconds and poll again. A worker that died (the PC restarted, a closed session) is started again by the
poll itself, `restarts` counts it. Failed: do what `error.fix` says, then run the command of step 3 again:

| `error.code` | What to do |
| --- | --- |
| `base_choice` | Ask the user who keeps the codes that collide: add `--keep package` or `--keep own`, run again |
| `network` | An antivirus that scans HTTPS may hold pypi.org, files.pythonhosted.org, download.pytorch.org, huggingface.co: ask the user to allow them, run again |
| `disk_full` | Ask the user to free space (or another disk: `--workspace`, `--machine-dir`), run again |
| `python` | Ask the user to install Python 3.11 from python.org (for the user), run again |
| `base_failed`, `stopped` | Run again: it continues; still failing: the status with `--tail 20`, tell the user the reason |
| `died`, `exception` | Run again from a terminal of the user that stays open; still failing: `<command> debug-report` |

## 5. When it is done

`state: done`: tell the user `problems` in plain words and do `next`. Each app needs a restart (Claude Desktop: the
icon by the clock → Quit; DeepSeek Harness and LM Studio reload by themselves). Claude Desktop also needs the skill:
`<command> skill`, zip the folder it names, upload it in Settings → Capabilities → Skills. Then tell the user:

- In any connected app: start a message with `AX:` or ask to "connect to the library" (the app calls `library_guide`);
  the answers cite `[code, cl. N, table N, p. N, PDF N]`.
- Their own documents: into the `inbox` folder of the workspace, then "AX: sort my documents".
- Something fails later: `<command> doctor --json`, `<command> connect --check --json` (each item has its `fix`).

The step-by-step commands, the codes of doctor, the update and the tools of the server:
[docs/INSTALL_REFERENCE.md](docs/INSTALL_REFERENCE.md).
