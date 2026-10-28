[English](README.md) | Русский

# Assistant X

Собственная база знаний с экспертом поверх неё: Assistant X хранит ваши документы (PDF, DOC/DOCX, PPTX, сканы) на
вашем компьютере в виде текстов с поиском и позволяет вашему ИИ-ассистенту читать, сверять и цитировать их
постранично через MCP-сервер: Claude (Desktop и Code), Codex и настольное приложение ChatGPT, DeepSeek Harness,
LM Studio с любой локальной моделью и любой другой MCP-клиент. Поиск по словам и по смыслу, изображения страниц
оригиналов, оглавления книг, предупреждение о качестве слабых сканов. Библиотека и поиск работают локально; модель
получает только то, что она читает из библиотеки для ответа (с локальной моделью в LM Studio ничего не покидает ПК).

Версия 0.5.4, прототип (что будет дальше: [`ROADMAP.md`](ROADMAP.ru.md)). Профиль по умолчанию `general` подходит для
библиотеки любой области; `oil-gas-ru` добавляет синонимы российского инженера-технолога нефтегазовой отрасли. Лицензия:
GNU AGPL-3.0-or-later; папки с данными также под CC-BY-4.0 (см. раздел «Лицензия» ниже).

**Автор:** Александр Яловой.

## Как получить программу

**Самый короткий путь: попросите своего агента.** Скажите Codex, Claude Code или DeepSeek Harness: «Установи мне
Assistant X: https://github.com/AlexandrYalovoy/Assistant_X» — агент выполнит [`INSTALL_FOR_AI.md`](INSTALL_FOR_AI.ru.md)
(последний релиз, подключение ваших приложений, проверка), а вы подтверждаете его команды. Codex и настольное приложение
ChatGPT также принимают плагин из этого репозитория: `codex plugin marketplace add AlexandrYalovoy/Assistant_X`;
Claude Code: `/plugin marketplace add AlexandrYalovoy/Assistant_X`.

- **Репозиторий:** https://github.com/AlexandrYalovoy/Assistant_X (там же issues и pull requests); зеркало на
  GitFlic: https://gitflic.ru/project/alexandryalovoy/assistant_x. Клонируйте его командой
  `git clone https://github.com/AlexandrYalovoy/Assistant_X.git` или скачайте ZIP с кодом со страницы проекта.
- **Релиз:** https://github.com/AlexandrYalovoy/Assistant_X/releases — исходный код версии, wheel
  `assistant_x-<version>-py3-none-any.whl` и описание версии (CHANGELOG).
