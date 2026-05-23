"""Quotes — store and recall lines worth remembering.

Commands:
  - ``addquote <text>`` — store a quote (attributed to the speaker)
  - ``quote [#n]`` — show a specific quote, or a random one
  - ``searchquote <query>`` — substring search across the quote body
  - ``delquote #n`` — remove a quote
  - ``quotecount`` — how many we have
"""

from __future__ import annotations

import random
import re
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, Text, func, select
from sqlalchemy.orm import Mapped, mapped_column

from ibid.db import Base
from ibid.plugin import Plugin, command
from ibid.utils import utcnow

if TYPE_CHECKING:
    from ibid.event import Event


class Quote(Base):
    __tablename__ = "quote"
    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str] = mapped_column(Text)
    added_by: Mapped[str] = mapped_column(String(100))
    network: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


_DEL_RE = re.compile(r"^\s*#?(?P<idx>\d+)\s*$")


class Quotes(Plugin):
    name = "quotes"

    @command("addquote", "quoteadd")
    async def add(self, event: Event, args: str) -> None:
        """addquote <text> — store a new quote."""
        body = args.strip()
        if not body:
            await event.reply("usage: addquote <text>")
            return
        async with event.bot.db.session() as sess:
            quote = Quote(body=body, added_by=event.nick, network=event.network)
            sess.add(quote)
            await sess.flush()
            qid = quote.id
        await event.reply(f"quote #{qid} added")

    @command("quote")
    async def show(self, event: Event, args: str) -> None:
        """quote [#n] — show a specific or random quote."""
        spec = args.strip()
        async with event.bot.db.session() as sess:
            if spec:
                m = _DEL_RE.match(spec)
                if not m:
                    await event.reply("usage: quote [#n]")
                    return
                quote = (
                    await sess.execute(select(Quote).where(Quote.id == int(m.group("idx"))))
                ).scalar_one_or_none()
                if quote is None:
                    await event.reply(f"no quote with id {m.group('idx')}")
                    return
            else:
                count = (await sess.execute(select(func.count(Quote.id)))).scalar_one()
                if count == 0:
                    await event.reply("no quotes yet")
                    return
                offset = random.randrange(count)
                quote = (await sess.execute(select(Quote).offset(offset).limit(1))).scalar_one()
        await event.reply(f"#{quote.id}: {quote.body} — added by {quote.added_by}", address=False)

    @command("searchquote", "quotesearch")
    async def search(self, event: Event, args: str) -> None:
        """searchquote <query> — substring search."""
        q = args.strip()
        if not q:
            await event.reply("usage: searchquote <query>")
            return
        async with event.bot.db.session() as sess:
            rows = (
                (
                    await sess.execute(
                        select(Quote).where(func.lower(Quote.body).contains(q.lower())).limit(5)
                    )
                )
                .scalars()
                .all()
            )
        if not rows:
            await event.reply(f"no quotes match {q!r}")
            return
        await event.reply(" | ".join(f"#{q.id}: {q.body[:80]}" for q in rows), address=False)

    @command("delquote", "quotedel")
    async def delete(self, event: Event, args: str) -> None:
        """delquote #n — remove a quote by id."""
        m = _DEL_RE.match(args)
        if not m:
            await event.reply("usage: delquote #<id>")
            return
        qid = int(m.group("idx"))
        async with event.bot.db.session() as sess:
            quote = (await sess.execute(select(Quote).where(Quote.id == qid))).scalar_one_or_none()
            if quote is None:
                await event.reply(f"no quote with id {qid}")
                return
            await sess.delete(quote)
        await event.reply(f"quote #{qid} removed")

    @command("quotecount")
    async def count(self, event: Event, _args: str) -> None:
        """quotecount — total number of quotes."""
        async with event.bot.db.session() as sess:
            count = (await sess.execute(select(func.count(Quote.id)))).scalar_one()
        await event.reply(f"{count} quote(s)")


PLUGINS = [Quotes]
