"""Telegram-бот: фронтенд для просмотра трендов arXiv.

Команды:
    /start      — приветствие и список команд
    /domains    — список доступных доменов с графиками
    /trends <domain_id>  — отправить графики для домена

Требует в .env:
    TELEGRAM_BOT_TOKEN   — токен бота от @BotFather

Запуск:
    python frontend/telegram_bot/bot.py
"""
from __future__ import annotations
import datetime as dt
import json
import logging
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

OUTPUTS_DIR = Path(os.environ.get("OUTPUTS_DIR", ".outputs"))

# Загружаем названия доменов из domains.json: slug → title, slug → raw_name
def _load_domain_titles() -> tuple[dict[str, str], dict[str, str]]:
    try:
        from slugify import slugify
        import json as _json
        cfg = Path(__file__).parent.parent.parent / "config" / "domains.json"
        domains = _json.loads(cfg.read_text(encoding="utf-8"))
        titles = {slugify(d["domain"]): d["title"] for d in domains}
        raw    = {slugify(d["domain"]): d["domain"] for d in domains}
        return titles, raw
    except Exception:
        return {}, {}

_DOMAIN_TITLES, _DOMAIN_RAW = _load_domain_titles()


def _load_domains_info(domain_slugs: list[str]) -> dict[str, dict]:
    """Один коннект к MongoDB: недели (из aggregates) + версии для всех доменов.

    Returns:
        {slug: {"total_weeks": int, "versions": list[int], "updated_at": datetime|None}}
    """
    empty = {s: {"total_weeks": 0, "versions": [], "updated_at": None} for s in domain_slugs}
    try:
        import pymongo
        mongo_uri = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017")
        mongo_db  = os.environ.get("MONGO_DB", "arxiv_trends")
        client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
        meta_col = client[mongo_db]["domain_meta"]
        agg_col  = client[mongo_db]["aggregates"]

        col     = client[mongo_db]["weekly_keyword_counts"]
        meta_by_raw = {m["domain"]: m for m in meta_col.find({}, {"_id": 0})}
        agg_by_raw  = {a["domain"]: a for a in agg_col.find({}, {"_id": 0, "domain": 1, "total_weeks": 1, "extractor_key": 1})}

        today   = dt.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        _before = today - dt.timedelta(days=today.weekday() + 7)

        def _extractor_version(extractor_key: str) -> list[int]:
            """Parse db_id from extractor_key string like '6_yake' → [6]."""
            try:
                return [int(extractor_key.split("_")[0])]
            except (AttributeError, ValueError, IndexError):
                return []

        result = {}
        for slug in domain_slugs:
            raw = _DOMAIN_RAW.get(slug, slug)
            agg_key = "_all" if slug == "_all" else raw
            agg_doc = agg_by_raw.get(agg_key, {})
            total_weeks = agg_doc.get("total_weeks") or 0
            if not total_weeks:
                weeks = col.distinct("week_start") if slug == "_all" else col.distinct("week_start", {"domain": raw})
                weeks = [w.replace(tzinfo=None) if getattr(w, "tzinfo", None) else w for w in weeks]
                total_weeks = len([w for w in weeks if w <= _before])
            versions   = _extractor_version(agg_doc.get("extractor_key", ""))
            if slug == "_all":
                updated_at = None
            else:
                updated_at = meta_by_raw.get(raw, {}).get("updated_at")
            result[slug] = {"total_weeks": total_weeks, "versions": versions, "updated_at": updated_at}
        return result
    except Exception:
        return empty


def _get_external_ips() -> list[str]:
    import subprocess
    _PRIVATE = ("10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.",
                "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
                "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")
    try:
        out = subprocess.check_output(["ip", "-4", "-o", "addr", "show"], text=True)
        ips = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[1] != "lo":
                ip = parts[3].split("/")[0]
                if not ip.startswith(_PRIVATE):
                    ips.append(ip)
        return ips
    except Exception:
        return []


