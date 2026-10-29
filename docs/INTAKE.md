English | [Русский](INTAKE.ru.md)

# The intake of new documents

Documents from `inbox` become originals in `library` (under codes), JSON cards and texts in `index`.
The intake runs on this PC with the pipeline `assistant_x.intake.pipeline` (`assistant-x intake …`).
How Claude works with it is in the skill (`assistant-x skill`), the section "How to sort new documents".

## Installation

`assistant-x setup-intake [--dry-run] [--no-install]` (or [`scripts\install_intake.bat`](../scripts/install_intake.bat)). On Linux and macOS it installs
nothing: it finds LibreOffice, Tesseract, 7-Zip and DjVuLibre on PATH and prints the command of the package manager
for what is missing (`sudo apt-get install …`, `sudo dnf install …`, `brew install …`, the Tesseract languages of the
packs included). On Windows:

- the Python packages of the extra `intake` of [`pyproject.toml`](../pyproject.toml) (pymupdf4llm, pymupdf_layout, psutil) into the
  environment `.venv`;
- LibreOffice (DOC/DOCX/PPTX → PDF): winget in user mode, otherwise the winget installer is unpacked with
  `msiexec /a` into `%LOCALAPPDATA%\Programs\LibreOffice` — no administrator rights needed;
- Tesseract (UB-Mannheim) with the languages of the language packs in use (`tesseract` of the packs: rus and eng by
  default): winget in user mode, otherwise the installer is unpacked with 7-Zip into
  `%LOCALAPPDATA%\Programs\Tesseract-OCR`; missing `<language>.traineddata` are downloaded from github.com/tesseract-ocr;
- 7-Zip (for .7z and .rar; zip and tar are unpacked without it);
- DjVuLibre (`ddjvu`, DjVu → PDF): winget in user mode, otherwise its installer (`DjVuLibre.DjView`, the hash checked
  by winget) is unpacked with 7-Zip into `%LOCALAPPDATA%\Programs\DjVuLibre`;
- the paths found are written to `assistant_x.local.toml` (the settings of this PC, not in Git; `assistant_x.toml` `[intake]` is the same on
  every PC).

For an offline media: `python -m assistant_x.setup.collect_programs` copies the Tesseract installed here (rus, eng, osd;
193 MB), LibreOffice (without help, dictionaries ru and en, the Visual C++ runtime beside soffice; ≈1.1 GB), 7-Zip and
DjVuLibre (the command-line tools without the viewer; the official installer with a pinned SHA-256 when it is not
installed here)
into `%USERPROFILE%\.assistant_x\programs` (`AX_PROGRAMS` names another folder; `VERSIONS.txt` says what is inside).
From there the programs run without installation and are found first. Without that folder the installed programs are
used.

Without LibreOffice the pipeline works: DOC/DOCX/PPTX and spreadsheets get the status "skipped" with the reason;
without DjVuLibre (`ddjvu`, found like the other programs: `[intake] ddjvu`, `AX_DDJVU`, the bundled programs folder
`DjVuLibre`, `Program Files\DjVuLibre`, PATH) a DjVu file is skipped with a note that names the program. Without Tesseract scans
are converted without OCR, such pages are counted in `no_ocr_pages`, and the quality report gives the document the
priority "high".

## Settings: `assistant_x.toml` `[intake]`

