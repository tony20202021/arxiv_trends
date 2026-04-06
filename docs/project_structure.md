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
│   │   ├── extractor.py                 # Unified extractor: LLM → regex fallback
│   │   └── llm_extractor.py             # LLM-экстрактор (USE_LLM_EXTRACTOR=1)
│   ├── llm/
│   │   └── client.py                    # OpenAI-совместимый LLM-клиент
│   ├── plots/
│   │   └── plotter.py                   # Построение PNG-графиков (matplotlib)
│   ├── storage/
│   │   └── mongo.py                     # MongoStore: articles, keyword_counts, aggregates
│   ├── pipeline.py                      # fetch_abstracts / extract_keywords_batch / recompute_aggregates / render_plots
│   └── utils.py                         # Вспомогательные функции работы с датами
│
├── config/
│   ├── constants.py                     # Все числовые параметры пайплайна
│   └── domains.json                     # Список доменов (9 шт.)
│
├── frontend/
│   ├── telegram_bot/
│   │   └── bot.py                       # Telegram-бот: /start /domains /trends
│   └── plots/
│       └── plotter.py                   # (устаревший оригинал, не используется)
│
├── tests/                               # Unit-тесты (85 шт.)
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
│   ├── 0_check_db.py                    # Диагностика БД (покрытие, топ-слова)
│   ├── 1_fetch_abstracts.py             # Сервис 1: загрузка абстрактов из arXiv → articles
│   ├── 2_extract_keywords.py            # Сервис 2: извлечение keywords из articles → counts
│   ├── 3_recompute_aggregates.py        # Сервис 3: пересчёт агрегатов (топ-популярные / растущие)
│   ├── 4_render_plots.py                # Сервис 4: построение PNG-графиков из агрегатов
│   └── run_scheduler.py                 # Планировщик: запуск шага pipeline в цикле
│
├── sh/                                  # Bash-скрипты запуска
│   ├── setup_conda.sh                   # Создание conda-окружения
│   ├── setup_systemd.sh                 # Генерация systemd-сервисов
│   ├── run_tests.sh                     # Запуск тестов
│   ├── start_1_db.sh                    # Запуск MongoDB
│   ├── start_2_1_fetch.sh               # Бэкенд 1: fetch (раз в сутки, watchfiles)
│   ├── start_2_2_extract.sh             # Бэкенд 2: extract keywords (раз в час, watchfiles)
│   ├── start_2_3_aggregates_plots.sh    # Бэкенд 3+4: aggregates + plots (раз в час, watchfiles)
│   └── start_3_frontend.sh              # Telegram-бот с авто-перезапуском (watchfiles)
│
├── .env.example                         # Шаблон переменных окружения
├── .gitignore
├── pyproject.toml                       # Настройки pytest
├── requirements.txt                     # Все зависимости
└── README.md
```

