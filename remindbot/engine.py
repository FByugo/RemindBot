"""Everything a reminder bot does, with no chat platform in it.

The Telegram and Discord adapters only pass text in and send text out. Reminders live in SQLite,
so a restart loses nothing, and a reminder that came due while the bot was down is sent once,
marked late, instead of being lost or sent twice.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .parse import ParseError, parse

HELP = ("/remind in 10m stretch\n/remind at 5pm call Sam\n/remind tomorrow 9am gym\n/remind 2026-12-01 rent\n"
        "/list shows yours · /cancel 3 removes number 3 · /tz America/New_York sets your timezone")
MAX_PENDING_PER_CHAT = 200
LATE_NOTE_AFTER = timedelta(minutes=2)


def iso(dt: datetime) -> str:
    """Fixed-width UTC text, so SQLite's text comparison sorts exactly like time does.
    The standard ISO writer drops microseconds when they are zero, and then two times a fraction of
    a second apart compare by punctuation instead of by value."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def from_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


class Engine:
    def __init__(self, db_path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(db_path), isolation_level=None)  # autocommit: every write is on disk before we reply
        self.db.execute("PRAGMA journal_mode=WAL") if str(db_path) != ":memory:" else None
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY, chat TEXT NOT NULL, user TEXT NOT NULL,
                due TEXT NOT NULL, message TEXT NOT NULL, created TEXT NOT NULL, sent TEXT);
            CREATE INDEX IF NOT EXISTS due_idx ON reminders(sent, due);
            CREATE TABLE IF NOT EXISTS chats (chat TEXT PRIMARY KEY, tz TEXT NOT NULL);
        """)

    # ---- settings
    def tz(self, chat: str) -> str:
        row = self.db.execute("SELECT tz FROM chats WHERE chat=?", (chat,)).fetchone()
        return row[0] if row else "UTC"

    # ---- commands
    def handle(self, chat: str, user: str, text: str, now: datetime) -> str | None:
        """Reply text for a command, or None if the message isn't for the bot."""
        text = (text or "").strip()
        if not text.startswith("/"):
            return None
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0].lower()  # Telegram sends /remind@BotName in groups
        if cmd in ("/start", "/help"):
            return HELP
        if cmd == "/remind":
            return self._remind(chat, user, arg, now)
        if cmd == "/list":
            return self._list(chat, now)
        if cmd == "/cancel":
            return self._cancel(chat, arg)
        if cmd == "/tz":
            return self._set_tz(chat, arg.strip())
        return None

    def _remind(self, chat, user, arg, now):
        pending = self.db.execute("SELECT COUNT(*) FROM reminders WHERE chat=? AND sent IS NULL", (chat,)).fetchone()[0]
        if pending >= MAX_PENDING_PER_CHAT:
            return f"this chat already has {pending} reminders waiting. Cancel some first."
        try:
            p = parse(arg, now, self.tz(chat))
        except ParseError as e:
            return f"couldn't set that: {e}"
        cur = self.db.execute("INSERT INTO reminders(chat,user,due,message,created) VALUES(?,?,?,?,?)",
                              (chat, user, iso(p.when_utc), p.message, iso(now)))
        return f"#{cur.lastrowid} set for {self._fmt(p.when_utc, chat)}: {p.message}"

    def _list(self, chat, now):
        rows = self.db.execute("SELECT id,due,message FROM reminders WHERE chat=? AND sent IS NULL ORDER BY due",
                               (chat,)).fetchall()
        if not rows:
            return "nothing waiting"
        return "\n".join(f"#{i} {self._fmt(from_iso(d), chat)}: {m}" for i, d, m in rows)

    def _cancel(self, chat, arg):
        if not arg.strip().lstrip("#").isdigit():
            return "say which one, like /cancel 3 (see /list)"
        rid = int(arg.strip().lstrip("#"))
        # scoped to this chat, so nobody can cancel another chat's reminder by guessing a number
        cur = self.db.execute("DELETE FROM reminders WHERE id=? AND chat=? AND sent IS NULL", (rid, chat))
        return f"cancelled #{rid}" if cur.rowcount else f"no waiting reminder #{rid} in this chat"

    def _set_tz(self, chat, name):
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(name)
        except Exception:
            return "unknown timezone. Use a name like America/New_York or Europe/London"
        self.db.execute("INSERT INTO chats(chat,tz) VALUES(?,?) ON CONFLICT(chat) DO UPDATE SET tz=excluded.tz", (chat, name))
        return f"timezone set to {name}"

    # ---- delivery
    def due(self, now: datetime) -> list[tuple[int, str, str]]:
        """Reminders that should go out now: (id, chat, text). Call mark_sent(id) after each one is delivered."""
        rows = self.db.execute("SELECT id,chat,due,message FROM reminders WHERE sent IS NULL AND due<=? ORDER BY due",
                               (iso(now),)).fetchall()
        out = []
        for rid, chat, due, msg in rows:
            late = now - from_iso(due)
            note = f" (late by {self._ago(late)}, the bot was offline)" if late > LATE_NOTE_AFTER else ""
            out.append((rid, chat, f"⏰ {msg}{note}"))
        return out

    def mark_sent(self, rid: int, now: datetime) -> bool:
        """True the first time only, so two overlapping ticks can't both send the same reminder."""
        return self.db.execute("UPDATE reminders SET sent=? WHERE id=? AND sent IS NULL", (iso(now), rid)).rowcount == 1

    def unclaim(self, rid: int) -> None:
        """Give a claimed reminder back after a temporary delivery failure, so the next tick retries it."""
        self.db.execute("UPDATE reminders SET sent=NULL WHERE id=?", (rid,))

    # ---- formatting
    def _fmt(self, when_utc: datetime, chat: str) -> str:
        from zoneinfo import ZoneInfo
        tz = self.tz(chat)
        return when_utc.astimezone(ZoneInfo(tz)).strftime("%a %b %d %H:%M") + ("" if tz == "UTC" else f" {tz}") \
            + (" UTC" if tz == "UTC" else "")

    @staticmethod
    def _ago(d: timedelta) -> str:
        m = int(d.total_seconds() // 60)
        return f"{m // 60}h {m % 60}m" if m >= 60 else f"{m}m"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
