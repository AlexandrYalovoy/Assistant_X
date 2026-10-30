English | [Русский](CHANGELOG.ru.md)

# Changes of Assistant X

New entries go under the version being prepared. The version number is `assistant_x.__version__` (pyproject.toml reads it).

## 0.5.6 — unreleased

The trial intake of a big real folder in batches, continued.

- Intake: a long document whose pages go as images (after the watchdog) no longer fills the memory: the copy is built
  25 pages at a time (a .doc of 2 428 pages grew a worker to 13 GB); on a memory emergency the worker that holds the
  most memory is not suspended, so it ends its task and gives the memory back (before, every worker was suspended and
  the batch waited for hours).
- Intake: an office file LibreOffice cannot open and reads as raw bytes (a .doc with a broken inner directory came out
  as 2 428 pages of signs) is reported as a damaged file to get again, not converted for hours.

## 0.5.5 — 2026-10-29

The trial intake of a big real folder in batches, continued: spreadsheets held in inbox by default, drawing sheets
and long documents read many times faster, and the fixes the batches found.

- A PowerPoint deck with macros (.pptm) is read like any deck (LibreOffice converts it to PDF without running a macro);
  before, it was left as a file the intake does not process.
- A compiled HTML help file (.chm, a book or a handbook) is one document now: 7-Zip takes its pages out, the contents
  of the file gives their order and titles, scripts, styles and pictures are left out, and the pages are laid out on A4
  like any HTML. Before, the 11 help files of a trial inbox were files the intake did not process.
- A folder of page scans (8 pictures and more, most of them with the shorter side of 800 pixels and more: a book
  scanned page by page) becomes one PDF named after the folder, its pages in the natural order of the names, the
  pictures to _to_delete; before, every page was a document of its own (a book of 240 pages in a trial inbox). Icons
  and the pictures of a site stay as they are.
- Sets of drawing sheets drawn in curves (A2 and up, no picture, no text layer) are planned by what they cost: about 25
  s a sheet, and a set of them goes in page ranges on several workers. Before, such a set of 16-18 sheets went to one
  worker as a cheap text file while the others idled (450-500 s, CPU 19 %).
- A folder of HTML pages (an e-book or a site saved article by article, 10 pages and more) becomes one HTML document
  named after the folder, its pages in the natural order of the names, scripts and pictures left out; the pages go to
  _to_delete.
- [intake] to_delete_ext names the extensions the user sends away (a list, or a table of extension = folder: dwg, cdw
  and bak into one folder): prepare moves such files, loose or out of an archive, to _to_delete\<folder>\ keeping their
  folders, a line of the journal each.
- By default the intake sends away the files it cannot read and that are no documents: programs (exe, dll, msi, lnk),
  CAD drawings (dwg, dwt, dwl, bak, cdw, spw), .gsfx, logs, videos and the scripts and icons of a site go to
  inbox\_to_delete\<kind>\ with their folders, loose or out of an archive, each with its SHA-256 in the journal;
  nothing is deleted. [intake.to_delete_ext] extends or changes the table, an empty folder keeps an extension, a list
  replaces it (docs/INTAKE.md).
- The default sends a GIF or an ICO away only when it is smaller than a page scan (an old page or a diagram saved as a
  GIF is read as a picture: GIF is a picture kind now), and a .bak or a .dwl only beside a drawing of the same name (a
  .bak of a Word file or of a database stays).
- The letters an archive holds are taken apart after the archive is unpacked (before, they were left as files nobody
  read), and a second reading of the page images that fails (a sheet of 2 x 3 m read at 29 dpi) keeps the text of the
  first reading instead of failing the file.
- A page without a text layer drawn of more than 20 000 vector paths (a sheet whose text is curves, a scheme of 2 x 6
  m) is read from its image: its layout analysis took more than 10 minutes (a project volume of 174 pages ran 40
  minutes in a trial batch; the page now 12 s). A watchdog limits a conversion to 180 s a page ([intake.timeouts]
  page): a range or a file it stops is prepared once more with all its pages without a text layer read as images, so
  one page cannot stall a batch.
