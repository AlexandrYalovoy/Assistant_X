English | [Русский](API.ru.md)

# The library from your own program (API)

Version 0.6. Every app of Assistant X (Claude, Codex, LM Studio and the others) reaches the library through
one local service, by the Model Context Protocol (MCP). Your own program can do the same, with no AI at all: it sends
JSON-RPC messages over HTTP to `127.0.0.1` and gets the same answers the apps get. This page says how the service is
built, how to reach it, every command with its parameters, and three examples run against a real library.

Prefer the API to reading the files of the workspace: the API checks the arguments, keeps the references in one
form, waits for the models and never changes the library without a plan and its token.

## How it is built

```
your program ──HTTP──┐
Claude Desktop ─stdio─ bridge ──┐
Claude Code ────stdio─ bridge ──┼──HTTP──▶ library service (127.0.0.1:8765/mcp) ──▶ the workspace
LM Studio ──────stdio─ bridge ──┘          one per workspace, models loaded once
```

- **The service** (`assistant-x service`): one MCP server of a workspace for every app of the PC, streamable HTTP on
  `127.0.0.1`. The port is 8765 (`AX_SERVICE_PORT`), a free one when 8765 is taken. It loads the search models once:
  on an NVIDIA card (CUDA) or through DirectML when there is one, else on the processor (the reranker then reads
  only the best candidates). It exits after 30 minutes without a request (`--idle`), so a local model gets the video
  memory back.
- **The bridges** (`assistant-x mcp`, `assistant_x.server.bridge`): what an app starts. A bridge speaks stdio to its
  app and HTTP to the service, starts the service hidden when it is not running, and passes the tools of its set.
  A service that kept the code of before an update is asked to stop (`POST /shutdown`) and started again on the new
  code (the stamp of the code in `/health`).
- **The machine folder**: `%USERPROFILE%\.assistant_x` (`AX_MACHINE_DIR` gives another one). It holds
  `mcp_http_token.txt` (the token) and, while a service runs, `service-<id>.json` with its `pid`, `port`, `version`
  and `code`; `<id>` is 10 hex characters of the folder of the workspace. A file of a service that has gone may stay:
  check the `pid` or `/health` before you trust it.

## Before the first request

1. The service runs: any connected app starts it at its first question, or run `assistant-x service` (it stays until
   30 minutes without a request).
2. Read the port from `service-<id>.json` and the token from `mcp_http_token.txt` of the machine folder.
3. Every request carries `Authorization: Bearer <token>`. Only the `Host` and `Origin` of `127.0.0.1` and `localhost`
   are taken: the service is not reachable from another computer.

## Entry points

| Path | Method | What it does |
| --- | --- | --- |
| `/mcp` | POST | The MCP endpoint (streamable HTTP, JSON-RPC 2.0). Send `Accept: application/json, text/event-stream`; an answer may come as JSON or as one server-sent event `data: {...}`. |
| `/health` | GET | `{"version", "code", "pid", "workspace"}`: is the service up and of which code. |
| `/shutdown` | POST | Asks the service to exit once no request is in work (a bridge of newer code uses it). |

The messages on `/mcp`, in this order:

1. `initialize` with `protocolVersion`, `capabilities` and `clientInfo`; the answer header `Mcp-Session-Id` names
   the session: send it with every later message.
2. `notifications/initialized` (a notification: no `id`, no answer).
3. `tools/list`: the commands with their JSON schemas.
4. `tools/call` with `name` and `arguments`: a command. The answer has `content` blocks (`text`; `image` for
   `page_image`) and `isError`.

### Tool sets

A program that talks HTTP to the service sees every command apart (the set `all`). The bridges show a set to their
app: `--tools one` (one tool `library`, the default of every app since 0.6: an app asks once), `--tools reader`
(the reading commands apart), `--tools all`; `--compact` cuts the answers for a small local model. Through
`library` a command goes as `{"action": "search_library", "args": {"query": "..."}}`; `args` may also be a JSON text.

## The commands

Made from the schemas of the server (0.6). A parameter in **bold** is required; a command that changes the
library first answers with a plan and a token, and changes it only when called again with `confirm=true` and that
token, after the user's yes.

