"""Parser and engine: times, daylight saving, restarts, double sends, cross-chat cancels."""
from datetime import datetime, timedelta, timezone

import pytest

from remindbot.engine import Engine, iso
from remindbot.parse import ParseError, parse

UTC = timezone.utc
NOW = datetime(2026, 10, 14, 22, 0, tzinfo=UTC)  # 18:00 in New York (EDT, UTC-4)
NY = "America/New_York"


@pytest.mark.parametrize("text,delta", [("in 10m stretch", 600), ("10m stretch", 600), ("1h 30m x", 5400),
                                        ("2 hours x", 7200), ("3 days x", 259200), ("1d x", 86400), ("in 45 seconds x", 45)])
def test_durations(text, delta):
    assert parse(text, NOW).when_utc == NOW + timedelta(seconds=delta)


def test_clock_times_in_chat_timezone():
    assert parse("at 7pm call Sam", NOW, NY).when_utc == datetime(2026, 10, 14, 23, 0, tzinfo=UTC)
    assert parse("at 5pm gym", NOW, NY).when_utc == datetime(2026, 10, 15, 21, 0, tzinfo=UTC)  # passed today, so tomorrow
    assert parse("tomorrow 9am gym", NOW, NY).when_utc == datetime(2026, 10, 15, 13, 0, tzinfo=UTC)
    assert parse("tomorrow pay rent", NOW, NY).when_utc == datetime(2026, 10, 15, 13, 0, tzinfo=UTC)  # 9am default
    assert parse("2026-12-01 rent", NOW, NY).when_utc == datetime(2026, 12, 1, 14, 0, tzinfo=UTC)  # EST by then
    assert parse("at 18:30 dinner", NOW, NY).message == "dinner"


def test_dst_fall_back_keeps_wall_clock():
    # New York leaves daylight time on 2026-11-01. "tomorrow 9am" set on Oct 31 must be 9am EST = 14:00 UTC, not 13:00
    oct31 = datetime(2026, 10, 31, 16, 0, tzinfo=UTC)
    assert parse("tomorrow 9am x", oct31, NY).when_utc == datetime(2026, 11, 1, 14, 0, tzinfo=UTC)


def test_dst_spring_forward_gap_moves_forward():
    # 2:30am on 2027-03-14 does not exist in New York; it should land at 3:30 EDT = 07:30 UTC
    mar13 = datetime(2027, 3, 13, 17, 0, tzinfo=UTC)
    assert parse("tomorrow 2:30am x", mar13, NY).when_utc == datetime(2027, 3, 14, 7, 30, tzinfo=UTC)


@pytest.mark.parametrize("text,why", [("", "say when"), ("whenever lol", "couldn't read"), ("in 5 parsecs x", "unit"),
                                      ("2026-01-01 old", "already passed"), ("2028-01-01 far", "more than a year"),
                                      ("at 25:00 x", "not a time"), ("at 13pm x", "not a time"), ("2026-02-30 x", "not a date"),
                                      ("in 0m x", "no time")])
def test_rejections(text, why):
    with pytest.raises(ParseError, match=why):
        parse(text, NOW, NY)


def test_unknown_timezone():
    with pytest.raises(ParseError, match="timezone"):
        parse("in 1m x", NOW, "Mars/Olympus")


def test_engine_flow_and_restart(tmp_path):
    db = tmp_path / "r.db"
    e = Engine(db)
    assert e.handle("c1", "u", "/tz America/New_York", NOW) == "timezone set to America/New_York"
    assert e.handle("c1", "u", "/remind@MyBot in 10m stretch", NOW).startswith("#1 set for")
    assert e.handle("c1", "u", "/remind tomorrow 9am gym", NOW).startswith("#2")
    assert "couldn't set that" in e.handle("c1", "u", "/remind whenever", NOW)
    assert e.handle("c1", "u", "hello", NOW) is None
    del e
    e2 = Engine(db)  # restart: nothing lost, timezone kept
    assert e2.tz("c1") == NY and e2.handle("c1", "u", "/list", NOW).count("#") == 2
    later = NOW + timedelta(minutes=11)
    due = e2.due(later)
    assert [(r, c) for r, c, _ in due] == [(1, "c1")] and due[0][2] == "⏰ stretch"
    assert e2.mark_sent(1, later) is True
    assert e2.mark_sent(1, later) is False  # a second tick can't claim it again
    assert e2.due(later) == []


def test_offline_downtime_sends_once_marked_late():
    e = Engine()
    e.handle("c", "u", "/remind in 10m x", NOW)
    back = NOW + timedelta(hours=3)
    (rid, _, text), = e.due(back)
    assert "late by 2h 50m" in text


def test_unclaim_retries():
    e = Engine()
    e.handle("c", "u", "/remind in 1m x", NOW)
    t = NOW + timedelta(minutes=2)
    rid = e.due(t)[0][0]
    assert e.mark_sent(rid, t)
    e.unclaim(rid)
    assert [r for r, _, _ in e.due(t)] == [rid]


def test_cancel_is_scoped_to_chat():
    e = Engine()
    e.handle("a", "u", "/remind in 1h x", NOW)
    assert e.handle("b", "u", "/cancel 1", NOW) == "no waiting reminder #1 in this chat"
    assert e.handle("a", "u", "/cancel #1", NOW) == "cancelled #1"
    assert e.handle("a", "u", "/cancel one", NOW).startswith("say which one")


def test_timestamps_sort_as_time():
    a = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    b = a + timedelta(microseconds=500000)
    assert iso(a) < iso(b) < iso(a + timedelta(seconds=1))
    e = Engine()
    e.handle("c", "u", "/remind in 10s x", a)
    assert e.due(a + timedelta(seconds=10)) and not e.due(a + timedelta(seconds=9, microseconds=999999))
