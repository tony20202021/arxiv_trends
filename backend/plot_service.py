"""Сервис 4: построение графиков из агрегатов и данных БД.

Публичный API:
    render_plots(domains, mongo_uri, mongo_db, out_dir, date_from)

Побочный продукт: рядом с каждым PNG сохраняется JSON-файл с ключевыми словами,
например top_popular.json — для использования в Telegram-боте без обращения к БД.
"""
from __future__ import annotations
import datetime as dt
import json
import logging
from pathlib import Path
from typing import List

from slugify import slugify

from config.constants import TOP_N, GROWTH_WINDOW_WEEKS
from keywords.registry import ACTIVE_EXTRACTOR_KEY
from storage.mongo import MongoStore
from analytics.trends import (
    to_frame, pivot_week_keyword, pivot_week_keyword_pct,
    top_popular_now, top_growing_last_window, growing_slopes,
)
from plots.plotter import plot_keywords_over_time, plot_article_counts, build_keyword_styles
from utils import last_complete_week_start

logger = logging.getLogger(__name__)


def _last_row(pivot, keywords: list[str]) -> dict[str, float]:
    """Значения из последней строки pivot для указанных ключевых слов."""
    if pivot.empty:
        return {}
    row = pivot.iloc[-1]
    return {kw: round(float(row[kw]), 2) for kw in keywords if kw in pivot.columns}