- **Офлайн-носитель** (Windows, интернет на ПК не нужен): папка, созданная командой `assistant-x prepare-media` на ПК
  с интернетом, — [`Setup.bat`](Setup.bat), программа в `app\` (её полный исходный код), пакеты, модели и программы
  для разбора. Скопируйте её на ПК и дважды щёлкните [`Setup.bat`](Setup.bat).

## Что есть в репозитории

| Путь | Что это |
| --- | --- |
| [`assistant_x/`](assistant_x) | Python-пакет: `core` (рабочая папка, настройки, языковые пакеты, блокировки, форматы файлов, вспомогательные функции для текстов и базы), `search` (сборка базы, эмбеддинги, поиск, отчёты), `intake` (разбор новых документов и его инструменты), `server` (MCP-сервер `assistant-x`), `setup` (установщик, отладочный отчёт, носитель), `cli` (команда `assistant-x`), `lang` (языковые пакеты: данные), `profiles` (профили предметных областей: данные), `templates` |
| [`pyproject.toml`](pyproject.toml) | пакет `assistant-x`: зависимости и дополнения (extras) `dense`, `intake`, `dml`, `export`, `dev` |
| [`Setup.bat`](Setup.bat), [`intake.bat`](intake.bat), [`assistant-x.bat`](assistant-x.bat) | запуск двойным щелчком: установка; разбор папки `inbox`; любая команда (`assistant-x.bat help`) |
| [`scripts/`](scripts) | тонкие .bat-файлы: отладочный отчёт, отчёт о библиотеке, журнал запросов, установка программ для разбора, носитель |
| [`assistant_x/templates/skill/`](assistant_x/templates/skill) | навык `assistant-x` (включается ключом «AX:») из одного ядра: SKILL.md для Claude и для агентов (Codex, DeepSeek Harness), краткие правила инструмента `library_guide`; `assistant-x skill` записывает его для профиля рабочей папки |
| [`assistant_x/clients/`](assistant_x/clients) | приложения, которые знает `assistant-x connect`: где каждое из них хранит свои MCP-серверы и навыки |
| [`INSTALL_FOR_AI.md`](INSTALL_FOR_AI.ru.md), [`AGENTS.md`](AGENTS.md), [`plugins/`](plugins) | инструкции для агента, который устанавливает Assistant X, заметки для агентов, плагин Codex и Claude Code (вместе с [`.agents/plugins`](.agents/plugins) и [`.claude-plugin`](.claude-plugin)): создаются командой `assistant-x gen-docs` из [`assistant_x/templates/docs/`](assistant_x/templates/docs) |
| [`assistant_x/schemas/`](assistant_x/schemas) | JSON Schema карточек документов (`card-1.json`) |
| [`tests/`](tests) | тесты ([`tests/base`](tests/base), [`tests/search`](tests/search), [`tests/intake`](tests/intake), [`tests/corpus`](tests/corpus) и верхний уровень `tests`: см. «Тесты») |
| [`docs/`](docs) | руководства: поиск ([`SEARCH.md`](docs/SEARCH.ru.md)), разбор ([`INTAKE.md`](docs/INTAKE.ru.md)), базовые пакеты ([`PACKAGES.md`](docs/PACKAGES.ru.md)), приложения ([`CLIENTS.md`](docs/CLIENTS.ru.md)), глоссарий ([`GLOSSARY.md`](docs/GLOSSARY.ru.md)) |
| [`ROADMAP.md`](ROADMAP.ru.md), [`CHANGELOG.md`](CHANGELOG.ru.md) | что будет дальше, что изменилось |
| [`LICENSE`](LICENSE), [`LICENSES/`](LICENSES), [`NOTICE`](NOTICE), [`CLA.md`](CLA.md), [`CONTRIBUTING.md`](CONTRIBUTING.ru.md), [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.ru.md) | лицензии, уведомления автора и сторонних компонентов, соглашение с участником, как внести вклад, кодекс поведения |
| [`SECURITY.md`](SECURITY.ru.md) | как сообщить об уязвимости конфиденциально и что продукт гарантирует в отношении недоверенных документов и пакетов |

## Профили и языки

Код написан только на английском; всё, что он знает о документах, — это данные. **Языковые пакеты**
([`assistant_x/lang/ru`](assistant_x/lang/ru), [`assistant_x/lang/en`](assistant_x/lang/en)) содержат алфавиты,
стеммеры, стоп-слова и слова, по которым распознаются документы: заголовки, ссылки на таблицы и рисунки, обозначения
стандартов, титульные листы, личные документы, скрытые инструкции. По умолчанию используются все пакеты
(`[documents] languages` в `assistant_x.toml`), поэтому русские и английские документы читаются одинаково в любой
рабочей папке, а у каждой карточки есть тексты для поиска на английском и на русском. Полки библиотеки (буквы шифров)
везде одинаковы: N — стандарты, L — литература, P — проекты и отчёты, E — документация на оборудование, R — нормативные
акты и законодательство, J — журналы и статьи, X — прочее
([`assistant_x/schemas/shelves.json`](assistant_x/schemas/shelves.json)). **Профиль предметной области**
(`assistant_x/profiles/<name>`) добавляет только знания одной области: `general` (по умолчанию) не содержит ничего,
`oil-gas-ru` приносит русские нефтегазовые синонимы и роль инженера-технолога в навыке (`assistant-x init --profile
oil-gas-ru`).

## Ваша рабочая папка (не в репозитории)

Все ваши данные хранятся в одной папке, по умолчанию `Documents\Assistant X` (её создаёт `assistant-x init [FOLDER]`;
другая папка: `AX_WORKSPACE` или `--workspace`): `assistant_x.toml` (настройки), `inbox/` (новые документы), `library/`
(оригиналы по полкам, `01_Standards … 99_Other`), `index/` (`cards/<code>.json` — JSON-карточки, единственный источник
истины о каждом документе; `texts/<code>.md` со страницами `=== page N ===`; `CATALOG.md` и `sources_to_update.md`,
созданные из карточек; `intake_events.tsv` и генерируемые `journal.md`, `manifest.tsv`, `ocr_quality.tsv`), `reports/`
и `.assistant_x/` (база, пакеты разбора, отладочные журналы; модели относятся к ПК и лежат в
`%USERPROFILE%\.assistant_x\models`). Храните собственную копию `library` и `index`: это ваши данные. В папку с кодом
ничего не записывается.

## Требования

- **Система:** Windows 10 или 11 (x64) либо Linux (x86_64; см. «Linux и macOS» ниже).
- **Python 3.11** (проверенная версия; на Windows Setup.bat установит его, если его нет).
- **Диск:** около 6 ГБ под модели (≈ 4,5 ГБ) и пакеты (≈ 1 ГБ), плюс место под вашу библиотеку.
- **Память:** рекомендуется 8 ГБ ОЗУ (модели и разбор сканов занимают несколько ГБ).
- **Видеокарта:** необязательна. NVIDIA (CUDA), AMD или Intel с собственной памятью (DirectML) ускоряют поиск по
  смыслу; без видеокарты он выполняется на процессоре.
- **Приложение с поддержкой MCP:** Claude Desktop или Claude Code; Codex (CLI, IDE) или настольное приложение ChatGPT;
  DeepSeek Harness; LM Studio с моделью, умеющей вызывать инструменты; или любой MCP-клиент (stdio либо streamable HTTP
  с `assistant-x serve --http`). Библиотекой можно пользоваться и только из командной строки (см. «Без приложения»
  ниже).
- **Куда уходит ваш текст:** поиск выполняется на вашем ПК, но страницы, которые модель читает для ответа, попадают к
  поставщику этой модели (Anthropic, OpenAI, DeepSeek). Для конфиденциальных документов используйте локальную модель в
  LM Studio.

## Начало работы (Windows)

1. [`Setup.bat`](Setup.bat) — находит или устанавливает Python, устанавливает пакеты и программу, создаёт рабочую папку
   `Documents\Assistant X` с профилем `general`, подключает библиотеку ко всем найденным приложениям (Claude Desktop,
   Claude Code, Codex, DeepSeek Harness, LM Studio: `assistant-x connect auto`), записывает навыки и запускает
   самопроверку. При установке с носителя (`assistant-x prepare-media --out E:\` на ПК с интернетом:
   [`Setup.bat`](Setup.bat), `app\`, `packages\`, `models\` с `MODELS.json`, `programs\`) всё, что относится к
   программе, помещается в `%USERPROFILE%\.assistant_x` — `app\<version>`, окружение `venv`, модели (сверяются с
   `MODELS.json`), программы для разбора, — а в рабочей папке остаются только ваши данные;
   `Setup.bat --base E:\base\x.axbase` сразу после этого устанавливает базовый пакет. Другая папка или нефтегазовый
   профиль: `Setup.bat --workspace "D:\My library"
   --profile oil-gas-ru`. Из папки с кодом (рабочая копия для разработки)
   используется `.venv` рядом с ней; затем `assistant-x.bat download-models` скачивает модели (≈ 4,5 ГБ) в
   `%USERPROFILE%\.assistant_x\models`; без них поиск идёт только по словам. Служебную папку ПК
   `%USERPROFILE%\.assistant_x` (программа, модели, программы для разбора, блокировки, токены) можно перенести: задайте
   `AX_MACHINE_DIR` с другой папкой до запуска [`Setup.bat`](Setup.bat) и не удаляйте эту переменную.
2. [`scripts\install_intake.bat`](scripts/install_intake.bat) (`assistant-x setup-intake`) — LibreOffice, Tesseract
   (языки пакетов: по умолчанию rus+eng), 7-Zip и DjVuLibre для разбора, без прав администратора.
3. Только для Claude Desktop: упакуйте в ZIP папку `skill` рабочей папки (в ней лежит `SKILL.md`) и загрузите её в
   Claude → Settings → Capabilities → Skills, затем перезапустите Claude Desktop (значок у часов → Quit, затем откройте
   снова). Codex, Claude Code и DeepSeek Harness получили свой навык от `connect`; в LM Studio любая модель узнаёт
   правила из инструмента `library_guide`.
4. Положите документы в `inbox` рабочей папки и напишите ассистенту «AX: разбери мои документы» (или дважды щёлкните
   [`intake.bat`](intake.bat), а карточки пусть ассистент напишет потом).
5. Задавайте вопросы, начиная сообщение с «AX:» (или «подключись к библиотеке»). Ответы содержат ссылки вида
   `[code, p. printed, PDF N]`. `assistant-x.bat doctor` показывает, где что находится и чего не хватает,
   `assistant-x connect --check` — доступна ли библиотека каждому приложению.

## Команды вкратце

`assistant-x <command>` ([`assistant-x.bat`](assistant-x.bat) на Windows; `assistant-x help` выводит их все;
`--workspace DIR` в любом месте выбирает другую рабочую папку):

| Команда | Что делает |
| --- | --- |
| `init [FOLDER]`, `doctor` | создать рабочую папку; показать, где что находится и чего не хватает |
| `intake run`, `intake status`, `intake check-meta`, `intake build`, `intake apply [--dry-run]` | разбор папки `inbox` ([docs/INTAKE.md](docs/INTAKE.ru.md)) |
| `remove CODE [--why TEXT] [--dry-run]` | убрать документ из библиотеки в сторону (`inbox\_to_delete`), его шифр остаётся зарезервированным ([docs/INTAKE.md](docs/INTAKE.ru.md)) |
| `build [--full]`, `embed [--cpu]` | поисковая база из карточек и текстов; смысловые векторы новых фрагментов |
| `search "question"` | запрос из командной строки |
| `base export`, `base inspect`, `base install`, `base update`, `base remove` | базовые пакеты: библиотека, которую передают другим людям ([docs/PACKAGES.md](docs/PACKAGES.ru.md)) |
| `connect APP\|auto`, `connect --list`, `connect --check`, `disconnect APP` | подключить приложения этого ПК ([docs/CLIENTS.md](docs/CLIENTS.ru.md)) |
| `update` | заново подключить все подключённые приложения (после новой версии: их запись и их навык) |
| `install --yes --json` | установка без вопросов, в конце сводка в JSON (для агента) |
| `mcp [--tools reader] [--compact]`, `service` | мост stdio, который запускает каждое приложение; сервис библиотеки, с которым он связывается (оба запускаются сами) |
| `serve [--http]` | MCP-сервер в процессе приложения (запасной вариант) или по HTTP для других клиентов |
| `setup-intake`, `download-models`, `skill` | программы для разбора; модели; навык |
| `report`, `query-log`, `debug-report` | состояние библиотеки; что спрашивали приложения; отчёт, который можно передать, если что-то не работает |

### Без приложения

Разбор запускается и из командной строки: `assistant-x intake run` создаёт тексты и `meta_draft.jsonl` в
`.assistant_x\work\<date>`; по черновику вручную напишите там `meta.jsonl` (одна строка JSON на файл:
[docs/INTAKE.md](docs/INTAKE.ru.md), раздел «Карточки»), проверьте его командой `assistant-x intake check-meta`, затем
выполните `assistant-x intake build`, `assistant-x intake apply
--dry-run`, `assistant-x intake apply`, `assistant-x build` и `assistant-x embed`.

## Устранение неполадок

- **«Found by words only»** или «N of M fragments have no meaning vectors»: эмбеддингов нет или они ещё загружаются.
  Подождите 10–20 с после запуска библиотеки; если не помогло, выполните `assistant-x embed` (или попросите ассистента
  вызвать `intake_reindex`), а `assistant-x doctor` назовёт недостающую модель (`assistant-x download-models`).
- **Установка, обновление или удаление базового пакета прервались** (ПК выключился): `assistant-x base install PACKAGE
  --resume` продолжает операцию, `--rollback` отменяет её (то же для `update` и `remove`); ассистент сообщает об этом в
  своём статусе.
- **Приложение не видит библиотеку**: `assistant-x connect --check` выполняет рукопожатие и поиск через запись каждого
  приложения и сообщает, какое звено не работает; `assistant-x connect APP` записывает запись заново.
- **Применение разбора прервалось**: `assistant-x intake apply --resume`.
- **«the machine lock is busy»**: выполняется другая тяжёлая задача (`assistant-x lock` скажет какая); подождите или
  добавьте `--wait`.
- **Всё остальное**: `assistant-x debug-report` создаёт файл, который можно передать тому, кто вам помогает (сначала
  прочитайте его: в нём названы папки и последние вопросы).

## Установка через pip (любая система)

Python 3.11 (проверенная версия; более новые версии пока не проверялись). В папке с кодом (клоне репозитория):

```
python -m venv .venv
.venv/bin/python -m pip install -c assistant_x/setup/constraints.txt -e ".[dense,intake]"
.venv/bin/assistant-x init
.venv/bin/assistant-x download-models
```

(на Windows `.venv\Scripts\…`). `constraints.txt` содержит версии релиза: те же пакеты, что и при установке через
Setup.bat. `[dense]` добавляет поиск по смыслу (torch; на Windows torch из PyPI работает только на процессоре, поэтому
для карты NVIDIA сначала установите сборку с CUDA с download.pytorch.org — без неё карта не используется, и `embed`
спрашивает о работе на процессоре), `[intake]` — разбор ваших собственных документов; без них поиск идёт по словам.
`assistant-x init` создаёт рабочую папку (`--profile oil-gas-ru` для нефтегазового профиля), `assistant-x doctor`
показывает, чего не хватает. Затем `assistant-x connect auto` подключает приложения (см. ниже).

### Linux и macOS

Программа работает и там (служебная папка ПК — `~/.cache/AssistantX` или `AX_MACHINE_DIR`); Setup.bat и офлайн-носитель
предназначены только для Windows. Программы для разбора берутся из системы: `apt install
libreoffice tesseract-ocr tesseract-ocr-rus p7zip-full djvulibre-bin` (Debian, Ubuntu) или `brew install libreoffice
tesseract tesseract-lang p7zip djvulibre` (macOS); `assistant-x setup-intake --no-install` находит их и записывает их
пути в `assistant_x.local.toml`. Тесты (все, кроме медленных) выполняются в CI на Linux и Windows с Python 3.11
([`.github/workflows/tests.yml`](.github/workflows/tests.yml)); macOS и более новые версии Python пока не проверялись.

### Подключение приложений

`assistant-x connect auto` (его запускает Setup.bat) записывает запись библиотеки во все найденные приложения; `assistant-x
connect APP` — в одно приложение (`claude_desktop`, `claude_code`, `codex`, `dsh`, `lmstudio`), `--full`
даёт приложению все инструменты, `assistant-x disconnect APP` убирает запись. Рядом сохраняется копия файла настроек,
чужие записи остаются на месте. Каждая запись запускает один и тот же лёгкий мост,
`<python> -m assistant_x.server.bridge`, который связывается с единственным сервисом библиотеки на 127.0.0.1: модели
загружаются один раз для всех приложений. Вручную (для любого MCP-клиента, который запускает программу):

```json
{
  "mcpServers": {
    "assistant-x": {
      "command": "C:\\Users\\you\\.assistant_x\\venv\\Scripts\\pythonw.exe",
      "args": ["-m", "assistant_x.server.bridge", "--tools", "reader"],
      "env": {"AX_WORKSPACE": "C:\\Users\\you\\Documents\\Assistant X", "PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1"}
    }
  }
}
```

**Добавление в LM Studio** без командной строки: `assistant-x connect lmstudio --link` выводит ссылку
(`lmstudio://add_mcp?...`, запись этого ПК); если её открыть, LM Studio предложит добавить сервер. Её же приводит
итоговая сводка установщика.

