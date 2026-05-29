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

**Группа A (предоставление контекста) — базовый минимум:**

| Инструмент | Что отдаёт | Откуда читает |
|---|---|---|
| `get_book_info` | название, аудитория, стиль, список глав | `book_meta/book_info.yaml` |
| `get_style_guide` | полный текст стилгайда | `book_meta/style_guide.md` |
| `get_chapter` | содержание главы или её части | `chapters/chapter_NN/chapter.md` (или `draft.md`) |

`get_chapter` принимает `chapter_number` и `section` (`all` по умолчанию,
либо `summary` / `bridge` / номер раздела как строка).

## Установка

1. Установить зависимости (рекомендуется в виртуальном окружении):

   ```powershell
   pip install -r mcp/requirements.txt
   ```

2. Проверить, что сервер импортируется и видит инструменты:

   ```powershell
   python -c "import sys; sys.path.insert(0, 'mcp'); import asyncio, server; print(sorted(t.name for t in asyncio.run(server.mcp.list_tools())))"
   ```

   Ожидаемый вывод: `['get_book_info', 'get_chapter', 'get_style_guide']`.

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
    context_tools.py     # Группа A — get_book_info / get_style_guide / get_chapter
  tests/
    conftest.py          # фикстуры book_repo / real_repo
    test_context_tools.py
```

## Что дальше (по брифингу, Часть 0)

- Группа A, остальное: `get_patterns_for_phase`, `get_pattern_details`,
  `get_glossary`, `get_pending_promises`, `get_chapter_plan`,
  `get_conflicts_table`.
- Группа B (проверки): `check_terms`, `check_markers`, `check_structure`,
  затем оркестратор `verify_chapter`, затем остальные проверки.
- `checks_config.yaml` — настройка строгости проверок.
