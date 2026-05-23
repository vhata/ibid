"""Seen — record when each nick last spoke, per network and channel."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, UniqueConstraint, select, update
from sqlalchemy.orm import Mapped, mapped_column

from ibid.db import Base
from ibid.plugin import Plugin, always, command
from ibid.utils import utcnow

if TYPE_CHECKING:
    from ibid.event import Event


class SeenRow(Base):
    __tablename__ = "seen"
    __table_args__ = (UniqueConstraint("network", "nick_lower", name="ux_seen_nick"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    network: Mapped[str] = mapped_column(String(80), index=True)
    nick: Mapped[str] = mapped_column(String(100))
    nick_lower: Mapped[str] = mapped_column(String(100), index=True)
    target: Mapped[str] = mapped_column(String(120), default="")
    text: Mapped[str] = mapped_column(String(500), default="")
    at: Mapped[datetime] = mapped_column(default=utcnow)


class Seen(Plugin):
    name = "seen"

    @always()
    async def record(self, event: Event) -> None:
        # Skip our own outbound and PMs (less useful).
        if event.is_private:
            return
        text = event.raw_text[:500]
        now = utcnow()
        nick_l = event.nick.lower()

        async with event.bot.db.session() as sess:
            row = (
                await sess.execute(
                    select(SeenRow).where(
                        SeenRow.network == event.network,
                        SeenRow.nick_lower == nick_l,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                sess.add(
                    SeenRow(
                        network=event.network,
                        nick=event.nick,
                        nick_lower=nick_l,
                        target=event.target,
                        text=text,
                        at=now,
                    )
                )
            else:
                await sess.execute(
                    update(SeenRow)
                    .where(SeenRow.id == row.id)
                    .values(nick=event.nick, target=event.target, text=text, at=now)
                )

    @command("seen")
    async def lookup(self, event: Event, args: str) -> None:
        """seen <nick> — when did they last speak?"""
        target = args.strip().lower()
        if not target:
            await event.reply("usage: seen <nick>")
            return
        async with event.bot.db.session() as sess:
            row = (
                await sess.execute(
                    select(SeenRow).where(
                        SeenRow.network == event.network,
                        SeenRow.nick_lower == target,
                    )
                )
            ).scalar_one_or_none()
        if row is None:
            await event.reply(f"never seen {target}")
            return
        delta = utcnow() - row.at
        await event.reply(
            f"{row.nick} was last seen in {row.target} {_humanise(delta)} ago saying: {row.text}"
        )


def _humanise(delta) -> str:  # type: ignore[no-untyped-def]
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s"
    mins, secs = divmod(secs, 60)
    if mins < 60:
        return f"{mins}m{secs}s"
    hours, mins = divmod(mins, 60)
    if hours < 24:
        return f"{hours}h{mins}m"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours}h"


PLUGINS = [Seen]
