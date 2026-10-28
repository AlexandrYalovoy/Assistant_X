English | [Русский](GLOSSARY.ru.md)

# Glossary

The English terms Assistant X uses everywhere (code, messages, documentation), with their Russian equivalents for the
users who work in Russian. The code, the tests and the rules for the models are English only; the documents for people
have Russian twins (name.ru.md); elsewhere Russian is kept only as data for Russian documents (the last section).

## Terms

| Russian | English | Notes |
| --- | --- | --- |
| шифр | code | the letter of a shelf and five digits, `N-00001`; a part `E-00006-02` |
| карточка | card | `index/cards/<code>.json`, the schema [`assistant_x/schemas/card-1.json`](../assistant_x/schemas/card-1.json) |
| полка (раздел библиотеки) | shelf, section | a letter of the codes and a folder of `library`, the same in every library (`schemas/shelves.json`) |
| тип документа | document type, genre | `doc_type`: one universal list (standard, book, serial_issue…) |
| языки карточки | card languages | English and every language of `[documents] languages` (Russian and English by default) |
| статья выпуска | unit | an article of a journal issue, a paper of proceedings: `doc.units`, a fragment of its own |
| текст (документа) | text | `index/texts/<code>.md`, pages marked `=== page N ===` |
| разбор | intake | processing of `inbox`: unpack, OCR, texts, card drafts |
| партия (разбора) | batch | one run of the intake, `intake/work/<date>` |
| перенос | apply | `intake.py apply`: originals to `library`, cards and texts to `index` |
| сборка (карточек) | build | `intake.py build`; also the build of the base (`build_index.py`) |
| библиотека | library | the originals, `library/` |
| каталог | catalog | `index/CATALOG.md` |
| манифест | manifest | `index/manifest.tsv` |
| журнал | journal | `index/journal.md` (generated); also the call journal `.assistant_x/debug/calls.log` |
| события разбора | intake events | `index/intake_events.tsv` |
| источники к обновлению | sources to update | `index/sources_to_update.md` |
| замок | lock | `core/lock.py`: the folder lock (one intake at a time), the machine lock (one heavy task per PC) |
| навык | skill | `<workspace>/skill/SKILL.md`, written by `assistant-x skill` |
| носитель | media | the folder or archive an offline installation runs from |
| выпуск | release | a released version |
| стандарты | standards | shelf N |
| нормативные акты и регламенты | regulations and law | shelf R |
| паспорта и руководства | equipment documents | shelf E |
| литература | literature | shelf L |
| проекты и отчёты | projects and reports | shelf P |
| журналы и статьи | journals and papers | shelf J |
| прочее | other | shelf X |
| база (поиска) | (search) base | `.assistant_x/db/library.sqlite` of the workspace |
| смыслы, векторы | embeddings, meaning vectors | `vectors-*.f16` |
| поиск по смыслу | semantic search, search by meaning | |
| поиск по словам | search by words | FTS5 with stemming and synonyms |
| модель смыслов | embedding model | BAAI/bge-m3 |
| переранжирование | reranking | bge-reranker-v2-m3 |
| распознавание | recognition, OCR | Tesseract |
| оценка распознавания | recognition score | 0–100, `ocr_quality.tsv` |
| скан | scan | |
| черновик (метаданных) | draft | `meta_draft.jsonl` |
| дубль | duplicate | |
| новая версия (документа) | new version | another edition of a document of the library: replace it or keep both (`intake/versions.py`) |
| отброшено | rejected | `inbox/_rejected` |
| под удаление | to delete | `inbox/_to_delete` |
| личный документ | personal document | `intake.personal` of the card |
| качество источника | source quality | the warning next to a found fragment |
| издательство, издание | publisher, edition | `doc.publisher`, `doc.edition` |
| нумерация страниц | page numbering | `doc.page_offset`: printed page = PDF page − value |
| отладочный отчёт | debug report | `assistant-x debug-report` |
| установка | installation | `install.bat` |
| пакет базы | base package | a ready library added to a workspace ([ROADMAP.md](../ROADMAP.md)) |
| рабочая папка проекта | workspace | the user's data folder with `assistant_x.toml` (`core/workspace.py`) |
| профиль | (domain) profile | the knowledge of a field: synonyms, the wording of the skill ([`assistant_x/profiles`](../assistant_x/profiles)) |

## File formats (assistant_x/core/formats.py, assistant_x/core/card.py)

Every file of a project is written with English names, whatever the language of the documents:

| What | Written as |
| --- | --- |
| page marker | `=== page N ===` |
| card | JSON: `schema`, `code`, `section`, `doc_type`, `doc` (the meaning), `file` (the file), `intake`; sorted keys, an indent of one space |
| catalog columns | Code, Document, Type, Section, Year, Format, Key topics (made from the cards: `search/catalog.py`) |
| catalog stamp | `Updated: DATE. Documents: N.` |
| sources to update | `## Open`, `## Closed`, `Updated: DATE. Open items: N.` |
| priority | high, medium, low |
| event status (start) | done, duplicate, rejected, to delete, error, to pdf, estimate, archive |
| events header | date, source_file, size, sha256, code, destination, status |
| manifest header | path, size, modified, sha256, code |
| ocr_quality.tsv header | code, score, nonword, words, pages, pages_below_threshold, worst_pages, source, date |
| format of a card | `file.format.kind`: pdf_text, pdf_mixed, pdf_scan, pdf_no_ocr, doc, presentation, image, ebook, text, spreadsheet, other; in words `PDF with text, 12 pages`, `PDF scan (OCR, errors possible), 3 pages` |
| places | in a card `library/01_Standards/…`; in the events and moves `library\01_Standards\…`, `inbox\…` |

## Kept in Russian (data)

Assistant X reads Russian documents, so Russian words are needed, but only as **data files**: the Python code holds
no Cyrillic (checked by [`tests/test_workspace.py::test_no_cyrillic_in_the_code`](../tests/test_workspace.py)). The code composes its patterns
from the language packs of the document languages (`[documents] languages`, all packs by default, Russian first) and
from the domain profile (`profile` in `assistant_x.toml`); `core/lang.py` and `core/config.py` load them. No rule
of the code names a language: which letters make a text Russian or English, which letters a broken font loses, which
stemmer, which two-letter words, which Tesseract language — all of it is a key of a pack, so a third pack (a folder
`<code>` with the same files; `AX_LANG_DIRS` names more folders of packs) works without a line of code
([`tests/test_lang_packs.py`](../tests/test_lang_packs.py) adds a small German one).

Language packs `assistant_x/lang/<code>/` (`ru` and its English counterpart `en`):

| File | What it holds | Used by |
| --- | --- | --- |
| `text.json` | letters for character classes, case folding (Russian yo as ye), the Snowball stemmer and the letters that choose it (`stem_detect`), the Tesseract language, stop words; `lang_share` (the share of the letters that makes a text of the language: Russian 0.7, English 0.85), `keep_share` (a converted page must keep the share of these letters: a broken font turns Cyrillic into Latin) | `core/common.py` (tokens, stemming, chunking, `langs_of`, `letter_shares`), every module that counts letters |
| `headings.json` | chapter words, generic headings that name no section, the words of a table of contents | `core/textmap.py` (`CHAPTER_RX`, `GENERIC_RX`; the search and the intake) |
| `references.json` | captions of tables, figures, appendices; reference words in running text; contents words; OCR dot leaders | `core/textmap.py` (captions, contents), `search/bookmap.py` (references) |
| `documents.json` | designations of state and international standards, places of publication, general publishers, company forms, words that are no title, title pages of standards, the phrase that names the document a standard replaces, the words that suggest a genre (`doc_type_words`: every genre of `schemas/card-1.json`, tried in its order), front-matter boilerplate, top headings, the title block of a drawing, general title words in English, transliteration | `intake/metadraft.py` |
| `intake.json` | personal papers by the name of a file, words of hidden text aimed at an AI, the kit folders of a national standard | `intake/pipeline.py` |
| `ocr.json` | two-letter words and units, letter triples that are no garbage | `intake/tools/ocr_score.py` |
| `questions.json` | the words of a question that asks for every place | `search/retrieval.py` |

Domain profiles `assistant_x/profiles/<name>/profile.json` (chosen at `assistant-x init --profile`):

- `general` (the default): no domain data.
- `oil-gas-ru`: `synonyms.txt` (Russian oil-and-gas abbreviations; the comments are English), the wording of the
  skill and `documents.json`: the words of documents of the field — designations of the industry and of companies
  (API, NORSOK, DEP, NACE, company standards), its publishers (API, Shell, GPSA, SPE, PennWell…), the English words of
  the titles of its standards (pumps, tubing, wellhead…). `core/lang.py` adds them after the packs for the same keys
  (`words`, `alt`, `table`, `lists`); the general profile does without them.
- A profile holds only the knowledge of its field. The shelves (N Standards, L Literature, P Projects and reports, E Equipment documents, R Regulations and law, J Journals and
papers, X Other) are one data file for every library,
  [`assistant_x/schemas/shelves.json`](../assistant_x/schemas/shelves.json), with the names in English and Russian; the cards carry English and every
  language the documents are read in, whatever the profile.

Also Russian, outside the package: the **test data** (Russian document text in the fixtures, to exercise stemming,
headings, references and OCR scoring; Cyrillic folder and file names to test paths with non-ASCII characters).