| Key | What | Default |
|------|-----|--------------|
| `[paths]` `inbox`, `library`, `index` | the folders, relative to the workspace | `inbox`, `library`, `index` |
| `[paths]` `work` | the work folders of batches `work\<DATE>` | `.assistant_x\work` |
| `[paths]` `reports` | the reports of the hidden text check | `reports` |
| `soffice`, `tesseract`, `tessdata`, `sevenzip` | programs; empty — look for them: the bundled programs folder `%USERPROFILE%\.assistant_x\programs` (portable copies of an offline media: `Tesseract-OCR`, `LibreOffice\program`, `7-Zip`; the folder — `AX_PROGRAMS`), the path of the settings, `%LOCALAPPDATA%\Programs`, `Program Files`, PATH; `-` — do not use. A path in the settings that is not there (another PC) does not stop the search. The paths of this PC are written to `assistant_x.local.toml` beside it (not in Git) and are read only from there: a program path in the shared `assistant_x.toml` is ignored, so a copied or received settings file never chooses which program runs | |
| `stage_mode` | `inproc` — long-lived worker processes (`pool.py`), `subprocess` — the former mode: a python process per tool | `inproc` |
| `workers` | at most this many worker processes (0 — everything in the main process, for debugging); how many really — `balance.py` decides by the PC | 16 |
| `profile` | `auto` — by the measurements; `day` — always "at the computer"; `weak` — a weak PC (1–2 workers, 1 thread, always "at the computer"); `night` — always "free" | `auto` |
| `priority` | `below_normal` — below the user's programs (always, in both states), `idle`, `normal` | `below_normal` |
| `affinity` | `auto` — all CPUs while the PC is free, E-cores (when there are enough of them) while someone works at it; `all`, `ecores`, a list `[2, 3]` — by hand | `auto` |
| `idle_minutes`, `cpu_share_idle`, `cpu_share_active` | the PC is "free" after this many minutes without input; the CPU share in the states "free" and "at the computer" | 7, 0.8, 0.5 |
| `temp_max_c`, `temp_cool_c` | above — remove workers one by one; add them again only below the second threshold | 85, 75 |
| `heavy_mb` | before their preparation (the pages are not known yet) bigger files go after the small ones and take a heavy slot | 40 |
| `ocr_shards` | `auto` — the OCR of a long scan (60 scanned pages and more) is cut into page ranges that every worker reads, the text is assembled when all are back; `off` — a document in one task, as in 0.1 | `auto` |
| `ocr_threads` | `subprocess` — processes of `convert_md.py` / `reocr_empty.py` per document | 2 |
| `worker_memory_mb` | the memory cap of a worker process and of every program it starts (with all its children); `workers` × the cap no more than the RAM | 3072 |
| `timeouts` | seconds: `soffice`, `hidden`, `convert` (the whole document), `unpack` | 900, 1800, 14400, 1800 |
| `unpack` | `max_total_gb` (the total unpacked), `max_depth` (nested archives) | 5, 3 |
| `auto_apply` | `true` — `intake_apply()` applies a batch whose `check-meta` finds no error at once, without the plan and its token, unless the plan needs the user (below); read **only** from `assistant_x.local.toml` | `false` |
| `disk` | free space before a run: `factor` × the input files and at least `min_free_gb` | 3, 10 |
| `to_delete_ext` | the files the intake cannot read and that are no documents: preparing moves them (never deletes) to `inbox\_to_delete\<folder>\` with their folders, loose or out of an archive, each with its SHA-256 in the journal; a table `[intake.to_delete_ext]` of extension = folder extends the default, `""` keeps an extension, a list replaces the whole table | `programs`: exe dll msi lnk; `cad`: dwg dwt dwl bak cdw spw; `gsfx`; `logs`: log; `video`: mp4 mov avi mkv wmv mpg flv; `site`: js css gif ico |

Environment variables override the file:
`AX_CONFIG` (another settings file), `AX_INBOX`,
`AX_LIBRARY`, `AX_INDEX`, `AX_WORK`, `AX_REPORTS`, `AX_SOFFICE`, `AX_TESSERACT`, `AX_TESSDATA`, `AX_SEVENZIP`,
`AX_WORKERS`, `AX_OCR_THREADS`, `AX_WORKER_MEMORY_MB`, `AX_STAGE_MODE`; `AX_ONNX_THREADS` — ONNX threads by hand (0 — as
onnxruntime intends, only for measurements). All the scripts take their paths only from here (`intake/config.py`).
The defaults of the table are in one place, `core/config.INTAKE` (`intake/config.py`, `balance.py`, `tools/unpack.py`
and `core/common.DISK` read them); no module reads the workspace when it is imported: its paths are resolved when
they are used (`dupcheck.texts_dir()`, `ocr_score.vocab_file()`, `manifest.main(--root)`, `debuglog.log_dir()`,
`onnx_models.onnx_dir()`, `intake_tools.P`, `install.P`; a test checks it).

## The pipeline

```
intake.bat  =  assistant-x intake run [--dry-run] [--workers N] [--resume]
   (no pause with AX_NOPAUSE, the exit code is that of the intake)
   preparing inbox (prepare.py): personal papers by the name of a file or folder (land register extracts,
                           insurance numbers, tax statements, mortgages, passports…: personal_papers of the
                           language packs, [intake] personal_words) → _to_delete without opening them, archives too;
                           archives → unpacked beside them (tools\unpack.py), the archive → _to_delete; with a
                           password → _to_delete ("an archive with a password", not an error of the batch);
                           letters (.eml .msg .oft) → their attachments into a folder of the letter's name
                           beside it (tools\letters.py; a forwarded letter is taken apart in turn), the letter →
                           _to_delete; macOS service files (__MACOSX\…, ._*) → _to_delete; what each extension is:
                           the one table core/formats.EXTENSIONS ("Formats" below)
   SHA-256: a duplicate by manifest.tsv, intake_events.tsv, the files of the batch (the journal hashes are read once)
   process pool (process.py → pool.py → work.py; only the main process writes the state):
     prep     → PDF (LibreOffice, images), hidden text (tools\hidden.py), a fingerprint of the text layer,
                the scanned pages, a broken font encoding (below)
     duplicates by content (dupcheck.THRESHOLDS: 8 % partial, 30 % a suspect, 60 % a duplicate at once only
                when it is the same edition, below)
     convert  → Markdown (tools\convert_md.py, reocr_empty.py, assemble_md.py); more than 100 lost symbols (U+FFFD)
                after it → prep again with OCR of the page images (the second guard of a broken encoding)
   quality report (quality_report.py), metadata draft (metadraft.py), summary (review.py)
Claude: meta.jsonl from meta_draft.jsonl (schema: meta_schema.py, assistant-x intake check-meta)
assistant-x intake build      → work\<DATE>\out (build.py; codes in codes.json)
   program files without a meta line (.exe .dll .msi, intake_cfg.PROGRAM_EXT, and those of the programs of the field
   of the profile: program_ext of profiles/<name>/documents.json; assistant_x.toml program_ext replaces the list)
   → _rejected\programs; a new version of a document of the library (versions.py, below):
   "replaces" takes its code, "other_version" keeps both
assistant-x intake apply [--dry-run | --resume]  (apply.py)
   moves into library / _duplicates / _rejected, a PDF beside a DOC, cards and texts into index,
   CATALOG.md and sources_to_update.md made again from all the cards, events, manifest.tsv, journal.md,
   empty folders of inbox; the base is marked behind the library (index_stale in its meta table, or
   index\index_stale.txt without a base): search_library says so first and `assistant-x check` warns, until
   `assistant-x build` reads the new documents (then `assistant-x embed`).
   The pipeline deletes nothing:
   it only moves into _to_delete, _duplicates, _rejected (the user deletes them).
   A transaction: the checks first, then out\apply.journal.json notes every move and step; an interrupted apply
   (the PC switched off) is refused until --resume, which goes on and adds no row twice. Missing folders of index
   are made first
