English | [Русский](COST.ru.md)

# Answer modes and cost

Assistant X limits repeated model reasoning and repeated context, not the strength of the evidence. It provides
explicit modes, a short reading guide and a one-command fallback.

## Choosing a mode explicitly

| User request | Mode | Matches | Full pages | Page characters | When to use |
|---|---|---:|---:|---:|---|
| `AX: быстро <question>` | `fast` | 3 | 1 | 12 000 | A simple fact, deliberately the shortest answer |
| `AX: <question>` | `balanced` | 4 | 2 | 24 000 | An ordinary cost-efficient question |
| `AX: глубоко <question>` | `deep` | 8 | 5 | 40 000 | Design, calculation, conflicting norms |

Deep also reads neighbouring pages of the two leading documents: a clause, a table and its continuation often stand
next to the best fragment. Fast and balanced do not expand the neighbourhood.

## One fallback command

When MCP is unavailable, an agent must not inspect the source or write its own client. One command returns JSON with
matches, the best full pages, ready citations, source quality and notes:

```bat
assistant-x context "question" --mode balanced
```

This is context for an answer, not the finished engineering answer: the model reads it and answers the user from it alone.
Use `--mode fast`, `--mode balanced`, `--mode deep`, or narrow the request with `--code`, `--section`, `--k`,
`--pages` and `--max-chars`. A full page's text is not repeated in its match. A successful run keeps technical model
logs out of the JSON.

## One safe MCP tool

Kimi uses `one_reader`: one `library` schema, with reading and reference export only. The bridge and the in-process
server reject changes. `library_guide(detail="reader")` leaves out intake and base-package administration. Fast and
deep answers in Kimi Work were live-tested on 25 November 2026; this does not separately confirm Kimi CLI / Kimi Code
or Kimi Chat.

`search_library_data` returns JSON fields of the document, pages, citation and source quality. `verify_answer` checks
page references in a finished answer and quotes it can associate with one citation; `verify_quote` is enough for a
simple fact. It does not prove that an unquoted paraphrase is correct or complete. Page images are for a user request,
a critical number, a complex table or weak OCR, not a default.

## Measurements

Before the optimization, a Work question about gas velocity explored the project and wrote a client; after it, one
fallback command was enough.

| Measure | Before | After | Reduction |
|---|---:|---:|---:|
| Model calls | 25 | 4 | 84 % |
| Uncached input | 48 304 | 13 968 | 71 % |
| Cache reads | 886 272 | 76 288 | 91 % |
| Output tokens | 12 031 | 1 670 | 86 % |
| Total processed context | 946 607 | 91 926 | 90 % |

Cache reads and ordinary input have separate tariffs; a reduction of context is not a monetary quotation.

On 19 real engineering questions on 25 November 2026, balanced found 19/26 expected pages and 11/12 values at about
4 000 tokens a context; improved deep found 26/26 and 12/12 at about 8 900. Choose deep for a complex calculation.

## Checks

```bat
python tests/golden/context_cost.py --mode balanced
python tests/golden/context_cost.py --mode deep
python scripts/release_check.py --fast
```

The search and JSON fields: [`SEARCH.md`](SEARCH.md) and [`API.md`](API.md). Change and release rules:
[`CONTRIBUTING.md`](../CONTRIBUTING.md).
