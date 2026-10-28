[English](GLOSSARY.md) | Русский

# Глоссарий

Английские термины, которые Assistant X использует везде (в коде, сообщениях, документации), и их русские соответствия
для пользователей, работающих на русском. Код, тесты и правила для моделей — только на английском; у документов для
людей есть русские двойники (name.ru.md); в остальном русский язык хранится лишь как данные для русских документов
(последний раздел).

## Термины

| Русский | English | Примечание |
| --- | --- | --- |
| шифр | code | буква полки и пять цифр, `N-00001`; у части — `E-00006-02` |
| карточка | card | `index/cards/<code>.json`, схема [`assistant_x/schemas/card-1.json`](../assistant_x/schemas/card-1.json) |
| полка (раздел библиотеки) | shelf, section | буква шифров и папка в `library`, одинаковые во всех библиотеках (`schemas/shelves.json`) |
| тип документа | document type, genre | `doc_type`: один универсальный список (standard, book, serial_issue…) |
| языки карточки | card languages | английский и каждый язык из `[documents] languages` (по умолчанию русский и английский) |
| статья выпуска | unit | статья из выпуска журнала, доклад из сборника трудов: `doc.units`, отдельный фрагмент |
| текст (документа) | text | `index/texts/<code>.md`, страницы размечены `=== page N ===` |
| разбор | intake | обработка `inbox`: распаковка, OCR, тексты, черновики карточек |
| партия (разбора) | batch | один запуск разбора, `intake/work/<date>` |
| перенос | apply | `intake.py apply`: оригиналы в `library`, карточки и тексты в `index` |
| сборка (карточек) | build | `intake.py build`; также сборка базы (`build_index.py`) |
| библиотека | library | оригиналы, `library/` |
| каталог | catalog | `index/CATALOG.md` |
| манифест | manifest | `index/manifest.tsv` |
| журнал | journal | `index/journal.md` (создаётся программой); также журнал вызовов `.assistant_x/debug/calls.log` |
| события разбора | intake events | `index/intake_events.tsv` |
| источники к обновлению | sources to update | `index/sources_to_update.md` |
| замок | lock | `core/lock.py`: замок папки (один разбор за раз), замок машины (одна тяжёлая задача на ПК) |
| навык | skill | `<workspace>/skill/SKILL.md`, записывается командой `assistant-x skill` |
| носитель | media | папка или архив, с которых идёт установка без интернета |
| выпуск | release | выпущенная версия |
| стандарты | standards | полка N |
| нормативные акты и регламенты | regulations and law | полка R |
| паспорта и руководства | equipment documents | полка E |
| литература | literature | полка L |
| проекты и отчёты | projects and reports | полка P |
| журналы и статьи | journals and papers | полка J |
| прочее | other | полка X |
| поисковая база | (search) base | `.assistant_x/db/library.sqlite` рабочей папки |
| векторы (смыслы) | embeddings, meaning vectors | `vectors-*.f16` |
| поиск по смыслу | semantic search, search by meaning | |
| поиск по словам | search by words | FTS5 со стеммингом и синонимами |
| модель векторов (модель смыслов) | embedding model | BAAI/bge-m3 |
| переранжирование | reranking | bge-reranker-v2-m3 |
| распознавание | recognition, OCR | Tesseract |
| оценка распознавания | recognition score | 0–100, `ocr_quality.tsv` |
| скан | scan | |
| черновик (метаданных) | draft | `meta_draft.jsonl` |
| дубль | duplicate | |
| новая версия (документа) | new version | другая редакция документа библиотеки: заменить его или оставить оба (`intake/versions.py`) |
| отброшено | rejected | `inbox/_rejected` |
| под удаление | to delete | `inbox/_to_delete` |
| личный документ | personal document | `intake.personal` в карточке |
| качество источника | source quality | предупреждение рядом с найденным фрагментом |
| издательство, издание | publisher, edition | `doc.publisher`, `doc.edition` |
| нумерация страниц | page numbering | `doc.page_offset`: печатная страница = страница PDF − значение |
| отладочный отчёт | debug report | `assistant-x debug-report` |
| установка | installation | `install.bat` |
| базовый пакет | base package | готовая библиотека, добавляемая в рабочую папку ([ROADMAP.ru.md](../ROADMAP.ru.md)) |
| рабочая папка | workspace | папка данных пользователя с `assistant_x.toml` (`core/workspace.py`) |
| профиль (предметной области) | (domain) profile | знания отрасли: синонимы, формулировки навыка ([`assistant_x/profiles`](../assistant_x/profiles)) |

## Форматы файлов (assistant_x/core/formats.py, assistant_x/core/card.py)

Все файлы проекта записываются с английскими названиями, на каком бы языке ни были документы:

