# Assistant X search

The local search through which Claude works with the library: by words with stemming and a dictionary of
abbreviations, by meaning (the model bge-m3) and with reranking of the best fragments (bge-reranker-v2-m3).
Claude connects to it as to an MCP server `assistant-x` and gets the commands `search_library`, `read_pages`,
`page_image`, `book_map`, `verify_quote`, `document_info`, `list_documents`, the base packages `base_*` and the intake commands `intake_*`
([`assistant_x/server/intake_tools.py`](../assistant_x/server/intake_tools.py)).

In short: after the intake has added documents, `assistant-x build` updates the base and `assistant-x embed` computes
the embeddings of the new fragments (the MCP command `intake_apply(confirm=True, token=…)` runs both).

## Where things are

```
<code folder>\              the program: assistant_x\ (the package), Setup.bat, intake.bat, assistant-x.bat (a
                            development checkout keeps .venv\ here)
<workspace>\                your data (Documents\Assistant X by default; assistant-x init makes it)
  assistant_x.toml          settings ([search], [intake], [paths]); assistant_x.local.toml: this PC only
  library\                  the originals (for page_image)
  index\                    cards\<code>.json, texts\, CATALOG.md and sources_to_update.md (made from the cards)
  questions.md              your own control questions for assistant-x eval (optional)
  .assistant_x\
    db\                     library.sqlite (catalog + fragments + word index), vectors.f16 (embeddings)
    db\vector_cache\        the embeddings by content: a fragment the model has read once is never computed again
    models\                 only in a workspace of before 2026-10-25 (or a link): its models
    debug\                  journals of failures and calls, debug reports, query reviews
%USERPROFILE%\.assistant_x\  per PC: app\<version> and venv\ (the program, from a medium), models\ (bge-m3,
                            bge-reranker-v2-m3, onnx\: everything works without internet), programs\ (of the
                            intake), the machine lock heavy.lock and its journal heavy.log, mcp_server.lock,
                            speed.json, model_fingerprints.json
```

Which workspace a command uses: `AX_WORKSPACE`, else the folder of `AX_CONFIG`, else the nearest folder with
`assistant_x.toml` from the current folder up, else `Documents\Assistant X` ([`assistant_x/core/workspace.py`](../assistant_x/core/workspace.py)). The
synonyms come from the domain profile ([`assistant_x/profiles/oil-gas-ru/synonyms.txt`](../assistant_x/profiles/oil-gas-ru/synonyms.txt)) unless `[search] synonyms`
names your own file. [`assistant_x/core/formats.py`](../assistant_x/core/formats.py) holds the formats of the project files (page markers, events, the
kinds of files by extension);
the cards are [`assistant_x/core/card.py`](../assistant_x/core/card.py) and the JSON Schema [`assistant_x/schemas/card-1.json`](../assistant_x/schemas/card-1.json) ([docs/INTAKE.md](INTAKE.md), "Cards").

## Build (once, then after every intake)

[`Setup.bat`](../Setup.bat) does steps 1 and 2 ([`docs/INTAKE.md`](INTAKE.md) for the intake itself); the apply of an intake offers the rest.

1. Python 3.11+ and the package with the search by meaning: `pip install -e ".[dense,intake]"` in the code folder.
   An RTX 50xx needs a PyTorch build with CUDA 12.8+, installed first:
   `pip install torch --index-url https://download.pytorch.org/whl/cu128`. Without the extra `dense` the search works by
   words only.
2. `assistant-x download-models` — the models into `.assistant_x\models` of the workspace (≈ 4.5 GB, once).
3. `assistant-x build` — the base and the word index, and `CATALOG.md` and `sources_to_update.md` made again from the
   cards. Updates only the changed documents: in a text whose sha256 (with its `.pages.json`) changed only the pages
   whose text or fragments changed are chunked again — the fragments of the other pages keep their numbers and
   embeddings, so a page fixed by hand costs the embedding of that page only; a card whose sha256 changed
   (`docs.card_sha`) is read again; `--full` rebuilds everything. First it runs the index check (`assistant-x check`,
   see "Index check") and stops on errors in the cards. No cards give an empty base.
   If the program changed the format of the base (the last time: the pages and the exact index, base schema 3,
   October 2026), it asks for `--full` itself.