- Search: the reranker orders the candidates and the hybrid score breaks its ties ([search] rerank_weight 100, was 1).
  On 80 control questions of real documents the page came first 57 times instead of 45 (MRR 0.705 -> 0.801; on a
  processor 44 -> 54), on the questions of 87 cards the MRR of the document 0.484 -> 0.512; the 10 questions the
  library cannot answer still say Low closeness.
- The tail of a batch starts the longest tasks first: once every file is prepared and no more conversions wait than
  there are workers, the costliest page range goes first, so a long range started last no longer holds the batch alone
  at its end; before that, the cheapest first as ever.
- intake redo no longer fills the disk: the copies of a document in its work (the copy of the library PDF, its
  variants, their page images) go as soon as the document is read, and a variant links to the copy instead of copying
  it again (one night had left 23.5 GB of copies).
- A PDF with no page that can be read (a cut download whose end is zeros, a broken tree of pages) is reported as a
  damaged or cut file to get again, not as a file without text.
- The page images read instead of a broken text layer are drawn at 300 dpi but at most 12 000 pixels on their longer
  side: a sheet of 2.4 m asked 210 MB at once and the worker failed a project volume of 174 pages.
- LibreOffice writes each conversion into a folder of its attempt and the file is moved into place: a LibreOffice
  stopped at its memory cap may still hold its half-written PDF, and the second attempt failed to store it (a chapter
  of a book in a trial batch).
- Letters and archives are taken apart until nothing new comes: an archive attached to a letter that an archive held is
  unpacked too (before, it was left as a file nobody read).
- A workbook (.xlsx, .xlsm) LibreOffice cannot draw (it crashed on a book of 83 sheets every time) is read from its
  cells: each sheet under its name as a table on text pages, the why naming the crash; before, the file was an error.
- An empty file (0 bytes) is skipped as nothing to read instead of failing as an error of the batch.
- An archive whose names hold signs Windows refuses (a letter saved under its subject: 'RE: FW: ... "Name" <mail>') is
  unpacked with those signs as underscores; before, the whole archive was refused. A path that climbs out, an absolute
  path and a device name of Windows stay refused.
- A page with a text layer drawn of more than 100 000 vector paths (a plan of 485 000 held the layout analysis for more
  than half an hour) loses its line art in the copy the intake reads, its text and pictures kept: the page converts in
  a second.
- A Word document (.docx, .docm) LibreOffice cannot draw even with the doubled memory (a report of 87 embedded PDFs
  went past 6 GB) is read from its parts: its text (headings, tables) and the PDFs embedded in it (an Acrobat object or
  a PDF part) are laid out as one PDF.
- Intake: drawing sheets (A2 and up) with a text layer lose their line art past 10 000 vector paths, and those whose
  text is drawn as curves (fewer than 300 characters in the layer) are read from their image; a set of A1/A0 drawings
  took 34 minutes, now 3.
- Intake: words of a legacy code page shown as Latin-1 in a text layer (the stamp of the sheets of a CAD export) are
  read back in the code page of the document language.
- OCR: a scanned page that stays weak after the retries is also read turned (the turn Tesseract guessed, else 180°)
  when Tesseract cannot tell its orientation; an upside-down offer of six pages went from 25-30 to 82-87 points.
- Intake: an Office file cut before the directory of its zip archive (a half-copied .pptx) is reported as a damaged
  file to get again, not as a failure of LibreOffice.
- Intake: a document of 300 text pages and more is converted in page ranges of 100 pages at least on every worker, as a
  long scan is; a workbook laid out on 1 029 pages took 33 minutes of one worker, now 7.
- Intake: spreadsheets (xls, xlsx, xlsm, xlsb, ods) are held in inbox by default ([intake] spreadsheets = "skip"):
  untouched, "held" in the ledger, listed in the summary and in intake_status with how to take them ([intake]
  spreadsheets = "include", or intake run --spreadsheets include). A workbook is mostly a dataset, not a document to
  cite.

## 0.5.4 — 2026-10-29

The documents for people in Russian too; the fixes found by the trial intake of a big real folder in batches of 50 files.