```
Other commands of `assistant-x intake`: `status`, `todo [--by-folder]`, `brief [T0001 …]` (a line per file: pages, OCR score,
section, designation and title from the draft, path — instead of `digest` on big batches), `digest [T0001 …]`,
`groups [--write]`, `pack <folder> [--main T0001] [--write]` (all processed files of a folder are one document: the main
one and its parts), `requeue T0001 …`, `draft`, `quality`, `journal [--check]`; all of them take `--work DIR` (default:
the latest batch, for `run` today's). The parts of the code: `prepare.py` (inbox), `process.py` (the batch and the
pool), `work.py` (the stages of a file; what they pass to each other: `results.py`), `review.py` (what Claude reads),
`build.py`, `apply.py`; `pipeline.py` holds the commands. What the intake shares with the search is in `core`: the
structure of a text (`core/textmap.py`: headings, contents, captions), the journal (`core/journal.py`), the formats.

The work folder of a batch `.assistant_x\work\<DATE>`: `state.sqlite` (the state: tid, path, status, reason, data in JSON;
`state.py`), `src` (hard links to the originals), `pdf`, `txt`, `cache`, `md`, `log`, `fp`, `meta_draft.jsonl`,
`meta.jsonl`, `codes.json`, `quality.json`, `summary.md`, `intake_quality.md`, `out`. The fingerprints of the library
texts for the duplicate check are cached in `.assistant_x\fingerprints` (one cache of the workspace: `<code>.fp`, valid only for the text
whose sha256 it holds).

### What the intake must not lose

- **Duplicates by content and editions** (`process.Batch.dup_verdict`). A file with 60 % and more of its phrases in a
  library text (or in a file of the batch) is a duplicate by itself only when it is the same edition: 90 % of the
  phrases and more (`THRESHOLDS["same"]`), page counts within 10 % of each other (`"pages_apart"`) and no other
  designation of the same document (the designation of the first pages without its year, `versions.key`: GOST R
  51858-2002 there, GOST R 51858-2020 here). Otherwise — and from 30 % — it stays a suspect: the state keeps
  `suspect` and `suspect_why`, `intake brief` shows "like N-00005?", and the draft asks Claude the question "the same
  document or another edition" (`{"dupof": …}`, or keep it: `replaces` / `other_version` for a library document). A
  SHA-256 match is a duplicate always. A DOC/DOCX beside an earlier scan of the same text keeps both (`rival`).
- **Scanned pages** (`work.scanned`). A page goes to OCR when raster images cover 70 % of its area and more (their
  boxes joined, clipped to the page) and its text layer is sparse (fewer than 1 character per cm²; a page of text has 4
  and more): a scan with a stamp, a header or a watermark in its text layer is recognised all the same. A page whose
  images give no boxes, and every page of a PDF made of an office file, is a scan by the former rule (fewer than 80
  characters and a picture). The scanned pages go to convert (`jobs.json` `"ocr_pages"`); `reocr_empty.py` reads by
  OCR the ones the conversion did not. The text layer of such a page stays after its OCR text when OCR did not read
  most of its words (`assemble_md.py`; the page source is `ocr`).
- **Broken font encoding** (`work.broken_encoding`), seen in prep before the conversion on the first 5 text pages (200
  letters at least): 30 % of the letters of no language of the active packs ("Íàñòîÿùèé": a Cyrillic code table read
  as Latin-1), 10 % lost symbols, or 80 % of the words unknown to the library vocabulary (when it has 1000 forms and
  more; it is not built in prep). Such a file is recognised from its page images at once (`imgocr`, the reason in the
  state); more than 100 U+FFFD after the conversion is the second guard.

**The card against the text** (`meta_schema.text_checks`, run by `check-meta` and `build`): a designation must be
on the first 3 pages of the text of its file or in the file name (its digits are enough after OCR), and the title must
share a word with the first pages of a text of 2 pages and more — else an error (a line written for another tid);
a year that does not occur in the text and fewer than half of the keywords of the document languages found in it
are warnings.

**The digest** (`intake digest`, the MCP `intake_card` with tids) shows a text by the genre of its draft (`review.DIGEST`,
one table of the parts and their sizes): a standard its title page and scope, an article or a thesis its title page
and abstract, a journal issue, proceedings or a book its title page and contents, a datasheet or a manual its
characteristics; any other the start of its text. The headings of the parts are words of the language packs
(`digest_heads`).

meta.jsonl: a line per file — a document `{tid, sec, doc_type, en, au, …the doc fields of the card…}`, a part
`{tid, part, what}`, a duplicate `{tid, dupof, why}`, rejected `{tid, drop}` (`meta_schema.py`). A document line is
checked as its card will be (`core/card.validate`: the schema, the card languages, the shelves, the limits). Whether a
document is in force is the user's matter: a card has no validity status.

## Formats

What the intake does with a file is the kind of its extension (`core/formats.EXTENSIONS`). A file that is no PDF gets
a PDF of its own (`work\<DATE>\pdf\<tid>.pdf`), which goes beside the original into the library (`file.pdf_copy` of
the card): the pages of a citation are the pages of that PDF, so they stay the same.

| Kind | Extensions | How |
|------|------------|-----|
| pdf | pdf | as it is; scanned pages by OCR |
| office | doc docx docm rtf odt ppt pptx pps ppsx odp | LibreOffice → PDF |
| spreadsheet | xls xlsx xlsm xlsb ods | LibreOffice → PDF for the pages; every sheet a Markdown table `## Sheet: <name>` at the end of the page that shows its first cells (`tools\sheets.py`; XLS, XLSB, ODS made XLSX by LibreOffice first; 2000 rows and 60 columns of a sheet at most, a note says so) |
| ebook | epub fb2 mobi xps oxps | PyMuPDF lays it out on A4 pages, its table of contents kept as bookmarks (MOBI as far as PyMuPDF opens it) |
| text | txt md markdown html htm xhtml | PyMuPDF lays it out on A4 pages; a TXT or Markdown file is read as UTF-8, else in the legacy code page of a language pack that gives the most stop words (`encodings` of the packs: cp1251, koi8-r, cp866, cp1252); Markdown is laid out as it is written |
| djvu | djvu djv | DjVuLibre (`ddjvu -format=pdf`) → PDF of page images, then OCR; skipped without it |
| image | jpg jpeg png tif tiff bmp | PyMuPDF → PDF, then OCR |
| archive | zip 7z rar tar tgz tar.gz tar.bz2 tar.xz gz | unpacked beside it, the archive to `_to_delete` |
| letter | eml msg oft | the attachments taken out beside it (`.eml` by the standard library, `.msg`/`.oft` from the Outlook compound file; an embedded item that is no file is named in the event), the letter to `_to_delete` |

Any other extension is "skipped: decide by hand". The kind of a card (`file.format.kind`) is `ebook`, `text` or
`spreadsheet` for those kinds; a DjVu file is a scan (`pdf_scan`).

