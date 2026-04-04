from __future__ import annotations
import datetime as dt
from storage.mongo import MongoStore


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
