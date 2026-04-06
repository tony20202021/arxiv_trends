"""Telegram-бот: фронтенд для просмотра трендов arXiv.

Команды:
    /start      — приветствие и список команд
    /domains    — список доступных доменов с графиками
    /trends <domain_id>  — отправить графики для домена

Требует в .env:
    TELEGRAM_BOT_TOKEN   — токен бота от @BotFather
    MONGO_URI            — URI MongoDB (для чтения агрегатов)
    MONGO_DB             — название БД

Запуск:
    python frontend/telegram_bot/bot.py
"""
from __future__ import annotations
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
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
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "arxiv_trends")


def _get_store():
    """Ленивый импорт MongoStore чтобы не требовать pymongo при тестах без БД."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from storage.mongo import MongoStore
    return MongoStore(MONGO_URI, MONGO_DB)


def _plots_for_domain(domain_id: str) -> tuple[Path | None, Path | None, Path | None]:
    base = OUTPUTS_DIR / "plots" / domain_id
    popular = base / "top_popular.png"
    growing = base / "top_growing.png"
    articles = base / "articles_per_week.png"
    return (
        popular if popular.exists() else None,
        growing if growing.exists() else None,
        articles if articles.exists() else None,
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "arXiv Trends Bot\n\n"
        "Показываю тренды ключевых слов из абстрактов статей arXiv.\n\n"
        "Команды:\n"
        "  /domains — список доменов с готовыми графиками\n"
        "  /trends <domain_id> — графики для домена\n\n"
        "Пример: /trends cs-lg"
    )
    await update.message.reply_text(text)


async def cmd_domains(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        store = _get_store()
        aggs = store.get_all_aggregated()
    except Exception as exc:
        logger.warning("Не удалось подключиться к MongoDB: %s", exc)
        aggs = []

    if not aggs:
        # fallback: смотрим по файловой системе
        plot_dirs = sorted(OUTPUTS_DIR.glob("plots/*/top_popular.png"))
        if not plot_dirs:
            await update.message.reply_text(
                "Нет готовых данных. Запустите pipeline: ./sh/start_2_1_fetch.sh && ./sh/start_2_2_extract.sh && ./sh/start_2_3_aggregates_plots.sh"
            )
            return
        domain_ids = [p.parent.name for p in plot_dirs]
    else:
        domain_ids = [a["domain"] for a in aggs]

    keyboard = [
        [InlineKeyboardButton(d, callback_data=f"trends:{d}")]
        for d in domain_ids
    ]
    await update.message.reply_text(
        "Доступные домены:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _send_trends(domain_id: str, update: Update) -> None:
    popular_path, growing_path, articles_path = _plots_for_domain(domain_id)

    if popular_path is None and growing_path is None and articles_path is None:
        text = (
            f"Графики для '{domain_id}' не найдены.\n"
            "Проверьте список доменов: /domains\n"
            "Или запустите pipeline: ./sh/start_2_1_fetch.sh && ./sh/start_2_2_extract.sh && ./sh/start_2_3_aggregates_plots.sh"
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return

    caption_extra = ""
    try:
        store = _get_store()
        agg = store.get_aggregated(domain_id)
        if agg:
            ts = agg.get("computed_at")
            ts_str = ts.strftime("%Y-%m-%d %H:%M UTC") if ts else "неизвестно"
            caption_extra = f"\nОбновлено: {ts_str}"
    except Exception:
        pass

    media = []
    if articles_path:
        media.append(InputMediaPhoto(
            media=articles_path.open("rb"),
            caption=f"Статей по неделям ({domain_id}){caption_extra}",
        ))
    if popular_path:
        media.append(InputMediaPhoto(
            media=popular_path.open("rb"),
            caption=f"Top-популярные ({domain_id}){caption_extra}",
        ))
    if growing_path:
        media.append(InputMediaPhoto(
            media=growing_path.open("rb"),
            caption=f"Top-растущие ({domain_id}){caption_extra}",
        ))

    reply = update.callback_query.message if update.callback_query else update.message
    for item in media:
        await reply.reply_photo(photo=item.media, caption=item.caption)


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
    ])


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")

    app = Application.builder().token(token).post_init(_set_commands).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("domains", cmd_domains))
    app.add_handler(CommandHandler("trends", cmd_trends))
    app.add_handler(CallbackQueryHandler(callback_trends, pattern=r"^trends:"))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    logger.info("Telegram-бот запущен. Ctrl+C для остановки.")
    app.run_polling()


if __name__ == "__main__":
    main()
