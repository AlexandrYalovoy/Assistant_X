# Changes of Assistant X

New entries go under the version being prepared. The version number is `assistant_x.__version__` (pyproject.toml reads it).

## Unreleased (0.3)

What the second real intake run showed, fixed.

- The visible text layer of a scan is kept: a page with a legible layer is read once and its recognition dropped when
  the layer has its words (only a caption or a stamp the layer lacks is added); a page whose every phrase appears twice
  gets the flag `doubled` (listed by the quality report, weighed less by the search), a line repeated word for word is
  dropped, and `intake redo` replaces a text that is no longer doubled.
- The picture on a text page is read once (sparse text, no orientation check, no retries) and kept only when it adds
  8 words the layer lacks; the retries stay for scans; a page with a picture costs a second more in the order of the
  work; the OCR seconds of a file show in the status.
- A file that failed, was rejected or sent to delete is no duplicate when it comes again: only the events of a file
  in the library (accepted, or a duplicate of a code) count, and a duplicate always names a code.
- The load regulator: a worker is one core, so a free PC runs a worker on every CPU past the reserve that the memory
  allows (`workers` 16 at most by default, `cpu_share_idle` 0.8); the disk slows the work only at the computer and only
  by its latency (`% Idle Time` and `Avg. Disk sec/Transfer` instead of `% Disk Time`); `balance.log` gets a line of
  the load every minute and `summary.md` the mean load; the time left goes by the cost of the files.
- Drafts of standards: designations with an em dash, the national designation before a foreign one on the title page,
  the adopted foreign standards in the new card field `adopts`, the year from the file name of the same number, the
  English title printed on the title page, an amendment drafted with `amends` (never a version of its base), contents
  without repeated entries and service lines; the headers of an exported legal text are no title.
- `intake_apply(confirm=True)` starts the transfer as one background job (build, apply, the base recalculation) and
  answers at once; `intake_status` shows its stage. `intake_reindex()` leaves a base that is up to date alone and says
  when it was last recalculated (`reindex_last.json`); `force=True` runs it anyway.
- A short `intake_status` (3 000 characters at most; `full=True` for the summary and the quality), jobs that ended before
  the batch left out, the harmless warnings of the model libraries out of the job tails, no fixed "Next" line in
  `summary.md`, a progress line every 5 minutes when nothing changes, `PYTHONUTF8=1` in the Claude Desktop entry.
- "Low closeness" also when half the words of a question are in none of the best results, with those words; the
  closeness threshold calibrated on the journal of the PC; the second server of one window no longer blames "another
  window".
- A table cell whose spaces OCR lost gets them back: a run of 17 letters and more splits into the cheapest sequence
  of known words (a linking vowel of a compound, `compound_links` of the packs, is no word; a word broken at a line
  end of the cell is joined first; a split into many three-letter pieces is refused).
- `assistant-x remove CODE [--why] [--dry-run]` and the MCP tool `library_remove` (a plan with a token, then the
  confirm): a document of the library taken aside into `inbox\_to_delete`, journaled, its code reserved, its fragments
  out of the base; a file removed so is no duplicate when it comes back.

## Unreleased (0.2)

What the first real intake run (42 files, 8 644 pages) showed, fixed.

### Intake from Claude

- No console window: every program is started through `core/proc.py` (CREATE_NO_WINDOW where a window could appear, a
  hidden console for a detached job); a test fails on a direct `subprocess` call elsewhere.
- The status in words: files done, in work with their stage and pages, waiting, errors, the time left, and the next
  step; the output of the parsers goes to the log of each file, not to the log of the batch. The base recalculation
  shows its step and progress.
- A stage that fails logs its traceback (the file's log and `failures.log`) and says why in words; a memory failure
  (a tool past its cap, a failed MuPDF allocation) is tried once more with the double cap. LibreOffice runs without
  `PYTHON*` variables.
- The card drafts appear as soon as each file is done; the document's own designation only from its title pages (a
  book citing a standard is no standard), no "OST" inside "GOST", titles not taken from a page of authors, slide decks
  and spreadsheets by their format, contents without picture names and service lines (or none when noisy), files and
  parts in natural order, a folder of chapters drafted as one book with an optional `order` of its parts.
- `intake_save_meta(path=…, check_only=…)`: a file of lines inside the batch folder, or a check without writing.
- `[intake] auto_apply = true` in `assistant_x.local.toml`: a batch with a clean check is applied at once, unless it
  replaces, links or duplicates a document of the library, rejects a file or holds hidden text addressed to an AI.
  The confirmation token lives 30 minutes.

### Throughput

- The conversions go cheapest first; heavy files run side by side while their memory caps fit into the free memory,
  with a worker kept for light ones; the OCR of a long scan is cut into page ranges read on every worker
  (`[intake] ocr_shards = "off"` turns it off).

### Text quality

- A seed vocabulary from open Hunspell dictionaries (Russian, English) scores the first batch of a new library as a
  later one; glued and repeated tokens are errors; a page of garbage gets the flag `garbled` (weighed less by the
  search, listed by the quality report); pages OCR read at a reduced resolution get `dpi_reduced`.
- A text layer shifted off the page box is reported once per page, not as hidden text.
- Small caps read in both cases and the lines of narrow table cells are joined back (Russian).

### Answers

- At most two cards in an answer ([search] max_cards), shown after the pages as "Documents on the topic".
- "Low closeness …" when the library may not cover a question; the wording of the second Claude window is honest.
- `[search] cpu_int8` is off by default; a hint of a domain profile in `intake_list`.

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