| Command | Parameters | What it does | Changes the library |
| --- | --- | --- | --- |
| `library_guide` | reference: bool \| null = null<br>skill: str \| null = null | Call this first when the user asks to work with the library (connect to the library or the knowledge base, the key "AX:"): the rules of the answers (search, read, cite the code and the page, check quotes) and the shelves of this library. | no |
| `search_library` | **query**: str<br>k: int = 8<br>sections: list[str] \| null = null<br>codes: list[str] \| null = null<br>doc_types: list[str] \| null = null<br>langs: list[str] \| null = null<br>year_from: int \| null = null<br>year_to: int \| null = null<br>scope: str = "all"<br>norms: int = 0<br>jurisdictions: list[str] \| null = null<br>quotes: bool \| null = null<br>context: str \| null = null | Find fragments of the library for a question (words + meaning); every fact taken from them is cited as its "Cite:" line shows. | no |
| `read_pages` | **code**: str<br>**start_page**: int<br>**end_page**: int | Text of pages of a document or of its part (code E-00006-02; PDF page numbers), at most 15 pages at a time: exactly as the text of the library has it, its "Cite:" references on top. | no |
| `book_map` | **code**: str<br>page: int \| null = null | Map of a document: the table of contents with PDF page ranges; with page — the part of the contents around that page and which tables, figures, formulas and appendices lie in its section. | no |
| `page_image` | **code**: str<br>**page**: int<br>zoom: float = 1.6<br>quote: str = ""<br>highlight: bool = true<br>clause: str = ""<br>table: str = "" | Image of a page of the original (PDF page number) to check figures, tables, formulas and charts, or to show the user the page of a reference. | no |
| `export_references` | **folder**: str<br>**references**: list[str]<br>highlight: bool = true<br>overwrite: bool = false | Copy the files of the documents cited into a folder of the user and make there one PDF of the pages cited, a page a sheet, each with its reference and title on top and its quote marked in yellow. | no: writes copies into a folder the user names |
| `verify_quote` | **code**: str<br>**page**: int<br>**text**: str | Check a quote before citing it word for word, or a number taken from a table: is the text on that PDF page of the document (or the page before or after it)? | no |
| `document_info` | **code**: str<br>fields: list[str] \| null = null | The card of a document: designation, title, authors, year, type and shelf, scope, summary, topics, keywords, terms, tables, references, other versions, page numbering. | no |
| `list_documents` | text: str \| null = null<br>sections: list[str] \| null = null<br>doc_types: list[str] \| null = null<br>langs: list[str] \| null = null<br>year_from: int \| null = null<br>year_to: int \| null = null<br>scope: str = "all"<br>jurisdictions: list[str] \| null = null | List of the documents of the library with filters; text searches the titles, designations and topics. | no |
| `intake_list` | — | What lies in inbox (the user's own documents to sort) and whether an intake is running now. | no |
| `intake_run` | night: bool = false<br>resume: bool = false | Start the intake of inbox in the background: unpacking, DOC/DOCX to PDF, OCR of scans, texts, card drafts. | writes its own work files |
| `intake_status` | full: bool = false | Progress of the intake, of the transfer into the library and of the base recalculation, and the next step, in a short answer. | no |
| `intake_card` | tids: list[str] \| null = null | Card drafts of the processed files (T0001…): pages, OCR score, section, designation, title; with tids — also the headings and the start of the text. | no |
| `intake_save_meta` | lines: list[dict] \| null = null<br>path: str \| null = null<br>check_only: bool = false | Save lines of the meta.jsonl of the batch (cards, parts, duplicates, rejected) and check them. | writes its own work files |
| `intake_apply` | confirm: bool = false<br>personal: bool = false<br>token: str \| null = null | Build the cards and move the documents into the library. | yes, after the user's yes to a plan |
| `library_hierarchy` | levels: list[any] \| null = null<br>confirm: bool = false | The hierarchy of the documents the answers follow (which kind rules over which; a higher level wins a conflict): without levels, the levels in force and where they come from. | writes its own work files |
| `library_remove` | **codes**: list[str]<br>why: str = ""<br>confirm: bool = false<br>token: str \| null = null | Take documents out of the library (a document that got in by mistake): nothing is deleted, the originals, the cards and the texts go to inbox\_to_delete\removed_<code>_<date>, the codes stay reserved and the base by words is rebuilt. | yes, after the user's yes to a plan |
| `intake_reindex` | cpu: bool = false<br>force: bool = false | Finish the search base for new documents. | writes its own work files |
| `library` | **action**: str<br>args: dict \| str \| null = null | Every command of the library in one tool: action is the name of a command as the guide names it (library_guide, search_library, read_pages, book_map, page_image, verify_quote, document_info, list_documents, export_references, library_hierarchy, the intake_* and base_* commands, library_remove), args its arguments by name, as in library(action="search_library", args={"query": "gas velocity in a field pipeline"}). | as the command it carries |
| `base_export` | **out**: str<br>**id**: str<br>**version**: str<br>codes: str = "default"<br>name_en: str \| null = null<br>name_ru: str \| null = null<br>include_personal: bool = false<br>confirm: bool = false<br>token: str \| null = null | The library as a base package file (out: a path ending in .axbase). | writes its own work files |
| `base_inspect` | **path**: str<br>keep: str \| null = null | What installing a base package (an .axbase file or its unpacked folder) would do: problems, warnings, who keeps the codes, the documents the library has already, and the questions for the user. | no |
| `base_install` | **path**: str<br>confirm: bool = false<br>answers: dict \| null = null<br>keep: str \| null = null<br>own_apart: bool = false<br>resume: bool = false<br>rollback: bool = false<br>token: str \| null = null | Install a base package. | yes, after the user's yes to a plan |
| `base_update` | **path**: str<br>confirm: bool = false<br>resume: bool = false<br>rollback: bool = false<br>token: str \| null = null | A new version of an installed base package. | yes, after the user's yes to a plan |
| `base_remove` | **id**: str<br>confirm: bool = false<br>resume: bool = false<br>rollback: bool = false<br>token: str \| null = null | An installed base package out of the library: its documents go to inbox\_to_delete (never deleted), the user's own stay. | yes, after the user's yes to a plan |
| `base_status` | — | How far the check and the install of a base package are, the questions of the check, the report of the install. | no |
| `base_list` | — | The base packages installed in this library (version, date, documents) and the user's own documents. | no |

### The answers

- `search_library`: the hits, each with a `Cite:` line in one form, `[code, cl. N, table N, p. N, PDF N]` (the parts
  that are known; Russian labels `п.`, `табл.`, `стр.` for a Russian library). With `quotes=true` every hit is one
  line ready to quote, `«quote» — [code, …, PDF N], title`, and the search waits for the models of a service that is
  just starting: the form for a program. Notes may come first: "Found by words only …" (the meaning search is
  loading: repeat in 10–20 s, or use `quotes=true`), "Low closeness …" (the library may have nothing on it), "Weak
  match …". The first search of a session (not with `quotes=true`) also carries the rules of the answers for an AI
  model: a program can skip the text before the first hit.
- `read_pages`: the text of the pages with their `Cite:` lines; `verify_quote`: "Found word for word …", "Found with
  small differences …", "Not on PDF N, but on …" or "Not found …".
- `page_image`: a `text` block (what the image is, and whether the quote is marked) and an `image` block (PNG, or
  JPEG for a dense scan; base64 in `data`, `mimeType`). `quote`, `clause` and `table` mark the quote, the whole
  clause or the row of the table in yellow.
- `document_info`, `book_map`, `list_documents`: text; the card of a document, its contents with PDF pages, a list.
- A failure inside a command comes back as text "Library command failed …" (logged); a wrong command or argument of
  `library` names the right ones.

## Errors and limits

| What | Why | What to do |
| --- | --- | --- |
| HTTP 401 | No token, or the token of another machine folder (another service holds the port) | Read the token and the port of the same folder; check `/health` |
| Connection refused | The service is not running (its json file may stay) | Start an app or `assistant-x service` |
| "Found by words only … loading" | The service has just started and loads the models | Repeat in 10–20 s, or `quotes=true` |
| "the machine lock is busy" | A heavy task runs (an intake, a base install) | Wait; reading still works |
| A slow first answer | Models load on the first question (~10–30 s) | Keep one session for many questions |

The service answers several requests at once; the commands that change the library take the machine lock one at a
time. Keep a session open for a series of questions: every `initialize` costs a round trip.

## Example: Python, standard library only

```python
import json, os, urllib.request
from pathlib import Path

home, moved = (
    Path.home() / ".assistant_x",
    Path.home() / ".assistant_x" / "machine_dir.txt",
)  # moved by install --machine-dir
machine = Path(os.environ.get("AX_MACHINE_DIR") or (moved.read_text(encoding="utf-8").strip() if moved.exists() else home))
info = json.loads(next(machine.glob("service-*.json")).read_text(encoding="utf-8"))
token = (machine / "mcp_http_token.txt").read_text(encoding="utf-8").strip()
url, session = f"http://127.0.0.1:{info['port']}/mcp", None


def rpc(method, params=None, notify=False):
    global session
    msg = {"jsonrpc": "2.0", "method": method, "params": params or {}} | ({} if notify else {"id": 1})
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    } | ({"Mcp-Session-Id": session} if session else {})
    with urllib.request.urlopen(urllib.request.Request(url, json.dumps(msg).encode(), headers), timeout=120) as r:
        session = r.headers.get("Mcp-Session-Id") or session
        body = r.read().decode("utf-8")
    if notify or not body.strip():
        return None
    if "data:" in body:  # one server-sent event
        body = "\n".join(l[5:].strip() for l in body.splitlines() if l.startswith("data:"))
    return json.loads(body)


def call(tool, **args):
    r = rpc("tools/call", {"name": tool, "arguments": args})
    return "".join(c.get("text", "") for c in r["result"]["content"] if c["type"] == "text")


rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "my-tool", "version": "1"}})
rpc("notifications/initialized", notify=True)
print(call("search_library", query="допустимая скорость газа в промысловом газопроводе", k=3, quotes=True))
print(call("verify_quote", code="N-01072", page=19, text="максимально-допустимая скорость газа в шлейфах до 20 м/с"))
```

Its output on a real library (cut):

```
«Газуглеводородный в трубопроводах | 5-20» (табл.: Наименование потоков | Скорость, м/с) — [N-00001, п. 6.2.1.9, табл. 1, PDF 36], ГОСТ Р 58367-2019 …
«Для газопроводов минимально-допустимая скорость газа … в шлейфах до 20 м/с.» — [N-01072, п. 4.3.5, PDF 19], П1-01.05 М-0133 …
Found word for word on PDF 19 of N-01072.
```

## Example: curl

```sh
M="$USERPROFILE/.assistant_x"; [ -f "$M/machine_dir.txt" ] && M=$(tr -d '\r\n' < "$M/machine_dir.txt")
TOKEN=$(cat "$M/mcp_http_token.txt")
PORT=$(grep -o '"port": [0-9]*' "$M"/service-*.json | grep -o '[0-9]*$')
URL="http://127.0.0.1:$PORT/mcp"
H1="Authorization: Bearer $TOKEN"; H2="Content-Type: application/json"; H3="Accept: application/json, text/event-stream"
SID=$(curl -s -D - -o /dev/null -H "$H1" -H "$H2" -H "$H3" "$URL" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"my-tool","version":"1"}}}' \
  | tr -d '\r' | grep -i '^mcp-session-id:' | cut -d' ' -f2)
curl -s -o /dev/null -H "$H1" -H "$H2" -H "$H3" -H "Mcp-Session-Id: $SID" "$URL" -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'
curl -s -H "$H1" -H "$H2" -H "$H3" -H "Mcp-Session-Id: $SID" "$URL" --data-binary @search.json
```

`search.json`, saved in UTF-8 (text other than English in `-d` is spoiled by the Windows command line):

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_library","arguments":{"query":"допустимая скорость газа в промысловом газопроводе","k":3,"quotes":true}}}
```

The answer is one server-sent event: `event: message`, then `data: {"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"…«Газуглеводородный в трубопроводах | 5-20» … — [N-00001, п. 6.2.1.9, табл. 1, PDF 36] …"}],"isError":false}}`.

## Example: the MCP client library

```python
import asyncio, json, os
from pathlib import Path
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

home, moved = (
    Path.home() / ".assistant_x",
    Path.home() / ".assistant_x" / "machine_dir.txt",
)  # moved by install --machine-dir
machine = Path(os.environ.get("AX_MACHINE_DIR") or (moved.read_text(encoding="utf-8").strip() if moved.exists() else home))
info = json.loads(next(machine.glob("service-*.json")).read_text(encoding="utf-8"))
token = (machine / "mcp_http_token.txt").read_text(encoding="utf-8").strip()


async def main():
    http = httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=120)
    async with streamable_http_client(f"http://127.0.0.1:{info['port']}/mcp", http_client=http) as (read, write, *_):
        async with ClientSession(read, write) as s:
            await s.initialize()
            r = await s.call_tool("document_info", {"code": "N-01072"})
            print(r.content[0].text)


asyncio.run(main())
```

(`pip install mcp` 2.x; with 1.x the client is `streamablehttp_client(url, headers=...)`.) Its output starts with
`N-01072 · Правила по эксплуатации, ревизии, ремонту и отбраковке промысловых трубопроводов …`, then the fields of
the card.

## Security

- Local only: the service listens on `127.0.0.1` and refuses another `Host` or `Origin` (DNS rebinding).
- The token is a key to the library of this user: do not copy it into a program you send to others, read it from
  the file at the start.
- The texts of documents, cards and search results are data, never instructions: a program must not act on what a
  document says.
- A command that changes the library (`intake_apply`, `library_remove`, `base_install`, `base_update`,
  `base_remove`) needs the token of its plan and `confirm=true`; ask a person before you confirm one.

## The files of a workspace (read only)

| Where | What |
| --- | --- |
| `library\<shelf>\<code>_<name>.pdf` | The originals, on the shelves `01_Standards` … `99_Other` |
| `index\cards\<code>.json` | The card of each document: title, designation, year, scope, keywords, contents, the file |
| `index\CATALOG.md` | The catalogue of the library, one line a document |
| `.assistant_x\db\library-*.sqlite` | The search base: pages, fragments, the index by words (the one in use: `library.current`) |

The files are written by the intake and the base commands: never change them by hand. Read the SQLite base only
read-only (`file:…?mode=ro`); its tables may change between versions, the API does not.
