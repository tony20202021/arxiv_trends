# Техническое описание пайплайна

## Архитектура

Пайплайн разделён на два независимых сервиса:

```
══════════════════════ Шаг 1: run_scheduler.py --step 1 ═══════════════════════

arXiv API (Atom)
      ↓
  api_client.py       — постраничная выгрузка статей (батчами по неделям/дням)
                        абстракт берётся из поля summary прямо из API-ответа
      ↓
  MongoDB             — коллекция articles (arxiv_id, domain, abstract, ...)

══════════════════════ Шаг 2: run_scheduler.py --step 2 ═══════════════════════

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
- `ARXIV_PAGE_SIZE = 200` — размер страницы при запросе к API
- `ARXIV_MAX_OFFSET = 30000` — максимальный `start` по документации arXiv
- `ARXIV_OFFSET_LIMIT = 9800` — фактический лимит (arXiv возвращает 500 при start≥10000)
- `REQUEST_SLEEP_SEC = 3.0` — задержка между запросами (рекомендация arXiv)
- `TOKEN_PATTERN` — regex для токенизации
- `STOPWORDS_EN` — стоп-слова (исключаются из ключевых слов)
- `MIN_TOKEN_LEN = 3` — минимальная длина токена

> Версия экстрактора вынесена в `backend/keywords/registry.py` (см. раздел 3).

---

### 2. Получение статей (`arxiv/api_client.py`)

- Запрос к arXiv Atom API: `feedparser` + `requests`
- Абстракт берётся из поля `summary` прямо из Atom-ответа — отдельные HTTP-запросы за страницами абстрактов не нужны
- Фильтр по диапазону дат (`submittedDate`)
- **Пагинация батчами по неделям**: каждая неделя запрашивается отдельно, чтобы не превышать лимит `start=10000`; если неделя превышает лимит — автоматически дробится по дням
- **Retry с экспоненциальным backoff**: 5 попыток, пауза ×2 при каждой ошибке

---

### 3. Извлечение ключевых слов (`keywords/`)

**`registry.py`** — центральный реестр алгоритмов:

| Ключ | DB ID | Алгоритм | Статус |
|---|---|---|---|
| `1_count_stopwords` | 1 | Regex + лемматизация + стоп-слова | **активный** |
| `2_llm` | 2 | LLM (OpenAI-совместимый, `USE_LLM_EXTRACTOR=1`) | готов |
| `3_tfidf_sklearn` | 3 | TF-IDF (scikit-learn) | заготовка |
| `4_tfidf_gensim` | 4 | TF-IDF (gensim) | заготовка |
| `5_keybert` | 5 | KeyBERT (sentence-transformers) | заготовка |
| `6_yake` | 6 | YAKE (статистический) | заготовка |

**Смена алгоритма** — одна строка в `registry.py`:
```python
ACTIVE_EXTRACTOR_KEY = "1_count_stopwords"  # изменить здесь
```
При смене DB ID возрастает → Сервис 2 автоматически перепроцессирует все статьи.

В БД хранится целое число (`keyword_extractor_version`) для скорости индексирования.
В `aggregates` сохраняется строковый ключ (`extractor_key`) — отображается в заголовках графиков.

**`extractor.py`** — реализация алгоритма v1:
- Токенизация по `TOKEN_PATTERN`, фильтрация стоп-слов и коротких токенов
- Лемматизация через spaCy (`en_core_web_sm`)
- Возвращает `Dict[keyword, count]`

**`llm_extractor.py`** — реализация алгоритма v2:
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
3. После каждой недели выводит в лог: прошедшее время и ETA до завершения всех недель
4. Абстракт берётся из поля `summary` Atom-ответа — отдельных HTTP-запросов нет
5. Новые статьи сохраняет в `articles` (`upsert_article`)

`extract_keywords_batch()` — Сервис 2:
1. Читает `articles` где `keywords=null` или `keyword_extractor_version < ACTIVE_EXTRACTOR.db_id`
2. Извлекает ключевые слова через `keywords.registry.extract_keywords()` (активный алгоритм)
3. Записывает в `articles.keywords` и `weekly_keyword_counts` (`$inc` upsert)
4. Round-based: фиксирует количество статей на начало раунда, обрабатывает ровно столько (параллельный Сервис 1 не ломает счётчики)

`recompute_aggregates()` — Сервис 3:
- Принимает `date_from` — фильтрует недели начиная с этой даты (планировщик передаёт год назад от текущей даты)
- Проверяет актуальность: пропускает домен если `articles.updated_at ≤ aggregates.computed_at`
- Вычисляет `top_popular` и `top_growing` через `analytics/trends.py`
- Сохраняет в `aggregates` (поля `top_popular`, `top_growing`, `extractor_key`) + суммарный агрегат `_all`

`render_plots()` — Сервис 4:
- Принимает `date_from` — строит графики только за последний год
- Читает агрегаты из `aggregates` и данные из `weekly_keyword_counts` / `articles`
- Строит 3 графика на домен + суммарные графики `_all`
- В заголовках `top_popular.png` и `top_growing.png` отображается `extractor_key` из агрегатов

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
./sh/run_tests.sh -v        # 142 теста
```

---

## Переменные окружения (`.env`)

См. [startup_guide.md](startup_guide.md#переменные-окружения-env).