После выхода новой версии `assistant-x update` заново записывает записи; навыки приложений обновляет сервис библиотеки
при первом запуске (навык, отредактированный вручную, сохраняется), а Claude Desktop один раз сообщит, что загруженный в
него навык устарел.

`--tools reader` даёт 8 инструментов для чтения (поиск, страницы, оглавление, изображение страницы, проверка цитаты,
карточка, список, руководство); без этого ключа доступны все инструменты (разбор, базовые пакеты). `--compact`
сокращает описания и ответы для небольших локальных моделей. Приложения и их файлы: [docs/CLIENTS.md](docs/CLIENTS.ru.md).
Клиенты, которые работают с MCP только по HTTP: `assistant-x serve --http [--port 8765]` (каждый запрос должен нести
bearer-токен из `mcp_http_token.txt` в служебной папке ПК: [SECURITY.md](SECURITY.ru.md)).

## Тесты

Модели и настоящая библиотека не нужны (мини-библиотека собирается на лету во временной рабочей папке):

```
.venv\Scripts\python.exe -m pytest -q tests
```

Папки: `tests\base` (базовые пакеты: экспорт, проверка, установка, обновление, враждебные пакеты), `tests\search`
(поиск, индекс, сервер, установщик), `tests\intake` (разбор), `tests\corpus` (распознавание корпуса в сравнении с его
эталоном) и тесты на верхнем уровне `tests` (карточки, языковые пакеты, профили, носитель, английская библиотека).
[`scripts\check.ps1`](scripts/check.ps1) запускает ruff и все тесты (`-Fast`: без медленных). Медленные тесты (полный
разбор с LibreOffice и OCR, корпус) помечены `@pytest.mark.slow`: `pytest -m slow tests`.
[`hooks/pre-commit`](hooks/pre-commit) запускает ruff и `pytest -m "not slow" tests` перед коммитом (скопируйте его в
`.git/hooks/`).

