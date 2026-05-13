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

# Загружаем названия доменов из domains.json: slug → title
def _load_domain_titles() -> dict[str, str]:
    try:
        from slugify import slugify
        import json as _json
        cfg = Path(__file__).parent.parent.parent / "config" / "domains.json"
        domains = _json.loads(cfg.read_text(encoding="utf-8"))
        return {slugify(d["domain"]): d["title"] for d in domains}
    except Exception:
        return {}

_DOMAIN_TITLES = _load_domain_titles()


def _resolve_web_url() -> str:
    """Вернуть публичный URL веб-дашборда.

    Приоритет: WEB_URL из .env → .tunnel_url (Cloudflare) → внешний IP + WEB_PORT.
    """
    url = os.environ.get("WEB_URL", "").strip().rstrip("/")
    if url:
        return url
    tunnel_file = Path(__file__).parent.parent.parent / ".outputs" / ".tunnel_url"
    try:
        tunnel_url = tunnel_file.read_text(encoding="utf-8").strip()
        if tunnel_url:
            return tunnel_url
    except OSError:
        pass
    port = os.environ.get("WEB_PORT", "8300")
    try:
        import urllib.request
        ip = urllib.request.urlopen("https://api.ipify.org", timeout=3).read().decode()
        return f"http://{ip.strip()}:{port}"
    except Exception:
        return ""


WEB_URL = _resolve_web_url()


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


def _fmt_slope(slope: float) -> str:
    if abs(slope) >= 10:
        return f"{slope:+.0f}/нед"
    if abs(slope) >= 1:
        return f"{slope:+.1f}/нед"
    return f"{slope:+.2f}/нед"


def _format_keywords_message(label: str, data: dict, is_growing: bool = False) -> str:
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
            parts.append(f"↑{_fmt_slope(slope)}")

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


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "arXiv Trends Bot\n\n"
        "Показываю тренды ключевых слов из абстрактов статей arXiv.\n\n"
        "Команды:\n"
        "  /domains — список доменов с готовыми графиками\n"
        "  /trends <domain_id> — графики для домена\n"
        "  /web — ссылка на веб-дашборд\n\n"
        "Пример: /trends cs-lg"
    )
    await update.message.reply_text(text)


async def cmd_web(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if WEB_URL:
        await update.message.reply_text(f"Веб-дашборд: {WEB_URL}")
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
    keyboard = [
        [InlineKeyboardButton(d, callback_data=f"trends:{d}")]
        for d in domain_ids
    ]
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

    # 3. Top-растущие: абс. → % → слова
    if plots["growing"]:
        await reply.reply_photo(
            photo=plots["growing"].open("rb"),
            caption=f"Top-растущие — абс. ({domain_id})",
        )
    if plots["growing_pct"]:
        await reply.reply_photo(
            photo=plots["growing_pct"].open("rb"),
            caption=f"Top-растущие — % от статей ({domain_id})",
        )
    if plots["growing"]:
        data = _read_keywords_data(plots["growing"])
        msg = _format_keywords_message("Top-растущие", data, is_growing=True)
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
    ])


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")

    app = Application.builder().token(token).post_init(_set_commands).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("domains", cmd_domains))
    app.add_handler(CommandHandler("web", cmd_web))
    app.add_handler(CommandHandler("trends", cmd_trends))
    app.add_handler(CallbackQueryHandler(callback_trends, pattern=r"^trends:"))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    logger.info("Telegram-бот запущен. Ctrl+C для остановки.")
    app.run_polling()


if __name__ == "__main__":
    main()
