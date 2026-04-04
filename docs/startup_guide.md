# Руководство по запуску arXiv Trends

## Быстрый старт (первый раз)

```bash
# 1. Создать conda-окружение
./scripts/setup_conda.sh
conda activate conda_arxive_trends

# 2. Настроить переменные окружения
cp .env.example .env
nano .env   # заполнить MONGO_URI, TELEGRAM_BOT_TOKEN и др.

# 3. Запустить MongoDB
./scripts/start_1_db.sh

# 4. Один прогон pipeline (скачать данные + построить графики)
./scripts/start_2_backend.sh --run-once

# 5. Запустить Telegram-бот
./scripts/start_3_frontend.sh
```

---

## Ежедневная эксплуатация

### Запустить всё

```bash
./scripts/start_1_db.sh
./scripts/start_2_backend.sh --interval-hours 6   # планировщик повторяет каждые 6 часов
./scripts/start_3_frontend.sh                      # Telegram-бот (в отдельном терминале)
```

### Запустить с auto-reload бота (при изменении кода)

```bash
./scripts/start_3_frontend_auto_reload.sh
```

### Один прогон pipeline вручную

```bash
# Через скрипт
./scripts/start_2_backend.sh --run-once

# Напрямую через Python (из корня проекта)
PYTHONPATH=backend:. python backend/scripts/run_pipeline.py \
  --out outputs \
  --log-level INFO
```

---

## Скрипты

| Скрипт | Назначение |
|---|---|
| `setup_conda.sh` | Создать conda-окружение `conda_arxive_trends` |
| `start_1_db.sh` | Запустить MongoDB |
| `start_2_backend.sh` | Запустить pipeline-планировщик |
| `start_3_frontend.sh` | Запустить Telegram-бот |
| `start_3_frontend_auto_reload.sh` | Telegram-бот с авто-перезапуском при изменении файлов |
| `run_tests.sh` | Запустить тесты |

### Аргументы start_2_backend.sh

```
--interval-hours N   Интервал между прогонами (по умолчанию: 6)
--run-once           Один прогон и выход
--out DIR            Директория для графиков (по умолчанию: outputs)
--log-level LEVEL    DEBUG / INFO / WARNING / ERROR (по умолчанию: INFO)
```

---

## Тесты

```bash
# Все тесты
./scripts/run_tests.sh -v

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
| `OUTPUTS_DIR` | нет | `outputs` |
| `USE_LLM_EXTRACTOR` | нет | `0` или `1` |
| `OPENAI_LLM_URL` | если LLM | `https://api.openai.com/v1` |
| `OPENAI_LLM_API_KEY` | если LLM | `sk-...` |
| `OPENAI_LLM_MODEL` | если LLM | `gpt-4o-mini` |
