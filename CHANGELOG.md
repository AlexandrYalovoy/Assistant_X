# Changes of Assistant X

New entries go under the version being prepared. The version number is `assistant_x.__version__` (pyproject.toml reads it).

## 0.5.1 — unreleased

Fixes and hardening after 0.5.

- The bridge passes the events of a tool call to the app as they come: a question of the library to the user inside a
  call (MCP elicitation, the confirmation of a change in Claude Code) reaches the app, and its answer the service; the
  question waits at most 10 minutes. A call that reached the service but got no answer in time is no longer sent a
  second time.
- base_export from the chat: a package file outside the workspace, or one with the personal documents, is written only
  with the token of its plan and the user's yes (a text in a document can no longer make the assistant copy the library
  into a synced folder); into the workspace without the personal documents it starts at once as before.
- verify_quote takes a quote cut with an ellipsis (… or ...): its parts are found in order on one page, each word for
  word, and the answer says to keep the cuts marked; a quote over 2000 characters is refused (to be checked in parts)
  instead of holding the service.
- search_library names the next calls before the fragments: read_pages of the best page before citing it, verify_quote
  before a verbatim quote or a number (in the live test a 9B local model cited 2 of 8 pages from the hits without
  reading them).

## 0.5 — 2026-10-28

Connected by one sentence, and up to date by itself.

- "Install Assistant X for me" to an agent (Codex, Claude Code, DeepSeek Harness): `INSTALL_FOR_AI.md` says what to
  do — the latest release, `assistant-x install --yes --json` (no question, one JSON summary with the downloads, the
  connected apps, the problems and the next steps), the models after the user's yes, `connect auto`, `connect --check`.
- The plugin of Codex and the ChatGPT desktop app and of Claude Code in this repository, with an onboarding skill:
  `codex plugin marketplace add AlexandrYalovoy/Assistant_X`, `/plugin marketplace add AlexandrYalovoy/Assistant_X`.
- `assistant-x gen-docs` makes `INSTALL_FOR_AI.md`, the agents section of `AGENTS.md`, `docs/CLIENTS.md` and the plugin
  from the registry of the apps, the tools, the commands and the version; a test fails when they are out of date and
  the pre-commit hook makes them again.
- Up to date by itself: the connections are recorded (`connections.json` of the machine folder), `assistant-x update`
  writes them again, the library service refreshes the outdated skills of the apps at its start (one edited by hand
  stays), and Claude Desktop is told once when its uploaded skill is of an older version.
- "Add to LM Studio": `assistant-x connect lmstudio --link` prints the link that adds the server in LM Studio; the
  installer's summary gives it too.

## 0.4 — 2026-10-28

The library for every app that speaks MCP: Claude, Codex and the ChatGPT desktop app, DeepSeek Harness, LM Studio.

- Every tool has a title and its annotations (read only, destructive): an app asks the user before a change of the
  library. The new tool `library_guide` gives any model the rules of the answers and the shelves of the library; the
  instructions, the tool descriptions and the answers name no app. `page_image` puts a text beside the picture for a
  model that sees no images. `serve --tools reader` gives only the 8 reading tools, `--compact` one-sentence
  descriptions and answers cut at 6 000 characters for small local models.
- One library service for every app of the PC: `assistant-x service` serves the workspace over streamable HTTP on
  127.0.0.1 (the token of the machine folder, DNS rebinding protection), loads the models once and exits after 30
  minutes without a request. The apps start `assistant-x mcp`, a light stdio bridge: it answers the handshake at
  once, starts the service hidden when it is not running (and again when it is gone), reads the token itself and
  passes the messages both ways; `--tools reader` and `--compact` there. `assistant-x serve` stays as the fallback.
- `assistant-x connect APP|auto` writes the entry of the bridge into the settings of Claude Desktop, Claude Code,
  Codex and the ChatGPT desktop app (`~/.codex/config.toml`), DeepSeek Harness (`~/.dsh/cordis.patch.yml`) and
  LM Studio (`~/.lmstudio/mcp.json`), with the skill where the app has a skills folder: the reading tools for DeepSeek
  Harness and LM Studio (and the compact answers for LM Studio), every tool for the others, `--full` / `--reader` to
  choose. A copy of the file first, the entries and comments of others kept, a second run changes nothing, a file that
  cannot be read is left alone with the entry to add by hand; `disconnect` takes it out again, `connect --list` shows
  the apps, `connect --check` makes the handshake and a search through every entry. The installer connects every app
  it finds; `pythonw.exe` on Windows, so no app opens a console window.
- One core for the skill of every app: SKILL.md for Claude and for the agents (no app named), the short rules of
  `library_guide` (`assistant-x skill --app guide` writes them as the system prompt of an LM Studio preset), one text
  of the safety rules; a stamp with the version and the hash of the text, so an outdated skill is replaced and one
  edited by hand is kept (the new one beside it as SKILL.md.new).
- Tried on a PC with a local model: Qwen 3.5 9B in LM Studio, with no system prompt, called `library_guide` by itself
  on "connect to the library" and cited the right document in 8 of 8 questions, the right page in 5 of 8.

## 0.3 — 2026-10-28

This release also contains the changes of 0.2 below, which were never tagged.

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

What the pipeline test of 2026-10-27/28 (rounds of real files, the 40 control questions) showed, fixed.

- Intake speed: every file is prepped before the conversions; a scan with a visible text layer and the picture pages
  of a text PDF are cut into OCR page ranges (20 pages at least, up to 3 ranges a worker); a text chunk ends at 5 pages
  with a picture. A round of 19 files (1 534 pages) went from 922 s to 375 s with the same texts.
- A PDF whose text layer scores below 90 by its words is read again from its page images, and the better text is kept;
  a scan without a text layer is not read twice.
- `intake redo` runs as the intake does (the pool, the load regulator, the OCR page ranges, reused readings first),
  writes each document as soon as it is ready (`--reuse` takes the readings of a stopped run), keeps a replaced text
  aside in `inbox\_to_delete\redo_<date>`, counts the known words once per page and reads the page images only when
  they can help; a text no longer doubled loses the doubled issue of its card.
- `assistant-x intake reflag [--dry-run] [CODE ...]`: the page flags (garbled, doubled) and the quality notes of the
  cards made again from their texts, without OCR; redo does the same for every document it reads.
- A page is doubled only when its repeated phrases occur exactly twice (a legal database export repeating a note is
  not); a digit or a sign in a tiny font is no hidden text; the word "system" alone is no instruction for an AI.
- Search: running headers and footers (a title, "Document provided by …", "Page 40 of 331") are left out of the
  fragments; a document that fills the candidates alone gives more than 3 pages; words broken at a line end and left on
  one line with the hyphen are joined (not a suspended compound: `hyphen_suspended` of the packs).
- `verify_quote`: a word in italics (`_word_`) glued to its neighbours by the converter is found.
- Drafts: the title of a legal database export and of a scanned GOST R title page (new pack key
  `standard_head_loose`), a quoted amendment line, no web address as an English title, a national designation in the
  file name before a foreign one on the page.
- The base is out of date when a page file, a text or `ocr_quality.tsv` changed (a tie of the modification times
  counts as newer); `build` and `reindex` take the machine lock; `reindex --help` builds nothing.
- The load regulator counts a quarter of the memory cap of a worker (14-15 workers on a 16-core PC instead of 11).

## 0.2 — released as part of 0.3

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
