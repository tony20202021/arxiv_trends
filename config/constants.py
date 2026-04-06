"""Все константы пайплайна (централизованно)."""

HISTORY_WEEKS = 52          # 1 год по неделям

# Версия экстрактора: см. backend/keywords/registry.py (ACTIVE_EXTRACTOR_KEY)
# В БД хранится как целое число (ACTIVE_EXTRACTOR.db_id).
TOP_N = 5                  # топ-N для графиков
GROWTH_WINDOW_WEEKS = 10    # окно роста (в неделях)

ARXIV_PAGE_SIZE = 200           # размер страницы arXiv API (один запрос к API); макс. 2000
ARXIV_MAX_OFFSET = 30000        # максимальный start по документации arXiv
ARXIV_OFFSET_LIMIT = 9800       # фактический лимит start (arXiv возвращает 500 при start≥10000)
ARXIV_BATCH_SIZE = 50           # статей обрабатывать за один батч перед паузой
ARXIV_BATCH_SLEEP_SEC = 2.0     # пауза между батчами обработки (сек)
REQUEST_SLEEP_SEC = 3.0         # пауза между запросами к API (рекомендация arXiv — 3 сек)

# --- Извлечение ключевых слов ---
TOKEN_PATTERN = r"[a-zA-Z][a-zA-Z0-9\-]{2,}"  # слова 3+ символов, допускает дефис
MIN_TOKEN_LEN = 3

STOPWORDS_EN: frozenset = frozenset({
    "the", "and", "for", "are", "was", "with", "this", "that", "have",
    "from", "but", "not", "can", "its", "our", "we", "in", "on", "of",
    "to", "a", "an", "is", "by", "as", "at", "be", "or", "it", "if",
    "also", "which", "such", "than", "more", "into", "over", "these",
    "their", "they", "all", "has", "had", "been", "when", "how", "may",
    "each", "both", "i", "s", "e", "g", "i.e", "e.g", "et", "al",
    "about", "other", "would", "while", "thus", "where", "show", "shows",
    "shown", "use", "used", "using", "based", "through", "via", "two",
    "one", "first", "second", "new", "high", "large", "well", "then",
    "here", "paper", "propose", "proposed", "present", "results", "result",
    "approach", "method", "model", "models", "data", "set", "sets",
    "problem", "task", "tasks", "work", "existing", "state", "art",
    "performance", "experiments", "experimental", "evaluation", "achieve",
    "achieves", "significantly", "demonstrate", "demonstrates",
    # незначимые для тематического анализа
    "across", "under", "methods", "introduce", "introduction",
    "without", "between", "different", "multiple", "various",
    "among", "within", "along", "number", "three", "four", "five",
    "however", "therefore", "furthermore", "moreover", "additionally",
    "recent", "previous", "often", "further", "need",
    # служебные глаголы и фразы
    "remain", "address", "provide", "enabling", "finding", "only", "yet",
    "study", "setting", "time", "achieve", "improve", "consider",
    # незначимые для тематического анализа (из анализа топ-20)
    "enable", "real", "multi", "fine", "non", "sample",
})

