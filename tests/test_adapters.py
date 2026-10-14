"""The two front ends, offline: wiring builds, and delivery errors are sorted into retry vs drop."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import discord
import pytest
from telegram.error import Forbidden, NetworkError

from adapters import discord_bot, telegram_bot
from remindbot.engine import utcnow


def _seed(engine):
    engine.handle("123", "u", "/remind in 1s x", utcnow() - timedelta(seconds=5))


def _tg_tick(app):
    jobs = app.job_queue.jobs() or app.job_queue.scheduler.get_jobs()
    return jobs[0].callback


@pytest.mark.parametrize("err,retried", [(NetworkError("down"), True), (Forbidden("blocked"), False)])
def test_telegram_tick(tmp_path, err, retried):
    app = telegram_bot.build("123456:TEST", str(tmp_path / "t.db"))
    engine = app.bot_data["engine"]
    _seed(engine)

    async def boom(**kw):
        raise err
    ctx = SimpleNamespace(bot=SimpleNamespace(send_message=boom))
    asyncio.run(_tg_tick(app)(ctx))
    assert bool(engine.due(utcnow())) is retried


def test_telegram_delivers(tmp_path):
    app = telegram_bot.build("123456:TEST", str(tmp_path / "t.db"))
    engine = app.bot_data["engine"]
    _seed(engine)
    sent = []

    async def ok(**kw):
        sent.append(kw)
    asyncio.run(_tg_tick(app)(SimpleNamespace(bot=SimpleNamespace(send_message=ok))))
    assert sent == [{"chat_id": 123, "text": "⏰ x"}] and engine.due(utcnow()) == []


def _http_err(cls, status):
    return cls(SimpleNamespace(status=status, reason="x"), "x")


@pytest.mark.parametrize("err,retried", [(_http_err(discord.HTTPException, 503), True),
                                         (_http_err(discord.Forbidden, 403), False), (OSError("reset"), True)])
def test_discord_tick(tmp_path, err, retried):
    client = discord_bot.RemindClient(str(tmp_path / "d.db"))
    _seed(client.engine)

    async def boom(text):
        raise err
    client.get_channel = lambda cid: SimpleNamespace(send=boom)
    asyncio.run(client.tick.coro(client))
    assert bool(client.engine.due(utcnow())) is retried