def _save_keywords_json(
    path: Path,
    keywords: list[str],
    extractor_key: str,
    counts: dict[str, float] | None = None,
    pcts: dict[str, float] | None = None,
    growth: dict[str, float] | None = None,
    growth_short: dict[str, float] | None = None,
    growth_window_weeks: int | None = None,
    total_weeks: int | None = None,
    styles: dict[str, tuple[str, str]] | None = None,
) -> None:
    meta: dict = {"keywords": keywords, "extractor": extractor_key}
    if counts:
        meta["counts"] = counts
    if pcts:
        meta["pcts"] = pcts
    if growth:
        meta["growth"] = {k: round(v, 3) for k, v in growth.items() if k in keywords}
    if growth_short:
        meta["growth_short"] = {k: round(v, 3) for k, v in growth_short.items() if k in keywords}
    if growth_window_weeks is not None:
        meta["growth_window_weeks"] = growth_window_weeks
    if total_weeks is not None:
        meta["total_weeks"] = total_weeks
    if styles:
        meta["colors"]  = {k: styles[k][0] for k in keywords if k in styles}
        meta["markers"] = {k: styles[k][1] for k in keywords if k in styles}
    path.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


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
    # Исключаем текущую (незакрытую) неделю из данных для графиков
    _before = last_complete_week_start()

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
        week_datetimes = [w.replace(tzinfo=None) if w.tzinfo is not None else w for w in week_datetimes]
        if _since is not None:
            week_datetimes = [w for w in week_datetimes if w >= _since]
        week_datetimes = [w for w in week_datetimes if w <= _before]
        if not week_datetimes:
            logger.warning("Домен '%s': нет данных keyword_counts, пропускаем", dname)
            results[dname] = {"plots": 0, "skipped": True}
            continue

        rows = store.get_counts_last_weeks(dname, week_datetimes)
        df = to_frame(rows)
        pivot = pivot_week_keyword(df)

        art_counts = store.get_article_counts_by_week(dname)
        art_counts = {(k.replace(tzinfo=None) if k.tzinfo is not None else k): v for k, v in art_counts.items()}
        if _since is not None:
            art_counts = {k: v for k, v in art_counts.items() if k >= _since}
        art_counts = {k: v for k, v in art_counts.items() if k <= _before}
        pivot_pct = pivot_week_keyword_pct(pivot, art_counts)

        slug = slugify(dname)
        base = Path(out_dir) / "plots" / slug
        base.mkdir(parents=True, exist_ok=True)

        ext_label = agg.get("extractor_key") or ACTIVE_EXTRACTOR_KEY
        styles = build_keyword_styles(list(dict.fromkeys(popular + growing)))

        # Значения последней недели для JSON-сайдкаров
        popular_counts    = _last_row(pivot, popular)
        popular_pcts      = _last_row(pivot_pct, popular)
        growing_counts    = _last_row(pivot, growing)
        growing_pcts      = _last_row(pivot_pct, growing)
        growing_growth       = growing_slopes(pivot,     growing)
        growing_growth_short = growing_slopes(pivot,     growing, window_weeks=GROWTH_WINDOW_WEEKS)
        growing_growth_pct       = growing_slopes(pivot_pct, growing)
        growing_growth_pct_short = growing_slopes(pivot_pct, growing, window_weeks=GROWTH_WINDOW_WEEKS)
        total_weeks = len(pivot.index)

        def _title(short: str) -> str:
            return f"{dname}\n{short}\n\n[экстрактор: {ext_label}]"

        plot_keywords_over_time(
            pivot, popular,
            _title(f"Top-{TOP_N} popular (last week)"),
            base / "top_popular.png",
            keyword_styles=styles,
        )
        _save_keywords_json(base / "top_popular.png", popular, ext_label,
                            counts=popular_counts, pcts=popular_pcts, styles=styles)
        plot_keywords_over_time(
            pivot, growing,
            _title(f"Top-{TOP_N} growing (last {GROWTH_WINDOW_WEEKS} weeks)"),
            base / "top_growing.png",
            keyword_styles=styles,
            regression_window=True,
            regression_window_short=GROWTH_WINDOW_WEEKS,
        )
        _save_keywords_json(base / "top_growing.png", growing, ext_label,
                            counts=growing_counts, pcts=growing_pcts,
                            growth=growing_growth, growth_short=growing_growth_short,
                            growth_window_weeks=GROWTH_WINDOW_WEEKS, total_weeks=total_weeks,
                            styles=styles)

        plot_article_counts(
            art_counts,
            f"{dname}\nArticles per week",
            base / "articles_per_week.png",
        )

        plot_keywords_over_time(
            pivot_pct, popular,
            _title(f"Top-{TOP_N} popular, % of weekly articles"),
            base / "top_popular_pct.png",
            keyword_styles=styles,
            ylabel="% of weekly articles",
        )
        _save_keywords_json(base / "top_popular_pct.png", popular, ext_label,
                            counts=popular_counts, pcts=popular_pcts, styles=styles)
        plot_keywords_over_time(
            pivot_pct, growing,
            _title(f"Top-{TOP_N} growing, % of weekly articles"),
            base / "top_growing_pct.png",
            keyword_styles=styles,
            regression_window=True,
            regression_window_short=GROWTH_WINDOW_WEEKS,
            ylabel="% of weekly articles",
        )
        _save_keywords_json(base / "top_growing_pct.png", growing, ext_label,
                            counts=growing_counts, pcts=growing_pcts,
                            growth=growing_growth_pct, growth_short=growing_growth_pct_short,
                            growth_window_weeks=GROWTH_WINDOW_WEEKS, total_weeks=total_weeks,
                            styles=styles)

        logger.info("  Графики сохранены → %s", base)
        results[dname] = {"plots": 5, "skipped": False}

    # Суммарные графики по всем доменам
    agg_all = store.get_aggregated("_all")
    if agg_all:
        all_week_datetimes = store.get_all_week_starts()
        all_week_datetimes = [w.replace(tzinfo=None) if w.tzinfo is not None else w for w in all_week_datetimes]
        if _since is not None:
            all_week_datetimes = [w for w in all_week_datetimes if w >= _since]
        all_week_datetimes = [w for w in all_week_datetimes if w <= _before]
        if all_week_datetimes:
            all_rows = store.get_counts_all_domains(all_week_datetimes)
            all_df = to_frame(all_rows)
            all_pivot = pivot_week_keyword(all_df)
            all_popular = agg_all.get("top_popular", [])
            all_growing = agg_all.get("top_growing", [])

            base_all = Path(out_dir) / "plots" / "_all"
            base_all.mkdir(parents=True, exist_ok=True)

            all_art_counts = store.get_article_counts_all_domains()
            if _since is not None:
                all_art_counts = {k: v for k, v in all_art_counts.items() if k >= _since}
            all_art_counts = {k: v for k, v in all_art_counts.items() if k <= _before}
            all_pivot_pct = pivot_week_keyword_pct(all_pivot, all_art_counts)

            all_ext_label = agg_all.get("extractor_key") or ACTIVE_EXTRACTOR_KEY
            styles = build_keyword_styles(list(dict.fromkeys(all_popular + all_growing)))

            all_popular_counts    = _last_row(all_pivot, all_popular)
            all_popular_pcts      = _last_row(all_pivot_pct, all_popular)
            all_growing_counts    = _last_row(all_pivot, all_growing)
            all_growing_pcts      = _last_row(all_pivot_pct, all_growing)
            all_growing_growth           = growing_slopes(all_pivot,     all_growing)
            all_growing_growth_short     = growing_slopes(all_pivot,     all_growing, window_weeks=GROWTH_WINDOW_WEEKS)
            all_growing_growth_pct       = growing_slopes(all_pivot_pct, all_growing)
            all_growing_growth_pct_short = growing_slopes(all_pivot_pct, all_growing, window_weeks=GROWTH_WINDOW_WEEKS)
            all_total_weeks = len(all_pivot.index)

            def _atitle(short: str) -> str:
                return f"_all\n{short}\n\n[экстрактор: {all_ext_label}]"

            plot_keywords_over_time(
                all_pivot, all_popular,
                _atitle(f"Top-{TOP_N} popular (last week)"),
                base_all / "top_popular.png",
                keyword_styles=styles,
            )
            _save_keywords_json(base_all / "top_popular.png", all_popular, all_ext_label,
                                counts=all_popular_counts, pcts=all_popular_pcts, styles=styles)
            plot_keywords_over_time(
                all_pivot, all_growing,
                _atitle(f"Top-{TOP_N} growing (last {GROWTH_WINDOW_WEEKS} weeks)"),
                base_all / "top_growing.png",
                keyword_styles=styles,
                regression_window=True,
                regression_window_short=GROWTH_WINDOW_WEEKS,
            )
            _save_keywords_json(base_all / "top_growing.png", all_growing, all_ext_label,
                                counts=all_growing_counts, pcts=all_growing_pcts,
                                growth=all_growing_growth, growth_short=all_growing_growth_short,
                                growth_window_weeks=GROWTH_WINDOW_WEEKS, total_weeks=all_total_weeks,
                                styles=styles)
            plot_article_counts(
                all_art_counts,
                "_all\nArticles per week",
                base_all / "articles_per_week.png",
            )
            plot_keywords_over_time(
                all_pivot_pct, all_popular,
                _atitle(f"Top-{TOP_N} popular, % of weekly articles"),
                base_all / "top_popular_pct.png",
                keyword_styles=styles,
                ylabel="% of weekly articles",
            )
            _save_keywords_json(base_all / "top_popular_pct.png", all_popular, all_ext_label,
                                counts=all_popular_counts, pcts=all_popular_pcts, styles=styles)
            plot_keywords_over_time(
                all_pivot_pct, all_growing,
                _atitle(f"Top-{TOP_N} growing, % of weekly articles"),
                base_all / "top_growing_pct.png",
                keyword_styles=styles,
                regression_window=True,
                regression_window_short=GROWTH_WINDOW_WEEKS,
                ylabel="% of weekly articles",
            )
            _save_keywords_json(base_all / "top_growing_pct.png", all_growing, all_ext_label,
                                counts=all_growing_counts, pcts=all_growing_pcts,
                                growth=all_growing_growth_pct, growth_short=all_growing_growth_pct_short,
                                growth_window_weeks=GROWTH_WINDOW_WEEKS, total_weeks=all_total_weeks,
                                styles=styles)
            logger.info("  Суммарные графики сохранены → %s", base_all)
            results["_all"] = {"plots": 5, "skipped": False}
    else:
        logger.warning("Суммарные агрегаты не найдены — запустите сначала скрипт 3.")
        results["_all"] = {"plots": 0, "skipped": True}

    return results
