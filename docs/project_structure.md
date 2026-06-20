# Структура проекта

```
arxiv_trends/
│
├── backend/                              # Бэкенд: pipeline, планировщик
│   ├── arxiv/
│   │   ├── api_client.py                # arXiv Atom API + retry + пагинация по неделям/дням
│   │   └── html_fetcher.py              # Скачивание /abs/<id> + retry (не используется в Сервисе 1)
│   ├── analytics/
│   │   └── trends.py                    # to_frame, pivot, pivot_week_keyword_pct, top_popular, top_growing
│   ├── keywords/
│   ├── keywords/
│   │   ├── registry.py                  # Реестр алгоритмов; ACTIVE_EXTRACTOR_KEY=30_ensemble
│   │   ├── extractor.py                 # v1: regex + лемматизация + стоп-слова
│   │   ├── llm_extractor.py             # v2: LLM
│   │   ├── gensim_extractor.py          # v4: corpus TF-IDF
│   │   ├── keybert_extractor.py         # v9: KeyBERT
│   │   ├── ensemble.py                  # merge веток ансамбля
│   │   ├── canonical.py                 # синонимы (llm ↔ large language model)
│   │   └── normalizer.py                # лемматизация + пост-нормализация (scispacy → web_sm)
│   ├── llm/
│   │   └── client.py                    # OpenAI-совместимый LLM-клиент
│   ├── plots/
│   │   └── plotter.py                   # Построение PNG-графиков (matplotlib); ylabel параметризован
│   ├── storage/
│   │   └── mongo.py                     # MongoStore: articles, weekly_keyword_counts, aggregates
│   ├── fetch.py                         # Сервис 1: fetch_abstracts (выделен из pipeline.py)
│   ├── extract.py                       # Сервис 2: extract_keywords_batch (выделен из pipeline.py)
│   ├── aggregate.py                     # Сервис 3: recompute_aggregates (выделен из pipeline.py)
│   ├── plot_service.py                  # Сервис 3: render_plots + JSON-сайдкары (выделен из pipeline.py)
│   └── pipeline.py                      # Тонкий фасад: реэкспортирует fetch/extract/aggregate/render_plots
│
├── config/
│   ├── constants.py                     # Числовые параметры пайплайна (без версии экстрактора)
│   └── domains.json                     # Список доменов (11 шт.)
│
├── utils/
│   ├── __init__.py                      # Утилиты работы с датами (week_start, to_week_datetime, ...)
│   ├── cli.py                           # parse_date — парсинг дат из аргументов CLI
│   ├── diagnostics.py                   # Функции диагностики БД (coverage, top, latest, search)
│   └── logging_setup.py                 # setup_logging: text/json форматы, ротация файлов
│
├── frontend/
│   ├── telegram_bot/
│   │   └── bot.py                       # Telegram-бот: /start /domains /trends; читает JSON-сайдкары
│   ├── web/
│   │   ├── app.py                       # FastAPI + Jinja2 веб-дашборд
│   │   └── templates/                   # HTML-шаблоны дашборда
│   └── plots/
│       └── plotter.py                   # (устаревший оригинал, не используется)
│
├── tests/                               # Тесты (200 шт.)
│   ├── integration/
│   │   └── test_store_integration.py    # 25 интеграционных тестов MongoStore (mongomock)
│   ├── test_api_client.py
│   ├── test_extractor.py
│   ├── test_html_fetcher.py
│   ├── test_llm_extractor.py
│   ├── test_mongo.py
│   ├── test_pipeline.py
│   ├── test_plotter.py
│   ├── test_registry.py
│   ├── test_trends.py
│   └── test_utils.py
│
├── docs/
│   ├── startup_guide.md                 # Инструкция по запуску
│   ├── deployment_new_server.md         # Миграция / развёртывание на новом сервере
│   ├── project_structure.md             # Этот файл
│   ├── db.md                            # MongoDB: схемы коллекций
│   ├── diagnostics.md                   # Диагностика БД: команды и примеры
│   ├── systemctl_guide.md               # Автозапуск через systemd
│   ├── technical_pipeline_ru.md         # Техническое описание пайплайна
│   └── user_goal_and_outputs_ru.md      # Описание для пользователя
│
├── .outputs/                            # Графики и логи (создаётся автоматически, в .gitignore)
│   ├── logs/
│   │   └── scheduler_step{1,2,3}.log   # Ротируемые логи планировщиков
│   └── plots/
│       └── <domain_id>/
│           ├── top_popular.png          # Топ-популярные (абсолютные счётчики)
│           ├── top_popular.json         # JSON-сайдкар: {"keywords": [...], "extractor": "..."}
│           ├── top_growing.png          # Топ-растущие (абсолютные счётчики)
│           ├── top_growing.json
│           ├── top_popular_pct.png      # Топ-популярные (% от статей недели)
│           ├── top_popular_pct.json
│           ├── top_growing_pct.png      # Топ-растущие (% от статей недели)
│           ├── top_growing_pct.json
│           └── articles_per_week.png    # Количество статей по неделям
│
├── scripts/                             # Python-утилиты и CLI
│   ├── 0_check_db.py                    # Диагностика БД: coverage / top / latest / search
│   ├── 1_fetch_abstracts.py             # Разовый запуск Сервиса 1 (fetch)
│   ├── 2_extract_keywords.py            # Разовый запуск Сервиса 2 (extract)
│   ├── 3_recompute_aggregates.py        # Разовый запуск Сервиса 3 (aggregates), флаг --force
│   ├── 4_render_plots.py                # Разовый запуск Сервиса 3 (plots + JSON-сайдкары)
│   ├── 5_cleanup_old_data.py            # Очистка старых данных из БД
│   ├── 6_compare_domains.py             # Сравнение доменов: топ слов и тренды
│   ├── train_gensim_model.py            # Обучение gensim TF-IDF на abstracts (v4); см. technical_pipeline_ru.md § gensim
│   └── run_scheduler.py                 # Планировщик: --step 1|2|3, бесконечный цикл с circuit breaker
│
├── sh/                                  # Bash-скрипты запуска
│   ├── setup_conda.sh                   # Создание conda-окружения
│   ├── setup_systemd.sh                 # Генерация systemd-сервисов (arxiv-backend-1/2/3)
│   ├── run_tests.sh                     # Запуск тестов
│   ├── start_1_db.sh                    # Запуск MongoDB
│   ├── start_2_fetch.sh               # Шаг 1: fetch  — следит за arxiv/, storage/, fetch.py, pipeline.py
│   ├── start_3_extract.sh             # Шаг 2: extract — следит за keywords/, llm/, extract.py, pipeline.py
│   ├── start_4_aggregates_plots.sh    # Шаг 3: aggregates+plots — следит за analytics/, plots/, aggregate.py, plot_service.py
│   ├── start_5_frontend.sh              # Telegram-бот с авто-перезапуском (watchfiles)
│   └── start_6_web.sh                   # Веб-дашборд (FastAPI) с авто-перезапуском
│
├── .env.example                         # Шаблон переменных окружения
├── .gitignore
├── pyproject.toml                       # Настройки pytest
├── requirements.txt                     # Все зависимости (включая mongomock для тестов)
└── README.md
```
