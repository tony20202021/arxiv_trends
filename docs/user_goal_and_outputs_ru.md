# Цель и результаты пайплайна (взгляд пользователя)

## Зачем нужен этот пайплайн

Отслеживать тренды по ключевым словам в научных статьях arXiv по разным доменам (ML, NLP, CV, AGI и др.).

- Статьи берутся с arXiv через официальный API
- Ключевые слова извлекаются **только из Abstract** (`/abs/<id>`)
- Данные агрегируются по неделям за последний год
- Результаты доступны через **Telegram-бот** (команда `/trends <domain>`)

---

## Домены (11 штук)

| ID | Название | arXiv категория |
|---|---|---|
| `cs_lg` | Machine Learning | cs.LG |
| `stat_ml` | Statistics ML | stat.ML |
| `cs_ai` | Artificial Intelligence | cs.AI |
| `cs_cl` | NLP / Computation and Language | cs.CL |
| `cs_cv` | Computer Vision | cs.CV |
| `cs_ne` | Neural and Evolutionary Computing | cs.NE |
| `cs_ro` | Robotics | cs.RO |
| `eess_sp` | Signal Processing | eess.SP |
| `quant_ph` | Quantum ML | quant-ph |
| `cs_ma` | Multiagent Systems | cs.MA |
| `cs_ir` | Information Retrieval | cs.IR |

Список доменов хранится в `config/domains.json` и легко расширяется.

---

## Что пользователь получает на выходе

По каждому домену строятся **5 графиков** (история 1 год от текущей даты назад):

### 1) Статей по неделям
- Столбчатая диаграмма: сколько статей выходило в каждую неделю

### 2–3) Top-5 самых популярных слов сейчас
- Выбираются 5 слов с наибольшим количеством упоминаний на **последней неделе**
- Два варианта: абсолютные счётчики и % от числа статей недели

### 4–5) Top-5 самых быстро-растущих за последние 10 недель
- Выбираются слова с максимальным наклоном линейной регрессии
- Два варианта: абсолютные счётчики и % от числа статей недели

### Где хранятся графики

```
.outputs/plots/<domain_id>/
    articles_per_week.png
    top_popular.png       top_popular.json
    top_popular_pct.png   top_popular_pct.json
    top_growing.png       top_growing.json
    top_growing_pct.png   top_growing_pct.json
```

JSON-файлы содержат ключевые слова с абсолютными значениями и процентами за последнюю неделю.

---

## Как получить результаты

### Через Telegram-бот

```
/domains           — список доменов с готовыми графиками
/trends cs-lg      — получить графики и ключевые слова для домена cs_lg
```

Бот присылает 7 сообщений: 5 графиков + 2 текстовых с топ-словами в формате:
```
📌 Top-популярные:
1. learn  (1 234, 3.2%)
2. train  (987, 2.5%)
...
```

### Через файловую систему

Графики сохраняются в `.outputs/plots/<domain>/` после каждого прогона pipeline.

---

## Как запустить

```bash
# Бэкенд (каждый сервис в отдельном процессе)
./sh/start_2_fetch.sh              # скачивание статей — раз в сутки
./sh/start_3_extract.sh            # ключевые слова — раз в час
./sh/start_4_aggregates_plots.sh         # агрегаты + графики — раз в час

# Telegram-бот
./sh/start_5_frontend.sh
```
