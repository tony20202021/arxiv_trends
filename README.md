# arXiv Keyword Trends

Строит **тренды ключевых слов** из абстрактов статей arXiv по доменам (ML, NLP, CV, AGI и др.).

## Архитектура

```
arXiv API → articles → keywords → weekly_keyword_counts → aggregates → графики
                                                                ↓
                                                         Telegram-бот
```

**Компоненты:**
- **Бэкенд** (`backend/`) — 4 независимых сервиса: fetch, extract, aggregates, plots
- **Фронтенд** (`frontend/telegram_bot/`) — Telegram-бот, отдаёт графики по команде
- **Конфиг** (`config/`) — домены и константы

## Быстрый старт

### 1. Создать conda-окружение
```bash
./sh/setup_conda.sh
conda activate conda_arxive_trends
```

### 2. Настроить окружение
```bash
cp .env.example .env
# Заполнить .env: MONGO_URI, TELEGRAM_BOT_TOKEN, и т.д.
```

### 3. Запустить MongoDB
```bash
./sh/start_1_db.sh
```

### 4. Заполнить данные (первый раз)
```bash
python scripts/1_fetch_abstracts.py --from 2025-04-01 --to 2026-04-05
python scripts/2_extract_keywords.py --from 2025-04-01 --to 2026-04-05
python scripts/3_recompute_aggregates.py
python scripts/4_render_plots.py
```

### 5. Запустить планировщики (в отдельных терминалах)
```bash
./sh/start_2_1_fetch.sh        # скачивание — раз в сутки
./sh/start_2_2_extract.sh      # ключевые слова — раз в час
./sh/start_2_3_aggregates_plots.sh   # агрегаты + графики — раз в час
```

### 6. Telegram-бот
```bash
./sh/start_3_frontend.sh
```

## Команды Telegram-бота

| Команда | Описание |
|---|---|
| `/start` | Приветствие и список команд |
| `/domains` | Список доменов с готовыми графиками |
| `/trends cs-lg` | Отправить графики для домена |

## Тесты
```bash
./sh/run_tests.sh -v
# или:
python -m pytest tests/ -v
```

## Конфигурация

### Домены (`config/domains.json`)
9 доменов из arXiv: cs.LG, stat.ML, cs.AI, cs.CL (NLP), cs.CV, cs.NE, cs.RO, eess.SP, quant-ph.

### Константы (`config/constants.py`)
- `HISTORY_WEEKS = 52` — глубина истории (1 год)
- `TOP_N = 10` — количество ключевых слов на графике
- `GROWTH_WINDOW_WEEKS = 10` — окно для расчёта роста

### LLM-экстрактор (опционально)
Добавьте в `.env`:
```
USE_LLM_EXTRACTOR=1
OPENAI_LLM_URL=https://...
OPENAI_LLM_API_KEY=...
OPENAI_LLM_MODEL=gpt-4o-mini
```
При ошибке LLM автоматически переключается на regex-fallback.

## Структура проекта

```
arxiv_trends/
├── backend/
│   ├── arxiv/              # API + HTML fetcher (с retry)
│   ├── analytics/          # trends.py: pivot, top_popular, top_growing
│   ├── keywords/           # extractor.py + llm_extractor.py
│   ├── llm/                # client.py: OpenAI-совместимый LLM-клиент
│   ├── plots/              # plotter.py
│   ├── storage/            # mongo.py
│   ├── pipeline.py         # сервисные функции
│   └── utils.py            # date helpers
├── config/
│   ├── constants.py
│   └── domains.json        # 9 доменов
├── frontend/
│   └── telegram_bot/
│       └── bot.py          # /start /domains /trends
├── scripts/
│   ├── 0_check_db.py       # диагностика БД
│   ├── 1_fetch_abstracts.py
│   ├── 2_extract_keywords.py
│   ├── 3_recompute_aggregates.py
│   ├── 4_render_plots.py
│   └── run_scheduler.py    # планировщик (вызывается sh-скриптами)
├── sh/
│   ├── start_1_db.sh
│   ├── start_2_1_fetch.sh
│   ├── start_2_2_extract.sh
│   ├── start_2_3_aggregates_plots.sh
│   └── start_3_frontend.sh
├── tests/
├── .env.example
├── requirements.txt
└── pyproject.toml
```
