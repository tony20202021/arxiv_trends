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
    """Возвращает статистику по доменам из обеих таблиц: articles и weekly_keyword_counts."""
    store = MongoStore(mongo_uri, mongo_db)
    domains = sorted(set(
        store.get_all_domains()
        + list(store.articles.distinct("domain"))
    ))
    result = []
    for domain in domains:
        # --- articles ---
        art_pipeline = [
            {"$match": {"domain": domain}},
            {"$group": {
                "_id": None,
                "total": {"$sum": 1},
                "with_keywords": {"$sum": {"$cond": [{"$ne": ["$keywords", None]}, 1, 0]}},
                "week_from": {"$min": "$week_start"},
                "week_to":   {"$max": "$week_start"},
            }},
        ]
        art_rows = list(store.articles.aggregate(art_pipeline))
        if art_rows:
            ar = art_rows[0]
            wf = ar["week_from"].date()
            wt = ar["week_to"].date()
            # количество недель = (последний понедельник - первый понедельник) / 7 + 1
            art_weeks = (wt - wf).days // 7 + 1
            articles_stat = {
                "total":         ar["total"],
                "with_keywords": ar["with_keywords"],
                "week_from":     wf,
                "week_to":       wt,
                "weeks":         art_weeks,
            }
        else:
            articles_stat = {"total": 0, "with_keywords": 0, "week_from": None, "week_to": None, "weeks": 0}

        # --- weekly_keyword_counts ---
        kw_docs = list(store.col.find(
            {"domain": domain},
            {"week_start": 1, "count": 1, "_id": 0},
        ))
        if kw_docs:
            weeks: dict[dt.datetime, int] = {}
            for d in kw_docs:
                ws = d["week_start"]
                weeks[ws] = weeks.get(ws, 0) + d.get("count", 0)
            sorted_weeks = sorted(weeks)
            kw_stat = {
                "weeks":          len(sorted_weeks),
                "week_from":      sorted_weeks[0].date(),
                "week_to":        sorted_weeks[-1].date(),
                "total_mentions": sum(weeks.values()),
            }
        else:
            kw_stat = {"weeks": 0, "week_from": None, "week_to": None, "total_mentions": 0}

        result.append({
            "domain":   domain,
            "articles": articles_stat,
            "keywords": kw_stat,
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


def latest_records(mongo_uri: str, mongo_db: str) -> dict:
    """Последняя запись в каждой коллекции: articles, weekly_keyword_counts, aggregates."""
    store = MongoStore(mongo_uri, mongo_db)
    result: dict = {}

    # articles — последняя по fetched_at
    art = store.articles.find_one(
        {"fetched_at": {"$exists": True}},
        {"_id": 0, "arxiv_id": 1, "domain": 1, "title": 1, "published": 1, "fetched_at": 1, "week_start": 1},
        sort=[("fetched_at", -1)],
    )
    result["articles"] = art

    # weekly_keyword_counts — последняя неделя
    kw = store.col.find_one(
        {},
        {"_id": 0, "domain": 1, "week_start": 1, "keyword": 1, "count": 1},
        sort=[("week_start", -1)],
    )
    result["weekly_keyword_counts"] = kw

    # aggregates — последняя по computed_at
    agg_col = store.db["aggregates"]
    agg = agg_col.find_one(
        {},
        {"_id": 0, "domain": 1, "computed_at": 1, "top_popular": 1, "top_growing": 1},
        sort=[("computed_at", -1)],
    )
    result["aggregates"] = agg

    return result


def print_latest(mongo_uri: str, mongo_db: str) -> None:
    data = latest_records(mongo_uri, mongo_db)

    print(f"\n{'=== articles (последняя запись) ':=<60}")
    art = data["articles"]
    if art:
        print(f"  arxiv_id  : {art.get('arxiv_id')}")
        print(f"  domain    : {art.get('domain')}")
        print(f"  title     : {str(art.get('title', ''))[:80]}")
        print(f"  published : {art.get('published')}")
        ws = art.get("week_start")
        print(f"  week_start: {ws.date() if ws else '—'}")
        fa = art.get("fetched_at")
        print(f"  fetched_at: {fa.strftime('%Y-%m-%d %H:%M:%S') if fa else '—'}")
    else:
        print("  — нет данных")

    print(f"\n{'=== weekly_keyword_counts (последняя неделя) ':=<60}")
    kw = data["weekly_keyword_counts"]
    if kw:
        ws = kw.get("week_start")
        print(f"  domain    : {kw.get('domain')}")
        print(f"  week_start: {ws.date() if ws else '—'}")
        print(f"  keyword   : {kw.get('keyword')}  (count={kw.get('count')})")
    else:
        print("  — нет данных")

    print(f"\n{'=== aggregates (последнее вычисление) ':=<60}")
    agg = data["aggregates"]
    if agg:
        ca = agg.get("computed_at")
        print(f"  domain      : {agg.get('domain')}")
        print(f"  computed_at : {ca.strftime('%Y-%m-%d %H:%M:%S') if ca else '—'}")
        print(f"  top_popular : {agg.get('top_popular', [])[:5]}")
        print(f"  top_growing : {agg.get('top_growing', [])[:5]}")
    else:
        print("  — нет данных")


def search_articles(mongo_uri: str, mongo_db: str, keyword: str, limit: int = 10) -> list[dict]:
    """Поиск статей содержащих ключевое слово (полнотекстовый поиск по abstract + title).

    Использует MongoDB text index. Для поиска фразы: keyword='\"neural network\"'.
    """
    store = MongoStore(mongo_uri, mongo_db)
    results = list(store.articles.find(
        {"$text": {"$search": keyword}},
        {"_id": 0, "arxiv_id": 1, "domain": 1, "title": 1, "published": 1, "week_start": 1,
         "abstract": 1, "score": {"$meta": "textScore"}},
        sort=[("score", {"$meta": "textScore"})],
        limit=limit,
    ))
    return results


def print_search(mongo_uri: str, mongo_db: str, keyword: str, limit: int = 10) -> None:
    results = search_articles(mongo_uri, mongo_db, keyword, limit)
    print(f"\nПоиск по ключевому слову: «{keyword}»  (топ {limit})")
    if not results:
        print("  — ничего не найдено")
        return
    for i, art in enumerate(results, 1):
        ws = art.get("week_start")
        abstract = (art.get("abstract") or "").replace("\n", " ")
        # Выделим контекст вокруг слова
        idx = abstract.lower().find(keyword.lower())
        if idx >= 0:
            start = max(0, idx - 60)
            end = min(len(abstract), idx + 60 + len(keyword))
            snippet = ("…" if start > 0 else "") + abstract[start:end] + ("…" if end < len(abstract) else "")
        else:
            snippet = abstract[:120] + ("…" if len(abstract) > 120 else "")
        print(f"\n  {i}. [{art.get('domain')}] {art.get('arxiv_id')}  ({art.get('published', '')[:10]})")
        print(f"     {str(art.get('title', ''))[:90]}")
        print(f"     «{snippet}»")


def keyword_quality(mongo_uri: str, mongo_db: str, top_n: int = 50) -> dict:
    """Статистика качества экстракции ключевых слов.

    Возвращает:
        - top_keywords: список (keyword, total_count) топ-N слов по всему корпусу
        - zero_keywords_pct: % статей с пустыми ключевыми словами
        - kw_per_article: статистика распределения числа ключевых слов на статью
    """
    store = MongoStore(mongo_uri, mongo_db)

    # Топ-N ключевых слов по всему корпусу (не фильтруем стопслова — это диагностика)
    top_raw = list(store.col.aggregate([
        {"$group": {"_id": "$keyword", "total": {"$sum": "$count"}}},
        {"$sort": {"total": -1}},
        {"$limit": top_n},
    ], maxTimeMS=30_000))
    top_keywords = [(r["_id"], r["total"]) for r in top_raw]

    # % статей без ключевых слов (keywords == null или пустой dict)
    total_arts = store.articles.count_documents({})
    zero_kw = store.articles.count_documents({
        "$or": [{"keywords": None}, {"keywords": {}}]
    })
    processed = store.articles.count_documents({"keywords": {"$ne": None}})
    zero_pct = (zero_kw / total_arts * 100) if total_arts else 0.0

    # Распределение числа ключевых слов на статью (только обработанные)
    kw_counts_raw = list(store.articles.aggregate([
        {"$match": {"keywords": {"$ne": None}, "keywords": {"$ne": {}}}},
        {"$project": {"n_keywords": {"$size": {"$objectToArray": "$keywords"}}}},
        {"$group": {
            "_id": None,
            "min": {"$min": "$n_keywords"},
            "max": {"$max": "$n_keywords"},
            "avg": {"$avg": "$n_keywords"},
            "count": {"$sum": 1},
        }},
    ], maxTimeMS=30_000))
    kw_dist = kw_counts_raw[0] if kw_counts_raw else {}

    return {
        "top_keywords": top_keywords,
        "total_articles": total_arts,
        "processed_articles": processed,
        "zero_keywords": zero_kw,
        "zero_keywords_pct": zero_pct,
        "kw_per_article": {
            "min": kw_dist.get("min"),
            "max": kw_dist.get("max"),
            "avg": round(kw_dist.get("avg", 0.0), 1),
            "count": kw_dist.get("count", 0),
        },
    }


def print_quality(mongo_uri: str, mongo_db: str, top_n: int = 50) -> None:
    data = keyword_quality(mongo_uri, mongo_db, top_n)

    print(f"\n{'=== Качество экстракции ключевых слов ':=<60}")
    total = data["total_articles"]
    processed = data["processed_articles"]
    zero = data["zero_keywords"]
    print(f"  Статей всего:       {total:>10,}")
    print(f"  Обработано:         {processed:>10,}  ({processed/total*100:.1f}%)" if total else "  Обработано: 0")
    print(f"  Без ключевых слов:  {zero:>10,}  ({data['zero_keywords_pct']:.1f}%)")

    kd = data["kw_per_article"]
    if kd["count"]:
        print(f"\n  Ключевых слов на статью (обработанные):")
        print(f"    min={kd['min']}  max={kd['max']}  avg={kd['avg']}  n={kd['count']:,}")

    print(f"\n{'=== Топ-'+str(top_n)+' ключевых слов (весь корпус) ':=<60}")
    for i, (kw, cnt) in enumerate(data["top_keywords"], 1):
        marker = "  [СТОП]" if kw in STOPWORDS_EN else ""
        print(f"  {i:>3}. {kw:<35} {cnt:>10,}{marker}")


def db_size(mongo_uri: str, mongo_db: str) -> dict:
    """Размер каждой коллекции и БД в целом."""
    store = MongoStore(mongo_uri, mongo_db)
    db = store.db
    result = {}
    for col_name in ["articles", "weekly_keyword_counts", "aggregates"]:
        stats = db.command("collStats", col_name)
        result[col_name] = {
            "documents": stats.get("count", 0),
            "size_bytes": stats.get("size", 0),
            "storage_bytes": stats.get("storageSize", 0),
            "index_bytes": stats.get("totalIndexSize", 0),
        }
    db_stats = db.command("dbStats")
    result["_db_total"] = {
        "data_bytes": db_stats.get("dataSize", 0),
        "storage_bytes": db_stats.get("storageSize", 0),
        "index_bytes": db_stats.get("indexSize", 0),
    }
    return result


def print_size(mongo_uri: str, mongo_db: str) -> None:
    def _fmt(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"

    data = db_size(mongo_uri, mongo_db)
    print(f"\n{'=== Размер коллекций ':=<60}")
    fmt = f"  {{:<28}} {{:>8}} {{:>10}} {{:>10}} {{:>10}}"
    print(fmt.format("Коллекция", "Документов", "Данные", "Хранилище", "Индексы"))
    print("  " + "-" * 56)
    for col in ["articles", "weekly_keyword_counts", "aggregates"]:
        s = data[col]
        print(fmt.format(
            col,
            f"{s['documents']:,}",
            _fmt(s['size_bytes']),
            _fmt(s['storage_bytes']),
            _fmt(s['index_bytes']),
        ))
    t = data["_db_total"]
    print("  " + "-" * 56)
    print(f"  {'ИТОГО БД':<28} {'':>8} {_fmt(t['data_bytes']):>10} {_fmt(t['storage_bytes']):>10} {_fmt(t['index_bytes']):>10}")


def _week_range(monday: dt.date) -> str:
    """'2026-03-16 – 2026-03-22'"""
    sunday = monday + dt.timedelta(days=6)
    return f"{monday} – {sunday}"


def print_coverage(mongo_uri: str, mongo_db: str) -> None:
    rows = db_coverage(mongo_uri, mongo_db)
    if not rows:
        print("БД пуста.")
        return

    w = 13  # ширина колонки даты

    # --- articles ---
    print(f"\n{'=== articles (абстракты) ':=<80}")
    print(f"{'Домен':<14} {'Первая неделя':<{w}} {'Последняя неделя':<{w}} {'Недель':>7} {'Статей':>8} {'С ключ.словами':>16}")
    print("-" * (14 + w * 2 + 33))
    for r in rows:
        a = r["articles"]
        if a["total"] == 0:
            print(f"  {r['domain']:<14}  — нет данных")
        else:
            print(f"  {r['domain']:<14} {str(a['week_from']):<{w}} {str(a['week_to']):<{w}} "
                  f"{a['weeks']:>7} {a['total']:>8,} {a['with_keywords']:>16,}")

    # --- weekly_keyword_counts ---
    print(f"\n{'=== weekly_keyword_counts (подсчёты по неделям) ':=<70}")
    print(f"{'Домен':<14} {'Первая неделя':<{w}} {'Последняя неделя':<{w}} {'Недель':>8} {'Вхождений':>12}")
    print("-" * (14 + w * 2 + 22))
    for r in rows:
        k = r["keywords"]
        if k["weeks"] == 0:
            print(f"  {r['domain']:<14}  — нет данных")
        else:
            print(f"  {r['domain']:<14} {str(k['week_from']):<{w}} {str(k['week_to']):<{w}} "
                  f"{k['weeks']:>8} {k['total_mentions']:>12,}")
