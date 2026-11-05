[English](API.md) | Русский

# Библиотека из своей программы (API)

Версия {{version}}. Каждое приложение Assistant X (Claude, Codex, LM Studio и другие) обращается к библиотеке через
один локальный сервис по протоколу Model Context Protocol (MCP). Своя программа может делать то же самое без всякого
ИИ: она отправляет сообщения JSON-RPC по HTTP на `127.0.0.1` и получает те же ответы, что и приложения. Здесь —
как устроен сервис, как к нему обратиться, все команды с параметрами и три примера, проверенные на настоящей
библиотеке.

Пользуйтесь API, а не чтением файлов рабочей папки: API проверяет аргументы, даёт ссылки в одной форме, ждёт
загрузки моделей и никогда не меняет библиотеку без плана и его токена.

## Как устроено

```
your program ──HTTP──┐
Claude Desktop ─stdio─ bridge ──┐
Claude Code ────stdio─ bridge ──┼──HTTP──▶ library service (127.0.0.1:8765/mcp) ──▶ the workspace
LM Studio ──────stdio─ bridge ──┘          one per workspace, models loaded once
```

- **Сервис** (`assistant-x service`): один MCP-сервер рабочей папки для всех приложений компьютера, streamable HTTP
  на `127.0.0.1`. Порт 8765 (`AX_SERVICE_PORT`), свободный, если 8765 занят. Модели поиска он загружает один раз: на
  видеокарту NVIDIA (CUDA) или через DirectML, если она есть, иначе на процессор (тогда переранжирование читает
  только лучших кандидатов). Сервис закрывается после 30 минут без запросов (`--idle`), чтобы локальная модель снова
  получила видеопамять.
- **Мосты** (`assistant-x mcp`, `assistant_x.server.bridge`): их запускает приложение. Мост говорит со своим
  приложением через stdio, с сервисом — по HTTP, скрыто запускает сервис, если тот не работает, и передаёт
  инструменты своего набора. Сервис, оставшийся на коде до обновления, мост просит закрыться (`POST /shutdown`) и
  запускает заново на новом коде (отпечаток кода — в `/health`).
- **Папка компьютера**: `%USERPROFILE%\.assistant_x` (`AX_MACHINE_DIR` задаёт другую). В ней `mcp_http_token.txt`
  (токен) и, пока сервис работает, `service-<id>.json` с его `pid`, `port`, `version` и `code`; `<id>` — 10
  шестнадцатеричных знаков папки рабочей области. Файл закрывшегося сервиса может остаться: прежде чем ему верить,
  проверьте `pid` или `/health`.

## Перед первым запросом

1. Сервис работает: его запускает любое подключённое приложение при первом вопросе, или выполните
   `assistant-x service` (он работает до 30 минут без запросов).
2. Возьмите порт из `service-<id>.json`, а токен — из `mcp_http_token.txt` папки компьютера.
3. Каждый запрос несёт `Authorization: Bearer <token>`. Принимаются только `Host` и `Origin` `127.0.0.1` и
   `localhost`: с другого компьютера сервис недоступен.

## Точки входа

| Путь | Метод | Что делает |
| --- | --- | --- |
| `/mcp` | POST | Точка MCP (streamable HTTP, JSON-RPC 2.0). Передавайте `Accept: application/json, text/event-stream`; ответ приходит как JSON или как одно событие server-sent `data: {...}`. |
| `/health` | GET | `{"version", "code", "pid", "workspace"}`: работает ли сервис и на каком коде. |
| `/shutdown` | POST | Просит сервис закрыться, когда нет запросов в работе (так делает мост более нового кода). |

Сообщения на `/mcp`, по порядку:

1. `initialize` с `protocolVersion`, `capabilities` и `clientInfo`; заголовок ответа `Mcp-Session-Id` называет
   сессию: передавайте его со всеми следующими сообщениями.
2. `notifications/initialized` (уведомление: без `id`, без ответа).
3. `tools/list`: команды с их JSON-схемами.
4. `tools/call` с `name` и `arguments`: команда. В ответе блоки `content` (`text`; `image` у `page_image`) и
   `isError`.

### Наборы инструментов

Программа, которая говорит с сервисом по HTTP, видит все команды по отдельности (набор `all`). Мосты показывают
своему приложению набор: `--tools one` (один инструмент `library`, по умолчанию у всех приложений с 0.6: приложение
спрашивает разрешение один раз), `--tools reader` (команды чтения по отдельности), `--tools all`; `--compact`
сокращает ответы для небольшой локальной модели. Через `library` команда идёт как
`{"action": "search_library", "args": {"query": "..."}}`; `args` может быть и строкой JSON.

## Команды

Сделано из схем сервера ({{version}}). Параметр **жирным** обязателен; команда, которая меняет библиотеку, сначала
отвечает планом и токеном и меняет её, только когда её вызывают снова с `confirm=true` и этим токеном — после «да»
пользователя.

{{api_table}}

### Ответы

