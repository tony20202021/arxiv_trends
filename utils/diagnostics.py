from __future__ import annotations
import datetime as dt
import sys
from pathlib import Path

_backend = str(Path(__file__).parent.parent / "backend")
if _backend not in sys.path:
    sys.path.insert(0, _backend)

from config.constants import STOPWORDS_EN
from storage.mongo import MongoStore


def _aggregate_top(col, match: dict, top_n: int) -> list[tuple[str, int]]:
    """Агрегирует keyword counts из БД (данные уже нормализованы при записи)."""
    raw = col.aggregate([
        {"$match": match},
        {"$group": {"_id": "$keyword", "total": {"$sum": "$count"}}},
        {"$match": {"_id": {"$not": {"$in": list(STOPWORDS_EN)}}}},
        {"$sort": {"total": -1}},
        {"$limit": top_n},
    ])
    return [(r["_id"], r["total"]) for r in raw if len(r["_id"]) >= 3]


def db_coverage(mongo_uri: str, mongo_db: str) -> list[dict]:
    """Возвращает список доменов с диапазоном недель и суммарными данными."""
    store = MongoStore(mongo_uri, mongo_db)
    domains = store.get_all_domains()
    result = []
    for domain in sorted(domains):
        docs = list(store.col.find(
            {"domain": domain},
            {"week_start": 1, "count": 1, "_id": 0},
        ))
        if not docs:
            result.append({"domain": domain, "weeks": 0})
            continue
        weeks: dict[dt.datetime, int] = {}
        for d in docs:
            ws = d["week_start"]
            weeks[ws] = weeks.get(ws, 0) + d.get("count", 0)
        sorted_weeks = sorted(weeks)
        result.append({
            "domain":     domain,
            "week_from":  sorted_weeks[0].date(),
            "week_to":    sorted_weeks[-1].date(),
            "weeks":      len(sorted_weeks),
            "total_mentions": sum(weeks.values()),
        })
    return result


def top_keywords(mongo_uri: str, mongo_db: str, top_n: int = 10) -> dict:
    """Топ-N ключевых слов за всё время — суммарно и по каждому домену.
    Применяет нормализацию форм слова и фильтрацию стоп-слов.
    """
    store = MongoStore(mongo_uri, mongo_db)
    domains = store.get_all_domains()

    global_counts: dict[str, int] = {}
    per_domain: dict[str, list[tuple[str, int]]] = {}

    for domain in sorted(domains):
        # единственный проход — результат используется и для per_domain, и для global
        domain_top = _aggregate_top(store.col, {"domain": domain}, top_n * 20)
        per_domain[domain] = domain_top[:top_n]
        for word, count in domain_top:
            global_counts[word] = global_counts.get(word, 0) + count

    global_top = sorted(global_counts.items(), key=lambda x: -x[1])[:top_n]
    return {"global": global_top, "per_domain": per_domain}


def print_top_keywords(mongo_uri: str, mongo_db: str, top_n: int = 10) -> None:
    result = top_keywords(mongo_uri, mongo_db, top_n)

    print(f"=== Топ-{top_n} слов по всем разделам ===")
    for i, (word, count) in enumerate(result["global"], 1):
        print(f"  {i:>2}. {word:<30} {count:>10,}")

    print()
    for domain, words in result["per_domain"].items():
        print(f"--- {domain} ---")
        for i, (word, count) in enumerate(words, 1):
            print(f"  {i:>2}. {word:<30} {count:>10,}")
        print()


def print_coverage(mongo_uri: str, mongo_db: str) -> None:
    rows = db_coverage(mongo_uri, mongo_db)
    if not rows:
        print("БД пуста.")
        return
    print(f"{'Домен':<14} {'С':<12} {'По':<12} {'Недель':>7} {'Упоминаний':>12}")
    print("-" * 55)
    for r in rows:
        if r["weeks"] == 0:
            print(f"{r['domain']:<14}  — нет данных")
        else:
            print(f"{r['domain']:<14} {str(r['week_from']):<12} {str(r['week_to']):<12} "
                  f"{r['weeks']:>7} {r['total_mentions']:>12,}")
