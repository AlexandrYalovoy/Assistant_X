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

Every cloud agent defaults to `one_reader`: one `library` schema, with reading and reference export only. The bridge
and the in-process server reject changes. `library_guide(detail="reader")` leaves out intake and base-package
administration. For inbox intake select `one_intake`. For package administration, the user or agent explicitly selects full `one`: `assistant-x connect APP --tools
one`; switch back with `--tools one_reader`. The full guide is loaded only in full mode, so an ordinary answer does not
carry its cost. Qwen in LM Studio stays in the compact reference mode.

Fast and deep answers in Kimi Work were live-tested on 25 November 2026; this does not separately confirm Kimi CLI /
Kimi Code or Kimi Chat.

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

## Measure the completed answer

Use `answer_context` through MCP for a bounded first call. The page character limit covers the sum of page bodies.
`truncated` marks an excerpt. Metadata and match excerpts add to the total response size. `one_intake` adds inbox intake to reading.

The historical table above used a metadata hit and a value anywhere in JSON. The current benchmark counts reference hits,
page bodies actually delivered, and values in expected page bodies separately. For an isolated comparison run
`python -m tests.golden.fixture_routes`. This measures local calls and serialized characters. The fixture includes
a wrong unit, a misleading table row, a superseded source, a scan and a question with no answer.
On the five fixture prompts in November 2026, balanced required 5 single calls (11,103 serialized response characters)
or 14 individual search/read calls (13,620 characters). Each route delivered all five expected source-page groups and
both marked numbers. One prompt requires abstention and is graded at the final-answer stage. These figures exclude
model prompts, reasoning, final answers and service billing.

Use the same version of the library and model for each live comparison. Run both routes and all modes in fresh chats,
grade the final answers against the review notes, and include failed attempts. Review the citation, source edition,
units, table row and applicability. An unsupported number or failure to abstain fails the attempt.

Record one JSON object per attempt in a JSONL file with id, client, model, library_version, route, mode,
correct (boolean), calls and seconds. Set optional uncached_input, cached_input, output and cost_usd from the client's
actual usage. Omit unavailable fields. Use `python -m tests.golden.context_cost --trials trials.jsonl`
to aggregate by configuration and report total usage per correct answer. A subscription has no assumed dollar tariff.
For private library evidence use `--set engineering|blind|blind2` and absolute count thresholds `--min-read` and
`--min-values` established on the same corpus. Failure to reach either threshold exits with status 1.

## Checks

```bat
python tests/golden/context_cost.py --mode balanced
python tests/golden/context_cost.py --mode deep
python scripts/release_check.py --fast
```

The search and JSON fields: [`SEARCH.md`](SEARCH.md) and [`API.md`](API.md). Change and release rules:
[`CONTRIBUTING.md`](../CONTRIBUTING.md).