4. `assistant-x embed` — embeddings for the new fragments (on the video card, float16) and an update of the FAISS index.
   After replacing many documents: `assistant-x embed --compact`. After `assistant-x build --full` the embeddings come
   from the vector cache (below) and the model is not even loaded when every fragment is there. A full build writes a new file `.assistant_x\db\library-<time>.sqlite`, and the search keeps using
   the previous base to the end: the new one waits for its embeddings (its name in `library.next`), and `embed`, when it
   has computed them, switches the search to it (`library.current`); the old file is deleted once nobody holds it. The
   base is in WAL mode: the search reads while the build writes.
5. `assistant-x eval` — a check on your own control questions (`questions.md` in the workspace: a table
   `| question | code:pages; … |`, groups by `## headings`): a table of metrics by group (document and page in the top
   10, MRR, all places of the answer). `--fast` — by words only, without the model; `--check` compares with the saved
   run `eval_baseline.json` and exits with an error when worse, `--save` writes a new run.
   A row may carry a third cell: an exact phrase of the answer page in quotes,
   `| what is the allowable gas velocity? | L-00015:12 | "the allowable velocity of the gas" |`. The column "Quotes"
   shows the share of such questions whose phrase stands on an answer page among the top results (compared by the
   skeleton of `verify_quote`, below); `--check` and `--save` include it. Two groups
   are worth writing besides the questions of your topics:
   - `## Designations` — questions that name a document or a grade by its designation, in the spellings users type:
     `GOST 1510-84`, `GOST R 51858-2002` in either script, a steel grade with Latin look-alike letters, a code with a hyphen or a slash;
     the answer is the page where the designation stands.
   - `## Quotes` — questions with a phrase in the third cell, taken word for word from the answer page (a sentence of a
     clause, a row of a table): they show that the text of the page is found and read exactly, not only its topic.

Check the search by hand: `assistant-x search "glycol carry-over from the absorber"` (`--section N`, `--code L-00015`,
`--doc-type handbook`, `--lang ru`, `--rerank`).

## Index check and the state of the library

- `assistant-x check` validates every card against the schema (the languages every text needs, the shelves, the
  limits) and compares the cards, texts and originals: a card that is no JSON or whose file name is not
  its code, no text of a document or of a part its card names, no original at its place in the library, one file for
  two documents, and the text format ([docs/INTAKE.md](INTAKE.md) "Text format"): page markers out of order or not one for every
  page of the original PDF. Errors stop `assistant-x build`; warnings (texts with lost symbols, empty pages, extra
  texts, other versions not in the library, CRLF line ends, invisible characters, a `.pages.json` missing or with
  other pages than its text) are only listed. `--all` — all cases, `--no-files` — without checking the originals.
- At the build the base remembers the language of a text and its quality (a scan, lost symbols, empty pages, the
  recognition score from `index\ocr_quality.tsv` — the column `docs.ocr_score`, below 70 it goes into the note), and
  the open issues of its card. Claude sees this next to a fragment and in `document_info` as the line
  "Source quality".
- `assistant-x report` ([`scripts\library_report.bat`](../scripts/library_report.bat)) once a month: a summary by section, the index errors, the text quality, texts worth recognizing again, open items to update, books
  without a table of contents in the map, editions before 1990 and the manifest of the originals. The report goes to
  `.assistant_x\debug`.
- `python -m assistant_x.intake.manifest` keeps `index\manifest.tsv`: the path, size, date and SHA-256 of every file of `library` with
  its code. Update it after new documents are applied; `--check` recomputes all hashes and shows damaged or missing
  files (e.g. after a restore from a backup).

## Connecting by hand

If the installer does not fit: Python 3.11+, `pip install -e ".[dense,intake]"` in the code folder (no video card
needed; the usual PyTorch is installed), `assistant-x init` and `assistant-x skill`. Reranking (`"rerank"` in `assistant_x.toml` `[search]`) is `"auto"` by default: every question on a video card
(CUDA or DirectML), when the model `bge-reranker-v2-m3` lies in `models`. Its score refines the hybrid order instead of
replacing it (`final = fused / max(fused) + rerank_weight · sigmoid(logit)`, `rerank_weight = 1.0`): replacing it
made simple questions worse (MRR 0.69 → 0.59 on the questions of the predecessor; 0.687 → 0.824 on the stand of
[`tests/search/quality.py`](../tests/search/quality.py) once fused). Without a video card it takes seconds per question and does not switch on;
`true` / `false` — always / never.