- The models of the PC no longer stay in the folder of the Microsoft Store app of Claude Desktop (which removing or
  resetting the app would delete): any command moves them into %USERPROFILE%\.assistant_x when nothing holds them, and
  doctor names the state until then.
- A PC without a video card reranks too: the reranker reads the first 8 candidates (rerank_cpu_top). On 40 control
  questions the page came first 24 times instead of 18 (MRR 0.70 instead of 0.59) for 2.6 s a question.
- The documents for people have Russian twins (README.ru.md, CHANGELOG.ru.md, docs/*.ru.md and the rest), with a line
  to switch the language at the top; gen-docs makes INSTALL_FOR_AI.ru.md and docs/CLIENTS.ru.md from Russian templates,
  and a test keeps every pair together (headings, code blocks, links, versions).
- Card drafts (Q6): capitals spaced out over several words are split again by the seed vocabulary
  (УСТАНОВКАОСУШКИГАЗА), a word OCR broke into pieces or at a hyphen is joined, the English title is left out of the
  title of a Russian standard, a garbled head line still gives the title of a standard, a series line is no title, a
  textbook is no plain book, the imprint line gives the year, and an OCR tilde in an RD designation reads as a dash. On
  the 40 hard documents of the rounds the titles came right 32 times instead of 26 (year 36/39, designation 35/35); the
  recognition snapshot moved only for the intended patterns.
- The ledger of a batch (ledger.csv in its work folder, a line at the end of summary.md): every file the batch met in
  inbox has exactly one outcome - done, duplicate, error, unsupported (a kind of file the intake does not process),
  skipped, moved aside (a letter, an unpacked archive, personal papers) or queued - with its pages, OCR pages,
  recognition score and seconds, so the totals add up to what the folder held.
- Intake summary and ledger wording: the load line says how long the regulator held workers back (it was called
  paused), a temporary Office file (~$) is no longer called a Word file, and a card draft whose text gives no title (a
  drawing, a scan without words) takes the name of the file.
- Card drafts of pictures: a photo whose recognition score is below 30 is proposed to drop even when OCR read its
  shapes as many words (26 of 31 photos of a trial batch had more than 25 such words), and a file name whose UTF-8
  bytes an old archiver showed in another code page is mended for the title.
- Letters: the small pictures of a letter body (a logo, a signature: an attachment with a Content-ID, under 100 KB)
  stay in the letter instead of becoming documents of the batch; the summary counts them. A bigger picture (a
  screenshot pasted into the letter) and the real attachments are taken out as before.
- An archive split in volumes (X.7z.001, X.zip.001, X.001 with .002, .003 … beside it) is unpacked from its first
  volume by 7-Zip; the next volumes go aside with it. Before, the first volume was left as a file the intake does not
  process.
- A drawing sheet too big for the page image (read at 80-120 dpi on A1/A0, its labels noise) has its title block - the
  bottom right corner with the name, the designation and the sheet - read again at 300 dpi; that reading is kept when
  the reading of the whole sheet is weak or scores lower. On one-page project drawings of a trial batch: score 68
  instead of 39, the designation read, 22 s instead of about 70 s.
- A page of A2 and bigger is a drawing sheet whatever the length of its document: one sparse-text pass and its title
  block, no retries (a set of 10 A1/A0 sheets of a trial batch: 127 s instead of 441 s). The corners where the title
  block is looked for are data of the settings (QUALITY title_blocks, default the bottom right 200 x 80 mm that holds
  the blocks of GOST 2.104 and ISO 7200); the block is kept only when it scores higher than the reading of the whole
  sheet.
- The workers of a batch in a new workspace no longer fail a file with Permission denied while they build the missing
  vocabulary of the recognition score at the same time: each writes a temporary file of its own and a busy replace is
  tried again.

## 0.5.3 — 2026-10-28

The first part of the open items of the observation journal.

- doctor --json names an app whose entry runs a library server of its own (made before 0.5): it holds the video card
  apart from the shared service; the fix is assistant-x connect APP and a restart of the app.
- python scripts/check.py runs the same checks as scripts\check.ps1 (with --fast, --log FOLDER and pytest options)
  where PowerShell scripts may not run, as in the shell of an agent.
- A background job that did not start (another heavy task holds the PC, or it waits for the user's yes to run on the
  processor) is no longer reported as failed with exit code 3.
- The tests can run in a shuffled order (AX_TEST_SHUFFLE=SEED); the first shuffled run found a test that left the
  models of a medium in the folder of the PC of the session, fixed.
- prepare-media --check reports a second build of a pinned package beside the pinned one (two builds of torch were in
  order).
- assistant-x init says how to let batches without warnings go into the library without the plan (auto_apply in
  assistant_x.local.toml); it never turns it on itself.
- The intake says at its start what limits the number of its workers: the processor cores, the free memory, the workers
  setting or the number of documents.
- Each release carries the source archive of its commit beside the wheel, both in SHA256SUMS.txt, and INSTALL_FOR_AI.md
  has an agent check the archive before installing it.

## 0.5.2 — 2026-10-28

After the live tests of 0.5.1: Codex, self-repair, video memory.

- The instructions of the server and the skill say where to find the tools of Assistant X when an app keeps them behind
  its search of tools (Codex): a small model looked among the resources of the server and never reached the library.
- docs/CLIENTS.md on Codex and ChatGPT: one config for the CLI, the IDE extension and the desktop app; on the Free plan
  Codex runs in the desktop app only and its sign-in may ask for a phone number. Tests check the Codex entry against
  the keys Codex documents, and against a real Codex CLI where one is installed (codex mcp list, our marketplace).
- An agent can repair the setup by itself: assistant-x doctor --json and connect --check --json name every known
  failure by a stable code with the command that fixes it (one table, also in docs/CLIENTS.md and a new step of
  INSTALL_FOR_AI.md); library_guide lists the problems of this PC first; AGENTS.md and the setup skill of the plugin
  tell agents to run doctor --json first.
- The hint of search_library ends with the citation of the best page in brackets ([code, PDF N]): small local models
  cited pages in other forms or named a standard in words.
- The reranker runs in float16 on a video card: on 40 control questions the ranks stayed the same, a search takes 0.5 s
  instead of 1.6 s and the search models need 2.9 GB of video memory instead of 4.6 GB, so a local language model in LM
  Studio keeps its speed.
- scripts\check.ps1 -Log FOLDER keeps a full record of the run (every test, the slowest, junit xml); other arguments go
  to pytest.
- embed on a video card keeps two processor threads of torch instead of dozens.
- The Tesseract languages are downloaded from a fixed commit of tessdata and tessdata_fast instead of their main
  branch: a change upstream can no longer break the install.

## 0.5.1 — 2026-10-28

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
- Suspect text is marked in more answers: document_info, book_map, list_documents, the drafts of intake_card and the
  questions of a base package, not only search hits and read_pages; library_remove counts as a tool word.
- connect --check no longer says in order when the search of an app answers by words only for want of a model (a model
  still loading is fine).
- AX_LOG_LEVEL (DEBUG, INFO, WARNING, ERROR) sets the level of the service log; at DEBUG every bridge writes a line per
  message into bridge-<id>.log beside it, for a debug run. By default the service log no longer gets the INFO lines of
  sentence_transformers.
- The note that the uploaded skill of Claude Desktop is outdated goes to Claude Desktop only, once; the shared service
  no longer gives it to LM Studio, DeepSeek Harness or Codex.
- Windows: the folder of the PC is %USERPROFILE%\.assistant_x instead of %LOCALAPPDATA%\AssistantX. Claude Desktop from
  the Microsoft Store redirects %LOCALAPPDATA% of the programs it starts into its package, so its apps and the others
  (LM Studio, DeepSeek Harness, Codex) ran two services, one without models. An older folder, and the private copy of
  the Store app, is taken over by itself: the small files copied, venv, models and programs linked, nothing moved;
  doctor and connect --check name it. Reconnect the apps once: assistant-x connect auto.
- The conversion no longer fails with I/O operation on closed file in a process that imported pymupdf under a stdout
  closed since (a test order that failed one test): the messages of MuPDF go to the stdout of the moment.

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
