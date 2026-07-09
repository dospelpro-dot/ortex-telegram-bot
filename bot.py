"""Telegram bot — front-end for the reflexive-attention scanner.

Commands:
  /start  — intro + mission
  /scan   — run the scan now, reply with the top-N names
  /status — show which data integrations are live

Token and (optional) auto-scan schedule come from .env. Run: python bot.py
"""
from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

import config
from scanner.pipeline import format_report, run_scan

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mis = config.MISSION
    await update.message.reply_text(
        "👋 Привет! Я сканирую US-equities на ранние рефлексивные петли "
        "розничного внимания — до того, как их подхватят momentum-кванты и ETF-потоки.\n\n"
        f"Цель: <b>{mis.n_names} имени</b>, потенциал <b>+{mis.target_move_pct:.0f}%</b> "
        f"за <b>{mis.horizon_days_min}–{mis.horizon_days_max} дня</b>, приоритет — social velocity.\n\n"
        "Команды:\n"
        "/scan — запустить скан сейчас\n"
        "/status — статус источников данных",
        parse_mode=ParseMode.HTML,
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    inactive = config.missing_keys()
    if not inactive:
        msg = "✅ Все интеграции активны."
    else:
        msg = "ℹ️ Неактивные интеграции (скан работает, но с урезанным сигналом):\n• " + "\n• ".join(inactive)
    await update.message.reply_text(msg)


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ Сканирую вселенную розничного внимания…")
    try:
        report = format_report(run_scan())
    except Exception as exc:  # noqa: BLE001
        log.exception("scan failed")
        await update.message.reply_text(f"❌ Ошибка скана: {exc}")
        return
    await update.message.reply_text(report, parse_mode=ParseMode.HTML)


async def _scheduled_scan(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not config.TELEGRAM_CHAT_ID:
        return
    report = format_report(run_scan())
    await context.bot.send_message(
        chat_id=config.TELEGRAM_CHAT_ID, text=report, parse_mode=ParseMode.HTML
    )


def build_app() -> Application:
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN не задан. Скопируй .env.example в .env и впиши токен от @BotFather."
        )
    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("status", status))

    # Optional: auto-scan every N minutes if a chat id and schedule are set.
    import os
    every = int(os.getenv("AUTOSCAN_MINUTES", "0"))
    if every > 0 and config.TELEGRAM_CHAT_ID and app.job_queue:
        app.job_queue.run_repeating(_scheduled_scan, interval=every * 60, first=30)
        log.info("auto-scan enabled: every %d min -> chat %s", every, config.TELEGRAM_CHAT_ID)
    return app


def main() -> None:
    for warn in config.missing_keys():
        log.warning("inactive: %s", warn)
    app = build_app()
    log.info("bot starting (polling)…")
    app.run_polling()


if __name__ == "__main__":
    main()