**Claude Desktop:** add to `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "assistant-x": {
      "command": "C:\\Assistant_X\\.venv\\Scripts\\python.exe",
      "args": ["-m", "assistant_x.server.mcp_server"],
      "env": { "HF_HUB_OFFLINE": "1", "AX_WORKSPACE": "C:\\Users\\you\\Documents\\Assistant X" }
    }
  }
}
```
**Claude Code:** `claude mcp add assistant-x --scope user -e HF_HUB_OFFLINE=1 -e "AX_WORKSPACE=<workspace>" -- "<code folder>\.venv\Scripts\python.exe" -m assistant_x.server.mcp_server`

After a restart of Claude the library commands appear in the list of tools.

The server loads the embedding model in the background (about 10 s, with a trial query to warm up the video card).
While it loads, `search_library` answers at once, by words only, with the note "the semantic search is still loading,
repeat the query in 10 s".

## When something breaks: the debug report

- All failures of the server and the scripts go to `.assistant_x\debug\failures.log` (with the traceback), every call of a
  library command goes as a line to `calls.log` (time, duration, result, arguments). The files trim themselves to 1–2 MB.
- When a command fails, Claude gets not a bare "Error executing tool" but the text of the error and a hint how to
  make a report.
- **The report:** double-click [`scripts\debug_report.bat`](../scripts/debug_report.bat). After 1–2 minutes `debug_report_<PC id>_<date>.md` appears in
  `.assistant_x\debug`, the folder opens by itself. This file is what to send. A quick variant without loading the models:
  `scripts\debug_report.bat --quick`.
- In the report: the PC (OS, processor, memory, disks, video card), Python and the package versions, whether torch sees
  the video card, the installation files with checksums (shows which version is installed), assistant_x.toml and a check of
  all paths, the state of the base and the embeddings, the connection in Claude Desktop and its journal about
  assistant-x, a self-test of every search layer with its time (words, meaning, reranking, page image, starting the
  MCP server), the last failures and calls, and on top a list of the problems found.
- What the report does not hold: the content of documents and other settings of Claude (other servers show only their
  names). It holds the names of the PC and the user, paths and the texts of the last queries to the library.
- If Python is not found on the PC, the window says so: then a screenshot of the window is enough.

## Query review: learning from real questions

[`scripts\query_log.bat`](../scripts/query_log.bat) (or `assistant-x query-log [journals of other PCs…]`) creates in `.assistant_x\debug` the file
`query_log_<PC id>_<date>.md`:
- a summary by command: how many calls, failures, how long they took;
- **weak queries**: the best fragment by meaning is closer than 0.5 or nothing was found by words. These are candidates
  for new documents or for new lines in `synonyms.txt`;
- **long searches**: 4 or more searches in a row on one question, i.e. what was needed was not found at once;
- slow calls, all queries and a draft of lines for `questions.md` (the answer, i.e. the code and pages, is filled in by
  a specialist, after which the question takes part in `assistant-x eval`).
The same summary is part of the debug report. Entries without the closeness and the number of
matches count only in the overall figures.

"Low closeness" above the results of `search_library` says the library may not cover a question. Two tests: the
closeness of the best fragment by meaning below the threshold (and the reranker not sure either), or half the content
words of the question (stop words aside, stemmed as in the word index, a synonym counting as the word) in none of the
5 best results ("the library has nothing on «…»"). The threshold is `[search] weak` when it is set; else, once the
journal of this PC holds 30 answered questions, the 10th percentile of their closeness, within 0.35–0.6 (computed once
per server start); else 0.5.

## How it works

- The base (schema 3) holds the text of every page exactly as `index\texts\<code>.md` has it (the table `pages`,
  with the printed label, source, recognition score and flags of its `.pages.json`, [docs/INTAKE.md](INTAKE.md) "Text format").
  `read_pages` gives it back unchanged, and a found fragment shows the very text of its page. A hit and
  `read_pages` show the printed page from the page labels of the PDF (`p. 218 (PDF 222)`; without labels the
  page numbering of the card) and a line "Page:" for a page with a complex table or a poor recognition.
- The text of every page is cut into fragments of 1–2 paragraphs (a Markdown table stays whole); a fragment does not
  cross a page boundary, so a reference is always exact. A fragment is a range of characters of its page
  (`chunks.start`, `chunks.end`): the fragments of a page in order are the page itself. The text a fragment is
  searched and embedded by differs from its page text in three ways only: its section heading goes before it; a
  piece of a long table cut by rows is led by the header of the table, and a piece of a long text cut in two by the
  last sentence of the piece before it (`chunks.lead`: in the search text, never in the page or in the results); the
  embedding takes the text without the Markdown marks (`**`, `#`, backticks; `[search] table_rows = true` in
  assistant_x.toml also turns a table into a line per row "header: value; …"). A card and a unit have a text of
  their own (`chunks.own_text`).
