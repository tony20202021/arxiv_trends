# Структура проекта

```
arxiv_trends/
│
├── backend/                              # Бэкенд: pipeline, планировщик
│   ├── arxiv/
│   │   ├── api_client.py                # arXiv Atom API + retry
│   │   └── html_fetcher.py              # Скачивание /abs/<id> + retry (не используется в Сервисе 1)
│   ├── analytics/
│   │   └── trends.py                    # to_frame, pivot, top_popular, top_growing
│   ├── keywords/
│   │   ├── registry.py                  # Реестр алгоритмов (6 версий); ACTIVE_EXTRACTOR_KEY
│   │   ├── extractor.py                 # Алгоритм v1: regex + лемматизация + стоп-слова
│   │   ├── llm_extractor.py             # Алгоритм v2: LLM (USE_LLM_EXTRACTOR=1)
│   │   └── normalizer.py                # Лемматизация через spaCy
│   ├── llm/
│   │   └── client.py                    # OpenAI-совместимый LLM-клиент
│   ├── plots/
│   │   └── plotter.py                   # Построение PNG-графиков (matplotlib)
│   ├── storage/
│   │   └── mongo.py                     # MongoStore: articles, keyword_counts, aggregates
│   └── pipeline.py                      # fetch_abstracts / extract_keywords_batch / recompute_aggregates / render_plots
│
├── config/
│   ├── constants.py                     # Числовые параметры пайплайна (без версии экстрактора)
│   └── domains.json                     # Список доменов (9 шт.)
│
├── utils/
│   ├── __init__.py                      # Утилиты работы с датами (week_start, to_week_datetime, ...)
│   └── diagnostics.py                   # Функции диагностики БД (coverage, top, latest, search)
│
├── frontend/
│   ├── telegram_bot/
│   │   └── bot.py                       # Telegram-бот: /start /domains /trends
│   └── plots/
│       └── plotter.py                   # (устаревший оригинал, не используется)
│
├── tests/                               # Unit-тесты (142 шт.)
│   ├── test_api_client.py
│   ├── test_extractor.py
│   ├── test_html_fetcher.py
│   ├── test_llm_extractor.py
│   ├── test_mongo.py
│   ├── test_pipeline.py
│   ├── test_plotter.py
│   ├── test_trends.py
│   └── test_utils.py
│
├── docs/
│   ├── startup_guide.md                 # Инструкция по запуску
│   ├── project_structure.md             # Этот файл
│   ├── db.md                            # MongoDB: схемы коллекций
│   ├── systemctl_guide.md               # Автозапуск через systemd
│   ├── technical_pipeline_ru.md         # Техническое описание пайплайна
│   └── user_goal_and_outputs_ru.md      # Описание для пользователя
│
├── outputs/                             # Графики (создаётся автоматически, в .gitignore)
│   └── plots/
│       └── <domain_id>/
│           ├── top_popular.png
│           └── top_growing.png
│
├── scripts/                             # Python-утилиты и CLI
│   ├── 0_check_db.py                    # Диагностика БД: coverage / top / latest / search
│   └── run_scheduler.py                 # Планировщик: --step 1|2|3, бесконечный цикл с watchfiles
│
├── sh/                                  # Bash-скрипты запуска
│   ├── setup_conda.sh                   # Создание conda-окружения
│   ├── setup_systemd.sh                 # Генерация systemd-сервисов (arxiv-backend-1/2/3)
│   ├── run_tests.sh                     # Запуск тестов
│   ├── start_1_db.sh                    # Запуск MongoDB
│   ├── start_2_1_fetch.sh               # Шаг 1: fetch  — следит за arxiv/, storage/, pipeline.py
│   ├── start_2_2_extract.sh             # Шаг 2: extract — следит за keywords/, llm/, storage/, pipeline.py
│   ├── start_2_3_aggregates_plots.sh    # Шаг 3: aggregates+plots — следит за analytics/, plots/, storage/, pipeline.py
│   └── start_3_frontend.sh              # Telegram-бот с авто-перезапуском (watchfiles)
│
├── .env.example                         # Шаблон переменных окружения
├── .gitignore
├── pyproject.toml                       # Настройки pytest
├── requirements.txt                     # Все зависимости
└── README.md
```

