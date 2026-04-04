# Техническое описание пайплайна

## Архитектура

```
arXiv API (Atom)
      ↓
  api_client.py       — постраничная выгрузка статей
      ↓
  html_fetcher.py     — скачивание /abs/<id>, извлечение Abstract
      ↓
  extractor.py        — извлечение ключевых слов (regex или LLM)
      ↓
  MongoDB             — коллекция weekly_keyword_counts
      ↓
  trends.py           — расчёт top_popular / top_growing
      ↓
  MongoDB             — коллекция aggregates (предвычисленные топ-списки)
      ↓
  plotter.py          — графики PNG в outputs/plots/<domain>/
      ↓
  Telegram-бот        — отдаёт графики пользователям по команде /trends
```

---

## Компоненты

### 1. Конфигурация

**`config/domains.json`** — список доменов:
```json
[
  { "domain": "cs_lg", "title": "...", "arxiv_search_query": "cat:cs.LG" },
  ...
]
```

**`config/constants.py`** — все числовые параметры:
- `HISTORY_WEEKS = 52` — глубина истории (1 год)
- `TOP_N = 10` — количество ключевых слов на графике
- `GROWTH_WINDOW_WEEKS = 10` — окно для расчёта тренда роста
- `MAX_RESULTS_PER_DOMAIN = 2000` — лимит статей на домен за период
- `ARXIV_PAGE_SIZE = 200` — размер страницы при запросе к API
- `REQUEST_SLEEP_SEC = 0.5` — задержка между запросами (rate limit)
- `TOKEN_PATTERN` — regex для токенизации
- `STOPWORDS_EN` — стоп-слова (исключаются из ключевых слов)
- `MIN_TOKEN_LEN = 3` — минимальная длина токена

---

### 2. Получение статей (`arxiv/api_client.py`)

- Запрос к arXiv Atom API: `feedparser` + `requests`
- Постраничная выгрузка (`start`, `max_results`) до `MAX_RESULTS_PER_DOMAIN`
- Фильтр по диапазону дат (`submittedDate`)
- **Retry с экспоненциальным backoff**: 3 попытки, пауза ×2 при каждой ошибке

---

### 3. Скачивание и парсинг Abstract (`arxiv/html_fetcher.py`)

- Скачивает HTML страницы `https://arxiv.org/abs/<id>`
- Извлекает текст из `blockquote.abstract` через `beautifulsoup4` + `lxml`
- Убирает тег `<span class="descriptor">Abstract:</span>`
- Нормализует пробелы
- **Retry с экспоненциальным backoff** — аналогично api_client

---

### 4. Извлечение ключевых слов (`keywords/`)

Два режима, переключаются через `.env`:

**Режим regex** (по умолчанию, `USE_LLM_EXTRACTOR=0`):
- `extractor.py`: токенизация по `TOKEN_PATTERN`, фильтрация стоп-слов и коротких токенов
- Возвращает `Dict[keyword, count]`

**Режим LLM** (`USE_LLM_EXTRACTOR=1`):
- `llm_extractor.py`: вызов OpenAI-совместимого API через `smkt_llm.py`
- Структурированный вывод через Pydantic (`KeywordList`)
- При ошибке LLM — автоматический fallback на regex

---

### 5. Хранение в MongoDB (`storage/mongo.py`)

**Коллекция `weekly_keyword_counts`** — сырые данные:

| Поле | Тип | Описание |
|---|---|---|
| `domain` | str | ID домена (`cs_lg`, `cs_cl`, ...) |
| `week_start` | datetime UTC | Понедельник недели |
| `keyword` | str | Ключевое слово |
| `count` | int | Количество упоминаний |

Уникальный индекс по `(domain, week_start, keyword)`. Запись через `$inc` (upsert) — идемпотентна.

**Коллекция `aggregates`** — предвычисленные топ-списки:

| Поле | Тип | Описание |
|---|---|---|
| `domain` | str | ID домена |
| `computed_at` | datetime UTC | Время расчёта |
| `top_popular` | list[str] | Топ-10 популярных слов |
| `top_growing` | list[str] | Топ-10 растущих слов |

Обновляется после каждого прогона pipeline. Используется Telegram-ботом.

---

### 6. Аналитика (`analytics/trends.py`)

**`to_frame(rows)`** — список документов MongoDB → `pandas.DataFrame`

**`pivot_week_keyword(df)`** — pivot-таблица: строки = недели, столбцы = ключевые слова

**`top_popular_now(pivot, top_n)`** — топ-N слов по последней неделе

**`top_growing_last_window(pivot, window_weeks, top_n)`**:
- берёт последние `window_weeks` недель
- для каждого слова считает наклон (`numpy.polyfit`, degree=1)
- возвращает топ-N с максимальным наклоном

---

### 7. Графики (`plots/plotter.py`)

- `matplotlib` — линейные графики по неделям
- Один вызов `plot_keywords_over_time(pivot, keywords, title, out_path)`:
  - Создаёт родительские директории автоматически
  - При пустых данных — сохраняет заглушку "No data"
  - Обрезает историю до `HISTORY_WEEKS`

Графики сохраняются в: `outputs/plots/<slug>/top_popular.png`, `top_growing.png`

---

### 8. Оркестратор (`pipeline.py`)

`run_for_domain()`:
1. Вычисляет диапазон недель (`iter_week_starts`)
2. Загружает статьи постранично через `ArxivApiClient`
3. Для каждой статьи: скачивает HTML, извлекает abstract, считает ключевые слова
4. Агрегирует по неделям
5. Записывает в MongoDB (`upsert_week_counts`)
6. Читает обратно, строит pivot, вычисляет топ-списки
7. Сохраняет агрегаты (`save_aggregated`)
8. Строит и сохраняет графики

Ошибки отдельных статей перехватываются и логируются — pipeline не падает.

`run_all()`: создаёт `outputs/`, инициализирует клиенты, запускает `run_for_domain` для каждого домена. Ошибки отдельных доменов перехватываются — остальные продолжают выполняться.

---

### 9. Планировщик (`backend/scripts/run_scheduler.py`)

Бесконечный цикл с настраиваемым интервалом:
- `--interval-hours` (по умолчанию 6)
- `--run-once` — один прогон и выход
- Graceful shutdown по `SIGINT` / `SIGTERM`
- Сон реализован маленькими чанками (30 сек) для быстрой реакции на сигналы

---

### 10. Telegram-бот (`frontend/telegram_bot/bot.py`)

- Библиотека: `python-telegram-bot` v21+
- Команды: `/start`, `/domains`, `/trends <domain_id>`
- Отправляет пару PNG через `reply_media_group`
- Список доменов и дату последнего обновления берёт из коллекции `aggregates`
- При недоступной БД — fallback на файловую систему (`outputs/plots/`)

---

## Запуск

```bash
# Создать окружение
./sh/setup_conda.sh && conda activate conda_arxive_trends

# MongoDB
./sh/start_1_db.sh          # systemctl или ~/mongodb/bin/mongod

# Бэкенд (pipeline в цикле)
./sh/start_2_backend.sh --interval-hours 6

# Фронтенд (Telegram-бот)
./sh/start_3_frontend.sh

# Тесты
./sh/run_tests.sh -v        # 85 тестов
```

---

## Переменные окружения (`.env`)

См. [startup_guide.md](startup_guide.md#переменные-окружения-env).