- Every fragment remembers the section it stands in: the chain of numbered headings and the last plain one
  ("11.9. Estimate of actual losses / 11.9.2. Losses at outflow…"). The headings come from the Markdown markup;
  repeated running headers, tables of contents and empty headings like "Solution" are skipped. The section takes part
  in the search by words and by meaning and is shown to Claude in the results, so a paragraph deep in a chapter is
  found by its topic too.
- Search by words: SQLite FTS5 over word stems (Snowball, the stemmers of the language packs: Russian and English) +
  the groups of `synonyms.txt` of the profile. The word index has a second column, `exact`: the whole tokens of the
  text in lower case, a designation one token with its hyphen, dot or slash (`1510-84`, `51858-2002`, `5.3`), the
  letters of two scripts that look alike as one (`homoglyphs` of the language packs: a Latin X, H or T in a Cyrillic
  steel grade). The designations of the cards a question names, its phrases in quotes and its codes with digits
  (`GOST 5632-2014`, `12X18H10T`) are looked for there as phrases, beside the stems: `stem : (…) OR exact : (…)`.
- Too frequent words of a query (in more than 5 % of the fragments, e.g. "oil", "calculation") do not go into the
  search by words: they hardly affect the ranking but slow it down many times on a big base (`common_term_share` in
  assistant_x.toml).
- Search by meaning: cosine closeness to the vectors of the fragments (`vectors.f16`, float16). Below 200 thousand
  fragments it is an exact scan; above, `assistant-x embed` builds a FAISS index itself (`vectors.f16.ivfpq.faiss`, needs the
  package `faiss-cpu`): the candidates come from the index and are recomputed exactly. A filter (codes, sections,
  genres, languages, years) is applied before the search: up to 100 thousand fragments it lets through are compared
  exactly, more are searched inside the index among them only (FAISS `IDSelectorBatch`).
- The lists are mixed (Reciprocal Rank Fusion); the best max(50, 4k) are the pool: the second model reranks them, then
  one document gives at most 3 pages of the results, so that different sources are visible. A designation named in
  the question puts its card first after the reranking. The embedding model and the reranker read the same text of a
  fragment (`common.model_text`: the short title of the document, the section heading, the text without Markdown).
- The cards are fragments too (`chunks.kind`): the card of every document, a fragment per language of the card
  (`card`: its designation, title, keywords and terms in that language, the scope and the summary, page 0), one of its
  questions and topics (`card_q`, weight 1.0: `[search] card_q_weight`; together with the `card` ones a single result
  of kind `card`), and the units of a journal
  issue or proceedings (`unit`: the title, authors and summary of an article, at its first page). So an English
  question finds a Russian document by its card and the other way round; a card counts with the weight 0.7
  (`[search] card_weight`), since it cites no page, and is shown as `[code, card]`.
- A designation named in the question (`GOST 1510-84`, `ГОСТ 1510-84`, in any spacing or dash) puts the card of that
  document first; the terms of the cards (an abbreviation, its name in every language, its expansion) join the synonym
  groups; a fragment inside a chapter of the contents of its card (the table `toc`, with the last page of every entry)
  whose title shares half of the words of the question is raised by a quarter (`[search] toc_boost`).
- Filters: section (the shelf, by its letter, its folder or its name in English or Russian, so "Datasheets" also finds
  "Datasheets and catalogs"), codes, genres (`doc_types`), languages of the documents (`langs`), years.
  Whether a document is in force is not the matter of the search: the library holds the versions the user chose (a
  card names the other versions kept beside it).
- The designations a card refers to go into the table `links` with the code of the document of the library that has
  that designation (empty when the library has none).
- A document of several files (its card has `file.parts`): the file of the card and the text `<code>.md` are the
  document itself (file -01 of its folder), the other files are parts with their own code `<code>-NN`, their own text
  `<code>-NN.md` and their own PDF page numbering. In the results and references a part is named the same way:
  [E-00006-02, PDF 3]. A filter by the code of a document searches its parts too; `list_documents` shows only
  documents, `document_info` of a part shows the card of its document.
