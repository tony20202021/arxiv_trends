# Техническое описание пайплайна

## Архитектура

Пайплайн разделён на три независимых сервиса (каждый — отдельный процесс с watchfiles):

```
══════════════════════ Шаг 1: run_scheduler.py --step 1 ═══════════════════════

arXiv API (Atom)
      ↓
  fetch.py / api_client.py
      — постраничная выгрузка статей батчами по неделям/дням
      — абстракт берётся из поля summary прямо из API-ответа
      ↓
  MongoDB             — коллекция articles (arxiv_id, domain, abstract, ...)

══════════════════════ Шаг 2: run_scheduler.py --step 2 ═══════════════════════

  MongoDB             — читает articles (где keywords = null или версия устарела)
      ↓
  extract.py / keywords/extractor.py
      — извлечение ключевых слов (regex / TF-IDF / YAKE / LLM)
      ↓
  MongoDB             — articles.keywords + weekly_keyword_counts ($inc upsert)

══════════════════ Шаг 3: run_scheduler.py --step 3 ═════════════════════════

  MongoDB             — weekly_keyword_counts
      ↓
  aggregate.py / analytics/trends.py
      — расчёт top_popular / top_growing (абсолютные + процентные)
      ↓
  MongoDB             — aggregates (предвычисленные топ-списки)
      ↓
  plot_service.py / plots/plotter.py
      — 5 PNG-графиков на домен + JSON-сайдкары
      ↓
  .outputs/plots/<domain>/
      ↓
  Telegram-бот / веб-дашборд  — отдаёт графики пользователям
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
- `TOP_N = 5` — количество ключевых слов на графике
- `GROWTH_WINDOW_WEEKS = 10` — окно для расчёта тренда роста
- `ARXIV_PAGE_SIZE = 200` — размер страницы при запросе к API
- `ARXIV_MAX_OFFSET = 30000` — максимальный `start` по документации arXiv
- `ARXIV_OFFSET_LIMIT = 9800` — фактический лимит (arXiv возвращает 500 при start≥10000)
- `REQUEST_SLEEP_SEC = 3.0` — задержка между запросами (рекомендация arXiv)
- `TOKEN_PATTERN` — regex для токенизации
- `STOPWORDS_EN` — стоп-слова (исключаются из ключевых слов)
- `MIN_TOKEN_LEN = 3` — минимальная длина токена

> Версия экстрактора вынесена в `backend/keywords/registry.py` (см. раздел 3).

---

### 2. Получение статей (`backend/fetch.py` + `arxiv/api_client.py`)

- Запрос к arXiv Atom API: `feedparser` + `requests`
- Абстракт берётся из поля `summary` прямо из Atom-ответа — отдельные HTTP-запросы за страницами абстрактов не нужны
- Фильтр по диапазону дат (`submittedDate`)
- **Пагинация батчами по неделям**: каждая неделя запрашивается отдельно, чтобы не превышать лимит `start=10000`; если неделя превышает лимит — автоматически дробится по дням (итеративный алгоритм с очередью, без рекурсии)
- **Retry с экспоненциальным backoff**: 5 попыток, пауза ×2 при каждой ошибке
- После каждой недели в лог выводится прогресс по доменам и неделям, прошедшее время и ETA:
  ```
  [домен 1/11] (нед. 21/53) прошло 0:03:30, осталось ~0:05:47 (ETA ~10:02 UTC)
  ```

---

### 3. Извлечение ключевых слов (`backend/extract.py` + `keywords/`)

**`keywords/registry.py`** — центральный реестр алгоритмов:

| Ключ | DB ID | Алгоритм | Статус |
|---|---|---|---|
| `1_count_stopwords` | 1 | Regex + лемматизация + стоп-слова | **активный** |
| `2_llm` | 2 | LLM (OpenAI-совместимый, `USE_LLM_EXTRACTOR=1`) | готов |
| `3_tfidf_sklearn` | 3 | Per-doc TF-IDF с биграммами (scikit-learn) | реализован |
| `4_tfidf_gensim` | 4 | TF-IDF (gensim) | заготовка |
| `5_keybert` | 5 | KeyBERT (sentence-transformers) | заготовка |
| `6_yake` | 6 | YAKE (статистический) | реализован |

**Смена алгоритма** — одна строка в `registry.py`:
```python
ACTIVE_EXTRACTOR_KEY = "1_count_stopwords"  # изменить здесь
```
При смене DB ID возрастает → Сервис 2 автоматически перепроцессирует все статьи.

В БД хранится целое число (`keyword_extractor_version`) для скорости индексирования.
В `aggregates` сохраняется строковый ключ (`extractor_key`) — отображается в заголовках графиков и в Telegram.

**`keywords/extractor.py`** — реализация алгоритма v1:
- Токенизация по `TOKEN_PATTERN`, фильтрация стоп-слов и коротких токенов
- Лемматизация через spaCy (пробует scispacy `en_core_sci_sm`, fallback — `en_core_web_sm`)
- Возвращает `Dict[keyword, count]`

**`keywords/llm_extractor.py`** — реализация алгоритма v2:
- Вызов OpenAI-совместимого API
- Структурированный вывод через Pydantic (`KeywordList`)
- Возвращает `None` если `USE_LLM_EXTRACTOR != 1`

---

### 4. Хранение в MongoDB (`storage/mongo.py`)

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
| `domain` | str | ID домена (в т.ч. `_all` — суммарный по всем) |
| `computed_at` | datetime UTC | Время расчёта |
| `top_popular` | list[str] | Топ-N популярных слов |
| `top_growing` | list[str] | Топ-N растущих слов |
| `extractor_key` | str | Ключ алгоритма (`1_count_stopwords` и т.д.) |

Обновляется после каждого прогона Сервиса 3. Используется Telegram-ботом и веб-дашбордом.

> **Производительность**: `get_counts_all_domains()` использует MongoDB `$group` агрегацию вместо `find()` —
> сервер суммирует counts по (week_start, keyword) и возвращает на порядок меньше данных.
> `get_article_counts_by_week()` и `get_article_counts_all_domains()` используют `allowDiskUse=True` без таймаута.

---

### 5. Аналитика (`analytics/trends.py`)

**`to_frame(rows)`** — список документов MongoDB → `pandas.DataFrame`

**`pivot_week_keyword(df)`** — pivot-таблица: строки = недели, столбцы = ключевые слова

**`pivot_week_keyword_pct(pivot, article_counts)`** — нормировка по числу статей (% упоминаний от всех статей недели);
нормализует ключи `article_counts` к UTC-aware datetime перед lookup, чтобы совпадали с индексом pivot

**`top_popular_now(pivot, top_n)`** — топ-N слов по последней неделе

**`top_growing_last_window(pivot, window_weeks, top_n)`**:
- берёт последние `window_weeks` недель
- для каждого слова считает наклон (`numpy.polyfit`, degree=1)
- возвращает топ-N с максимальным наклоном

**`growing_slopes(pivot, keywords, window_weeks=None)`**:
- `window_weeks=None` → наклон по **всему отображаемому периоду** (весь `pivot`)
- `window_weeks=N` → наклон по последним N неделям (`pivot.iloc[-N:]`)
- вызывается дважды для каждого growing-графика: полный период и `GROWTH_WINDOW_WEEKS`
- для `top_growing_pct.png` вычисляется отдельно по `pivot_pct` → slopes в %/нед

---

### 6. Графики (`backend/plot_service.py` + `plots/plotter.py`)

`render_plots()` строит **5 графиков на домен** (+ суммарные для `_all`):

| Файл | Описание |
|---|---|
| `top_popular.png` | Топ-N популярных слов (абсолютные счётчики) |
| `top_growing.png` | Топ-N растущих слов (абсолютные счётчики) |
| `top_popular_pct.png` | Топ-N популярных (% от числа статей недели) |
| `top_growing_pct.png` | Топ-N растущих (% от числа статей недели) |
| `articles_per_week.png` | Количество статей по неделям |

**JSON-сайдкары** — рядом с каждым keyword-графиком сохраняется `.json` с данными последней недели:
```json
{
  "keywords": ["learn", "train", "llm", "reason", "agent"],
  "counts":   {"learn": 1234, "train": 987, ...},
  "pcts":     {"learn": 3.2, "train": 2.5, ...},
  "growth":       {"learn": 14.9, "train": 8.2, ...},
  "growth_short": {"learn": 22.1, "train": 5.1, ...},
  "growth_window_weeks": 24,
  "total_weeks": 51,
  "extractor": "1_count_stopwords"
}
```
- `growth` / `growth_short` / `growth_window_weeks` / `total_weeks` — только в `top_growing*.json`
- `growth` — slopes за весь отображаемый период (`total_weeks`)
- `growth_short` — slopes за последние `growth_window_weeks` недель
- В `top_growing.json` — slopes в ед./нед; в `top_growing_pct.json` — в %/нед

Telegram-бот читает эти файлы для отображения слов с цифрами — без обращения к БД.

`plot_keywords_over_time(pivot, keywords, title, out_path, ylabel, regression_window, regression_window_short)`:
- `regression_window=True` — рисует линию регрессии за **весь период** (стиль `·····`, alpha=0.5)
- `regression_window_short=N` — рисует линию регрессии за **последние N недель** (стиль `- - -`, alpha=0.85)
- Обе линии того же цвета что и кривая ключевого слова, но разным стилем
- При пустых данных — сохраняет заглушку "No data"
- Обрезает историю до `HISTORY_WEEKS`; подпись оси X: `Week  (N нед.)`

`plot_article_counts(counts_by_week, title, out_path)` — столбчатая диаграмма статей по неделям

---

### 7. Модули сервисов (`backend/`)

Монолитный `pipeline.py` разделён на четыре самостоятельных модуля.
`pipeline.py` оставлен как тонкий фасад (реэкспортирует все функции) для обратной совместимости.

**`fetch.py`** — Сервис 1 (`fetch_abstracts`):
1. Разбивает диапазон дат на недели (`_date_ranges_for_period`)
2. Для каждой недели — пагинация через `_fetch_range` (итеративный алгоритм с очередью); при превышении `ARXIV_OFFSET_LIMIT` автоматически дробит по дням
3. Новые статьи сохраняет в `articles` (`upsert_article`)

**`extract.py`** — Сервис 2 (`extract_keywords_batch`):
1. Читает `articles` где `keywords=null` или `keyword_extractor_version < ACTIVE_EXTRACTOR.db_id`
2. Извлекает ключевые слова через `keywords.registry.extract_keywords()` (активный алгоритм)
3. Записывает в `articles.keywords` и `weekly_keyword_counts` (`$inc` upsert)
4. Round-based: фиксирует количество статей на начало раунда, обрабатывает ровно столько (параллельный Сервис 1 не ломает счётчики)

**`aggregate.py`** — Сервис 3, часть 1 (`recompute_aggregates`):
- Принимает `date_from` — фильтрует недели начиная с этой даты
- Проверяет актуальность: пропускает домен если `articles.updated_at ≤ aggregates.computed_at`
- Вычисляет `top_popular` и `top_growing` через `analytics/trends.py`
- Сохраняет в `aggregates` (поля `top_popular`, `top_growing`, `extractor_key`) + суммарный агрегат `_all`

**`plot_service.py`** — Сервис 3, часть 2 (`render_plots`):
- Принимает `date_from` — строит графики только за последний год
- Читает агрегаты из `aggregates` и данные из `weekly_keyword_counts` / `articles`
- Строит 5 графиков на домен + суммарные графики `_all`
- После каждого keyword-графика сохраняет JSON-сайдкар рядом с PNG

---

### 8. Планировщик (`scripts/run_scheduler.py`)

Бесконечный цикл для одного шага pipeline:
- `--step 1|2|3` — шаг: 1=fetch abstracts, 2=extract keywords, 3=aggregates+plots
- `--interval-hours` — интервал между прогонами
- `--from` / `--to` — диапазон дат (по умолчанию: год назад → сегодня, пересчитывается каждый прогон)
- `--run-once` — один прогон и выход
- Graceful shutdown по `SIGINT` / `SIGTERM`
- Логи содержат человекочитаемое название шага:
  ```
  INFO  Планировщик запущен. Шаг 3 (aggregates + plots), интервал=1.0 ч.
  INFO  === Начало прогона: aggregates + plots ===
  INFO  === Прогон завершён успешно ===
  INFO  Следующий прогон через 1.0 ч. (~09:30 UTC). Ctrl+C для остановки.
  ```

**Circuit breaker**: после `ALERT_FAIL_THRESHOLD` (3) последовательных ошибок отправляет Telegram-алерт
(если заданы `TELEGRAM_BOT_TOKEN` и `ALERT_TELEGRAM_CHAT_ID` в `.env`). Сервис не останавливается.

---

### 9. Telegram-бот (`frontend/telegram_bot/bot.py`)

- Библиотека: `python-telegram-bot` v21+
- Команды: `/start`, `/domains`, `/web`, `/status`, `/trends <domain_id>`
- Авто-перезапуск при изменении файлов в `frontend/telegram_bot/`, `config/`, `utils/` (watchfiles)

Отправляет **9 отдельных сообщений** в следующем порядке:
1. Заголовок: название домена + время обновления
2. График: статей по неделям
3. График: топ-популярные (абс.)
4. График: топ-популярные (%)
5. Текст: топ-популярные слова с цифрами
6. График: топ-растущие (абс.)
7. Текст: топ-растущие (абс. slopes в ед./нед)
8. График: топ-растущие (%)
9. Текст: топ-растущие (% slopes в %/нед)

Команда `/domains` показывает inline-кнопки с количеством недель данных в каждом домене
(тот же диапазон дат что и на графиках: последние `HISTORY_WEEKS` завершённых недель).

Команда `/status` показывает CPU / RAM / Disk (топ-3 процессов) и состояние каждого
systemd-сервиса с датой и фрагментом последней строки лога.

Формат текстового сообщения (данные из JSON-сайдкаров, без обращения к БД):
```
📌 Top-растущие (абс.):
🔵● 1. learn  (2 862, 49.1%, ↑+15/нед(51), +22/нед(24))
🟠■ 2. train  (1 194, 71.9%, ↑+8.2/нед(51), +5.1/нед(24))
...

