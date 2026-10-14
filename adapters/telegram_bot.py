"""Telegram front end. All logic is in remindbot.engine; this file only moves text.

Run:  TELEGRAM_TOKEN=... python -m adapters.telegram_bot
"""
from __future__ import annotations

import logging
import os

from telegram import Update
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from remindbot.engine import Engine, utcnow

log = logging.getLogger("remindbot.telegram")
TICK_SECONDS = 15


def build(token: str, db_path: str = "reminders.db") -> Application:
    engine = Engine(db_path)
    app = Application.builder().token(token).build()

    async def on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.effective_message
        reply = engine.handle(str(update.effective_chat.id), str(update.effective_user.id), msg.text, utcnow())
        if reply:
            await msg.reply_text(reply)

    async def tick(context: ContextTypes.DEFAULT_TYPE):
        for rid, chat, text in engine.due(utcnow()):
            if not engine.mark_sent(rid, utcnow()):  # claim first: an overlapping tick can't send it twice
                continue
            try:
                await context.bot.send_message(chat_id=int(chat), text=text)
            except (Forbidden, BadRequest) as e:  # blocked or chat gone: retrying won't help, keep it marked
                log.warning("dropping #%s for %s: %s", rid, chat, e)
            except TelegramError as e:  # network trouble: give it back for the next tick
                log.warning("will retry #%s for %s: %s", rid, chat, e)
                engine.unclaim(rid)

    app.add_handler(MessageHandler(filters.COMMAND, on_command))
    app.job_queue.run_repeating(tick, interval=TICK_SECONDS, first=1)
    app.bot_data["engine"] = engine
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build(os.environ["TELEGRAM_TOKEN"], os.environ.get("REMINDBOT_DB", "reminders.db")).run_polling()