## Лицензия

- **Код** — свободное программное обеспечение под лицензией GNU AGPL-3.0-or-later ([`LICENSE`](LICENSE)). Вы можете
  использовать его для себя или внутри своей компании, изменять и передавать другим. Тот, кто передаёт копии,
  изменённые или нет, передаёт вместе с ними исходный код под той же лицензией; тот, кто запускает изменённую версию
  как сетевой сервис для других людей, предоставляет этим людям её исходный код.
- **Данные** в [`assistant_x/lang`](assistant_x/lang), [`assistant_x/profiles`](assistant_x/profiles) и
  [`assistant_x/schemas`](assistant_x/schemas) (языковые пакеты, профили предметных областей, схема карточки и полки)
  также доступны под CC-BY-4.0 ([`LICENSES/CC-BY-4.0.txt`](LICENSES/CC-BY-4.0.txt)): их можно использовать в любом
  проекте, открытом или закрытом, с указанием «Assistant X by Alexandr Yalovoy» и ссылкой на лицензию.
- **Ваши документы**, карточки, тексты и база принадлежат вам: лицензии программы на них не распространяются.
- **Сторонние компоненты** (PyMuPDF, Tesseract, LibreOffice, 7-Zip, модели) сохраняют собственные лицензии:
  [`NOTICE`](NOTICE).
- **Вклад** принимается на условиях соглашения с участником (Contributor License Agreement, [`CLA.md`](CLA.md), см.
  [`CONTRIBUTING.md`](CONTRIBUTING.ru.md)).

## Безопасность

Сообщайте об уязвимости конфиденциально (GitHub → Security → Report a vulnerability), никогда не публикуя её
подробности в открытом issue (если эта форма вам недоступна: issue с заголовком «private contact request» и больше
ничего): [`SECURITY.md`](SECURITY.ru.md) объясняет, как это сделать и что Assistant X гарантирует в отношении
документов и базовых пакетов, которые он читает.

## Отказ от ответственности

Автор не несёт ответственности за документы и библиотеки, которые пользователи загружают в ассистента. Права на эти
документы принадлежат их правообладателям; пользователи сами отвечают за то, чтобы проверить, вправе ли они загружать и
использовать то, что загружают. Это дополняет положение об отсутствии гарантий в GNU AGPL.

## Разработка с помощью ИИ

Assistant X разработан с помощью Claude Desktop и Claude Code на моделях Claude Opus 5.5 и Claude Fable 5.1.
