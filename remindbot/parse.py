"""Turn "in 10m drink water" or "tomorrow 9am call mom" into a time and a message.

Times are read in the chat's own timezone and stored in UTC, so a reminder set before a daylight
saving change still fires at the wall-clock time the person asked for.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

MAX_AHEAD = timedelta(days=366)
UNITS = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
         "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
         "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
         "d": 86400, "day": 86400, "days": 86400, "w": 604800, "week": 604800, "weeks": 604800}

DUR = re.compile(r"^(?:in\s+)?((?:\d+\s*[a-z]+\s*)+)\s+(.+)$", re.I)
DUR_PART = re.compile(r"(\d+)\s*([a-z]+)", re.I)
CLOCK = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"
AT = re.compile(rf"^(?:(today|tomorrow)\s+)?(at\s+)?{CLOCK}\s+(.+)$", re.I)
TOMORROW_ONLY = re.compile(r"^tomorrow\s+(.+)$", re.I)
ON_DATE = re.compile(rf"^(?:on\s+)?(\d{{4}}-\d{{2}}-\d{{2}})(?:\s+(?:at\s+)?{CLOCK})?\s+(.+)$", re.I)


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class Parsed:
    when_utc: datetime
    message: str


def _clock(h: str, m: str | None, ap: str | None) -> tuple[int, int]:
    hour, minute = int(h), int(m or 0)
    if ap:
        if not 1 <= hour <= 12:
            raise ParseError(f"{hour}{ap} is not a time")
        hour = hour % 12 + (12 if ap.lower() == "pm" else 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ParseError(f"{h}:{m or '00'} is not a time")
    return hour, minute


def _local(day: datetime, hour: int, minute: int, tz: ZoneInfo) -> datetime:
    """Wall-clock time on a given local day. A time inside the spring-forward gap (2:30am that never happens)
    resolves to the same instant as 3:30am: zoneinfo reads it with the pre-change offset. Tested, not patched;
    an explicit correction here was dead code (mutation run 2026-10-14)."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


def parse(text: str, now_utc: datetime, tz_name: str = "UTC") -> Parsed:
    """Read a reminder. Raises ParseError with a plain reason when it can't."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        raise ParseError("say when and what, like: in 10m stretch")
    try:
        tz = ZoneInfo(tz_name)
    except Exception as e:
        raise ParseError(f"unknown timezone {tz_name!r}") from e
    now_local = now_utc.astimezone(tz)

    if m := ON_DATE.match(text):
        try:
            day = datetime.strptime(m.group(1), "%Y-%m-%d")
        except ValueError as e:
            raise ParseError(f"{m.group(1)} is not a date") from e
        hour, minute = _clock(m.group(2), m.group(3), m.group(4)) if m.group(2) else (9, 0)
        when, msg = _local(day, hour, minute, tz), m.group(5)
    elif (m := AT.match(text)) and (m.group(1) or m.group(2) or m.group(4) or m.group(5)):
        # a bare number is NOT a clock time: "2 hours x" must be a duration, not 2 o'clock with message "hours x"
        hour, minute = _clock(m.group(3), m.group(4), m.group(5))
        day = now_local + timedelta(days=1 if (m.group(1) or "").lower() == "tomorrow" else 0)
        when, msg = _local(day, hour, minute, tz), m.group(6)
        if when <= now_utc and not m.group(1):  # bare "at 9am" that already passed today means tomorrow
            when = _local(now_local + timedelta(days=1), hour, minute, tz)
    elif m := TOMORROW_ONLY.match(text):
        when, msg = _local(now_local + timedelta(days=1), 9, 0, tz), m.group(1)
    elif m := DUR.match(text):
        total = 0
        for n, unit in DUR_PART.findall(m.group(1)):
            if unit.lower() not in UNITS:
                raise ParseError(f"don't know the unit {unit!r}; use s, m, h, d or w")
            total += int(n) * UNITS[unit.lower()]
        if total <= 0:
            raise ParseError("that is no time at all")
        when, msg = now_utc + timedelta(seconds=total), m.group(2)
    else:
        raise ParseError("couldn't read a time. Try: in 10m stretch · at 5pm call Sam · tomorrow 9am gym · 2026-12-01 rent")

    when = when.astimezone(timezone.utc)
    if when <= now_utc:
        raise ParseError("that time has already passed")
    if when - now_utc > MAX_AHEAD:
        raise ParseError("that is more than a year away")
    msg = msg.strip()
    if not msg:
        raise ParseError("what should the reminder say?")
    return Parsed(when, msg[:500])
