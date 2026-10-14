"""Discord front end. All logic is in remindbot.engine; this file only moves text.

Run:  DISCORD_TOKEN=... python -m adapters.discord_bot
Needs the Message Content intent turned on for the bot in the Discord developer portal.
"""
from __future__ import annotations

import logging
import os

import discord
from discord.ext import tasks

from remindbot.engine import Engine, utcnow

log = logging.getLogger("remindbot.discord")
TICK_SECONDS = 15


class RemindClient(discord.Client):
    def __init__(self, db_path: str = "reminders.db"):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.engine = Engine(db_path)

    async def setup_hook(self):
        self.tick.start()

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        reply = self.engine.handle(str(message.channel.id), str(message.author.id), message.content, utcnow())
        if reply:
            await message.channel.send(reply)

    @tasks.loop(seconds=TICK_SECONDS)
    async def tick(self):
        for rid, chat, text in self.engine.due(utcnow()):
            if not self.engine.mark_sent(rid, utcnow()):  # claim first: an overlapping tick can't send it twice
                continue
            try:
                channel = self.get_channel(int(chat)) or await self.fetch_channel(int(chat))
                await channel.send(text)
            except (discord.Forbidden, discord.NotFound) as e:  # no permission or channel gone: keep it marked
                log.warning("dropping #%s for %s: %s", rid, chat, e)
            except (discord.HTTPException, OSError) as e:  # Discord or network trouble: retry next tick
                log.warning("will retry #%s for %s: %s", rid, chat, e)
                self.engine.unclaim(rid)

    @tick.before_loop
    async def _wait_ready(self):
        await self.wait_until_ready()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    RemindClient(os.environ.get("REMINDBOT_DB", "reminders.db")).run(os.environ["DISCORD_TOKEN"])
