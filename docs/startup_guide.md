# Руководство по запуску arXiv Trends

## Быстрый старт (первый раз)

```bash
# 1. Создать conda-окружение
./sh/setup_conda.sh
conda activate conda_arxive_trends

# 2. Настроить переменные окружения
cp .env.example .env
nano .env   # заполнить MONGO_URI, TELEGRAM_BOT_TOKEN и др.

# 3. Запустить MongoDB
./sh/start_1_db.sh

# 4. Заполнить данные (один прогон каждого шага)
python scripts/run_scheduler.py --step 1 --from 2025-04-01 --to 2026-04-05 --run-once
python scripts/run_scheduler.py --step 2 --from 2025-04-01 --to 2026-04-05 --run-once
python scripts/run_scheduler.py --step 3 --run-once

# 5. Запустить Telegram-бот
./sh/start_3_frontend.sh
```

---

## Ежедневная эксплуатация

### Запустить всё (в отдельных терминалах)

```bash
./sh/start_1_db.sh
./sh/start_2_1_fetch.sh        # скачивание статей — раз в сутки
./sh/start_2_2_extract.sh      # ключевые слова — раз в час
./sh/start_2_3_aggregates_plots.sh   # агрегаты + графики — раз в час
./sh/start_3_frontend.sh   # Telegram-бот
```

Каждый скрипт бэкенда отслеживает только свои каталоги через watchfiles:
- `start_2_1_fetch.sh` — `backend/arxiv`, `backend/storage`, `backend/pipeline.py`
- `start_2_2_extract.sh` — `backend/keywords`, `backend/llm`, `backend/storage`, `backend/pipeline.py`
- `start_2_3_aggregates_plots.sh` — `backend/analytics`, `backend/plots`, `backend/storage`, `backend/pipeline.py`

---

## Скрипты

| Скрипт | Назначение |
|---|---|
| `setup_conda.sh` | Создать conda-окружение `conda_arxive_trends` |
| `start_1_db.sh` | Запустить MongoDB |
| `start_2_1_fetch.sh` | Бэкенд 1: скачивание статей из arXiv (раз в сутки) |
| `start_2_2_extract.sh` | Бэкенд 2: извлечение ключевых слов (раз в час) |
| `start_2_3_aggregates_plots.sh` | Бэкенд 3+4: агрегаты и графики (раз в час) |
| `start_3_frontend.sh` | Telegram-бот с авто-перезапуском |
| `run_tests.sh` | Запустить тесты |

### Аргументы run_scheduler.py (вызывается через sh-скрипты)

```
--step 1|2|3        Шаг pipeline
--interval-hours N   Интервал между прогонами (по умолчанию зависит от скрипта)
--from YYYY-MM-DD    Начало диапазона дат (по умолчанию: год назад)
--to YYYY-MM-DD      Конец диапазона дат (по умолчанию: сегодня)
--run-once           Один прогон и выход
--out DIR            Директория для графиков (по умолчанию: .outputs)
--log-level LEVEL    DEBUG / INFO / WARNING / ERROR (по умолчанию: INFO)
```

---

## Тесты

```bash
# Все тесты
./sh/run_tests.sh -v

# Конкретный модуль
python -m pytest tests/test_api_client.py -v

# С отчётом покрытия
python -m pytest tests/ --cov=backend/src --cov-report=term-missing
```

---

## Автозапуск через systemd

Для постоянной работы на сервере — см. [systemctl_guide.md](systemctl_guide.md).

---

## Переменные окружения (.env)

| Переменная | Обязательна | Пример |
|---|---|---|
| `MONGO_URI` | да | `mongodb://localhost:27017` |
| `MONGO_DB` | да | `arxiv_trends` |
| `TELEGRAM_BOT_TOKEN` | да (бот) | `123456:ABC-...` |
| `ARXIV_API_URL` | нет | `https://export.arxiv.org/api/query` |
| `HTTP_USER_AGENT` | нет | `arxiv-trends-bot/0.1` |
| `OUTPUTS_DIR` | нет | `.outputs` |
| `USE_LLM_EXTRACTOR` | нет | `0` или `1` |
| `OPENAI_LLM_URL` | если LLM | `https://api.openai.com/v1` |
| `OPENAI_LLM_API_KEY` | если LLM | `sk-...` |
| `OPENAI_LLM_MODEL` | если LLM | `gpt-4o-mini` |
