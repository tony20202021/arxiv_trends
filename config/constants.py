"""Все константы пайплайна (централизованно)."""

HISTORY_WEEKS = 52          # 1 год по неделям
TOP_N = 10                  # топ-N для графиков
GROWTH_WINDOW_WEEKS = 10    # окно роста (в неделях)

MAX_RESULTS_PER_DOMAIN = 2000   # защита от перегруза
ARXIV_PAGE_SIZE = 200           # размер страницы arXiv API
REQUEST_SLEEP_SEC = 0.5         # вежливый rate-limit

