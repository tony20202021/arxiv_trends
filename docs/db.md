# MongoDB: коллекции

### `weekly_keyword_counts` — сырые данные

| Поле | Тип | Описание |
|---|---|---|
| `domain` | str | ID домена (`cs_lg`, `cs_cl`, ...) |
| `week_start` | datetime UTC | Понедельник недели |
| `keyword` | str | Ключевое слово |
| `count` | int | Количество упоминаний |

Индексы:
- Уникальный: `(domain, week_start, keyword)`
- Поисковый: `(domain, week_start)`

Запись через `$inc` + upsert — идемпотентна, безопасно перезапускать.

### `aggregates` — предвычисленные топ-списки

| Поле | Тип | Описание |
|---|---|---|
| `domain` | str | ID домена |
| `computed_at` | datetime UTC | Время последнего расчёта |
| `top_popular` | list[str] | Топ-10 слов по последней неделе |
| `top_growing` | list[str] | Топ-10 растущих слов (10 недель) |

Обновляется после каждого прогона pipeline. Используется Telegram-ботом.
