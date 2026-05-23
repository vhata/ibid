"""Factoids — store and recall arbitrary "X is Y" facts.

The headline feature of the original ibid. Reduced to the moves people
actually used:
  - ``remember X is Y`` / ``X = Y``
  - ``X?`` (lookup) — when the bot is addressed
  - ``forget X`` / ``forget X #2`` (forget a specific value)
  - ``search Y`` — substring search across stored values

Multiple values per key are kept; lookup picks one at random for fun.
Verb forms (``X is Y``, ``X are Y``) round-trip in the canonical reply.
"""

from __future__ import annotations

import random
import re
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, func, select
from sqlalchemy.orm import Mapped, mapped_column, relationship, selectinload

from ibid.db import Base
from ibid.plugin import Plugin, command, match
from ibid.utils import utcnow

if TYPE_CHECKING:
    from ibid.event import Event

VERBS = ("is", "are", "was", "were", "has", "have", "does", "can", "should", "would")


class Factoid(Base):
    __tablename__ = "factoid"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    values: Mapped[list[FactoidValue]] = relationship(
        back_populates="factoid",
        cascade="all, delete-orphan",
        order_by="FactoidValue.id",
    )


class FactoidValue(Base):
    __tablename__ = "factoid_value"
    id: Mapped[int] = mapped_column(primary_key=True)
    factoid_id: Mapped[int] = mapped_column(
        ForeignKey("factoid.id", ondelete="CASCADE"),
        index=True,
    )
    verb: Mapped[str] = mapped_column(String(16), default="is")
    value: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(100), default="unknown")
    network: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    factoid: Mapped[Factoid] = relationship(back_populates="values")


# "remember X is Y"
_REMEMBER_RE = re.compile(
    r"^remember\s+(?P<key>.+?)\s+(?P<verb>" + "|".join(VERBS) + r")\s+(?P<value>.+)$",
    re.IGNORECASE | re.DOTALL,
)
# "X = Y" (compact form)
_ASSIGN_RE = re.compile(r"^(?P<key>.+?)\s*=\s*(?P<value>.+)$", re.DOTALL)
# "X?" lookup
_LOOKUP_RE = re.compile(r"^(?P<key>.+?)\s*\?+\s*$", re.DOTALL)
# "forget X" or "forget X #2"
_FORGET_RE = re.compile(
    r"^forget\s+(?P<key>.+?)(?:\s+#(?P<idx>\d+))?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_SEARCH_RE = re.compile(r"^search\s+(?P<q>.+)$", re.IGNORECASE | re.DOTALL)


class Factoids(Plugin):
    name = "factoid"

    @command("remember")
    async def remember_command(self, event: Event, args: str) -> None:
        """remember <key> is/are/... <value> — store a factoid."""
        m = _REMEMBER_RE.match("remember " + args)
        if m is None:
            await event.reply("usage: remember <key> is <value>")
            return
        await self._store(event, m.group("key"), m.group("verb").lower(), m.group("value"))

    @command("=", addressed=True)
    async def assign(self, event: Event, args: str) -> None:
        """X = Y — compact remember form (works as ``= X Y`` too)."""
        m = _ASSIGN_RE.match(args)
        if not m:
            await event.reply("usage: <key> = <value>")
            return
        await self._store(event, m.group("key"), "is", m.group("value"))

    @match(r"\?+\s*$", addressed=True)
    async def lookup(self, event: Event, _m: re.Match[str]) -> None:
        """Match `X?` and reply with a stored value."""
        m = _LOOKUP_RE.match(event.text)
        if m is None:
            return
        key = _norm(m.group("key"))
        async with event.bot.db.session() as sess:
            fact = (
                await sess.execute(
                    select(Factoid).options(selectinload(Factoid.values)).where(Factoid.key == key)
                )
            ).scalar_one_or_none()
            if fact is None or not fact.values:
                await event.reply(f"i don't know about {key!r}")
                return
            value = random.choice(list(fact.values))
            verb = value.verb
            if verb == "<reply>":
                await event.reply(value.value, address=False)
            elif verb == "<action>":
                await event.action(value.value)
            else:
                await event.reply(f"{key} {verb} {value.value}", address=False)

    @command("forget")
    async def forget(self, event: Event, args: str) -> None:
        """forget <key> [#n] — drop a factoid (or just the nth value)."""
        m = _FORGET_RE.match("forget " + args)
        if m is None:
            await event.reply("usage: forget <key> [#index]")
            return
        key = _norm(m.group("key"))
        idx = int(m.group("idx")) if m.group("idx") else None
        async with event.bot.db.session() as sess:
            fact = (
                await sess.execute(
                    select(Factoid).options(selectinload(Factoid.values)).where(Factoid.key == key)
                )
            ).scalar_one_or_none()
            if fact is None:
                await event.reply(f"no such factoid: {key}")
                return
            if idx is None:
                await sess.delete(fact)
                await event.reply(f"forgotten {key}")
                return
            values = list(fact.values)
            if not 1 <= idx <= len(values):
                await event.reply(f"{key} only has {len(values)} value(s)")
                return
            await sess.delete(values[idx - 1])
            await event.reply(f"forgotten {key} #{idx}")

    @command("search")
    async def search(self, event: Event, args: str) -> None:
        """search <query> — substring search over factoid values."""
        m = _SEARCH_RE.match("search " + args)
        if m is None:
            await event.reply("usage: search <query>")
            return
        q = m.group("q").strip()
        if not q:
            await event.reply("nothing to search for")
            return
        async with event.bot.db.session() as sess:
            rows = (
                await sess.execute(
                    select(Factoid.key, FactoidValue.value)
                    .join(FactoidValue, FactoidValue.factoid_id == Factoid.id)
                    .where(func.lower(FactoidValue.value).contains(q.lower()))
                    .limit(10)
                )
            ).all()
        if not rows:
            await event.reply(f"no matches for {q!r}")
            return
        snippets = [f"{key} = {val[:60]}" for key, val in rows]
        await event.reply(" | ".join(snippets))

    async def _store(
        self,
        event: Event,
        key_raw: str,
        verb: str,
        value: str,
    ) -> None:
        key = _norm(key_raw)
        if not key or not value.strip():
            await event.reply("can't remember nothing")
            return
        async with event.bot.db.session() as sess:
            fact = (
                await sess.execute(
                    select(Factoid).options(selectinload(Factoid.values)).where(Factoid.key == key)
                )
            ).scalar_one_or_none()
            if fact is None:
                # Pre-init the collection so .append() doesn't trigger a
                # lazy-load on the unattached relationship.
                fact = Factoid(key=key, values=[])
                sess.add(fact)
                await sess.flush()
                existing: list[str] = []
            else:
                existing = [v.value.strip().lower() for v in fact.values]
            if value.strip().lower() in existing:
                await event.reply(f"already knew {key!r}")
                return
            fact.values.append(
                FactoidValue(
                    verb=verb,
                    value=value.strip(),
                    author=event.nick,
                    network=event.network,
                )
            )
        await event.reply(f"ok, {key} {verb} {value.strip()}", address=False)


def _norm(key: str) -> str:
    return " ".join(key.lower().split())


PLUGINS = [Factoids]
