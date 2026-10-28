English | [Русский](PACKAGES.ru.md)

# Base packages

A base package is a library made by one workspace and installed into another: the cards, the texts, the originals
and the embeddings of its documents in one file. A team builds its library once; every colleague installs it and
adds their own documents on top.

## Export

    assistant-x base export OUT.axbase --id oil-gas-norms --version 2026.10 [--name-en ... --name-ru ...]
                            [--about-en ... --about-ru ...]
                            [--include-personal] [--strip-names] [--no-vectors] [--codes default|reference]
    assistant-x base export --folder DIR ...        the same layout as a folder

- The library must pass `assistant-x check` first.
- `--codes reference` releases a reference base: its codes are meant to be the same for everyone who installs it, so
  colleagues cite the same codes; the install recommends keeping them. `--codes default` (the default): each installer
  chooses who keeps the codes, with no recommendation. `axbase.json` records it as `codes`.
- Personal documents (`intake.personal` of the card: `assistant-x intake build --personal`) stay out unless
  `--include-personal`.
- Every exported card names the package: `intake.package = {id, version, code}` (its code in the package; after an
  install the code in a library may differ). `intake.batch` is cleared (the batch folders are of the PC that made
  them); `source_name`, the name an original had before its intake, stays unless `--strip-names`. A card's
  `other_versions` that are not exported are dropped from the exported copy.
- The intake events keep only the date, the code and the status (no file names, no folders of the user).
- The vectors come from the vector cache ([`docs/SEARCH.md`](SEARCH.md)); the vectors of the base are put into it first. A PC with
  the same model (the same model fingerprint) installs the package without computing a single embedding.
- Never in a package: `assistant_x.toml`, `assistant_x.local.toml`, the debug journals, the query logs, the intake
  batches, the search base itself (the installing PC builds its own from the cards and texts).

A package is a zip file without compression (the PDFs are compressed already), with zip64 records when it is big.
A FAT32 flash drive takes no file over 4 GB: the export refuses to write a bigger package there and asks for
`--folder` (an unpacked package; inspect and install take a folder as well as a file).

## Inspect

    assistant-x base inspect PACKAGE [--keep own|package] [--json REPORT.json] [--no-verify]

What installing the package into this workspace would do; nothing changes. The exit code is 1 when the install
could not start. The JSON report (for Claude) has:

- `problems` — what stops the install: another card schema or text format; files that do not match their checksums;
  cards that do not pass this workspace (its card languages, its shelves, its controlled topics: a package whose cards
  lack a language this workspace reads documents in); an intake batch built but not applied, or an apply
  interrupted, or an intake running; a document path over 255 characters while long paths are off in Windows; too
  little disk space (the package, the base built anew, the embeddings to compute, plus `[intake.disk] min_free_gb`).
- `warnings` — an app holds the library now (its search server runs: the install has it release the files it moves);
  the workspace is in OneDrive; the package was made by a newer version; the package is installed already.
- `compatibility` — format, card schema, text format, chunk version; profile, card languages and topics of the package
  and of the workspace. An empty workspace takes the profile and the card languages of the package (`adopt`).