def _resolve_web_urls() -> list[str]:
    """Вернуть список публичных URL веб-дашборда.

    Приоритет: WEB_URL из .env → .tunnel_url (Cloudflare) → все внешние IP + WEB_PORT.
    """
    url = os.environ.get("WEB_URL", "").strip().rstrip("/")
    if url:
        return [url]
    tunnel_file = Path(__file__).parent.parent.parent / ".outputs" / ".tunnel_url"
    try:
        tunnel_url = tunnel_file.read_text(encoding="utf-8").strip()
        if tunnel_url:
            return [tunnel_url]
    except OSError:
        pass
    port = os.environ.get("WEB_PORT", "8300")
    ips = _get_external_ips()
    if ips:
        return [f"http://{ip}:{port}" for ip in ips]
    return []


WEB_URL = _resolve_web_urls()[0] if _resolve_web_urls() else ""
WEB_URLS = _resolve_web_urls()


def _plot_updated_at(path: Path) -> str:
    """Возвращает время последнего изменения файла как строку UTC."""
    try:
        mtime = path.stat().st_mtime
        ts = dt.datetime.fromtimestamp(mtime, tz=dt.timezone.utc)
        return ts.strftime("%Y-%m-%d %H:%M UTC")
    except OSError:
        return "неизвестно"


def _read_keywords_data(plot_path: Path) -> dict:
    """Читает JSON-сайдкар рядом с графиком.

    Returns dict с ключами: keywords, counts, pcts, extractor.
    """
    json_path = plot_path.with_suffix(".json")
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


_COLOR_EMOJI: dict[str, str] = {
    "#1f77b4": "🔵",
    "#ff7f0e": "🟠",
    "#2ca02c": "🟢",
    "#d62728": "🔴",
    "#9467bd": "🟣",
    "#8c564b": "🟤",
    "#e377c2": "🩷",
    "#7f7f7f": "⚫",
    "#bcbd22": "🟡",
    "#17becf": "🩵",
}
_MARKER_CHAR: dict[str, str] = {
    "o": "●", "s": "■", "^": "▲", "D": "◆", "v": "▼",
    "P": "✚", "*": "★", "X": "✖", "h": "⬡",
    "<": "◀", ">": "▶", "p": "⬠", "H": "⬡", "+": "＋", "x": "×",
}


def _fmt_slope(slope: float, unit: str = "/нед") -> str:
    if abs(slope) >= 10:
        return f"{slope:+.0f}{unit}"
    if abs(slope) >= 1:
        return f"{slope:+.1f}{unit}"
    return f"{slope:+.3f}{unit}"


def _slope_arrow(slope: float) -> str:
    return "🟢▲" if slope >= 0 else "🔴▼"


def _format_keywords_message(label: str, data: dict, is_growing: bool = False,
                             slope_unit: str = "/нед") -> str:
    keywords = data.get("keywords", [])
    if not keywords:
        return ""
    counts       = data.get("counts", {})
    pcts         = data.get("pcts", {})
    growth       = data.get("growth", {})
    growth_short = data.get("growth_short", {})
    total_weeks  = data.get("total_weeks")
    win_weeks    = data.get("growth_window_weeks")
    colors  = data.get("colors", {})
    markers = data.get("markers", {})

    lines = [f"📌 {label}:"]
    for i, kw in enumerate(keywords, 1):
        color_e  = _COLOR_EMOJI.get(colors.get(kw, ""), "")
        marker_c = _MARKER_CHAR.get(markers.get(kw, ""), "")
        prefix   = f"{color_e}{marker_c} " if (color_e or marker_c) else ""

        count = counts.get(kw)
        pct   = pcts.get(kw)
        slope_full  = growth.get(kw)       if is_growing else None
        slope_short = growth_short.get(kw) if is_growing else None

        sub = [f"{prefix}{i}. {kw}"]
        count_pct = []
        if count is not None:
            count_pct.append(f"{int(count):,}")
        if pct is not None:
            count_pct.append(f"{pct:.1f}%")
        if count_pct:
            sub.append(f"   {', '.join(count_pct)}")
        if slope_full is not None and slope_short is not None:
            w_full  = f"({total_weeks})" if total_weeks else ""
            w_short = f"({win_weeks})"   if win_weeks  else ""
            sub.append(f"   {_slope_arrow(slope_full)}{_fmt_slope(slope_full, slope_unit)}{w_full}")
            sub.append(f"   {_slope_arrow(slope_short)}{_fmt_slope(slope_short, slope_unit)}{w_short}")
        elif slope_full is not None:
            sub.append(f"   {_slope_arrow(slope_full)}{_fmt_slope(slope_full, slope_unit)}")
        lines.append("\n".join(sub))

    return "\n".join(lines)