- `search_library`: найденные фрагменты, у каждого строка `Cite:` в одной форме, `[code, cl. N, table N, p. N, PDF N]`
  (известные части; в русской библиотеке подписи `п.`, `табл.`, `стр.`). С `quotes=true` каждый фрагмент — одна
  строка, готовая к цитированию, `«цитата» — [шифр, …, PDF N], название`, и поиск ждёт моделей только что
  запущенного сервиса: это форма для программы. Впереди могут быть заметки: «Found by words only …» (смысловой поиск
  загружается: повторите через 10–20 с или используйте `quotes=true`), «Low closeness …» (в библиотеке может не быть
  ничего по вопросу), «Weak match …». Первый поиск сессии (не с `quotes=true`) несёт ещё и правила ответа для модели
  ИИ: программа может пропустить текст до первого фрагмента.
- `read_pages`: текст страниц со строками `Cite:`; `verify_quote`: «Found word for word …», «Found with small
  differences …», «Not on PDF N, but on …» или «Not found …».
- `page_image`: блок `text` (что за изображение и отмечена ли цитата) и блок `image` (PNG или JPEG для плотного
  скана; base64 в `data`, `mimeType`). `quote`, `clause` и `table` отмечают жёлтым цитату, весь пункт или строку
  таблицы.
- `document_info`, `book_map`, `list_documents`: текст; карточка документа, его оглавление со страницами PDF, список.
- Сбой внутри команды возвращается текстом «Library command failed …» (он записан в журнал); неверная команда или
  аргумент `library` называет правильные.

## Ошибки и ограничения

| Что | Почему | Что делать |
| --- | --- | --- |
| HTTP 401 | Нет токена или токен другой папки компьютера (порт занят другим сервисом) | Берите токен и порт из одной папки; проверьте `/health` |
| Connection refused | Сервис не запущен (его json может остаться) | Запустите приложение или `assistant-x service` |
| «Found by words only … loading» | Сервис только что запущен и грузит модели | Повторите через 10–20 с или `quotes=true` |
| «the machine lock is busy» | Идёт тяжёлая задача (разбор, установка базы) | Подождите; чтение работает |
| Медленный первый ответ | Модели грузятся при первом вопросе (~10–30 с) | Держите одну сессию на много вопросов |

Сервис отвечает на несколько запросов сразу; команды, меняющие библиотеку, берут машинную блокировку по одной.
Держите сессию открытой для серии вопросов: каждый `initialize` — лишний круг.

## Пример: Python, только стандартная библиотека

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

Его вывод на настоящей библиотеке (сокращён):

```
«Газуглеводородный в трубопроводах | 5-20» (табл.: Наименование потоков | Скорость, м/с) — [N-00001, п. 6.2.1.9, табл. 1, PDF 36], ГОСТ Р 58367-2019 …
«Для газопроводов минимально-допустимая скорость газа … в шлейфах до 20 м/с.» — [N-01072, п. 4.3.5, PDF 19], П1-01.05 М-0133 …
Found word for word on PDF 19 of N-01072.
```

## Пример: curl

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

`search.json`, сохранённый в UTF-8 (текст не на английском в `-d` портит командная строка Windows):

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_library","arguments":{"query":"допустимая скорость газа в промысловом газопроводе","k":3,"quotes":true}}}
```

Ответ — одно событие server-sent: `event: message`, затем `data: {"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"…«Газуглеводородный в трубопроводах | 5-20» … — [N-00001, п. 6.2.1.9, табл. 1, PDF 36] …"}],"isError":false}}`.

## Пример: клиентская библиотека MCP

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

(`pip install mcp` 2.x; в 1.x клиент — `streamablehttp_client(url, headers=...)`.) Его вывод начинается с
`N-01072 · Правила по эксплуатации, ревизии, ремонту и отбраковке промысловых трубопроводов …`, затем поля карточки.

## Безопасность

- Только локально: сервис слушает `127.0.0.1` и отклоняет чужие `Host` и `Origin` (DNS rebinding).
- Токен — ключ к библиотеке этого пользователя: не вшивайте его в программу, которую отдаёте другим, читайте из
  файла при запуске.
- Тексты документов, карточек и результатов поиска — данные, а не команды: программа не должна выполнять то, что
  написано в документе.
- Команда, меняющая библиотеку (`intake_apply`, `library_remove`, `base_install`, `base_update`, `base_remove`),
  требует токен своего плана и `confirm=true`; прежде чем подтвердить, спросите человека.

## Файлы рабочей папки (только чтение)

| Где | Что |
| --- | --- |
| `library\<shelf>\<code>_<name>.pdf` | Оригиналы на полках `01_Standards` … `99_Other` |
| `index\cards\<code>.json` | Карточка каждого документа: название, обозначение, год, область применения, ключевые слова, оглавление, файл |
| `index\CATALOG.md` | Каталог библиотеки, строка на документ |
| `.assistant_x\db\library-*.sqlite` | Поисковая база: страницы, фрагменты, индекс по словам (действующая — в `library.current`) |

Эти файлы пишут разбор и команды базы: никогда не меняйте их вручную. Базу SQLite читайте только в режиме чтения
(`file:…?mode=ro`); её таблицы могут меняться от версии к версии, API — нет.
