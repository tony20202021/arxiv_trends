# MongoDB: коллекции

### `articles` — статьи с абстрактами

| Поле | Тип | Описание |
|---|---|---|
| `arxiv_id` | str | ID статьи на arXiv |
| `domain` | str | ID домена (`cs_lg`, `cs_cl`, ...) |
| `week_start` | datetime UTC | Понедельник недели публикации |
| `title` | str | Заголовок статьи |
| `published` | str | Дата публикации (ISO строка) |
| `abstract` | str | Текст абстракта |
| `fetched_at` | datetime UTC | Время загрузки |
| `keywords` | dict \| null | Извлечённые ключевые слова `{word: count}` |
| `keyword_extractor_version` | int \| null | Версия алгоритма экстрактора |
| `updated_at` | datetime UTC \| null | Время последнего обновления keywords Сервисом 2 |

Индексы:
- Уникальный: `(arxiv_id, domain)`
- `(domain, week_start)` — основной поиск по домену и диапазону дат
- `(domain, week_start, keyword_extractor_version)` — запросы экстрактора
- `(domain, updated_at)` — проверка свежести агрегатов
- `fetched_at DESC` — поиск последней загруженной записи
- `published DESC` — сортировка при полнотекстовом поиске
- Text index на `(abstract, title)` — полнотекстовый поиск (`0_check_db.py search`)

Заполняется Сервисом 1 (`run_scheduler.py --step 1`). Keywords и `updated_at` заполняются Сервисом 2 (`--step 2`).

---

### `weekly_keyword_counts` — агрегированные подсчёты

| Поле | Тип | Описание |
|---|---|---|
| `domain` | str | ID домена (`cs_lg`, `cs_cl`, ...) |
| `week_start` | datetime UTC | Понедельник недели |
| `keyword` | str | Ключевое слово |
| `count` | int | Количество упоминаний |

Индексы:
- Уникальный: `(domain, week_start, keyword)`
- `(domain, week_start)` — основной поиск по домену и диапазону дат
- `(domain, keyword, week_start)` — история конкретного слова (`get_keyword_history`)
- `week_start` — запросы по всем доменам без фильтра по домену

Запись через `$inc` + upsert — идемпотентна, безопасно перезапускать. Заполняется Сервисом 2.

---

### `aggregates` — предвычисленные топ-списки

| Поле | Тип | Описание |
|---|---|---|
| `domain` | str | ID домена (или `_all` — суммарно по всем доменам) |
| `computed_at` | datetime UTC | Время последнего расчёта |
| `top_popular` | list[str] | Топ-N популярных слов по последней неделе |
| `top_growing` | list[str] | Топ-N растущих слов |
| `extractor_key` | str | Ключ алгоритма экстрактора (`1_count_stopwords`, ...) |

Обновляется Сервисом 3. Используется Telegram-ботом и `render_plots`. `extractor_key` отображается в заголовках графиков.

---

### Логика обновлений по полям дат

| Поле | Коллекция | Кто пишет | Назначение |
|---|---|---|---|
| `articles.fetched_at` | articles | Сервис 1 | Когда статья была скачана |
| `articles.updated_at` | articles | Сервис 2 | Когда keywords последний раз пересчитывались |
| `aggregates.computed_at` | aggregates | Сервис 3 | Когда агрегаты последний раз пересчитывались |

**Проверка актуальности агрегатов** (Сервис 3):
- Если `max(articles.updated_at)` для домена ≤ `aggregates.computed_at` — агрегаты актуальны, пересчёт пропускается.
- `--force` отключает проверку, пересчитывает всегда.

**Обнаружение статей для экстракции** (Сервис 2):
- Статьи где `keywords = null` — ещё не обработаны.
- Статьи где `keyword_extractor_version < ACTIVE_EXTRACTOR.db_id` — обработаны старой версией, нужен пересчёт.
- Активный алгоритм задаётся в `backend/keywords/registry.py` (`ACTIVE_EXTRACTOR_KEY`).