| Что | Как записывается |
| --- | --- |
| маркер страницы | `=== page N ===` |
| карточка | JSON: `schema`, `code`, `section`, `doc_type`, `doc` (содержание документа), `file` (файл), `intake`; ключи отсортированы, отступ в один пробел |
| столбцы каталога | Code, Document, Type, Section, Year, Format, Key topics (строятся по карточкам: `search/catalog.py`) |
| штамп каталога | `Updated: DATE. Documents: N.` |
| источники к обновлению | `## Open`, `## Closed`, `Updated: DATE. Open items: N.` |
| приоритет | high, medium, low |
| статус события (начало строки) | done, duplicate, rejected, to delete, error, to pdf, estimate, archive |
| заголовок событий | date, source_file, size, sha256, code, destination, status |
| заголовок манифеста | path, size, modified, sha256, code |
| заголовок ocr_quality.tsv | code, score, nonword, words, pages, pages_below_threshold, worst_pages, source, date |
| формат в карточке | `file.format.kind`: pdf_text, pdf_mixed, pdf_scan, pdf_no_ocr, doc, presentation, image, ebook, text, spreadsheet, other; словами `PDF with text, 12 pages`, `PDF scan (OCR, errors possible), 3 pages` |
| места | в карточке `library/01_Standards/…`; в событиях и перемещениях `library\01_Standards\…`, `inbox\…` |

## Что хранится на русском (данные)

Assistant X читает русские документы, поэтому русские слова нужны, но только в **файлах данных**: в коде Python нет
кириллицы (это проверяет [`tests/test_workspace.py::test_no_cyrillic_in_the_code`](../tests/test_workspace.py)). Код
составляет свои шаблоны из языковых пакетов языков документов (`[documents] languages`, по умолчанию все пакеты,
русский первым) и из профиля предметной области (`profile` в `assistant_x.toml`); их загружают `core/lang.py` и
`core/config.py`. Ни одно правило кода не называет язык: какие буквы делают текст русским или английским, какие буквы
теряются при испорченном шрифте, какой стеммер, какие двухбуквенные слова, какой язык Tesseract — всё это ключи пакета,
поэтому третий пакет (папка `<code>` с теми же файлами; `AX_LANG_DIRS` указывает дополнительные папки пакетов)
работает без единой строки кода ([`tests/test_lang_packs.py`](../tests/test_lang_packs.py) добавляет небольшой
немецкий).

Языковые пакеты `assistant_x/lang/<code>/` (`ru` и его английский аналог `en`):

| Файл | Что содержит | Где используется |
| --- | --- | --- |
| `text.json` | буквы для классов символов, приведение регистра (русская ё как е), стеммер Snowball и буквы, по которым он выбирается (`stem_detect`), язык Tesseract, стоп-слова; `lang_share` (доля букв, при которой текст считается написанным на этом языке: русский 0.7, английский 0.85), `keep_share` (преобразованная страница должна сохранить такую долю этих букв: испорченный шрифт превращает кириллицу в латиницу) | `core/common.py` (токены, стемминг, разбиение на фрагменты, `langs_of`, `letter_shares`), каждый модуль, который считает буквы |
| `headings.json` | слова глав, общие заголовки, не называющие раздел, слова оглавления | `core/textmap.py` (`CHAPTER_RX`, `GENERIC_RX`; поиск и разбор) |
| `references.json` | подписи таблиц, рисунков, приложений; слова ссылок в основном тексте; слова оглавления; точечные заполнители после OCR | `core/textmap.py` (подписи, оглавление), `search/bookmap.py` (ссылки) |
| `documents.json` | обозначения государственных и международных стандартов, места издания, общие издательства, организационно-правовые формы компаний, слова, которые не являются названием, титульные листы стандартов, фраза, называющая документ, который заменяет стандарт, слова, указывающие на жанр (`doc_type_words`: каждый жанр из `schemas/card-1.json`, проверяются в его порядке), типовой текст начальных страниц, верхние заголовки, основная надпись чертежа, общие слова названий на английском, транслитерация | `intake/metadraft.py` |
| `intake.json` | личные бумаги по имени файла, слова скрытого текста, адресованного ИИ, папки комплекта национального стандарта | `intake/pipeline.py` |
| `ocr.json` | двухбуквенные слова и единицы измерения, сочетания из трёх букв, которые не являются мусором | `intake/tools/ocr_score.py` |
| `questions.json` | слова вопроса, который просит найти все места | `search/retrieval.py` |

Профили предметных областей `assistant_x/profiles/<name>/profile.json` (выбираются при `assistant-x init --profile`):

- `general` (по умолчанию): без данных предметной области.
- `oil-gas-ru`: `synonyms.txt` (русские нефтегазовые сокращения; комментарии на английском), формулировки навыка и
  `documents.json`: слова документов отрасли — обозначения отраслевых и корпоративных стандартов (API, NORSOK, DEP,
  NACE, стандарты компаний), её издательства (API, Shell, GPSA, SPE, PennWell…), английские слова из названий её
  стандартов (pumps, tubing, wellhead…). `core/lang.py` добавляет их после пакетов к тем же ключам (`words`, `alt`,
  `table`, `lists`); общий профиль обходится без них.
- Профиль хранит только знания своей отрасли. Полки (N Стандарты, L Литература, P Проекты и отчёты, E Паспорта и
  руководства, R Нормативные акты и регламенты, J Журналы и статьи, X Прочее) — один файл данных для всех библиотек,
  [`assistant_x/schemas/shelves.json`](../assistant_x/schemas/shelves.json), с названиями на английском и русском;
  карточки содержат английский и каждый язык, на котором читаются документы, независимо от профиля.

Также на русском, вне пакета: **тестовые данные** (русский текст документов в фикстурах — для проверки стемминга,
заголовков, ссылок и оценки распознавания; кириллические имена папок и файлов — для проверки путей с не-ASCII
символами).
