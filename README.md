# arXiv Keyword Trends

Строит **тренды ключевых слов** из абстрактов статей arXiv по доменам (ML, NLP, CV, AGI и др.).

## Архитектура

```
arXiv API → HTML парсинг → извлечение слов → MongoDB → агрегаты → графики
                                                              ↓
                                                       Telegram-бот
```

**Компоненты:**
- **Бэкенд** (`backend/`) — pipeline: скачивает, парсит, считает, строит графики
- **Фронтенд** (`frontend/telegram_bot/`) — Telegram-бот, отдаёт графики по команде
- **Конфиг** (`config/`) — домены и константы

## Быстрый старт

### 1. Создать conda-окружение
```bash
./scripts/setup_conda.sh
conda activate conda_arxive_trends
```

### 2. Настроить окружение
```bash
cp .env.example .env
# Заполнить .env: MONGO_URI, TELEGRAM_BOT_TOKEN, и т.д.
```

### 3. Запустить MongoDB
```bash
./scripts/start_1_db.sh
```

### 4. Один прогон pipeline (скачать данные + построить графики)
```bash
./scripts/start_2_backend.sh --run-once
# или напрямую:
python backend/scripts/run_pipeline.py --out outputs --log-level INFO
```

### 5. Планировщик (повторять каждые 6 часов)
```bash
./scripts/start_2_backend.sh --interval-hours 6
```

### 6. Telegram-бот
```bash
./scripts/start_3_frontend.sh
```

## Команды Telegram-бота

| Команда | Описание |
|---|---|
| `/start` | Приветствие и список команд |
| `/domains` | Список доменов с готовыми графиками |
| `/trends cs-lg` | Отправить графики для домена |

## Тесты
```bash
./scripts/run_tests.sh -v
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
- `MAX_RESULTS_PER_DOMAIN = 2000` — лимит статей на домен

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
│   ├── storage/            # mongo.py (upsert + read + aggregates)
│   ├── pipeline.py         # оркестратор
│   └── utils.py            # date helpers
├── config/
│   ├── constants.py
│   └── domains.json        # 9 доменов
├── frontend/
│   └── telegram_bot/
│       └── bot.py          # /start /domains /trends
├── scripts/                # Скрипты запуска и утилиты
│   ├── run_scheduler.py    # CLI: loop с таймаутом
│   ├── setup_conda.sh
│   ├── setup_systemd.sh
│   ├── run_tests.sh
│   ├── start_1_db.sh
│   ├── start_2_backend.sh
│   └── start_3_frontend.sh
├── tests/                  # 85 unit-тестов
├── outputs/                # графики (gitignore)
├── .env.example
├── requirements.txt
└── pyproject.toml
```
