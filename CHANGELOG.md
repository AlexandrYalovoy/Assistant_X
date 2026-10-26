# Changes of Assistant X

New entries go under the version being prepared. The version number is `assistant_x.__version__` (pyproject.toml reads it).

## 0.1 — 2026-10-26 (the first open prototype)

The first public version. What it does, by area; the details are in [README.md](README.md) and docs/.

### Your library

- One workspace folder (`Documents\Assistant X` by default; `assistant-x init`, `assistant-x doctor`): `inbox`,
  `library` (the originals on seven shelves N L P E R J X), `index` (a JSON card per document — the one source of
  truth — and its text by pages), the search base in `.assistant_x`. The models and programs are of the PC
  (`%LOCALAPPDATA%\AssistantX`, `AX_MACHINE_DIR` moves it).
- Codes of five digits (`N-00012`, parts `E-00006-02`) that never come back once given.
- Language packs (`lang/ru`, `lang/en`) and domain profiles (`general`, `oil-gas-ru`) as data: the code names no
  language and no field.

### Intake of your own documents

- PDF (text and scans), DOC/DOCX/PPTX, spreadsheets, DjVu, e-books, texts, letters with their attachments, archives
  (unpacked with limits on names, size and depth); OCR by Tesseract with a recognition score per page; hidden text,
  personal papers and duplicates found; new editions of a document recognised and asked about.
- Claude writes the cards from drafts ("AX: sort my documents"); one check of `meta.jsonl` for `intake_save_meta`
  and the build; `intake apply` is a transaction that can be resumed, and nothing is ever deleted (the rest goes to
  `inbox\_to_delete`, `_duplicates`, `_rejected`). It also runs without Claude, from the command line.
- A load regulator keeps the PC usable; one heavy task per PC (the machine lock).

### Search and answers

- Words (SQLite FTS5 with stemming, synonyms, exact designations) + meaning (bge-m3, FAISS) + reranking
  (bge-reranker-v2-m3) on NVIDIA (CUDA), AMD/Intel (DirectML) or the processor; a vector cache recomputes nothing
  that did not change.
- The MCP server `assistant-x` for Claude Desktop, Claude Code and other clients (stdio, or HTTP on 127.0.0.1 with a
  bearer token): search with filters and scope, page text, page images, book maps, document cards, `verify_quote` for
  verbatim quotes and table numbers, citations `[code, p. printed, PDF N]`, source-quality warnings.
- The answer says when it is by words only and why, including how many fragments have no meaning vectors yet.
- The cost of a question is profiled in [docs/SEARCH.md](docs/SEARCH.md) (about 0.9 s on a video card with the reranker, the memory
  flat).

### Base packages

- A library passed between people as one `.axbase` file: `base export`, `inspect`, `install`, `update`, `remove`, from
  the command line or the chat; duplicates merged by rule, the user chooses who keeps colliding codes; every change a
  transaction with resume and rollback (a rollback removes only what it made).
- A package is untrusted data: its manifest, entry names, checksums, cards, card paths and vectors are checked before
  anything changes; a damaged file is refused by name.

### Safety

- Every change of the library from the chat takes two steps: the plan, then a confirmation with its token, bound to
  the action, the target, the workspace and what the plan was made of; where the client supports MCP elicitation the
  server asks the user itself. The server instructions say that document text is data, and text addressed to an AI
  assistant is marked "Suspect text". [SECURITY.md](SECURITY.md) says what is guaranteed and what is not.
- Background jobs (intake, recalculation, base changes) run detached from the server, so closing Claude does not cut
  them; their status says running, finished, failed or stopped, and an interrupted change is reported.

### Installation

- [`Setup.bat`](Setup.bat) on Windows, from the internet or from an offline medium (`assistant-x prepare-media`): Python, the
  packages at the versions of `setup/constraints.txt` (hashed on a medium), the models (checked), the programs of the
  intake with their source archives, the connection to Claude, the skill, a self-test. `pip install` on any system.
- A debug report and a query log to pass on, naming the PC by a hash only.

### For contributors

- ruff (check and format), the tests ([`scripts\check.ps1`](scripts/check.ps1)), a golden corpus with its baseline, a recognition snapshot;
  CI on Linux and Windows with Python 3.11, actions pinned by commit (the first run comes with the first push).
- License GNU AGPL-3.0-or-later; the data folders also CC-BY-4.0; contributions under the CLA.