- `matches` — package documents that look like documents of the library and what happens to them, by rule, with no
  question (`inspection.classify`): the same file (sha256) — the library's stays; the same content (the duplicate
  check finds 90 % of the phrases, and the same designation without its year, or neither has one) — the higher
  recognition score stays, a tie keeps the library's; another edition of the same designation — the newer one stays
  (the year of the designation, else of the card; unknown or equal: the library's). The other one is never deleted:
  its original, card and text go to `inbox\_to_delete\merged_<date>` (a package document's under `package <id>`
  there), its code is never given again, and the report lists every pair. When the library keeps its numbering, a
  package document that wins takes the code of the library document it replaces (the same shelf). Anything less (a
  similar title, a partial overlap) stays as two documents (`separate`).
- `codes` — the facts of the codes: the documents on each side, the codes that collide, the new codes they would get
  (the next free numbers above both sides and the marks of `index\codes.json`), and the two options: `package`
  (keep the codes of the package; the colliding documents of the library get new codes) and `own` (append the package
  after the numbering of the library; its colliding documents get new codes). The user chooses (`--keep`, or the
  answer `codes`). A reference package (exported with `--codes reference`) recommends `package` and takes it when
  nobody answered (an install without a window); a package with default settings recommends nothing, and an install
  without the choice does not start. An empty workspace takes the package's codes as they are, no question. An update
  of a package never renumbers the documents of the library: a new package document whose code is taken gets a local
  code, its package code stays in `intake.package.code`.
- **A number never comes back.** A package code at or below the mark of its letter in `index\codes.json` that no
  document of the library has now was given here once, to a document since removed; an old citation of it must not
  name another document. Such a code is listed in `codes.retired` with the new code the package document gets (the
  next free number), whoever keeps the codes, at an install and at an update. Two exceptions: the number belonged to
  the same document of the same package before (its events say "installed from package <id>" under that code), and a
  reference package whose numbering is kept (`package`): then the codes are reused as the reference gives them and
  listed in `codes.reused` (the report and inspect name them, so the user knows that old citations of those numbers
  now name the package documents).
- `embed` — whether the vectors of the package fit the model here (the same model fingerprint), and how many
  fragments would be computed, with the time on this PC's processor and video card when measured.
- `paths`, `disk` — the longest path a document would get, the space needed and free.
- `questions` — what Claude asks the user, as data (no sentences: Claude phrases every question in the language the
  user writes in, with the consequence of every option): only `codes`, when codes collide, with `recommended`
  ("package" or null), `collisions`, `new_codes` and `consequences`.

## Install

    assistant-x base install PACKAGE                   the plan of inspect; nothing changes
    assistant-x base install PACKAGE --confirm [--keep own|package] [--answers answers.json] [--own-apart]
    assistant-x base install PACKAGE --resume          go on with an install that was interrupted
    assistant-x base install PACKAGE --rollback        undo an install that was interrupted

`answers.json` holds the answer to the question of inspect: `{"codes": "package" | "own"}` (the same as `--keep`).
`--own-apart` marks the documents of this library personal: nothing moves, the search filter tells them apart.

The install is a transaction with a journal (`.assistant_x\w\<8 characters>\install.journal.json`, a short folder so
the deep paths of the library fit under it). It holds the machine lock, the lock of the intake (`intake.lock`) and the
lock of the code numbers. Its steps:

1. **marker** — `.assistant_x\db\maintenance.json`: a running search server lets the originals go (Windows refuses to
   rename an open file) and answers page images "being changed"; the search itself answers on.
2. **backup** — the small files of the index (cards, tables, views, packages.json, the settings, questions.md,
   eval_baseline.json; not the texts: the renames are undone from the journal) into `.assistant_x\backups`.
3. **extract** — every name checked first (no `..`, no absolute path, no link, no device name, no `:`, no trailing dot
   or space, no two names equal but for the case, NFC, stored entries only), then extracted at its declared size and
   checked against `CHECKSUMS.sha256`.
4. **plan, aside, renames** — the code plan of inspect with the choice of the codes and the merges by rule; the
   document that lost a merge goes to `inbox\_to_delete\merged_<date>`; the documents that get new codes are renamed
   in two phases (every file to a
   temporary name, then to its new name, so a swap of two codes works). A file another program holds is tried again;
   then the install stops with its journal (`--resume` once Claude is closed).
5. **cards, package, place** — the renumbered cards, manifest rows (no file hashed again), recognition scores,
   questions.md and eval_baseline.json, the fingerprints of the duplicate check; the package's skipped documents out,
   its renumbered ones renamed in the work folder; then its documents moved into `library\` and `index\`.
6. **tables** — events (`installed from package <id> <version>`, `renumbered: A -> B`), the marks of the code numbers,
   `packages.json`, the profile and card languages of the package for an empty workspace, the catalog, `manifest.tsv`,
   `journal.md`.
7. **build, vectors, base** — `build` (the base updated; built anew only when it is of another schema; a failed build
   stops the install with its journal); the package's vectors into the vector cache when they are of the model here,
   checked (see "Trust" below); `embed` (from the cache; what it lacks waits for the model: the search goes by words
   for those fragments until `assistant-x embed` has run), `check`.
8. **report** — `reports\base_install_<id>_<time>.md`; the marker removed, the work folder emptied.

A second install of the same version changes nothing. `--rollback` moves every noted file back in the reverse order,
restores the small files of the backup, removes the marker and asks for `assistant-x build`.

## Trust: what is checked in a package received from someone else

A package is data from someone else, and the product treats it so. Before anything changes:

- **the manifest** — every string of `axbase.json` that may reach a path, the settings or a report is validated
  (`id`, `version`, `codes`, `profile` among the profiles of the program, `card_languages` among its language packs,
  `name`, `about`, `docs`, `embed`); a package that fails is refused. The values an empty workspace takes into
  `assistant_x.toml` are written escaped, and the paths of programs are never read from the shared settings file;
- **the files** — every entry name (no `..`, absolute path, drive, colon, link, device name, compression, case clash),
  the size of every file and every checksum;
- **the cards** — the schema of the workspace, in the form the install writes them, and every path they name: under
  `library/` or `index/texts/`, nothing else; every move and removal of the install is checked to stay in the
  workspace;
- **the vectors** — the three files together, `meta.json` against the manifest, the sizes against the rows and the
  dimension, the dimension against the model here, unique keys, every vector finite and of length 1. After the
  build, only the keys of fragments of the package's own documents that have no vector yet are taken (a vector of
  another fragment, a user's above all, is never set by a package), and when the embedding model is on this PC a
  random sample of them (5 %, at least 32 — every one of a small package —, at most 256) is encoded again: one with
  a cosine under 0.99 drops every vector of the package (`embed` computes them). Without the model the sample is
  skipped and the report says so.

What is not guaranteed: the texts and cards of a package are what Claude reads, so a package may carry wrong content
or text written to steer Claude (the destructive commands of the server need a confirmation token for that reason:
[SECURITY.md](../SECURITY.md)); vectors that pass rank the package's fragments by what the model sees in them.

## Update and remove

    assistant-x base update PACKAGE [--confirm] [--resume | --rollback]
    assistant-x base remove ID [--confirm] [--resume | --rollback]

An update takes a new version of an installed package (the same id) and matches its documents with the ones the
library has by the package id and their code in the package (`intake.package.code`), whatever their code here:
unchanged (the same original, text and card) — only the version in the card changes; changed — the old files go to
`inbox\_to_delete\updated_<id>_<date>` and the new ones come under the code the document has here; new — under its
package code when it is free here and was never given here to another document (a reference package keeps it and
the report lists the reuse), else the next free code of its shelf (the package code stays in
`intake.package.code`); removed from the package — to `inbox\_to_delete\removed_<id>_<date>`. The documents of the
library that are not of the package never change and are never renumbered. A remove puts every document of the package
into `inbox\_to_delete\removed_<id>_<date>` and forgets the package. Both are transactions like the install (marker,
backup, journal, `--resume`, `--rollback`), then build, embed and check; without `--confirm` they only tell the plan.
The numbers of removed documents are never given again.

## From the chat

The server has the commands `base_export(out, id, version, codes, …)`, `base_inspect(path)`, `base_install(path,
confirm, answers, keep, own_apart, resume, rollback)`, `base_update(path, confirm, …)`, `base_remove(id, confirm, …)`,
`base_status()` and `base_list()` (`server/base_tools.py`). The check and the install run in the
background like the intake (`.assistant_x\work\_claude\base_*.log`); `base_status` shows how far they are, the
questions of the check with their ids and the report of the install. The skill tells Claude the flow: "AX: install
the base <path>" → `base_inspect` → the questions to the user → `base_install(confirm=True, answers=…, token=…)`
after an explicit yes → `base_status` → the report; and "AX: make a base package" → the question "a reference base or default
settings?" → `base_export`. The commands return facts and options; Claude asks and summarizes in the user's language.

The commands that change the library (`base_install`, `base_update`, `base_remove`, and `intake_apply` of the
intake) take two steps (`server/confirm.py`): the plan call (without `confirm`) answers with a token, valid 10
minutes, for that action and that package or id in that workspace, once, and bound to the package file of the plan
(its manifest and checksums) or the installed entry of the id; the `confirm=True` call must give it back. A call
with `confirm=True` alone, which a text inside a document or a package could ask Claude for, changes nothing, and a
file replaced at the same path after the plan is refused. Where the client supports MCP elicitation, the server asks
the user itself before the change. Every such call, planned, refused, declined or started, is a line of
`.assistant_x\debug\changes.log`. [SECURITY.md](../SECURITY.md) says what the token does not prove.

`search_library` and `list_documents` take `scope`: `"all"` (the default), `"own"` (documents of this library, not of
a package), `"package"` (documents of installed packages: `intake.package` in their card), `"personal"` (the
documents kept apart: `intake.personal`, e.g. after `--own-apart`). Nothing of the search base changes for it.

## Format "axbase/1"

    axbase.json          what the package is (below)
    README.txt           how to install it, in every language whose pack has the text (lang/<code>/package.json)
    cards/<code>.json    the cards
    texts/<code>.md      the texts and their <code>.pages.json (part texts <code>-NN.md)
    library/...          the originals and their PDF copies, by shelf, as in a workspace
    vectors/             meta.json {dim, fingerprint, model, max_seq_length, table_rows, rows}, keys.bin (16 bytes
                         per row), vectors.f16 (float16, normalized): the vector cache of its fragments
    events.tsv           date, code and status of the intake events of its documents
    ocr_quality.tsv      the recognition scores of its texts
    CHECKSUMS.sha256     "sha256  path" of every other file

`axbase.json`: `format`, `id`, `version`, `codes` (`default` or `reference`), `name` and `about` ({language: text}),
`created` (the date it was made; a package carries nothing of who made it), `requires` {`app`, `card_schema`, `text_format`}, `chunk_version` (informational: the base is
built anew on the installing PC), `profile`, `card_languages` (every card has its texts in these), `topics` and
`topics_controlled` (the controlled list of the profile, or the topics the cards use), `languages` (of the
documents), `embed` (the meta of the vectors, or null), `shelves` {letter: documents}, `documents`, `bytes`, `docs`
[{`code`, `sha256` of the original, `card_sha`, `text_sha`, `parts`}].
