"""Memo — leave a message for someone, delivered when they next speak."""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from ibid.db import Base
from ibid.plugin import Plugin, always, command
from ibid.utils import utcnow

if TYPE_CHECKING:
    from ibid.event import Event

_TELL_RE = re.compile(
    r"^(?P<recipient>\S+)\s+(?P<msg>.+)$",
    re.DOTALL,
)


class Memo(Base):
    __tablename__ = "memo"
    id: Mapped[int] = mapped_column(primary_key=True)
    network: Mapped[str] = mapped_column(String(80), index=True)
    recipient_lower: Mapped[str] = mapped_column(String(100), index=True)
    recipient: Mapped[str] = mapped_column(String(100))
    sender: Mapped[str] = mapped_column(String(100))
    body: Mapped[str] = mapped_column(Text)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class MemoPlugin(Plugin):
    name = "memo"

    @command("tell", "msg")
    async def leave(self, event: Event, args: str) -> None:
        """tell <nick> <message> — leave a memo to be delivered later."""
        m = _TELL_RE.match(args)
        if not m:
            await event.reply("usage: tell <nick> <message>")
            return
        recipient = m.group("recipient").rstrip(":,")
        body = m.group("msg")
        async with event.bot.db.session() as sess:
            sess.add(
                Memo(
                    network=event.network,
                    recipient=recipient,
                    recipient_lower=recipient.lower(),
                    sender=event.nick,
                    body=body,
                )
            )
        await event.reply(f"will tell {recipient} when next they speak")

    @always()
    async def deliver(self, event: Event) -> None:
        async with event.bot.db.session() as sess:
            rows = (
                (
                    await sess.execute(
                        select(Memo).where(
                            Memo.network == event.network,
                            Memo.recipient_lower == event.nick.lower(),
                            Memo.delivered.is_(False),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for memo in rows:
                memo.delivered = True
        for memo in rows:
            ago = _ago(utcnow() - memo.created_at)
            await event.reply(
                f"{event.nick}: memo from {memo.sender} ({ago} ago): {memo.body}",
                address=False,
            )


def _ago(delta) -> str:  # type: ignore[no-untyped-def]
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


PLUGINS = [MemoPlugin]