**The outline of a file** (`tools\outline.py`): the bookmarks of the PDF (with their pages) or, for a DOCX without
them, its heading styles (Heading 1…9 or an outline level; the page of each is found by its text) are the first source
of the outline: they go into `<code>.pages.json` (`"outline"`), the draft takes the contents of the card from them,
and the base keeps them (`given_outline`) for the book map. The headings guessed from the text are the fallback
(`core/textmap.build`).

## Text format (AX text 1)

`index\texts\<code>.md` is the text of a document as the search and Claude read it, and it may be edited by hand (a
recognition error fixed, a table put right); the base is built from it (`assistant-x build`). Its rules
(`core/formats.py`, `TEXT_FORMAT = "1"`), kept by `tools\assemble_md.py` and checked by `assistant-x check`:

- **Encoding and lines**: UTF-8 without a BOM, line ends LF (a CRLF text is a warning of the check), Unicode NFC
  (a letter with its accent is one character).
- **Pages**: every page of the PDF starts with a marker line of its own `=== page N ===`, N the page of the PDF (not
  the printed number), in order, one for every page (a text with other markers than its PDF is an error of the
  check when the original is at hand). A line of the body that would read as a marker is written with a backslash
  before it: `\=== page 3 ===` (and one more backslash before a line that has some already); the search gives it back
  without the backslash.
- **What the body may hold**: Markdown headings (`#`…`######`), paragraphs, lists, GFM tables (a header row, the
  separator row `|---|`, the rows). Not allowed: raw HTML, invisible characters (zero width, text direction, Unicode
  tags, variation selectors: the intake removes them, the check warns about them), the soft hyphen (written as "-").
- **Hyphenation**: the text layer of a PDF is read with the words broken at the line ends joined (PyMuPDF
  `TEXT_DEHYPHENATE`); on an OCR page a word broken with a hyphen at the end of a line is joined only when the
  vocabulary of the library (`.assistant_x\ocr_vocab.txt`, "Recognition score") knows the whole word.
- **What is known of every page**: `index\texts\<code>.pages.json` beside the text, written by the intake and moved,
  replaced (`assistant-x intake redo`) and put aside (a new version) together with it:

  ```json
  {"format": 1, "pages": {"12": {"source": "ocr", "ocr_score": 83.5, "label": "218", "flags": ["complex_table"]}},
   "outline": [[1, "1 General", 3], [2, "1.1 Scope", 3]]}
  ```

  `outline` (when the file gives one: PDF bookmarks, DOCX heading styles): `[level, title, PDF page or null]`.

  `source`: `layer` (the plain text layer of the PDF, the page was not converted), `markdown` (converted with its
  layout), `ocr` (converted and recognised by OCR), `fallback` (the conversion was refused, the text layer taken
  instead); `ocr_score`: the recognition score of the page; `label`: the printed page number from the page labels of
  the PDF, `null` when the PDF has none (the `page_offset` of the card is used then); `flags`: `complex_table` (a
  table with a row of another cell count than its header: merged cells, numbers to check against the page image),
  `formula` (a line ending with an equation number), `garbled` (a quarter of the words unknown), `doubled` (every phrase
  twice), `dpi_reduced` (OCR at a reduced resolution); `layer` (on some pages only): `kept` or `added` (the visible text
  layer of a scan, see "Recognition score"). A text without it is still searched (a warning of the check);
  after a hand edit that adds or removes pages, put it right or delete it.

## Cards

A card is `index/cards/<code>.json`, strict JSON checked by the JSON Schema [`assistant_x/schemas/card-1.json`](../assistant_x/schemas/card-1.json)
(`core/card.py`); it is the one source of truth about a document: `CATALOG.md`, `sources_to_update.md` and the `docs`
table of the base are made from the cards, nobody edits the first two by hand.

- The code: the letter of a shelf and five digits, `N-00012`; the parts of a document of several files `N-00012-02`.
  The next free number of the shelf is given (`<work>/codes.json` keeps it for the batch).
- `doc` — what the document is, written by Claude from the draft: `title`, `designation`, `authors`, `year`,
  `publisher`, `edition`, `lang`, `scope` (≤ 300 characters), `summary` (≤ 800), `questions` (≤ 5), `topics` (1–8
  ids), `keywords` (≤ 30 per language), `terms` (≤ 40), `toc` (≤ 300 entries, `pdf_from` only: an entry ends where the
  next one starts), `tables` (≤ 100), `references` (designations only: the base resolves them to codes), `units` and
  `serial` of a journal issue or proceedings, `other_versions`, `adopts` (the foreign standards a national one adopts,
  as its title page names them: `ISO 10424-2:2007`; searched with the designation), `amends` (the designation of the
  standard an amendment changes), `page_offset`, `note`.
- `file` — what the code knows of the file: `format` (`kind`, pages, recognized pages, the score 0–1), `library`
  (the place, `/` between folders), `source_name`, `sha256`, `size`, `text`, `pdf_copy`, `hidden_text`, `issues` (what
  is wrong with the source: the sources to update are made from them), `parts`.
- `intake` — the batch, the date and `personal` (false by default; true only for an addition the user asked to keep
  apart, "Personal documents" below).
- Top level: `schema` (1), `code`, `section` (the shelf), `doc_type` (the genre).
- The languages: every text searched by exact words is a map `{"en": …, "ru": …}`. English always, and every
  language the documents are read in (`[documents] languages` of `assistant_x.toml`: Russian and English by default),
  whatever the profile.
  `scope`, `summary`, `questions`, `note` and `units[].summary` are English only: the search by meaning (bge-m3) finds
  them by a question in any language.
- Two axes of classification, both proposed by the draft and confirmed by Claude: `doc_type`, a universal genre (law,
  regulation, standard, guideline, contract, court_decision, clinical_guideline, book, textbook, handbook,
  serial_issue, proceedings, article, thesis, report, manual, datasheet, drawing, project, presentation,
  lecture_notes, dataset, other), and `section`, the shelf: the same shelves in every library
  ([`assistant_x/schemas/shelves.json`](../assistant_x/schemas/shelves.json): N Standards, L Literature, P Projects and reports, E Equipment documents, R Regulations and law, J Journals and
papers, X Other; a letter, a folder, names in English and Russian, what goes
  there). Every genre is on exactly one shelf, so the shelf follows from the genre; Claude puts a document elsewhere
  only with a reason. The same shelves keep the codes of every library and base package compatible.