def _plots_for_domain(domain_id: str) -> dict[str, Path | None]:
    base = OUTPUTS_DIR / "plots" / domain_id

    def _p(name: str) -> Path | None:
        p = base / name
        return p if p.exists() else None

    return {
        "articles":     _p("articles_per_week.png"),
        "popular":      _p("top_popular.png"),
        "growing":      _p("top_growing.png"),
        "popular_pct":  _p("top_popular_pct.png"),
        "growing_pct":  _p("top_growing_pct.png"),
    }


_SERVICES = [
    ("mongod",          "MongoDB"),
    ("arxiv-backend-1", "Backend 1: fetch"),
    ("arxiv-backend-2", "Backend 2: extract"),
    ("arxiv-backend-3", "Backend 3: plots"),
    ("arxiv-frontend",  "Telegram bot"),
    ("arxiv-web",       "Web dashboard"),
    ("arxiv-tunnel",    "CF Tunnel"),
]


def _service_status(name: str) -> tuple[str, str]:
    """Возвращает (active_state, log_summary).

    log_summary: "HH:MM:SS | <first 20> | <last 20>"
    """
    try:
        active = subprocess.check_output(
            ["systemctl", "is-active", name], text=True
        ).strip()
    except subprocess.CalledProcessError as e:
        active = (e.output or "unknown").strip()

    try:
        raw = subprocess.check_output(
            ["journalctl", "-u", name, "-n", "10", "--no-pager", "-o", "short"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        all_lines = [l for l in raw.splitlines() if l.strip()]
        if not all_lines:
            return active, ""

        # Timestamp из последней записи (даже если blob)
        # Формат строки: "May 17 00:51:16 host unit[pid]: msg"
        ts_parts = all_lines[-1].split()
        time_str = " ".join(ts_parts[:3]) if len(ts_parts) >= 3 else ""

        # Текст сообщения — из последней НЕ-blob записи
        _ts_re = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[\d.,]*\s*")

        def _msg(line: str) -> str:
            text = line.split(": ", 1)[1].strip() if ": " in line else line.strip()
            return _ts_re.sub("", text).strip()

        text_lines = [l for l in all_lines if "blob data" not in l]
        full_text  = _msg(text_lines[-1]) if text_lines else ""
        first_msg  = full_text[:20]
        last_msg   = full_text[-20:] if len(full_text) > 20 and full_text[-20:] != full_text[:20] else ""

        parts = [time_str]
        if first_msg:
            parts.append(f"       └ {first_msg}")
        if first_msg and last_msg:
            parts.append(f"       └ ...")
        if last_msg:
            parts.append(f"       └ {last_msg}")
        summary = "\n".join(parts)
    except Exception:
        summary = ""

    return active, summary


def _proc_label(p_info: dict) -> str:
    """Краткое читаемое имя процесса из cmdline."""
    try:
        import psutil
        cmdline = psutil.Process(p_info["pid"]).cmdline()
    except Exception:
        return (p_info.get("name") or "?")[:30]

    if not cmdline:
        return (p_info.get("name") or "?")[:30]

    # python -m watchfiles ... → "watchfiles:<target>"
    if len(cmdline) >= 3 and cmdline[1] == "-m" and cmdline[2] == "watchfiles":
        target = next((a for a in cmdline[3:] if not a.startswith("-")), "")
        short = target.split()[-1] if target else "watchfiles"
        return f"watchfiles:{short}"

    # run_scheduler.py --step N → "scheduler:step1:fetch" etc.
    _step_names = {"1": "fetch", "2": "extract", "3": "plots"}
    if any("run_scheduler.py" in a for a in cmdline):
        try:
            idx = cmdline.index("--step")
            step = cmdline[idx + 1]
            return f"scheduler:step{step}:{_step_names.get(step, step)}"
        except (ValueError, IndexError):
            return "run_scheduler.py"

    # python scripts/foo.py → "foo.py"
    if len(cmdline) >= 2 and cmdline[1].endswith(".py"):
        return cmdline[1].rsplit("/", 1)[-1]

    # python -m module → "module"
    if len(cmdline) >= 3 and cmdline[1] == "-m":
        return cmdline[2]

    # python frontend/telegram_bot/bot.py → "bot.py"
    for arg in cmdline[1:]:
        if arg.endswith(".py"):
            return arg.rsplit("/", 1)[-1]

    return (p_info.get("name") or cmdline[0].rsplit("/", 1)[-1])[:30]


def _collect_procs_cpu(top_n: int = 3) -> list[tuple[str, float]]:
    """Два замера с паузой для корректного cpu_percent по процессам."""
    import psutil, time
    # Первый вызов — инициализация счётчиков (всегда 0.0)
    proc_objs = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            p.cpu_percent()
            proc_objs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    time.sleep(1.0)
    # Второй вызов — реальный % за прошедшую секунду
    results = []
    for p in proc_objs:
        try:
            cpu = p.cpu_percent()
            results.append((p.info, cpu))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    results.sort(key=lambda x: x[1], reverse=True)
    lines = []
    for info, cpu in results[:top_n]:
        label = _proc_label(info)
        lines.append((label, f"{cpu:.1f}%"))
    return lines


def _collect_procs_mem(top_n: int = 3) -> list[tuple[str, str]]:
    import psutil
    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_percent"]):
        try:
            procs.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    procs.sort(key=lambda x: x.get("memory_percent") or 0, reverse=True)
    lines = []
    for p in procs[:top_n]:
        label = _proc_label(p)
        try:
            mem_mb = psutil.Process(p["pid"]).memory_info().rss // 1024 ** 2
            lines.append((label, f"{mem_mb} MB"))
        except Exception:
            lines.append((label, f"{p.get('memory_percent', 0):.1f}%"))
    return lines


def _sys_stats() -> str:
    try:
        import psutil
        # CPU: сначала запускаем замер процессов (включает sleep 1s),
        # потом берём системный % за тот же период
        psutil.cpu_percent()          # инициализация системного счётчика
        top_cpu_data = _collect_procs_cpu(top_n=5)   # внутри sleep(1s)
        cpu = psutil.cpu_percent()    # % за последнюю секунду

        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        top_mem_data = _collect_procs_mem(top_n=5)

        top_cpu = "\n".join(f"  {l}: {v}" for l, v in top_cpu_data)
        top_mem = "\n".join(f"  {l}: {v}" for l, v in top_mem_data)

        lines = [f"CPU:  {cpu:.0f}%"]
        if top_cpu:
            lines.append(top_cpu)
        lines.append("")
        lines.append(f"RAM:  {mem.used // 1024**2} / {mem.total // 1024**2} MB  ({mem.percent:.0f}%)")
        if top_mem:
            lines.append(top_mem)
        lines.append("")
        lines.append(f"Disk: {disk.used // 1024**3} / {disk.total // 1024**3} GB  ({disk.percent:.0f}%)")
        return "\n".join(lines)
    except Exception:
        return "Системная статистика недоступна"


def _last_plot_age() -> str:
    """Возвращает строку с временем последнего обновления любого графика."""
    try:
        pngs = list(OUTPUTS_DIR.glob("plots/*/*.png"))
        if not pngs:
            return "нет графиков"
        newest = max(pngs, key=lambda p: p.stat().st_mtime)
        age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromtimestamp(
            newest.stat().st_mtime, tz=dt.timezone.utc
        )
        minutes = int(age.total_seconds() // 60)
        if minutes < 60:
            return f"{minutes} мин назад"
        return f"{minutes // 60} ч {minutes % 60} мин назад"
    except Exception:
        return "?"


def _build_status_text() -> str:
    lines = ["Статус сервера\n"]
    lines.append(_sys_stats())
    lines.append("")
    lines.append(f"Последний график: {_last_plot_age()}")
    lines.append("")
    lines.append("Службы:")
    icon = {"active": "✅", "inactive": "⛔", "failed": "❌"}
    for svc, label in _SERVICES:
        state, last_log = _service_status(svc)
        mark = icon.get(state, "❓")
        line = f"{mark} {label}: {state}"
        if last_log:
            line += f"\n    └ {last_log}"
        lines.append(line)
        lines.append("")
    return "\n".join(lines)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import asyncio
    text = await asyncio.to_thread(_build_status_text)
    await update.message.reply_text(text)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "arXiv Trends Bot\n\n"
        "Показываю тренды ключевых слов из абстрактов статей arXiv.\n\n"
        "Команды:\n"
        "  /domains — список доменов с готовыми графиками\n"
        "  /trends <domain_id> — графики для домена\n"
        "  /meta — версии экстрактора и недели по доменам\n"
        "  /web — ссылка на веб-дашборд\n"
        "  /status — состояние сервера и служб\n\n"
        "Пример: /trends cs-lg"
    )
    await update.message.reply_text(text)


async def cmd_web(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if WEB_URLS:
        lines = "\n".join(WEB_URLS)
        await update.message.reply_text(f"Веб-дашборд:\n{lines}")
    else:
        await update.message.reply_text(
            "WEB_URL не задан в .env — добавьте адрес дашборда."
        )


async def cmd_domains(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    plot_dirs = sorted(OUTPUTS_DIR.glob("plots/*/top_popular.png"))
    if not plot_dirs:
        await update.message.reply_text(
            "Нет готовых данных. Запустите pipeline: ./sh/start_2_fetch.sh && ./sh/start_3_extract.sh && ./sh/start_4_aggregates_plots.sh"
        )
        return

    domain_ids = [p.parent.name for p in plot_dirs]
    info = _load_domains_info(domain_ids)
    keyboard = []
    for d in domain_ids:
        d_info      = info.get(d, {})
        total_weeks = d_info.get("total_weeks", 0)
        versions    = d_info.get("versions", [])
        v_str    = ("v" + ",".join(str(v) for v in versions)) if versions else ""
        week_str = f"{total_weeks} недель" if total_weeks else ""
        parts    = [p for p in [v_str, week_str] if p]
        label    = f"{d}:  {' | '.join(parts)}" if parts else d
        keyboard.append([InlineKeyboardButton(label, callback_data=f"trends:{d}")])
    await update.message.reply_text(
        "Доступные домены:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _send_trends(domain_id: str, update: Update) -> None:
    plots = _plots_for_domain(domain_id)

    if not any(plots.values()):
        text = (
            f"Графики для '{domain_id}' не найдены.\n"
            "Проверьте список доменов: /domains\n"
            "Или запустите pipeline: ./sh/start_2_fetch.sh && ./sh/start_3_extract.sh && ./sh/start_4_aggregates_plots.sh"
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return

    ref_path = next(p for p in plots.values() if p is not None)
    ts_str = _plot_updated_at(ref_path)
    updated_line = f"\nОбновлено: {ts_str}"

    reply = update.callback_query.message if update.callback_query else update.message

    # 0. Полное название домена
    title = _DOMAIN_TITLES.get(domain_id, "")
    header = f"{domain_id}"
    if title:
        header += f"\n{title}"
    header += f"\nОбновлено: {ts_str}"
    await reply.reply_text(header)

    # 1. Статей по неделям
    if plots["articles"]:
        await reply.reply_photo(
            photo=plots["articles"].open("rb"),
            caption=f"Статей по неделям ({domain_id}){updated_line}",
        )

    # 2. Top-популярные: абс. → % → слова
    if plots["popular"]:
        await reply.reply_photo(
            photo=plots["popular"].open("rb"),
            caption=f"Top-популярные — абс. ({domain_id})",
        )
    if plots["popular_pct"]:
        await reply.reply_photo(
            photo=plots["popular_pct"].open("rb"),
            caption=f"Top-популярные — % от статей ({domain_id})",
        )
    if plots["popular"]:
        data = _read_keywords_data(plots["popular"])
        msg = _format_keywords_message("Top-популярные", data)
        if msg:
            domain_line = f"({title})" if title else ""
            await reply.reply_text(f"{domain_id} {domain_line}\n{msg}".strip())

    # 3. Top-растущие: абс. → слова (абс.) → % → слова (%)
    if plots["growing"]:
        await reply.reply_photo(
            photo=plots["growing"].open("rb"),
            caption=f"Top-растущие — абс. ({domain_id})",
        )
    if plots["growing"]:
        data = _read_keywords_data(plots["growing"])
        msg = _format_keywords_message("Top-растущие (абс.)", data, is_growing=True)
        if msg:
            domain_line = f"({title})" if title else ""
            await reply.reply_text(f"{domain_id} {domain_line}\n{msg}".strip())
    if plots["growing_pct"]:
        await reply.reply_photo(
            photo=plots["growing_pct"].open("rb"),
            caption=f"Top-растущие — % от статей ({domain_id})",
        )
    if plots["growing_pct"]:
        data = _read_keywords_data(plots["growing_pct"])
        msg = _format_keywords_message("Top-растущие (%/нед)", data, is_growing=True,
                                       slope_unit="%/нед")
        if msg:
            domain_line = f"({title})" if title else ""
            await reply.reply_text(f"{domain_id} {domain_line}\n{msg}".strip())


async def cmd_trends(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Укажите домен. Пример: /trends cs-lg\nСписок: /domains"
        )
        return

    domain_id = context.args[0].strip().replace("/", "-")
    await _send_trends(domain_id, update)


async def callback_trends(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    domain_id = query.data.split(":", 1)[1]
    await _send_trends(domain_id, update)


async def cmd_meta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Метаданные доменов: версии экстрактора и количество недель."""
    plot_dirs = sorted(OUTPUTS_DIR.glob("plots/*/top_popular.png"))
    domain_ids = [p.parent.name for p in plot_dirs]
    if not domain_ids:
        await update.message.reply_text("Нет готовых данных.")
        return

    info = _load_domains_info(domain_ids)

    lines = ["📊 Метаданные доменов:\n"]
    for d in domain_ids:
        d_info      = info.get(d, {})
        total_weeks = d_info.get("total_weeks", 0)
        versions    = d_info.get("versions", [])
        updated_at  = d_info.get("updated_at")
        v_str    = ("v" + ", v".join(str(v) for v in versions)) if versions else "—"
        week_str = f"{total_weeks}" if total_weeks else "нет данных"
        upd_str  = updated_at.strftime("%d.%m %H:%M") if updated_at else ""
        upd_part = f"  [{upd_str}]" if upd_str else ""
        lines.append(f"{d}:  {v_str}  |  {week_str} нед.{upd_part}")

    await update.message.reply_text("\n".join(lines))


async def cmd_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Неизвестная команда. /start — список команд.")


async def _set_commands(app) -> None:
    await app.bot.set_my_commands([
        BotCommand("start", "Приветствие"),
        BotCommand("domains", "Список доменов с графиками"),
        BotCommand("web", "Ссылка на веб-дашборд"),
        BotCommand("status", "Состояние сервера и служб"),
    ])


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")

    app = Application.builder().token(token).post_init(_set_commands).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("domains", cmd_domains))
    app.add_handler(CommandHandler("meta", cmd_meta))
    app.add_handler(CommandHandler("web", cmd_web))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("trends", cmd_trends))
    app.add_handler(CallbackQueryHandler(callback_trends, pattern=r"^trends:"))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    logger.info("Telegram-бот запущен. Ctrl+C для остановки.")
    app.run_polling()


if __name__ == "__main__":
    main()