📌 Top-растущие (%/нед):
🔵● 1. learn  (2 862, 49.1%, ↑+0.171%/нед(51), +0.7%/нед(24))
...
```
Два slope: за весь период `(N)` и за последние `GROWTH_WINDOW_WEEKS` недель `(24)`.

---

### 10. Веб-дашборд (`frontend/web/app.py`)

- FastAPI + Jinja2 шаблоны
- Отображает графики PNG из `.outputs/plots/` через HTTP
- Запуск: `./sh/start_6_web.sh`

---

### 11. Утилиты (`utils/`)

- **`utils/__init__.py`** — функции работы с датами: `week_start`, `to_week_datetime`, `iter_weeks_between`
- **`utils/cli.py`** — `parse_date(s)`: парсинг `YYYY-MM-DD` для argparse
- **`utils/logging_setup.py`** — `setup_logging(level, log_file, fmt)`: text/json форматы, RotatingFileHandler
- **`utils/diagnostics.py`** — функции диагностики БД: coverage, top keywords, latest update, search

---

### 12. Тесты (`tests/`)

**200 тестов** в двух категориях:

- **Unit-тесты** (`tests/test_*.py`) — 175 тестов, используют `unittest.mock`
  - Патчи нацелены на фактический модуль (`aggregate.MongoStore`, `fetch.ArxivApiClient` и т.д.), а не на `pipeline.*`
- **Интеграционные тесты** (`tests/integration/test_store_integration.py`) — 25 тестов
  - Используют `mongomock` для реальной MongoDB-семантики без запущенного сервера
  - Покрывают: upsert-идемпотентность, накопление счётчиков, кэширование агрегатов, запросы на экстракцию, операции очистки

Запуск: `./sh/run_tests.sh -v`

---

## Запуск

```bash
# Создать окружение
./sh/setup_conda.sh && conda activate conda_arxive_trends

# MongoDB
./sh/start_1_db.sh                  # systemctl или ~/mongodb/bin/mongod

# Бэкенд (каждый сервис в отдельном процессе с авто-перезапуском)
./sh/start_2_fetch.sh              # скачивание статей — раз в сутки
./sh/start_3_extract.sh            # ключевые слова — раз в час
./sh/start_4_aggregates_plots.sh   # агрегаты + графики — раз в час

# Фронтенд
./sh/start_5_frontend.sh             # Telegram-бот
./sh/start_6_web.sh                  # веб-дашборд (FastAPI)

# Тесты
./sh/run_tests.sh -v                 # 200 тестов
```

---

## Переменные окружения (`.env`)

См. [startup_guide.md](startup_guide.md#переменные-окружения-env).