- Written with sorted keys, an indent of one space, UTF-8 letters as they are, LF and a trailing newline: the same card
  gives the same bytes, so `assistant-x build` reads again only the cards whose sha256 changed. The schema version
  is 1; `card.migrate` is the chain of later versions (empty yet). Libraries of the Markdown cards of earlier versions
  are not migrated: a new library is made by its own intake.

The draft (`metadraft.py`) suggests from the text: the genre and the shelf (the words of the language packs,
`doc_type_words` of the packs and the profile, every genre of `schemas/card-1.json` tried in its order; a designation
of a standard first), the title and the designation in the language of the document,
the year, the publisher, the languages, the contents with PDF pages (`search/bookmap.py`), the tables, the
designations the text refers to, and the articles of a journal issue from its contents page. Claude checks it against
the text and adds what the code cannot: English, the summary, the topics, the keywords.

The designations of a standard: every number class takes a hyphen, an en dash and an em dash (`GOST 33000—2014` of a
title page). Of the designations standing as its own on a title page, the national one (`national_standard` of the
packs) wins over a foreign one printed beside it; a foreign one in parentheses right after it goes to `adopts`. The
file name gives the designation when the text has none, and its form when it is the same number with the year the
text left out. The English title of a standard is the line of Latin letters of three words or more nearest to its
designation on the title page (the word-by-word translation of the title in capitals when there is none). A first
page starting with the words of an amendment (`amendment` of the packs: "Amendment No. 1", "Corrigendum") gives a
draft of the genre standard with `amends` = the designation it names: an amendment is never asked about as a new
version of its base. A guessed contents drops an entry said twice on one page and the service lines of a title page
(`not_heading` of the packs: "Date of publication").

## A new version of a document

The draft (`metadraft.write_drafts`) compares every file with the documents of the library (`versions.py`): the same
designation of another year (GOST R 51858-2002 in the library, GOST R 51858-2020 in inbox) or a very similar title
(80 % of the words in common). Such a file gets `version_of` and a `question` in `meta_draft.jsonl`; Claude asks the
user and writes the answer:

- `"replaces": "N-00001"` — the new file takes the code N-00001 (its section must be N too); the old original, its
  card and its text go to `inbox\_to_delete\replaced_<DATE>` (nothing is deleted), the catalog row is the new one, the
  events say "to delete: replaced by a new version" and "done: a new version". A document of several files is not
  replaced (keep both).
- `"other_version": "N-00001"` — the new file gets a code of its own; both cards name each other in
  `doc.other_versions`.

**Codes between batches.** `build` gives the codes under the lock `index\codes.lock` (one process at a time reads the
numbers in use and writes `codes.json`). Two batches built one after the other get the same next free numbers; the
one applied second sees, before its first move, that a card of the library has taken a code of its batch, gives
those documents the next free codes and builds the batch again (cards, texts, moves, events: everything that names
a code), deterministically by the order of the tids. A number is never given twice: `index\codes.json` keeps the
highest number given per shelf letter, so the number of a removed or replaced document does not come back. A build
that cannot take `codes.lock` within two minutes stops and says so (another build or a base install holds it).

**On Linux and macOS** a tool runs with the address space capped (`resource.prlimit` RLIMIT_AS; this process:
`setrlimit`), the priority class as a nice value (below normal 10, idle 19) and the CPUs by `os.sched_setaffinity`
where the system has it; what a system lacks is said once on stderr and the work goes on, psutil watching the tree as
before (`intake\limits.py`). The Job Objects stay on Windows. With no peak of a job to read there, a tool that failed
counts as over the memory cap when its output says so (`MemoryError`, "Cannot allocate memory", `std::bad_alloc`,
"out of memory") or the kernel killed it (SIGKILL).

Reliability: an interrupted run (Ctrl+C, a failure) goes on with the same `run` — files "in work" go back to the queue,
finished OCR pages come from the cache. Every program (LibreOffice, OCR, hidden.py) runs under a Windows Job Object: a
memory cap on the whole process tree, a timeout, the tree is taken down as a whole, no error windows appear
(`limits.py`; outside Windows — psutil supervision). Exceeding them gives the status "error" with the reason. A
pool process that crashed twice on one file marks it as an error. LibreOffice profiles are short paths in
`%TEMP%\at_lo\<slot>`.

The `inproc` mode (default): a worker process imports PyMuPDF, pymupdf4llm and the tools once and calls the stages as
functions; LibreOffice stays a separate program. Every worker is in its own Job Object (the cap `worker_memory_mb` on it
and the programs it starts). A task longer than its term (prep — `soffice` + `hidden` + 600 s, convert —
2 × `convert` + 1800 s) or a worker that hit the memory cap: the worker is killed and created anew, the file gets an
"error" with the reason ("time exceeded", "memory cap exceeded"), the other workers go on. A crashed worker: the file
goes back to the queue, a second crash is an error. An exception of a tool is an error of the file with the text of the
exception. A worker is replaced by a new one after 100 tasks. The layout models (ONNX) are limited to one thread without
active waiting (`tools\onnx_threads.py`, any session, also the ones pymupdf4llm creates): by default onnxruntime takes all
cores, and several documents at once wasted CPU on waiting.

