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

**Said plainly.** A small local model is much weaker than Claude or ChatGPT: the quality of the assistant in LM
Studio is much lower and not guaranteed. It works as a narrow reference desk (quotes of the library with their
references); the engineering answer, a page shown with its quote marked and the intake of documents are for Claude
or ChatGPT (Codex).

## Install without a command line

The program comes as one archive (`AssistantX_<version>_setup.zip`), a base of documents, when you have one, as a
separate file (`<name>.axbase`).

1. Install LM Studio and download the model in it first (then the installer finds LM Studio).
2. Unpack the archive of the program into a folder. When you have a base, put its `.axbase` file into the same folder,
   beside `Setup.bat`.
3. Double-click `Setup.bat`. It installs the program and the models of the search, makes the library
   `Documents\Assistant X` and writes the library into the settings of LM Studio (`~/.lmstudio/mcp.json`) in the reference
   mode made for small local models: the one tool `library` with `library_guide`, `search_library`, `read_pages` and
   `export_references`, with short answers, the preset "Assistant X" (its rules as the system prompt), and a context
   of 32768 tokens as the default of every model of LM Studio. At its end it names the base beside it ("A base package was
   found: ... Install it? [Y/N]"): answer Y. With no base beside it, the Windows window "Open a file" asks for one:
   choose the `.axbase` file, or press Cancel to go on without a base.
4. Open LM Studio, start a chat with the model, pick the preset "Assistant X" in the settings of the chat and turn on
   the server `assistant-x` among its tools (integrations).
5. Integrations (the panel on the right of the chat): only `mcp/assistant-x` is on; the built-in `rag-v1` and
   `js-code-sandbox` stay off, or the model searches its own way instead of the library.
6. Check the context: the number under the field of the message reads `0/32768`. If it reads `0/8192`, the model was
   loaded with a smaller context: click the gear beside the name of the model at the top, set Context Length to 32768
   and reload the model (`Setup.bat` once more sets it as the default). With 8192 the rules and the quotes do not fit
   and the answers lose their references.

A base you get later: double-click `Install-Base.bat` in the folder of the program (the window "Open a file" asks for
the file, or it takes the one beside it); it shows what it installs, asks once and ends with "Base installed: N
documents". LM Studio installed after Assistant X: double-click `Setup.bat` once more, it connects the apps it finds.
A new version: double-click `Update.bat` (the latest release from GitHub; the library stays as it is).

## Ask

Start a question with `AX:` so that the model works with the library:

```
AX: what is the design pressure of a three-phase separator by GOST R 58367?
```

The model works as a reference desk: it calls `library_guide` once, searches with `search_library` and answers
with the lines of the library about the question, up to 15, each a verbatim quote with its reference
`[code, cl. N, table N, p. N, PDF N]`, then the sources; no analysis or calculation of its own (that is the work of
Claude or ChatGPT). Every quote line comes from the search itself, so it is the text of the page. "Copy the
references to D:\Project": the model calls `export_references`, which puts there the files of the documents cited and
one PDF of the pages cited with the quotes marked. Nothing else is written: the intake of new documents and the base
packages are done with `Setup.bat`, `intake.bat` or an app with all the tools (Claude, Codex).

## A preset for small models

`connect lmstudio` (and so `Setup.bat`) writes the preset `Assistant X` beside the settings of LM Studio
(`~/.lmstudio/config-presets/Assistant X.preset.json`): the rules of the reference mode as the system prompt and
thinking off, so that the model answers instead of thinking at length. Choose it for the model in LM Studio; the
model works without it too, the rules reach it through `library_guide`.

## When something fails

```
assistant-x doctor
assistant-x connect --check lmstudio
```

`doctor` checks the program, the models and the library; `connect --check` starts the entry of LM Studio as LM Studio
does, lists the tools and searches once, and says which part fails and what to do. When the answer of the model is
"Library command failed…", run `scripts\debug_report.bat` and send the report it makes.
