# Cards
One card per document: `<code>.json` (a code is the letter of a shelf, `assistant_x/schemas/shelves.json`, and five digits: `N-00012`).
A card is strict JSON checked by the schema `assistant_x/schemas/card-1.json`; it is the one source of truth about the
document: `CATALOG.md` and `sources_to_update.md` are made from the cards, and so is the search base.

- `doc`: what the document is (title, designation, authors, year, scope, summary, topics, keywords, terms, contents,
  tables, references, units of a journal issue); written by Claude at the intake from the drafts.
- `file`: the file (format, recognition, place in the library, hashes, parts, issues); written by the code.
- Searchable texts are maps `{"en": "…", "ru": "…"}`: English always, and every language the documents are read in
  (`[documents] languages` of `assistant_x.toml`: Russian and English by default).

The intake writes the cards; `assistant-x check` validates them; `assistant-x build` brings the changes into the
search. Problems of a source (a poor scan, a new edition needed) are `file.issues`: the search shows them to Claude in
the line "Source quality".
