"""Remind — schedule a future ping or message.

Usage:
  - ``remind me in 5 minutes to take the pizza out``
  - ``remind alice in 1 hour about the meeting``
  - ``remind me at 2026-12-01 09:00 about the deploy``

Persists across bot restarts: on startup, all undelivered reminders are
re-scheduled. ``dateparser`` handles the natural-language time strings.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import dateparser
from sqlalchemy import Boolean, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from ibid.db import Base
from ibid.plugin import Plugin, command
from ibid.utils import utcnow

if TYPE_CHECKING:
    from ibid.event import Event

log = logging.getLogger("ibid.plugin.remind")

# "remind <who> in/at/on <when> about/to/of <what>" — ``what`` is optional.
_REMIND_RE = re.compile(
    r"""
    ^
    (?P<who>\S+)
    \s+(?P<at>in|at|on)\s+
    (?P<when>.+?)
    (?:\s+(?:about|to|of|that|with)\s+(?P<what>.+))?
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)


class Reminder(Base):
    __tablename__ = "reminder"
    id: Mapped[int] = mapped_column(primary_key=True)
    network: Mapped[str] = mapped_column(String(80), index=True)
    target: Mapped[str] = mapped_column(String(120))
    recipient: Mapped[str] = mapped_column(String(100))
    sender: Mapped[str] = mapped_column(String(100))
    body: Mapped[str] = mapped_column(Text)
    deliver_at: Mapped[datetime] = mapped_column(index=True)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


def _humanise(delta: timedelta) -> str:
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h{(secs % 3600) // 60}m"
    days, hours = divmod(secs // 3600, 24)
    return f"{days}d{hours}h"


class RemindPlugin(Plugin):
    name = "remind"
    _tasks: list[asyncio.Task[None]]

    def __init__(self, bot: object) -> None:
        super().__init__(bot)
        self._tasks = []

    async def setup(self) -> None:
        """Re-schedule any reminders that survived a restart."""
        async with self.bot.db.session() as sess:
            rows = (
                (await sess.execute(select(Reminder).where(Reminder.delivered.is_(False))))
                .scalars()
                .all()
            )
        for row in rows:
            self._schedule(row.id, row.deliver_at)
        if rows:
            self.log.info("re-scheduled %d pending reminder(s)", len(rows))

    async def teardown(self) -> None:
        for t in self._tasks:
            t.cancel()

    @command("remind", "ping", "alarm")
    async def remind(self, event: Event, args: str) -> None:
        """remind <who> in/at <when> [about <what>] — schedule a reminder."""
        m = _REMIND_RE.match(args)
        if m is None:
            await event.reply("usage: remind <who> in/at <when> [about <what>]")
            return

        who = m.group("who")
        when_text = m.group("when").strip()
        what = (m.group("what") or "").strip()

        # Parse the time. dateparser handles "5 minutes", "in 2 hours",
        # "tomorrow at 10am", "2026-12-01 09:00", etc.
        settings = {
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": False,
            "TIMEZONE": "UTC",
            "TO_TIMEZONE": "UTC",
        }
        if m.group("at").lower() == "in":
            parsed = dateparser.parse("in " + when_text, settings=settings)
        else:
            parsed = dateparser.parse(when_text, settings=settings)
        if parsed is None:
            await event.reply(f"i can't parse {when_text!r} as a time")
            return

        deliver_at = parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
        now = utcnow()
        if deliver_at <= now:
            await event.reply("that's in the past — can't time-travel (yet)")
            return
        if deliver_at - now > timedelta(days=365):
            await event.reply("more than a year out — pick something closer")
            return

        # "me" → the sender; otherwise we ping the named nick.
        recipient = event.nick if who.lower() == "me" else who

        async with event.bot.db.session() as sess:
            reminder = Reminder(
                network=event.network,
                target=event.target,
                recipient=recipient,
                sender=event.nick,
                body=what,
                deliver_at=deliver_at,
            )
            sess.add(reminder)
            await sess.flush()
            rid = reminder.id

        self._schedule(rid, deliver_at)
        wait = _humanise(deliver_at - now)
        if recipient == event.nick:
            await event.reply(f"will ping you in {wait}")
        else:
            await event.reply(f"will ping {recipient} in {wait}")

    def _schedule(self, reminder_id: int, deliver_at: datetime) -> None:
        delay = max(0.0, (deliver_at - utcnow()).total_seconds())
        task = asyncio.create_task(
            self._fire_later(reminder_id, delay),
            name=f"remind:{reminder_id}",
        )
        self._tasks.append(task)

    async def _fire_later(self, reminder_id: int, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        try:
            await self._deliver(reminder_id)
        except Exception:
            self.log.exception("delivering reminder %s failed", reminder_id)

    async def _deliver(self, reminder_id: int) -> None:
        async with self.bot.db.session() as sess:
            row = (
                await sess.execute(select(Reminder).where(Reminder.id == reminder_id))
            ).scalar_one_or_none()
            if row is None or row.delivered:
                return
            row.delivered = True
            # Snapshot the fields we need before the session closes.
            network = row.network
            target = row.target
            recipient = row.recipient
            sender = row.sender
            body = row.body
            created_at = row.created_at

        source = self.bot.get_source(network)
        if source is None:
            self.log.warning(
                "source %s not attached; can't deliver reminder %s",
                network,
                reminder_id,
            )
            return

        delta = utcnow() - created_at
        ago = _humanise(delta)
        if body:
            msg = f"{recipient}: {sender} asked me to remind you about {body} ({ago} ago)"
        else:
            msg = f"{recipient}: {sender} asked me to ping you ({ago} ago)"
        await source.send_message(target, msg)


PLUGINS = [RemindPlugin]
