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


def _domain_week_count(domain_slug: str) -> int:
    """Число недель в MongoDB для домена."""
    try:
        import pymongo
        raw = _DOMAIN_RAW.get(domain_slug, domain_slug)
        mongo_uri = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017")
        mongo_db  = os.environ.get("MONGO_DB", "arxiv_trends")
        client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
        col = client[mongo_db]["weekly_keyword_counts"]
        return len(col.distinct("week_start", {"domain": raw}))
    except Exception:
        return 0


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


def _format_keywords_message(label: str, data: dict, is_growing: bool = False,
                             slope_unit: str = "/нед") -> str:
    keywords = data.get("keywords", [])
    if not keywords:
        return ""
    counts  = data.get("counts", {})
    pcts    = data.get("pcts", {})
    growth  = data.get("growth", {})
    colors  = data.get("colors", {})
    markers = data.get("markers", {})

    lines = [f"📌 {label}:"]
    for i, kw in enumerate(keywords, 1):
        color_e  = _COLOR_EMOJI.get(colors.get(kw, ""), "")
        marker_c = _MARKER_CHAR.get(markers.get(kw, ""), "")
        prefix   = f"{color_e}{marker_c} " if (color_e or marker_c) else ""

        count = counts.get(kw)
        pct   = pcts.get(kw)
        slope = growth.get(kw) if is_growing else None

        parts = []
        if count is not None:
            parts.append(f"{int(count):,}")
        if pct is not None:
            parts.append(f"{pct:.1f}%")
        if slope is not None:
            parts.append(f"↑{_fmt_slope(slope, slope_unit)}")

        suffix = f"  ({', '.join(parts)})" if parts else ""
        lines.append(f"{prefix}{i}. {kw}{suffix}")

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
    """Возвращает (active_state, last_log_line)."""
    try:
        active = subprocess.check_output(
            ["systemctl", "is-active", name], text=True
        ).strip()
    except subprocess.CalledProcessError as e:
        active = (e.output or "unknown").strip()
    try:
        log = subprocess.check_output(
            ["journalctl", "-u", name, "-n", "1", "--no-pager", "-o", "short"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip().splitlines()
        last = log[-1] if log else ""
        # убрать длинный prefix journalctl (дата хост юнит pid)
        if ": " in last:
            last = last.split(": ", 1)[1][:80]
        else:
            last = last[:80]
    except Exception:
        last = ""
    return active, last


def _top_procs(key: str, top_n: int = 3) -> str:
    """Топ-N процессов по cpu_percent или memory_percent."""
    try:
        import psutil
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                procs.append(p.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(key=lambda x: x.get(key) or 0, reverse=True)
        unit = "%" if key == "cpu_percent" else "MB"
        lines = []
        for p in procs[:top_n]:
            val = p.get(key) or 0
            name = (p.get("name") or "?")[:20]
            if key == "memory_percent":
                import psutil as _ps
                try:
                    mem_mb = _ps.Process(p["pid"]).memory_info().rss // 1024 ** 2
                    lines.append(f"  {name}: {mem_mb} MB")
                except Exception:
                    lines.append(f"  {name}: {val:.1f}%")
            else:
                lines.append(f"  {name}: {val:.1f}%")
        return "\n".join(lines)
    except Exception:
        return ""


def _sys_stats() -> str:
    try:
        import psutil
        # Первый вызов cpu_percent всегда 0.0 — нужен прогрев
        for p in psutil.process_iter(["cpu_percent"]):
            pass
        import time; time.sleep(0.5)

        cpu = psutil.cpu_percent(interval=0.0)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        top_cpu = _top_procs("cpu_percent")
        top_mem = _top_procs("memory_percent")

        lines = [
            f"CPU:  {cpu:.0f}%",
        ]
        if top_cpu:
            lines.append(top_cpu)
        lines += [
            f"RAM:  {mem.used // 1024**2} / {mem.total // 1024**2} MB  ({mem.percent:.0f}%)",
        ]
        if top_mem:
            lines.append(top_mem)
        lines.append(
            f"Disk: {disk.used // 1024**3} / {disk.total // 1024**3} GB  ({disk.percent:.0f}%)"
        )
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


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = ["Статус сервера\n"]

    lines.append(_sys_stats())
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

    await update.message.reply_text("\n".join(lines))


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "arXiv Trends Bot\n\n"
        "Показываю тренды ключевых слов из абстрактов статей arXiv.\n\n"
        "Команды:\n"
        "  /domains — список доменов с готовыми графиками\n"
        "  /trends <domain_id> — графики для домена\n"
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
    keyboard = []
    for d in domain_ids:
        weeks = _domain_week_count(d)
        label = f"{d}  ({weeks} нед.)" if weeks else d
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
    app.add_handler(CommandHandler("web", cmd_web))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("trends", cmd_trends))
    app.add_handler(CallbackQueryHandler(callback_trends, pattern=r"^trends:"))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    logger.info("Telegram-бот запущен. Ctrl+C для остановки.")
    app.run_polling()


if __name__ == "__main__":
    main()