- `verify_quote(code, page, text)` checks a quote before Claude puts it in quotation marks (the skill asks for it
  before a verbatim quote and before a number taken from a table): the quote and the page are compared by their
  skeleton (`common.skeleton`: NFKC, lower case, the folding of the languages and of look-alike Latin and Cyrillic
  letters, every dash as "-" and every quote as a double quote from the tables `dashes` and `quotes` of the language
  packs, the soft hyphen and the Markdown marks dropped, white space collapsed), on the page, then on the one before
  and the one after it. Word for word: "found" (or "found_nearby" on a neighbouring page, which is then the one to
  cite); else the closest run of words of the three pages by `difflib.SequenceMatcher`: a similarity of 0.9 or more is
  found with small differences (the differences are listed, e.g. «450» → «400»), less is "not found" with the closest
  place, and the quote goes into the answer as a paraphrase. The answer also carries the printed page and a "Page:"
  line for a complex table or a poor recognition of that page.
- `page_image` takes the page image from library (the PDF copy of a DOC/DOCX beside it), and if the document has not
  been moved yet, looks for a file with the same name in the whole library. A DOC/DOCX needs a PDF copy with the same
  name beside it.
- The book map (`bookmap.py`, since 2026-10-22; the outline is read from the text by `core/textmap.py`, which the
  intake uses for the contents of a card too): at the build every document remembers its table of contents (numbered
  sections and chapters with PDF page ranges) and where its tables, figures, formulas and appendices are (the caption
  "Table 4.2", the formula number "(12)" at the end of a line, the first place outside the table of contents). The
  captions and reference words come from the language packs (`lang/<code>/references.json`: "Table 4.14", "see
  table 4.14", "formula (9.8)", "see fig. 1.5", "cl. 5.3" and their Russian forms). When a
  found fragment refers to one, the results get a line "References: … → PDF N", and Claude reads the needed page too.
  The command `book_map` (and `python -m assistant_x.search.bookmap L-00015 --page 300`) shows the table of contents around a page and what
  lies in its section. The map is built from the base, without models, in minutes; scans with a poor recognition get a
  poorer table of contents.

## Performance (measured 2026-10-20 on a test library)

Then: 24 documents (0.76 GB of originals) = 9.2 thousand pages = 26 thousand fragments. 200 GB is roughly 2.4 million
pages and 7 million fragments (more when many PDFs have a text layer: they hold more text per megabyte).

| What | 26 thousand fragments | 1 million (measured) | 7 million (estimate) |
|---|---|---|---|
| Search by words | 0.01–0.04 s | 0.1–0.2 s (before the fix 0.6–1.5 s) | ~1 s |
| Search by meaning, exact scan | 0.04 s | 3 s | 20+ s — not usable |
| Search by meaning, FAISS | — | 3 ms | ~5–10 ms |
| Base library.sqlite | 53 MB | 2 GB | ~14 GB |
| Embeddings vectors.f16 | 54 MB | 2 GB | ~14 GB (+0.5 GB index) |
| Computing the embeddings on an RTX 5080 | 11 min fp32, 3.5 min fp16 (measured) | ~7 h fp32, ~2 h fp16 | ~2 days fp32, ~14 h fp16 |

Measured on a virtual machine with 4 cores; on a desktop PC the search by words was 2–3 times faster. fp16 on the PC: 3.4 times faster
than fp32 (61 against 18 fragments/s on the longest fragments), the vectors match fp32 (cosine ≥ 0.99997, more precise
than the float16 storage itself). On the PC (26 thousand fragments): the first query ~7.6 s (loading the model), then
0.06 s; by words only 0.002 s.

### The cost of a question (profiled 2026-10-26)

A synthetic library of 3000 documents of 9 pages (36 138 fragments), an RTX 5080 Laptop with CUDA (shared with
another server holding 7 GB of it), the reranker on, `k = 8`; 1000 random questions of 2–6 words after the warm-up
(17 s: both models), `Library.search` profiled with cProfile over the first 100:

| Measure | Value |
|---|---|
| Latency | p50 900 ms, p95 976 ms, max 1.9 s |
| The reranker (50 candidates, `POOL`) | 0.80 s of 0.885 s per question (90 %); most of it is waiting for the video card where the batches go to and come back from it |
| The search by meaning (query embedding + FAISS) | 0.07 s |
| The search by words and the scoring of the rows | 0.05 s |
| Memory of the process (RSS) | 2533 MB after the warm-up, 2564 MB after 100 questions, 2574 MB after 1000 |

The memory grows while the caches fill (the first ~100 questions) and then stays flat: no leak. The reranker is what a
question costs; `rerank = false` (or `"auto"` on a processor) answers in about 0.1 s at the price of the order of
the hits. The ranking was not changed for this measurement.

## AMD and Intel video cards: DirectML (`onnx_models.py`)

`assistant_x.toml` `[search]`: `backend` — `auto` (default: CUDA when present; otherwise DirectML on a non-NVIDIA video card with 2 GB of
its own memory or more; otherwise the processor), `torch` (torch only), `onnx-dml` (DirectML always, when the package
and the models are there); `dml_device` — the number of the DirectML adapter (`python -m assistant_x.search.onnx_models --adapters`;
numbered by performance: the discrete card first). The ONNX models (fp32, 2.1 GB each) are
`.assistant_x\models\onnx\<model>\model.onnx` + `.data`; build them with `python -m assistant_x.search.onnx_models --export` (under the
lock, ≈30 s; needs the extra `export`: onnx and onnxscript, offline from `.assistant_x\packages\wheels_dml`). The ONNX vectors match torch (cosine 1.0000 on 100
fragments, ≥ 0.9997 to the base), so the base is shared. The package `onnxruntime-directml` replaces `onnxruntime`
(`install.py` does it itself when it chose DirectML).
Measured on 2026-10-24 (100 fragments / a query / the reranker on 50 candidates): CUDA fp16 1.2 s / — / 0.34 s; DirectML on
an RTX 5080 6.8 s / 89 ms / 2.0 s; DirectML on an integrated Intel (Core Ultra 9 275HX) 121 s / 327 ms / 25 s; the processor
93 s / 62 ms / 28 s. The control questions through DirectML without CUDA — as on CUDA (97 % / 86 % / MRR 0.66).

## The vector cache (`vector_cache.py`)

`.assistant_x\db\vector_cache\` keeps every vector `embed` has computed or found in the base, under the key
sha256(model fingerprint, kind of the fragment, the text the model reads of it — `common.model_text`). A fragment
whose text did not change takes its vector from there: after `build --full`, after documents got new codes (a base
package installed), in a new base of the same workspace. The vectors of a base embedded before the cache existed are
put into it by the first `embed` (once: `meta vector_cache_seeded`), or by `assistant-x embed --seed-cache` alone;
never under the key of another model (the name, or `meta embed_fingerprint`, differs). `embed --compact` also drops the
cached vectors no base uses any more.

The model fingerprint names the vectors a model gives: its name, the sha256 of its `config.json` and `tokenizer.json`,
the sha256 of its weights (the one HuggingFace wrote beside a download in `.cache\huggingface\download`, else hashed
once and kept per PC in `%USERPROFILE%\.assistant_x\model_fingerprints.json`; nothing is ever written into the model
folder) and `max_seq_length` (a text cut at another length gives another vector). A base remembers it
(`meta embed_fingerprint`); a base package carries it with its vectors.

## One base, one model; int8 on the processor (`models.py`)

A base is embedded by one model forever (`meta embed_model`, the name of the model folder, e.g. `bge-m3`): a library
you build and a library you install and extend mix their vectors, so `assistant-x embed` refuses to add vectors to a
base of another model ("The base was embedded with X, this workspace is set to Y; one base, one model."), and the
search reports it and answers by words. The speed-ups keep the vectors: float16 on a video card, DirectML, and on a
processor bge-m3 in int8 ONNX (`python -m assistant_x.search.onnx_models --int8` writes
`models\onnx\bge-m3\model.int8.onnx` and checks it at once: 200 fragments of the base, or the sample sentences of the
language packs, must keep a mean cosine of 0.99 to the float32 vectors and 0.97 each, or the file is deleted;
`[search] cpu_int8 = true` uses it; off by default since 0.2: its vectors are about 2 % apart from the full model's). `search/models.py` is the one place that loads the models, for `embed` and the
search alike. The estimates of the time (`embed` on the processor, `intake_reindex`) use the speeds measured on this PC
(`speed.json` in `%USERPROFILE%\.assistant_x`: every `embed` of 50 fragments or more, and `--check`). Measured on 2026-10-25 (200 fragments of a
library, 120 Russian and 80 English, Core Ultra 9 275HX): int8 accepted only when the mean cosine to the torch float32
vectors is 0.99 or more and every one 0.97 or more — one scale per tensor gave 0.980 (min 0.972), a scale per channel
0.983 (min 0.970), per channel with the first and the last layer in float32 0.984 (min 0.970): all refused, so the
processor keeps float32 (1.3 fragments/s in ONNX float32, 2.2 in int8).
