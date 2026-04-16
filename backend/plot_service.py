"""Сервис 4: построение графиков из агрегатов и данных БД.

Публичный API:
    render_plots(domains, mongo_uri, mongo_db, out_dir, date_from)
"""
from __future__ import annotations
import datetime as dt
import logging
from pathlib import Path
from typing import List

from slugify import slugify

from config.constants import TOP_N, GROWTH_WINDOW_WEEKS
from keywords.registry import ACTIVE_EXTRACTOR_KEY
from storage.mongo import MongoStore
from analytics.trends import (
    to_frame, pivot_week_keyword, pivot_week_keyword_pct,
    top_popular_now, top_growing_last_window,
)
from plots.plotter import plot_keywords_over_time, plot_article_counts, build_keyword_styles

logger = logging.getLogger(__name__)


def render_plots(
    domains: List[dict],
    mongo_uri: str,
    mongo_db: str,
    out_dir: str,
    date_from: dt.date | None = None,
) -> dict:
    """Сервис 4: построить графики из агрегатов и данных БД.

    Читает aggregates и weekly_keyword_counts / articles из БД.
    Если date_from задан — рисует только данные начиная с этой даты.
    Агрегаты не пересчитываются.

    Генерирует для каждого домена:
      - top_popular.png       — топ по популярности (абс. счёт)
      - top_growing.png       — топ по росту (абс. счёт)
      - top_popular_pct.png   — топ по популярности (% статей в неделю)
      - top_growing_pct.png   — топ по росту (% статей в неделю)
      - articles_per_week.png — количество статей в неделю

    Returns:
        dict {domain: {"plots": int, "skipped": bool}}
    """
    store = MongoStore(mongo_uri, mongo_db)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {}
    _since = (
        dt.datetime(date_from.year, date_from.month, date_from.day)
        if date_from is not None else None
    )

    for domain in domains:
        dname = domain["domain"]

        agg = store.get_aggregated(dname)
        if not agg:
            logger.warning("Домен '%s': нет агрегатов, пропускаем. Запустите сначала скрипт 3.", dname)
            results[dname] = {"plots": 0, "skipped": True}
            continue

        popular = agg.get("top_popular", [])
        growing = agg.get("top_growing", [])

        week_datetimes = sorted(store.col.distinct("week_start", {"domain": dname}))
        if _since is not None:
            week_datetimes = [w for w in week_datetimes if w >= _since]
        if not week_datetimes:
            logger.warning("Домен '%s': нет данных keyword_counts, пропускаем", dname)
            results[dname] = {"plots": 0, "skipped": True}
            continue

        rows = store.get_counts_last_weeks(dname, week_datetimes)
        df = to_frame(rows)
        pivot = pivot_week_keyword(df)

        slug = slugify(dname)
        base = Path(out_dir) / "plots" / slug
        base.mkdir(parents=True, exist_ok=True)

        ext_label = agg.get("extractor_key") or ACTIVE_EXTRACTOR_KEY
        styles = build_keyword_styles(list(dict.fromkeys(popular + growing)))
        plot_keywords_over_time(
            pivot, popular,
            f"{domain['title']} — Top-{TOP_N} popular (last week)  [{ext_label}]",
            base / "top_popular.png",
            keyword_styles=styles,
        )
        plot_keywords_over_time(
            pivot, growing,
            f"{domain['title']} — Top-{TOP_N} growing (last {GROWTH_WINDOW_WEEKS} weeks)  [{ext_label}]",
            base / "top_growing.png",
            keyword_styles=styles,
            regression_window=GROWTH_WINDOW_WEEKS,
        )

        art_counts = store.get_article_counts_by_week(dname)
        if _since is not None:
            art_counts = {k: v for k, v in art_counts.items() if k >= _since}
        plot_article_counts(
            art_counts,
            f"{domain['title']} — Articles per week",
            base / "articles_per_week.png",
        )

        pivot_pct = pivot_week_keyword_pct(pivot, art_counts)
        plot_keywords_over_time(
            pivot_pct, popular,
            f"{domain['title']} — Top-{TOP_N} popular, % of weekly articles  [{ext_label}]",
            base / "top_popular_pct.png",
            keyword_styles=styles,
            ylabel="% of weekly articles",
        )
        plot_keywords_over_time(
            pivot_pct, growing,
            f"{domain['title']} — Top-{TOP_N} growing, % of weekly articles  [{ext_label}]",
            base / "top_growing_pct.png",
            keyword_styles=styles,
            regression_window=GROWTH_WINDOW_WEEKS,
            ylabel="% of weekly articles",
        )

        logger.info("  Графики сохранены → %s", base)
        results[dname] = {"plots": 5, "skipped": False}

    # Суммарные графики по всем доменам
    agg_all = store.get_aggregated("_all")
    if agg_all:
        all_week_datetimes = store.get_all_week_starts()
        if _since is not None:
            all_week_datetimes = [w for w in all_week_datetimes if w >= _since]
        if all_week_datetimes:
            all_rows = store.get_counts_all_domains(all_week_datetimes)
            all_df = to_frame(all_rows)
            all_pivot = pivot_week_keyword(all_df)
            all_popular = agg_all.get("top_popular", [])
            all_growing = agg_all.get("top_growing", [])

            base_all = Path(out_dir) / "plots" / "_all"
            base_all.mkdir(parents=True, exist_ok=True)

            all_ext_label = agg_all.get("extractor_key") or ACTIVE_EXTRACTOR_KEY
            styles = build_keyword_styles(list(dict.fromkeys(all_popular + all_growing)))
            plot_keywords_over_time(
                all_pivot, all_popular,
                f"All domains — Top-{TOP_N} popular (last week)  [{all_ext_label}]",
                base_all / "top_popular.png",
                keyword_styles=styles,
            )
            plot_keywords_over_time(
                all_pivot, all_growing,
                f"All domains — Top-{TOP_N} growing (last {GROWTH_WINDOW_WEEKS} weeks)  [{all_ext_label}]",
                base_all / "top_growing.png",
                keyword_styles=styles,
                regression_window=GROWTH_WINDOW_WEEKS,
            )
            all_art_counts = store.get_article_counts_all_domains()
            if _since is not None:
                all_art_counts = {k: v for k, v in all_art_counts.items() if k >= _since}
            plot_article_counts(
                all_art_counts,
                "All domains — Articles per week",
                base_all / "articles_per_week.png",
            )

            all_pivot_pct = pivot_week_keyword_pct(all_pivot, all_art_counts)
            plot_keywords_over_time(
                all_pivot_pct, all_popular,
                f"All domains — Top-{TOP_N} popular, % of weekly articles  [{all_ext_label}]",
                base_all / "top_popular_pct.png",
                keyword_styles=styles,
                ylabel="% of weekly articles",
            )
            plot_keywords_over_time(
                all_pivot_pct, all_growing,
                f"All domains — Top-{TOP_N} growing, % of weekly articles  [{all_ext_label}]",
                base_all / "top_growing_pct.png",
                keyword_styles=styles,
                regression_window=GROWTH_WINDOW_WEEKS,
                ylabel="% of weekly articles",
            )
            logger.info("  Суммарные графики сохранены → %s", base_all)
            results["_all"] = {"plots": 5, "skipped": False}
    else:
        logger.warning("Суммарные агрегаты не найдены — запустите сначала скрипт 3.")
        results["_all"] = {"plots": 0, "skipped": True}

    return results
