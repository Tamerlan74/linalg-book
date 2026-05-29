# linalg-book-mcp

MCP-сервер для книги «Линейная алгебра, по-человечески». Работает как
**внешнее хранилище контекста** для Claude в чате claude.ai: вместо того
чтобы в каждом новом чате заново объяснять стиль книги, паттерны и
содержание предыдущих глав, Claude обращается к этому серверу по
требованию.

Дополнительно сервер будет выполнять **проверки** написанной главы
(Группа B) — это добавится следующими сеансами.

> Сервер — детерминированный инструмент: только читает файлы репозитория
> и проверяет их. Никаких вызовов LLM, БД, генерации текста.

## Что уже реализовано

**Группа A (предоставление контекста) — полностью:**

| Инструмент | Что отдаёт | Откуда читает |
|---|---|---|
| `get_book_info` | название, аудитория, стиль, список глав | `book_meta/book_info.yaml` |
| `get_style_guide` | полный текст стилгайда | `book_meta/style_guide.md` |
| `get_chapter` | содержание главы или её части | `chapters/chapter_NN/chapter.md` (или `draft.md`) |
| `get_chapter_plan` | план главы целиком (metadata.json) | `chapters/chapter_NN/metadata.json` |
| `get_pending_promises` | обещания, висящие на главе `for_chapter` | `chapters/*/metadata.json` → `bridge_to_next.promises` |
| `get_glossary` | термины с определениями и главой ввода | разметка `**[термин]{определение}**` в главах |
| `get_patterns_for_phase` | карточки паттернов для фазы главы | `patterns/<phase>/*.md` (YAML-фронтматтер) |
| `get_pattern_details` | полный текст паттерна по `pattern_id` | `patterns/**/<pattern>.md` (по имени файла или `id`) |
| `get_conflicts_table` | таблица конфликтов паттернов | `patterns/00_conflicts.md` |

- `get_chapter` принимает `chapter_number` и `section` (`all` по умолчанию,
  либо `summary` / `bridge` / номер раздела как строка).
- `get_patterns_for_phase` принимает `phase` — одно из: `global`,
  `chapter_opening`, `introducing_concept`, `deriving_formula`, `climax`,
  `biohazards`, `pauses`, `chapter_closing`, `tasks`, `book_level`.
- `get_pending_promises` принимает `for_chapter`: возвращает обещания из
  мостика **предыдущей** главы (та обещала их для этой).

**Группа B (проверки готовой главы) — первый срез:**

| Инструмент | Что проверяет | С чем сверяет |
|---|---|---|
| `check_structure` | H1, наличие/порядок/заголовки разделов, итог, мостик | проза ↔ `metadata.json` (`sections`, `bridge_to_next`) |
| `check_markers` | число маркеров ⚠, их частоту и размещение | `metadata.json` (`biohazards_in_chapter`) + паттерн `biohazard_marker` |
| `verify_chapter` | оркестратор: запускает обе проверки | сводный отчёт с вердиктом `ok`/`warn`/`fail` |

- Все три принимают `chapter_number`. `check_*` возвращают список находок
  `{check, severity, code, message, location}`, где `severity ∈ {error,
  warning, info}`. `verify_chapter` агрегирует находки, считает
  `error/warning/info` и выдаёт `verdict`: `fail` при любой `error`, иначе
  `warn` при `warning`, иначе `ok`.
- Если файла главы нет — ошибка «глава не написана». Если нет
  `metadata.json` — это находка `missing_metadata` (error), а не падение.
- Строгость кодов пока захардкожена в `verify_tools.py`; `checks_config.yaml`
  появится, когда проверок станет больше.

> Глоссарий собирается из разметки терминов прямо в главах (источник
> истины), а не из производного `book_meta/glossary.md`. Фронтматтер
> паттернов разбирается своим мини-парсером поверх `pyyaml` — отдельной
> зависимости `python-frontmatter` нет.

