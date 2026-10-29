English | [Русский](ROADMAP.ru.md)

# Roadmap

Version 0.5.5 is an open prototype, for Windows and Linux (0.1 was the first) ([CHANGELOG.md](CHANGELOG.md) says what it does). What is done and
what comes next, roughly in this order.

## Done in 0.1

- **The library and the intake.** One workspace folder; the intake of PDF, DOC/DOCX, PPTX, scans, DjVu and archives
  into texts with a page marker per PDF page, OCR with a quality score per page, duplicates and editions found,
  hidden text cut out of the search text and reported.
- **Cards as data.** JSON cards checked by a JSON Schema (`schemas/card-1.json`) are the one source of truth; the
  catalog and the sources to update are made from them; the shelves are one list for every library; the cards are
  bilingual; the texts have a format of their own ("AX text 1") and a quote can be checked against the page
  (`verify_quote`).
- **The search and the MCP server.** Search by words (SQLite FTS5) and by meaning (bge-m3, FAISS) with reranking, on
  an NVIDIA card (CUDA), an AMD or Intel card (DirectML), or the processor (int8 ONNX); tables of contents of books,
  page images, a "Source quality" warning; changes of the library only through a plan and its confirmation token.
- **Base packages.** A library (cards, texts, base, without personal documents) exported by one user and installed,
  updated or removed in the workspace of another, merged with their own documents, every step resumable or undone.
- **Profiles and language packs.** `general` and `oil-gas-ru`; the Russian and English packs.
- **Installation.** [`Setup.bat`](Setup.bat) and `assistant-x install` (from the internet or an offline medium made by
  `assistant-x prepare-media`), `assistant-x doctor`, `assistant-x debug-report`; pip with the versions of the release.
- **Tests, CI and documentation.** The tests on Windows and Linux in GitHub Actions, the release wheel built from the tag; [`CONTRIBUTING.md`](CONTRIBUTING.md),
  [`SECURITY.md`](SECURITY.md), [`CLA.md`](CLA.md); the guides in [`docs/`](docs).

## Next

1. **Profiles for other fields and more languages.** A profile is the knowledge of a field only
   (`assistant_x/profiles/<name>`): synonyms, the wording of the skill. More languages as language packs
   (`assistant_x/lang/<code>`): the detection of the language of a text and the checks of a scan (the share of
   Cyrillic, a broken encoding, the OCR score with its two stemmers) know Russian and English only and need to be made
   general for a third language.
2. **Cards.** A controlled list of topics per profile, the cards edited from the chat, migrations when the card schema
   grows, the places of a quote on the page image (its boxes) for a highlight.
3. **A lighter installation.** ONNX Runtime by default for the embeddings and the reranking, torch only for NVIDIA
   CUDA; an installer for Linux; macOS tested.
4. **Documentation and tooling.** `logging` and `--json` output, an architecture guide, a data guide, a profile guide,
   an example mini library.

Proposals and questions are welcome as issues.
