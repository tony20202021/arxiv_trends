# Техническое описание пайплайна

## Архитектура

Пайплайн разделён на два независимых сервиса:

```
═══════════════════════ Сервис 1: 1_fetch_abstracts.py ═══════════════════════

arXiv API (Atom)
      ↓
  api_client.py       — постраничная выгрузка статей (батчами по неделям/дням)
                        абстракт берётся из поля summary прямо из API-ответа
      ↓
  MongoDB             — коллекция articles (arxiv_id, domain, abstract, ...)

══════════════════════ Сервис 2: 2_extract_keywords.py ═══════════════════════

  MongoDB             — читает articles (где keywords = null или версия устарела)
      ↓
  extractor.py        — извлечение ключевых слов (regex или LLM)
      ↓
  MongoDB             — articles.keywords + weekly_keyword_counts ($inc upsert)

══════════════════════════════ Аналитика и графики ═══════════════════════════

  MongoDB             — weekly_keyword_counts
      ↓
  trends.py           — расчёт top_popular / top_growing
      ↓
  MongoDB             — aggregates (предвычисленные топ-списки)
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
- `TOP_N = 5` — количество ключевых слов на графике
- `GROWTH_WINDOW_WEEKS = 10` — окно для расчёта тренда роста
- `KEYWORD_EXTRACTOR_VERSION = 1` — версия алгоритма экстрактора (увеличить при изменении логики)
- `ARXIV_PAGE_SIZE = 200` — размер страницы при запросе к API
- `ARXIV_MAX_OFFSET = 30000` — максимальный `start` по документации arXiv
- `ARXIV_OFFSET_LIMIT = 9800` — фактический лимит (arXiv возвращает 500 при start≥10000)
- `REQUEST_SLEEP_SEC = 3.0` — задержка между запросами (рекомендация arXiv)
- `TOKEN_PATTERN` — regex для токенизации
- `STOPWORDS_EN` — стоп-слова (исключаются из ключевых слов)
- `MIN_TOKEN_LEN = 3` — минимальная длина токена

---

### 2. Получение статей (`arxiv/api_client.py`)

- Запрос к arXiv Atom API: `feedparser` + `requests`
- Абстракт берётся из поля `summary` прямо из Atom-ответа — отдельные HTTP-запросы за страницами абстрактов не нужны
- Фильтр по диапазону дат (`submittedDate`)
- **Пагинация батчами по неделям**: каждая неделя запрашивается отдельно, чтобы не превышать лимит `start=10000`; если неделя превышает лимит — автоматически дробится по дням
- **Retry с экспоненциальным backoff**: 5 попыток, пауза ×2 при каждой ошибке

---

### 3. Извлечение ключевых слов (`keywords/`)

Два режима, переключаются через `.env`:

**Режим regex** (по умолчанию, `USE_LLM_EXTRACTOR=0`):
- `extractor.py`: токенизация по `TOKEN_PATTERN`, фильтрация стоп-слов и коротких токенов
- Возвращает `Dict[keyword, count]`

**Режим LLM** (`USE_LLM_EXTRACTOR=1`):
- `llm_extractor.py`: вызов OpenAI-совместимого API через `smkt_llm.py`
- Структурированный вывод через Pydantic (`KeywordList`)
- При ошибке LLM — автоматический fallback на regex

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
| `domain` | str | ID домена |
| `computed_at` | datetime UTC | Время расчёта |
| `top_popular` | list[str] | Топ-10 популярных слов |
| `top_growing` | list[str] | Топ-10 растущих слов |

Обновляется после каждого прогона pipeline. Используется Telegram-ботом.

---

### 5. Аналитика (`analytics/trends.py`)

**`to_frame(rows)`** — список документов MongoDB → `pandas.DataFrame`

**`pivot_week_keyword(df)`** — pivot-таблица: строки = недели, столбцы = ключевые слова

**`top_popular_now(pivot, top_n)`** — топ-N слов по последней неделе

**`top_growing_last_window(pivot, window_weeks, top_n)`**:
- берёт последние `window_weeks` недель
- для каждого слова считает наклон (`numpy.polyfit`, degree=1)
- возвращает топ-N с максимальным наклоном

---

### 6. Графики (`plots/plotter.py`)

- `matplotlib` — линейные и столбчатые графики по неделям
- `plot_keywords_over_time(pivot, keywords, title, out_path, regression_window=N)`:
  - При `regression_window` — рисует линии линейной регрессии за последние N недель (тот же цвет, `alpha=0.4`)
  - При пустых данных — сохраняет заглушку "No data"
  - Обрезает историю до `HISTORY_WEEKS`
- `plot_article_counts(counts_by_week, title, out_path)` — количество статей по неделям
- `build_keyword_styles(keywords)` — единый словарь цвет+маркер для обоих keyword-графиков

Графики сохраняются в `.outputs/plots/<domain>/`: `top_popular.png`, `top_growing.png`, `articles_per_week.png`

---

### 7. Сервисные функции (`pipeline.py`)

`fetch_abstracts()` — Сервис 1:
1. Разбивает диапазон дат на недели (`_date_ranges_for_period`)
2. Для каждой недели — пагинация через `_fetch_range`; при превышении `ARXIV_OFFSET_LIMIT` автоматически дробит по дням
3. Абстракт берётся из поля `summary` Atom-ответа — отдельных HTTP-запросов нет
4. Новые статьи сохраняет в `articles` (`upsert_article`)

`extract_keywords_batch()` — Сервис 2:
1. Читает `articles` где `keywords=null` или версия экстрактора устарела
2. Извлекает ключевые слова через `extractor.py`
3. Записывает в `articles.keywords` и `weekly_keyword_counts` (`$inc` upsert)
4. Round-based: фиксирует количество статей на начало раунда, обрабатывает ровно столько (параллельный Сервис 1 не ломает счётчики)

`recompute_aggregates()` — Сервис 3:
- Проверяет актуальность: пропускает домен если `articles.updated_at ≤ aggregates.computed_at`
- Вычисляет `top_popular` и `top_growing` через `analytics/trends.py`
- Сохраняет в `aggregates` + суммарный агрегат `_all` по всем доменам

`render_plots()` — Сервис 4:
- Читает агрегаты из `aggregates` и данные из `weekly_keyword_counts` / `articles`
- Строит 3 графика на домен + суммарные графики `_all`

---

### 8. Планировщик (`scripts/run_scheduler.py`)

Бесконечный цикл для одного шага pipeline:
- `--step 1|2|3` — шаг: 1=fetch, 2=extract, 3=aggregates+plots
- `--interval-hours` — интервал между прогонами
- `--from` / `--to` — диапазон дат (по умолчанию: год назад → сегодня, пересчитывается каждый прогон)
- `--run-once` — один прогон и выход
- Graceful shutdown по `SIGINT` / `SIGTERM`

---

### 9. Telegram-бот (`frontend/telegram_bot/bot.py`)

- Библиотека: `python-telegram-bot` v21+
- Команды: `/start`, `/domains`; домен выбирается через inline-кнопки
- Отправляет 3 графика отдельными сообщениями: `articles_per_week`, `top_popular`, `top_growing`
- Список доменов и дату последнего обновления берёт из коллекции `aggregates`
- При недоступной БД — fallback на файловую систему (`.outputs/plots/`)

---

## Запуск

```bash
# Создать окружение
./sh/setup_conda.sh && conda activate conda_arxive_trends

# MongoDB
./sh/start_1_db.sh                  # systemctl или ~/mongodb/bin/mongod

# Бэкенд (каждый сервис в отдельном процессе)
./sh/start_2_1_fetch.sh              # скачивание статей — раз в сутки
./sh/start_2_2_extract.sh            # ключевые слова — раз в час
./sh/start_2_3_aggregates_plots.sh         # агрегаты + графики — раз в час

# Фронтенд (Telegram-бот)
./sh/start_3_frontend.sh

# Тесты
./sh/run_tests.sh -v        # 85 тестов
```

---

## Переменные окружения (`.env`)

См. [startup_guide.md](startup_guide.md#переменные-окружения-env).