> **Все 36 карточек паттернов приведены к единому формату:** `id` = имя
> файла, `task_type`, `frequency_per_chapter`, тело с разделом `# Суть`.
> Парсер при этом остаётся **устойчивым к старому формату** (`category`
> вместо `task_type`, тело с разделом `# Описание`, `id` = код вида
> `T1`/`B3`) — на случай новых файлов или ручных правок. Поля собираются
> с fallback'ом: `task_type ← task_type | category`,
> `frequency ← frequency | frequency_per_chapter | frequency_per_book`,
> а `summary` / `when_to_apply` / `when_not_to_apply` / `example` берутся
> из фронтматтера, а при отсутствии — из соответствующих H1-разделов тела
> (`# Суть`/`# Описание`, `# Когда применять`, `# Когда не применять`,
> `# Пример …`). `get_pattern_details` находит паттерн и по имени файла,
> и по `id` (включая legacy-коды `T1`/`B3`). Коды `T*/B*/S*` — устаревшая
> схема перекрёстных ссылок, она встречается только в прозе разделов
> «Совместимость» (поле `source` фронтматтера дублирует код в скобках,
> напр. `(T1)`); машиночитаемый `00_conflicts.md` ссылается на паттерны
> по имени файла.

## Установка

1. Установить зависимости (рекомендуется в виртуальном окружении):

   ```powershell
   pip install -r mcp/requirements.txt
   ```

2. Проверить, что сервер импортируется и видит инструменты:

   ```powershell
   python -c "import sys; sys.path.insert(0, 'mcp'); import asyncio, server; print(sorted(t.name for t in asyncio.run(server.mcp.list_tools())))"
   ```

   Ожидаемый вывод (9 инструментов Группы A + 3 Группы B):
   `['check_markers', 'check_structure', 'get_book_info', 'get_chapter', 'get_chapter_plan', 'get_conflicts_table', 'get_glossary', 'get_pattern_details', 'get_patterns_for_phase', 'get_pending_promises', 'get_style_guide', 'verify_chapter']`.

## Подключение к Claude Desktop

1. Открыть конфиг Claude Desktop:

   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`

2. Добавить сервер в секцию `mcpServers` (путь — до **вашего** `server.py`):

   ```json
   {
     "mcpServers": {
       "linalg-book": {
         "command": "python",
         "args": ["D:\\projects\\linalg-book\\mcp\\server.py"]
       }
     }
   }
   ```

   - Если вы используете виртуальное окружение, в `command` укажите путь
     к его `python.exe` (например,
     `D:\\projects\\linalg-book\\.venv\\Scripts\\python.exe`).
   - По умолчанию сервер определяет корень репозитория как родителя папки
     `mcp/`. Если нужно указать корень явно (например, при нестандартном
     расположении), добавьте переменную окружения:

     ```json
     "linalg-book": {
       "command": "python",
       "args": ["D:\\projects\\linalg-book\\mcp\\server.py"],
       "env": { "LINALG_BOOK_ROOT": "D:\\projects\\linalg-book" }
     }
     ```

3. Перезапустить Claude Desktop.

4. Проверить: в любом чате написать «используй MCP linalg-book, вызови
   get_book_info». Claude должен вернуть название книги и список глав.

## Запуск вручную (для отладки)

```powershell
python mcp/server.py
```

Сервер запускается в режиме stdio и ждёт MCP-протокол на stdin. Все логи
идут в **stderr** (stdout зарезервирован под протокол). Чтобы остановить —
Ctrl+C или закрытие stdin.

## Тесты

```powershell
python -m pytest mcp/tests/ -q
```

## Структура

```
mcp/
  server.py              # FastMCP-сервер, регистрация инструментов
  config.py              # определение корня репозитория
  cache.py               # in-memory кеш чтений файлов (mtime)
  requirements.txt
  README.md
  tools/
    context_tools.py     # Группа A — все 9 функций контекста
    verify_tools.py      # Группа B — check_structure / check_markers / verify_chapter
  tests/
    conftest.py          # фикстуры book_repo / real_repo
    test_context_tools.py
    test_verify_tools.py
```

## Что дальше (по брифингу, Часть 0)

- ✅ Группа B, первый срез: `check_structure`, `check_markers`,
  оркестратор `verify_chapter`.
- Группа B, далее: `check_terms` (термины ↔ глоссарий/разметка),
  `check_promises` (обещания мостика отработаны в следующей главе).
- Группа B, остальное: `check_patterns`, `check_links`,
  `check_terminology`, `check_styleguide`.
- `checks_config.yaml` — настройка строгости проверок (когда проверок
  станет больше).
