"""Karma — track `++` / `--` votes on arbitrary things.

Recognises:
  - ``thing++`` and ``(multi word thing)++`` — increment
  - ``thing--`` — decrement
  - ``thing++ # reason`` or ``thing++ for being great`` — note a reason
  - ``karma thing`` (command) — show current score
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text, func, select, update
from sqlalchemy.orm import Mapped, mapped_column

from ibid.db import Base
from ibid.plugin import Plugin, command, match
from ibid.utils import utcnow

if TYPE_CHECKING:
    from ibid.event import Event


class Karma(Base):
    __tablename__ = "karma"
    id: Mapped[int] = mapped_column(primary_key=True)
    thing: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class KarmaChange(Base):
    __tablename__ = "karma_change"
    id: Mapped[int] = mapped_column(primary_key=True)
    karma_id: Mapped[int] = mapped_column(
        ForeignKey("karma.id", ondelete="CASCADE"),
        index=True,
    )
    delta: Mapped[int] = mapped_column(Integer)
    actor: Mapped[str] = mapped_column(String(100))
    network: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(default=utcnow)


# Match ``foo++``, ``(foo bar)++``, optionally followed by reason.
# Symbols permitted inside the thing: word chars, dots, dashes, underscores.
_VOTE_RE = re.compile(
    r"""
    (?:
        \(\s*(?P<thing_paren>[^)]+?)\s*\)
        |
        (?P<thing_bare>[\w.\-]+)
    )
    (?P<op>\+\+|--)
    (?:\s*(?:[#:,]\s*|for\s+)(?P<reason>.+))?
    """,
    re.VERBOSE,
)


class KarmaPlugin(Plugin):
    name = "karma"

    @match(_VOTE_RE)
    async def vote(self, event: Event, m: re.Match[str]) -> None:
        thing = (m.group("thing_paren") or m.group("thing_bare") or "").strip().lower()
        if not thing:
            return
        # Don't let people self-vote.
        if thing == event.nick.lower():
            await event.reply("nice try")
            return
        op = m.group("op")
        delta = 1 if op == "++" else -1
        reason = (m.group("reason") or "").strip()

        async with event.bot.db.session() as sess:
            row = (
                await sess.execute(select(Karma).where(Karma.thing == thing))
            ).scalar_one_or_none()
            if row is None:
                row = Karma(thing=thing, score=0)
                sess.add(row)
                await sess.flush()
            await sess.execute(
                update(Karma)
                .where(Karma.id == row.id)
                .values(score=Karma.score + delta, updated_at=utcnow())
            )
            sess.add(
                KarmaChange(
                    karma_id=row.id,
                    delta=delta,
                    actor=event.nick,
                    network=event.network,
                    reason=reason,
                )
            )
        # Quiet confirmation; karma is meant to be ambient.

    @command("karma")
    async def show(self, event: Event, args: str) -> None:
        """karma <thing> — show the current score for a thing."""
        thing = args.strip().lower()
        if not thing:
            await event.reply("usage: karma <thing>")
            return
        async with event.bot.db.session() as sess:
            row = (
                await sess.execute(select(Karma).where(Karma.thing == thing))
            ).scalar_one_or_none()
            if row is None:
                await event.reply(f"{thing} has no karma")
                return
            await event.reply(f"{thing}: {row.score}")

    @command("karmatop")
    async def top(self, event: Event, _args: str) -> None:
        """karmatop — list the top ten things by karma."""
        async with event.bot.db.session() as sess:
            rows = (
                await sess.execute(
                    select(Karma.thing, Karma.score).order_by(Karma.score.desc()).limit(10)
                )
            ).all()
        if not rows:
            await event.reply("no karma tracked yet")
            return
        await event.reply(", ".join(f"{t} ({s})" for t, s in rows))

    @command("karmabottom")
    async def bottom(self, event: Event, _args: str) -> None:
        """karmabottom — list the bottom ten things by karma."""
        async with event.bot.db.session() as sess:
            rows = (
                await sess.execute(
                    select(Karma.thing, Karma.score)
                    .where(Karma.score < 0)
                    .order_by(Karma.score.asc())
                    .limit(10)
                )
            ).all()
        if not rows:
            await event.reply("no negative karma")
            return
        await event.reply(", ".join(f"{t} ({s})" for t, s in rows))


# Suppress noqa for unused import — func is used by other models in the future.
_ = func


PLUGINS = [KarmaPlugin]
