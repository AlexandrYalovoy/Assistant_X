English | [Русский](LMSTUDIO.ru.md)

# Assistant X with a local model in LM Studio

A model in LM Studio runs on your PC: the pages it reads to answer never leave it. It cannot install anything
itself, so the installer of Assistant X does the installation and connects LM Studio; the model only uses the
library: it searches, reads the pages and cites the document and the page.

## What you need

- Windows 10 or 11, the medium of Assistant X (or its release from GitHub or GitFlic).
- [LM Studio](https://lmstudio.ai) with a model that can call tools, for example a Qwen3 model of 8 billion
  parameters or more; the larger the model, the better it keeps to the rules of the library.
- Memory for the model: about 8 GB of RAM or video memory for a model of 8 billion parameters in 4 bits, more for a
  larger one, besides the memory of the search of the library.

## Install without a command line

The program comes as one archive (`AssistantX_<version>_setup.zip`), a base of documents, when you have one, as a
separate file (`<name>.axbase`).

1. Install LM Studio and download the model in it first (then the installer finds LM Studio).
2. Unpack the archive of the program into a folder. When you have a base, put its `.axbase` file into the same folder,
   beside `Setup.bat`.
3. Double-click `Setup.bat`. It installs the program and the models of the search, makes the library
   `Documents\Assistant X` and writes the library into the settings of LM Studio (`~/.lmstudio/mcp.json`): the 8 reading
   tools with short answers, made for small local models. At its end it names the base beside it ("A base package was
   found: ... Install it? [Y/N]"): answer Y. With no base beside it, the Windows window "Open a file" asks for one:
   choose the `.axbase` file, or press Cancel to go on without a base.
4. Open LM Studio, start a chat with the model and turn on the server `assistant-x` among its tools (integrations).

A base you get later: double-click `Install-Base.bat` in the folder of the program (the window "Open a file" asks for
the file, or it takes the one beside it); it shows what it installs, asks once and ends with "Base installed: N
documents". LM Studio installed after Assistant X: double-click `Setup.bat` once more, it connects the apps it finds.
A new version: double-click `Update.bat` (the latest release from GitHub; the library stays as it is).

## Ask

Start a question with `AX:` so that the model works with the library:

```
AX: what is the design pressure of a three-phase separator by GOST R 58367?
```

The model calls `library_guide` once (the rules of the answers and the shelves of the library), searches with
`search_library`, reads the pages it needs with `read_pages` and answers citing `[code, p. printed, PDF N]`. Before a
verbatim quote or a number of a table it checks it with `verify_quote`; ask "check the quote" when in doubt. The
library of LM Studio only reads: the intake of new documents and the base packages are done with `Setup.bat`,
`intake.bat` or an app with all the tools (Claude, Codex).

## A preset for small models

A small model keeps the rules better with them in its system prompt:

```
assistant-x skill --app guide
```

writes `system-prompt.md` into `Documents\Assistant X\skill`. In LM Studio make a preset of the model and paste the
text into its system prompt.

## When something fails

```
assistant-x doctor
assistant-x connect --check lmstudio
```

`doctor` checks the program, the models and the library; `connect --check` starts the entry of LM Studio as LM Studio
does, lists the tools and searches once, and says which part fails and what to do. When the answer of the model is
"Library command failed…", run `scripts\debug_report.bat` and send the report it makes.
