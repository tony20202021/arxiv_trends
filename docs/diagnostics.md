# Диагностика и утилиты

Все команды запускаются из корня проекта через conda-окружение:

```bash
cd arxiv/arxiv_trends
conda run -n conda_arxive_trends python scripts/0_check_db.py <команда> [параметры]
```

---

## Команды `0_check_db.py`

### `coverage` — покрытие БД по доменам

Показывает диапазон недель, количество статей и количество keyword-записей по каждому домену.

```bash
python scripts/0_check_db.py coverage
```

Пример вывода:

```
=== articles (абстракты) =============================================
Домен          Первая неделя Последняя неделя  Недель  Статей  С ключ.словами
----------------------------------------------------------------------
  cs_ai          2025-04-07    2026-03-30          52  58,654          58,622
  cs_lg          2025-04-07    2026-03-30          52  58,843          58,810
  ...

=== weekly_keyword_counts (подсчёты по неделям) ======================
Домен          Первая неделя Последняя неделя  Недель   Вхождений
----------------------------------------------------------------------
  cs_ai          2025-04-07    2026-03-30          52     312,847
  cs_lg          2025-04-07    2026-03-30          52     298,103
  ...
```

---

### `top` — топ ключевых слов

Топ-N наиболее частых слов — суммарно по всем доменам и отдельно по каждому.
Стоп-слова и короткие слова отфильтрованы. Данные нормализованы (лемматизированы).

```bash
# Топ-10 (по умолчанию)
python scripts/0_check_db.py top

# Топ-30
python scripts/0_check_db.py top --top-n 30
```

Пример вывода:

```
=== Топ-10 слов по всем разделам ===
   1. learn                               7,364
   2. framework                           6,278
   3. train                               5,225
   ...

--- cs_ro ---
   1. robot                               2,170
   2. learn                               1,556
   ...
```

---

### `latest` — последняя запись в каждой коллекции

Быстрая проверка: что последним попало в БД по каждой коллекции.

```bash
python scripts/0_check_db.py latest
```

Пример вывода:

```
=== articles (последняя запись) =============================
  arxiv_id  : 2503.19876
  domain    : cs_ai
  title     : Efficient Attention via...
  published : 2026-03-30
  week_start: 2026-03-30
  fetched_at: 2026-04-06 09:06:12

=== weekly_keyword_counts (последняя неделя) ================
  domain    : cs_lg
  week_start: 2026-03-30
  keyword   : transformer  (count=412)

=== aggregates (последнее вычисление) =======================
  domain      : cs_ai
  computed_at : 2026-04-06 08:54:03
  top_popular : ['transformer', 'attention', ...]
  top_growing : ['diffusion', 'agent', ...]
```

---

### `search` — поиск статей по ключевому слову

Полнотекстовый поиск по полям `abstract` и `title`. Использует MongoDB text index — быстро даже на больших объёмах.

```bash
# Базовый поиск
python scripts/0_check_db.py search --keyword "diffusion model"

# Поиск точной фразы (в кавычках)
python scripts/0_check_db.py search --keyword '"neural network"'

# Топ-20 результатов
python scripts/0_check_db.py search --keyword "reinforcement learning" --limit 20
```

Результаты отсортированы по релевантности (text score). Выводится контекст вокруг найденного слова в абстракте.

Пример вывода:

```
Поиск по ключевому слову: «diffusion model»  (топ 10)

  1. [cs_cv] 2503.12345  (2026-03-28)
     Fast Diffusion Models for Image Synthesis
     «…we propose a novel diffusion model architecture that…»

  2. [cs_lg] 2503.67890  (2026-03-27)
     Score-Based Generative Modeling
     «…diffusion model trained on latent representations…»
```

---

## Конфигурация подключения

Все команды читают параметры из `.env` (корень проекта):

```
MONGO_URI=mongodb://127.0.0.1:27017
MONGO_DB=arxiv_trends
```

Переопределить для конкретного вызова:

```bash
python scripts/0_check_db.py --uri mongodb://other-host:27017 --db other_db coverage
```