The load on the PC (`balance.py`) is decided by measurements on any PC, without core numbers and processor models. At the
start, a survey: CPU (logical, cores, E-cores if the CPU is hybrid), RAM, video card. The budget: a worker is one core
(one thread of onnxruntime, OpenMP, MKL, torch; `threads` of `[intake]` changes it, `ocr_threads` stays the Tesseract
threads); "free" — as many workers as there are logical CPUs past the reserve of 2, as fit into the available memory
minus a reserve (≥ 4 GB or 15 % of the RAM, whichever is more, a third of `worker_memory_mb` per worker) and no more
than `workers`; "at the computer" — at most the cores − 2 and the share `cpu_share_active`. The regulator (a thread in
`pool.py`, every 4 s) measures the total CPU and the share of our processes
(Job Object accounting: the load of others shows apart), the disk (busy = 100 − `% Idle Time`, and the latency
`Avg. Disk sec/Transfer`), the available memory, the time since
the last input (`GetLastInputInfo`), the temperature (LibreHardwareMonitor / OpenHardwareMonitor when installed,
otherwise `MSAcpi_ThermalZoneTemperature`, the video card — `nvidia-smi`; without a sensor the heat shows by the falling
frequency under load, `% Processor Performance`) and keeps: "free" (no input for `idle_minutes` and no load of others) —
a total CPU of 70–85 %; "at the computer" — 40–55 %. The user is back — in one step the extra workers pause; gone — one
worker more every 45 s. Always: a priority below normal and a low disk priority, 2 CPUs free, a memory reserve, the
temperature below `temp_max_c`; the disk slows the work only "at the computer" and only when a transfer takes more
than 50 ms on average (a fast SSD 100 % busy at 0.2 ms is no reason). Emergencies: memory < 1.5 GB, CPU > 90 % or a
disk 90 % busy with transfers over 200 ms for more than 15 s — half of the workers pause, memory < 1 GB — all of them.
`balance.log` gets a line of the load every minute even when nothing changes ("cpu 42 % (ours 31 %), workers 8/8
active, mem 17.2 GB free, disk 1 ms, gpu 0 %"), and `summary.md` the mean CPU share of the batch and the minutes with
paused workers. The time left of `intake status` goes by the cost of the files (`schedule.cost`: text pages, scans,
pages with a picture; a file not prepared yet by its size) over the cost done per second so far, told once 5 files are
done: the cheap files go first, so pages per second would promise too much. A pause: the worker gets no new tasks, its tree (with LibreOffice
and Tesseract) gets the IDLE priority until the end of the current task; on an emergency and overheating the tree is
suspended, the pause time does not count against the time limit of the task. The decisions go to
`work\<batch>\balance.log` (time, state, active/total, measurements, reasons).
Heavy files (bigger than `heavy_mb`) go at the end and one at a time; `assistant-x intake run --resume` continues the latest batch.
The memory cap of a task goes by the pages known after prep: up to 300 pages `worker_memory_mb`, up to 800 — 6 GB, more
— 8 GB and such a document goes alone (no more than half of the RAM). A worker hit the cap — the document is repeated
once with a doubled cap in a new worker (in the output and in the state: `memory_retry`), the second time it is an error
of the file.
One heavy task per PC (`core/lock.py`, the lock `%USERPROFILE%\.assistant_x\heavy.lock`, the journal `heavy.log` beside it): `run`,
`redo`, `build`, `apply`; busy — they print who holds it and exit with code 3, `--wait` — they wait. Other heavy commands
under the lock: `assistant-x lock --wait "embed" -- assistant-x embed`; who holds it:
`assistant-x lock`. The former mode: `stage_mode = "subprocess"` in `assistant_x.toml` `[intake]` or
`set AX_STAGE_MODE=subprocess`. Measurements: `debug\intake_timing\timings.md` (not in Git).

## Recognition score

Every text gets a score of 0–100 (`tools\ocr_score.py`, thresholds — `QUALITY` in [`assistant_x\core\common.py`](../assistant_x/core/common.py), the keys
`ocr_*`). Its base is the share of nonwords: a word is known when it occurs in 3+ documents of the library (the
vocabulary `.assistant_x\ocr_vocab.txt`; rebuilt by every `assistant-x intake apply` as its last step, with a line in
its output, and by `assistant-x intake vocab` by hand; about a minute). While the vocabulary
is small (fewer than 1000 forms: a new library) the words are judged by their shape only, so a clean document is not
called poor. Under the library vocabulary lies the seed vocabulary of each language pack (`lang/<code>/vocab.txt`): a
seed made of the words of the pack data and, for English, of the documentation (no frequency list of a third party is
bundled); it counts only once the library vocabulary is big enough. Counted as errors: the letters of two packs in one word (Latin mixed with Cyrillic), U+FFFD and a "broken" font (Latin Extended-B), junk of
signs, recognition crumbs (two-letter pairs outside the lists of the language packs, a pair of the same capital, extra
single letters). Numbers, codes and abbreviations are neutral. For OCR pages the
Tesseract confidence goes into the score with a weight of 0.25. A clean text PDF gives 95–100, garbage below 50. Checked
against the accuracy on 20 pages looked at by eye: `debug\ocr_quality\review.md`.

An OCR page goes like this (`tools\ocr_page.py`; pymupdf4llm calls it instead of the built-in Tesseract):

- **recognition**: the Tesseract program (`--oem 1`, LSTM, as in PyMuPDF), `tsv txt`; the words go onto the page as
  invisible text, each in its own box — so the spaces in tables are kept;
- **rotation** (OSD, `--psm 0`, on a half-size copy) is checked on every OCR page: on a confident rotation of
  90/180/270 the page is recognized turned, and its text replaces the Markdown;
- **a weak page** (a confidence below 60 — since 2026-10-24, it was 70 — or more than 25 % nonwords) is recognized twice
  more: at 400 dpi and in black and white; the variant with the best score stays;
- **a loss check**: if the Markdown after the layout analysis kept less than 60 % of the recognized words, the page takes
  the plain text of Tesseract (or it is appended after the Markdown of a page recognized in part).

A page with a legible text layer of 8 words or more (a scan the publisher gave a visible text, a text page with a
picture) is read once, without the rotation check and the retries. When 70 % of the distinct recognized words are
already in the layer (lower case, letters and digits), the recognition is dropped and the page is its layer (`"layer":
"kept"` in `<tid>.pages.json`); else only the recognized words the layer lacks are added (a figure caption, a stamp:
`"layer": "added"`). Such a layer is often shifted from the glyphs under it, so the image still shows them: an invisible
copy of the whole page would make the layout analysis extract every phrase twice. As a safety net the score counts
for every page of 30 words and more the share of its word 3-grams that occur twice (`repeated`); from 0.4 the page gets
the flag `doubled` (weighed like `garbled` by the search), a document with more than 10 % of such pages is listed in
`intake_quality.md` ("re-extract the text"), and `assistant-x intake redo` replaces a library text whose doubled pages
fall by 30 points of the page share (or whose mean share falls from above 0.4 to below 0.1) while it keeps its known
words. A line or a sentence that repeats the one before it word for word is dropped at the assembly. In the rows of a Markdown
table a run of 17 letters and more that is no word (a cell whose spaces OCR lost) is split into the cheapest sequence
of words of the vocabulary (a word form 1, a stop word of one or two letters 1.6, a word known by its stem 2.5, a form
of three letters 3; a linking vowel of a compound, `compound_links` of the packs, is no word), a word broken at a line
end of the cell joined first; a split with more than a quarter of three-letter pieces is refused. A word of five
letters and more in small caps that OCR read in both cases ("INhIBITORS") takes the case of most of its letters.

A page prep does not count as a scan but pymupdf4llm sends to OCR (a text page with a picture: a diagram, a photo
with labels) gets one reading in the sparse text mode (`--psm 11`), without the rotation check and the retries, and
it is kept only when it adds 8 words the text layer lacks (`convert_md` gives `ocr_page.SCAN_PAGES` the scans of the
document; the retries stay for them). The order of the work counts such a page a second more than a text page
(`schedule.cost`, the `image_pages` of prep); the seconds of OCR of every file are summed (`ocr_seconds`) and shown by
`intake status --json` and `intake_status`.

`intake_status` answers in 3 000 characters at most: the batch (done, in work with the stage, the pages and the OCR
seconds, waiting, errors with the reason, the time left), a line per background job (a finished one only when it
ended after the batch started: "Base recalculation: finished 8 h ago in 14 min, 82286 fragments, 113/s") and the next
step; `intake_status(full=True)` adds `summary.md`, `intake_quality.md` and the files without a card. The known
harmless warnings of the model libraries are left out of the job tails (`HARMLESS` of `server/intake_tools.py`), and
the batch prints its progress line on a change or every 5 minutes.

A page costs about 2.5 s instead of 2 s with the built-in Tesseract (+0.5 s for the rotation check); a weak one 6–15 s.
Per document, so the outputs stay the same (`tools\ocr_page.py`, checked on the golden corpus byte for byte):

- **the orientation** is checked on the first 5 OCR pages (`OSD_SAMPLE`); when they agree the other pages take it,
  and only a page whose first reading is weak is checked itself (a uniform scan of 12 pages: 23.5 s → 20.3 s);
- **the retry**: after 10 weak pages, a variant (400 dpi or black and white) that won 70 % of them is the only one
  tried on the next weak pages;
- **the first reading of the scanned pages of a chunk** runs in one Tesseract process (a list of images); a page whose
  image differs is read alone. On this PC it saves little (Tesseract itself is the cost, not starting it);
- `convert_md.py` keeps one open PDF per document and chunks of 50 text pages or 5 scanned ones; a PDF of page images
  only skips the hidden text check (no text at all). In the `inproc` mode the tools (hidden.py, assemble_md…) already
  run in the worker process; `stage_mode = "subprocess"` keeps a process per tool.

Where the score shows:

- the confidence and the score of every page — in `work\<DATE>\ocr\<tid>.json`;
- the score of a document — in `intake_quality.md`, in `meta_draft.jsonl` (`ocr_score`) and in `index\ocr_quality.tsv`
  (written by `apply`);
- `assistant-x build` puts it into `docs.ocr_score`; below 70 the search writes it into "Source quality".

Commands:

```
assistant-x intake ocr-score [CODE …] [--all] [--report file.md]
    score the library texts as they are (no OCR) → index\ocr_quality.tsv
assistant-x intake sample 20 [--seed S]
    random OCR pages (a third each of the worst, middle, good ones): PNG at 150 dpi, the library text
    and the new recognition side by side → debug\ocr_quality\sample
assistant-x intake redo CODE … | --worst N [--below 70] [--dry-run]
    recognize documents again (ocr_redo.py, work\redo\<date_time>); the text is replaced only when the
    vocabulary score grew by 10+ and the new text kept 80 % of the known words of the old one;
    every document is a row in intake_events.tsv, the report in reports\ocr_redo_*.md;
    after replacements — assistant-x build and assistant-x embed
```
## Journal and events

`index\intake_events.tsv` — all events of the intake (accepted, duplicate, rejected, to delete, error, to PDF, estimate,
archive); `index\manifest.tsv` — the truth about the files of the library (`manifest.py`). `journal.md` is built by
`python -m assistant_x.core.journal` (`--check`, `--stats`): the same table as before, size and hash come from the manifest when
an event lacks them, at the end a check against the manifest. Rows added to `journal.md` by hand are
moved into the events by `core/journal.py` (`assistant_x.intake.journal` is the same module). `assistant-x check` warns when the journal is behind.

## Hidden text in the whole library

`python -m assistant_x.intake.tools.hidden_scan` (in the background: `pythonw`) — `hidden.py` over every PDF of `library`, going on
from where it stopped; the result is `reports\hidden_text_<DATE>.tsv`, the progress and the result (the last line
"DONE …") in the `.log` beside it; `--status` — how many are checked; `--new` — a new pass only over the PDFs that were
not in the last finished one (under the machine lock; `set AX_PRIORITY=idle` — only when the PC is free). After a full
pass `--apply [--dry-run]` writes `file.hidden_text` into the cards, `assistant-x build` shows it in "Source quality". New
documents are checked at the intake (`prep`); the summary of a batch shows only the fragments that look like
instructions for an AI (a word of suspect_words of the language packs: ignore, instruction, assistant, prompt, system,
and their Russian counterparts, in a phrase addressed to an AI as the search marks it), the rest as a number.

## Tests

`.venv\Scripts\python -m pytest tests\intake` — the fast ones (unpacking, the meta schema, the draft, SQLite, the
journal, limits, build/apply and an interrupted apply in a temporary workspace) run in the pre-commit hook and in
`scripts\check.ps1 -Fast`; the end-to-end run of the pipeline (`-m slow`, about 40 s, LibreOffice and Tesseract when
present) separately. The tests never touch a real workspace.

**The golden corpus** ([`tests/corpus`](../tests/corpus)): 14 small synthetic documents made by code (a clean standard, two columns, a
table with a merged cell, a formula, a scan at 150 dpi, a noisy turned scan, a stamp over a scan, two editions of a
standard and a re-saved copy, a DOCX with heading styles, a journal issue, a drawing sheet, a book with a contents
page), each with what the intake must get: phrases on given pages, headings, the genre, the designation, the
duplicate verdict, the source text of its scans. `python -m tests.corpus.report [--full]` prints the metrics (phrase
recall, heading recall and precision, OCR character accuracy, verdict and metadata accuracy, seconds) and writes
`tests/corpus/last_report.json`; the fast mode (the text layer, the outline, the draft, the duplicate check) runs with
every test run, the full one (the whole intake) with the slow tests; neither may fall below
[`tests/corpus/baseline.json`](../tests/corpus/baseline.json), which only `--baseline` changes, on purpose.

## Other

- `python -m assistant_x.intake.manifest` — `index\manifest.tsv` (`--check`, `--dry-run`, `--root`).
- `hooks\pre-commit` — the check before a commit (copy it to `.git\hooks\`).
- `assistant_x\intake\tools\` — the tools a worker or a process runs (`dupcheck`, `hidden`, `hidden_scan`,
  `convert_md`, `assemble_md`, `reocr_empty`, `ocr_page`, `ocr_score`, `onnx_threads`, `unpack`; each
  also as `python -m assistant_x.intake.tools.<name>`); they take Tesseract from `TESSERACT`, the folders of
  `dupcheck` from `AX_TEXTS` and `AX_FP_CACHE` when given.

## The order of the work (`schedule.py`)

After its preparation every file has an estimate of its conversion: its text pages at 0.5 s and its scanned pages at
3.3 s (the speeds of the first real batch). The conversions go cheapest first, so a small file never waits behind a
big scan. A heavy task (an estimate of 15 min and more, more than 800 pages, a file that needed a bigger memory cap)
runs beside other heavy ones while their memory caps fit into 70 % of the free memory past the reserve of `balance.py`,
measured again at every start; while light work is left, one worker stays for it. The OCR of a long scan is cut into
page ranges (at least 40 scanned pages a range, at most one range a worker) that the pool runs as tasks of their own;
the conversion of the file then finds them in the cache and assembles the text. `ocr_shards = "off"` turns the
cutting off.

## Applying a batch from Claude: the plan, the token, `auto_apply`

`intake_apply()` builds the cards and returns the plan (what moves where, which codes) with a confirmation token;
`intake_apply(confirm=True, token=…)` applies it after the user's yes. A token is valid 30 minutes and once
(`server/confirm.py`). The transfer runs in the background as one job (`intake/apply_job.py`: build, apply, then the
base recalculation) and the answer comes at once ("The transfer started in the background: N documents…");
`intake_status` shows its stage (`build`, `apply`, `build_index`, `embed`) and the next step after it; a second call
while it runs says so. The plan itself stays a call that waits (build and `apply --dry-run`). `intake_reindex()` does
nothing when the base is up to date — no fragment without a vector, no text or card newer than the base — and says
when it was last recalculated (`reindex_last.json` beside the base: start, end, fragments, vectors per second, the
device); `intake_reindex(force=True)` runs it anyway. Claude writes the lines of `meta.jsonl` with `intake_save_meta(lines)`, or writes a file of lines
with its own file tools inside the folder of the batch and passes `intake_save_meta(path=…)` (the `meta.jsonl` of the
batch itself is checked as it is); `check_only=True` checks the lines with the file and writes nothing.

`auto_apply = true` in `[intake]` of `assistant_x.local.toml` (this PC, the user's own choice; never read from
`assistant_x.toml`, a package or a document): a batch whose check finds no error is built, applied and recalculated at
once, and the answer says "Applied automatically (auto_apply …)"; `changes.log` notes the call with `"auto": true`. The
plan and the token stay mandatory, `auto_apply` or not, when the batch
- replaces a document of the library or is another version of one (`replaces`, `other_version`),
- holds a duplicate of a document of the library (`dupof` a code, or the duplicate verdict of the intake),
- rejects a file (`drop`),
- holds hidden text addressed to an AI (the hidden text of a file with the words of `ai_phrases` or the names of the
  tools of the server).

## Taking a document out of the library

`assistant-x remove N-00268 [CODE …] [--why TEXT] [--dry-run]` (from Claude: `library_remove(codes, why)`, the plan
with a token, then `confirm=True` with it after the user's yes, run in the background) takes documents that got into
the library by mistake aside; nothing is deleted. For every code and the parts of a document of several files: the
originals of the manifest (a PDF copy too), the card and the text with `<code>.pages.json` and `<code>.hidden.json`
go to `inbox\_to_delete\removed_<code>_<date>\` under the same folders; the code leaves the `other_versions` of other
cards and `ocr_quality.tsv`; `intake_events.tsv` gets a row per file, "removed: <why>" (`event_kind` "removed": the
same file brought again is no duplicate); `manifest.tsv`, `journal.md`, `CATALOG.md` and `sources_to_update.md` are
made again; `index\codes.json` keeps the number reserved; `build_index` drops its fragments and vectors (no embeddings
are computed); `changes.log` notes it. A journal (`index\remove.journal.json`) lets the same command finish an
interrupted removal.

## Personal documents

The documents a user adds go by default into the same workspace, shelves and folders as an installed base package,
as if the user had filled it: `intake.personal` of their cards is false, there is no shelf of personal documents.
Only when the user asks to keep an addition apart is it marked: `assistant-x intake build --personal` (this batch;
the MCP command `intake_apply(personal=True)`), or `personal = true` in `[intake]` of `assistant_x.toml` (every
batch; `assistant-x init --personal`). The cards then get `intake.personal: true` and the search marks such a document
"personal document". The codes are the same either way, the next free one of the shelf: the codes of a shared base
package and of the user's documents are reconciled when the package is added ([ROADMAP.md](../ROADMAP.md), item 5), not by ranges of
numbers.
