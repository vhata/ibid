"""Factoids — store, recall, alias, and modify arbitrary "X is Y" facts.

Faithful port of the legacy ibid ``factoid`` plugin's command surface:

  - **Set / append / replace**
    - ``remember X is Y`` / ``X is Y`` — store (errors if X is already known)
    - ``X is also Y`` — explicitly append another value to X
    - ``no, X is Y`` — replace all of X's values with Y
  - **Lookup**
    - ``X?`` — explicit lookup ("i don't know" on miss)
    - ``@bot X`` (bare addressed) — silent on miss
    - ``literal X`` — show every stored value with its index and verb
  - **Aliases**
    - ``X is the same as Y`` — make X an alias for Y; lookups under X
      see Y's values; updates to either show under both
  - **Modification (operate on Nth value, or matching ``/regex/``)**
    - ``X #2 += suffix`` — append text to value #2
    - ``X #2 ~= s/foo/bar/[gir]`` — regex substitute on a value
    - ``X #2 ~= y/abc/xyz/`` — translate (per-character substitute)
  - **Forget**
    - ``forget X`` — drop the factoid
    - ``forget X #2`` — drop value #2 (or the factoid if it was the last one)
    - ``forget X /pattern/[r]`` — drop the value(s) matching the pattern
  - **Search / meta**
    - ``search Y`` — substring search across stored values
    - ``last set factoid`` — name of the most recently created factoid

Wildcard / ``$arg``-style factoids from the legacy schema aren't ported —
those need runtime pattern matching that's outside this round's scope.
"""

from __future__ import annotations

import random
import re
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, func, select
from sqlalchemy.orm import Mapped, mapped_column, relationship, selectinload

from ibid.db import Base
from ibid.plugin import Plugin, always, command, match
from ibid.utils import utcnow

if TYPE_CHECKING:
    from ibid.event import Event

VERBS = ("is", "are", "was", "were", "has", "have", "does", "can", "should", "would")
INTERROGATIVES = ("what", "wtf", "where", "when", "who", "what's", "who's", "why")
_VERB_ALTS = "|".join(VERBS)


# ----------------------------------------------------------------- schema


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
    aliases: Mapped[list[FactoidAlias]] = relationship(
        back_populates="factoid",
        cascade="all, delete-orphan",
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


class FactoidAlias(Base):
    __tablename__ = "factoid_alias"
    id: Mapped[int] = mapped_column(primary_key=True)
    factoid_id: Mapped[int] = mapped_column(
        ForeignKey("factoid.id", ondelete="CASCADE"),
        index=True,
    )
    alias: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    factoid: Mapped[Factoid] = relationship(back_populates="aliases")


# ----------------------------------------------------------------- patterns

# "name is value" / "no, name is value" / "name is also value" / "name is also Y".
# We anchor on a verb token from VERBS to avoid matching every chat utterance.
_SET_RE = re.compile(
    rf"^(?P<no>no[,.:]\s+)?(?P<key>.+?)\s+(?P<verb>{_VERB_ALTS})\s+"
    rf"(?P<also>also\s+)?(?P<value>.+)$",
    re.IGNORECASE | re.DOTALL,
)
# "X?" explicit lookup
_LOOKUP_RE = re.compile(r"^(?P<key>.+?)\s*\?+\s*$", re.DOTALL)
# "X = Y" compact assignment
_ASSIGN_RE = re.compile(r"^(?P<key>.+?)\s*=\s*(?P<value>.+)$", re.DOTALL)
# "forget X [#n | /pattern/[r]]"
_FORGET_RE = re.compile(
    r"^forget\s+(?P<key>.+?)"
    r"(?:\s+#(?P<idx>\d+)|\s+/(?P<pat>.+?)/(?P<r>r?))?\s*$",
    re.IGNORECASE | re.DOTALL,
)
# "X is the same as Y" — alias
_ALIAS_RE = re.compile(
    r"^(?P<target>.+?)\s+is\s+the\s+same\s+as\s+(?P<source>.+)$",
    re.IGNORECASE,
)
# "literal X [#n | /pat/[r]]"
_LITERAL_RE = re.compile(
    r"^literal\s+(?P<key>.+?)"
    r"(?:\s+#(?P<idx>\d+)|\s+/(?P<pat>.+?)/(?P<r>r?))?\s*$",
    re.IGNORECASE | re.DOTALL,
)
# "X [#n | /pat/[r]] += suffix"
_APPEND_RE = re.compile(
    # Don't consume whitespace after `+=` — the legacy ibid let users include
    # a leading space in the appended text by writing "X += foo".
    r"^(?P<key>.+?)(?:\s+#(?P<idx>\d+)|\s+/(?P<pat>.+?)/(?P<r>r?))?"
    r"\s*\+=(?P<suffix>.+)$",
    re.DOTALL,
)
# "X [#n | /pat/[r]] ~= s/foo/bar/[gir] | ~= y/abc/xyz/"
_MODIFY_RE = re.compile(
    r"^(?P<key>.+?)"
    r"(?:\s+#(?P<idx>\d+)|\s+/(?P<pat>.+?)/(?P<r>r?))?"
    r"\s*(?:~=|=~)\s*(?P<op>[sy])(?P<rest>.+)$",
    re.DOTALL,
)
# "search [query]"
_SEARCH_RE = re.compile(r"^search\s+(?P<q>.+)$", re.IGNORECASE | re.DOTALL)

# Last-set-factoid query
_LAST_RE = re.compile(
    r"^(?:last\s+set\s+factoid|what\s+did\s+\S+\s+just\s+set)$",
    re.IGNORECASE,
)


# -------------------------------------------------------------- helpers


def _norm(key: str) -> str:
    """Normalise a factoid key for storage/lookup."""
    return " ".join(key.lower().strip("?!.").split())


def _strip_name(name: str) -> str:
    """Drop trailing punctuation from a factoid name."""
    m = re.match(r"^\s*(.*?)\s*[?!.]*\s*$", name, re.DOTALL)
    return m.group(1) if m else name


# Match ``$word`` placeholders (not ``$<digit>`` — those are factoid content).
_PLACEHOLDER_RE = re.compile(r"\$([A-Za-z_]\w*)")


def _substitute(value: str, event: Event) -> str:
    """Replace known legacy placeholders (``$who``, ``$channel``, ...).

    Unknown ``$name`` tokens are left as-is.
    """
    if "$" not in value:
        return value
    now = utcnow()

    def lookup(name_lower: str) -> str | None:
        if name_lower == "who":
            return event.nick
        if name_lower == "channel":
            return event.target
        if name_lower == "date":
            return now.strftime("%Y-%m-%d")
        if name_lower == "time":
            return now.strftime("%H:%M:%S")
        if name_lower == "year":
            return now.strftime("%Y")
        if name_lower == "month":
            return now.strftime("%B")
        if name_lower == "day":
            return now.strftime("%d")
        if name_lower == "dow":
            return now.strftime("%A")
        if name_lower == "hour":
            return now.strftime("%H")
        if name_lower == "minute":
            return now.strftime("%M")
        if name_lower == "second":
            return now.strftime("%S")
        if name_lower == "unixtime":
            return str(int(now.timestamp()))
        if name_lower == "random":
            return str(random.randint(0, 99))
        return None

    def replace(match: re.Match[str]) -> str:
        sub = lookup(match.group(1).lower())
        return sub if sub is not None else match.group(0)

    return _PLACEHOLDER_RE.sub(replace, value)


async def _resolve(sess, key: str) -> Factoid | None:  # type: ignore[no-untyped-def]
    """Find a Factoid by key, falling through aliases."""
    fact: Factoid | None = (
        await sess.execute(
            select(Factoid).options(selectinload(Factoid.values)).where(Factoid.key == key)
        )
    ).scalar_one_or_none()
    if fact is not None:
        return fact
    alias: FactoidAlias | None = (
        await sess.execute(select(FactoidAlias).where(FactoidAlias.alias == key))
    ).scalar_one_or_none()
    if alias is None:
        return None
    via_alias: Factoid | None = (
        await sess.execute(
            select(Factoid)
            .options(selectinload(Factoid.values))
            .where(Factoid.id == alias.factoid_id)
        )
    ).scalar_one_or_none()
    return via_alias


def _select_values(
    fact: Factoid, idx: str | None, pat: str | None, is_regex: str | None
) -> list[FactoidValue]:
    """Pick the value(s) targeted by an ``#n`` / ``/pattern/`` selector."""
    values = list(fact.values)
    if idx is not None:
        n = int(idx)
        if 1 <= n <= len(values):
            return [values[n - 1]]
        return []
    if pat is not None:
        if is_regex:
            try:
                regex = re.compile(pat)
            except re.error:
                return []
            return [v for v in values if regex.search(v.value)]
        return [v for v in values if pat.lower() in v.value.lower()]
    return values


# -------------------------------------------------------------- plugin


class Factoids(Plugin):
    name = "factoid"

    def __init__(self, bot: object) -> None:
        super().__init__(bot)
        # In-memory; matches the legacy plugin's class-level last_set_factoid.
        self._last_set: str | None = None

    # ------------------------------ remember (explicit) + natural set form

    @command("remember")
    async def remember(self, event: Event, args: str) -> None:
        """remember X is Y — store a factoid (errors if X already known)."""
        await self._do_set(event, args, allow_remember_prefix=False)

    @match(rf"^(?:no[,.:]\s+)?.+?\s+(?:{_VERB_ALTS})\s+.+$", addressed=True)
    async def natural_set(self, event: Event, _m: re.Match[str]) -> None:
        """``X is Y`` / ``X is also Y`` / ``no, X is Y``."""
        # Skip aliases — they have their own handler.
        if " is the same as " in event.text.lower():
            return
        # Skip assignment compact form — handled by :meth:`assign`.
        if "=" in event.text:
            return
        await self._do_set(event, event.text, allow_remember_prefix=False)

    @command("=", addressed=True)
    async def assign(self, event: Event, args: str) -> None:
        """X = Y — compact set form."""
        m = _ASSIGN_RE.match(args)
        if not m:
            await event.reply("usage: <key> = <value>")
            return
        await self._store(event, m.group("key"), "is", m.group("value"), append=True)

    async def _do_set(self, event: Event, raw: str, *, allow_remember_prefix: bool) -> None:
        m = _SET_RE.match(raw)
        if m is None:
            await event.reply("usage: remember <key> is <value>")
            return
        key = _strip_name(m.group("key"))
        if not key:
            await event.reply("not interested in empty factoids")
            return
        if key.lower() in INTERROGATIVES:
            await event.reply(
                random.choice(["i'm afraid i have no idea", "not a clue", "erk, dunno"]),
                address=False,
            )
            return
        await self._store(
            event,
            key,
            m.group("verb").lower(),
            m.group("value"),
            append=bool(m.group("also")),
            correction=bool(m.group("no")),
        )

    async def _store(
        self,
        event: Event,
        key_raw: str,
        verb: str,
        value: str,
        *,
        append: bool = False,
        correction: bool = False,
    ) -> None:
        key = _norm(key_raw)
        if not key or not value.strip():
            await event.reply("can't remember nothing")
            return
        async with event.bot.db.session() as sess:
            fact = await _resolve(sess, key)
            if fact is None:
                fact = Factoid(key=key, values=[])
                sess.add(fact)
                await sess.flush()
            else:
                if correction:
                    for v in list(fact.values):
                        await sess.delete(v)
                elif not append:
                    await event.reply(f"i already know stuff about {key}")
                    return
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
            self._last_set = fact.key
        await event.reply(
            random.choice(
                [
                    "if you say so",
                    "one learns a new thing every day",
                    "i'll remember that",
                    "got it",
                ]
            ),
        )

    # ------------------------------ alias

    @match(_ALIAS_RE, addressed=True)
    async def alias(self, event: Event, m: re.Match[str]) -> None:
        """X is the same as Y — make X an alias for Y."""
        target = _norm(_strip_name(m.group("target")))
        source = _norm(_strip_name(m.group("source")))
        if not target or not source:
            return
        if target == source:
            await event.reply("that makes no sense, they *are* the same")
            return
        async with event.bot.db.session() as sess:
            source_fact = await _resolve(sess, source)
            if source_fact is None:
                await event.reply(f"i don't know about {source}")
                return
            existing = await _resolve(sess, target)
            if existing is not None:
                await event.reply(f"i already know stuff about {target}")
                return
            sess.add(FactoidAlias(factoid_id=source_fact.id, alias=target))
        await event.reply(f"ok, {target} is the same as {source}", address=False)

    # ------------------------------ lookup

    @match(r"\?+\s*$", addressed=True)
    async def lookup(self, event: Event, _m: re.Match[str]) -> None:
        """X? — explicit lookup ("i don't know" on miss)."""
        m = _LOOKUP_RE.match(event.text)
        if m is None:
            return
        key = _norm(m.group("key"))
        async with event.bot.db.session() as sess:
            fact = await _resolve(sess, key)
            if fact is None or not fact.values:
                await event.reply(f"i don't know about {key!r}")
                return
            await self._respond(event, key, fact)

    @always(addressed=True)
    async def bare_lookup(self, event: Event) -> None:
        """Addressed bare key — silent on miss (legacy ibid's voice)."""
        text = event.text.strip()
        if not text or text.endswith("?") or "=" in text or "~=" in text or "+=" in text:
            return
        # Skip set-shaped messages — the natural_set handler owns those.
        if _SET_RE.match(text) or _ALIAS_RE.match(text):
            return
        if _LITERAL_RE.match(text) or _FORGET_RE.match(text) or _SEARCH_RE.match(text):
            return
        key = _norm(text)
        if len(key) < 2:
            return
        async with event.bot.db.session() as sess:
            fact = await _resolve(sess, key)
            if fact is None or not fact.values:
                return
            await self._respond(event, key, fact)

    async def _respond(self, event: Event, key: str, fact: Factoid) -> None:
        value = random.choice(list(fact.values))
        text = _substitute(value.value, event)
        verb = value.verb
        if verb == "<reply>":
            await event.reply(text, address=False)
        elif verb == "<action>":
            await event.action(text)
        else:
            await event.reply(f"{key} {verb} {text}", address=False)

    # ------------------------------ literal

    @command("literal")
    async def literal(self, event: Event, args: str) -> None:
        """literal X [#n | /pat/[r]] — show every stored value with its index."""
        m = _LITERAL_RE.match("literal " + args)
        if m is None:
            await event.reply("usage: literal <key> [#n | /pat/[r]]")
            return
        key = _norm(m.group("key"))
        async with event.bot.db.session() as sess:
            fact = await _resolve(sess, key)
            if fact is None:
                await event.reply(f"i don't know about {key}")
                return
            values = _select_values(fact, m.group("idx"), m.group("pat"), m.group("r"))
            if not values:
                await event.reply(f"no matching values for {key}")
                return
            # Renumber against the full list so users can target by #.
            full = list(fact.values)
            indexes = [full.index(v) + 1 for v in values]
            await event.reply(
                ", ".join(f"{i}: {v.verb} {v.value}" for i, v in zip(indexes, values, strict=True)),
                address=False,
            )

    # ------------------------------ forget

    @command("forget")
    async def forget(self, event: Event, args: str) -> None:
        """forget X [#n | /pat/[r]] — drop a factoid, a value, or matching values."""
        m = _FORGET_RE.match("forget " + args)
        if m is None:
            await event.reply("usage: forget <key> [#n | /pat/[r]]")
            return
        key = _norm(m.group("key"))
        async with event.bot.db.session() as sess:
            fact = await _resolve(sess, key)
            if fact is None:
                await event.reply(f"i didn't know about {key} anyway")
                return
            values = _select_values(fact, m.group("idx"), m.group("pat"), m.group("r"))
            if m.group("idx") is None and m.group("pat") is None:
                # Drop the whole factoid.
                await sess.delete(fact)
                await event.reply(f"forgotten {key}")
                return
            if not values:
                await event.reply(f"no matching values for {key}")
                return
            for v in values:
                await sess.delete(v)
            # If we just emptied the factoid, drop the shell too.
            remaining = [x for x in fact.values if x not in values]
            if not remaining:
                await sess.delete(fact)
                await event.reply(f"forgotten {key}")
            else:
                await event.reply(f"forgotten {len(values)} value(s) of {key}")

    # ------------------------------ modify: ``+= suffix``

    @match(_APPEND_RE, addressed=True)
    async def append(self, event: Event, m: re.Match[str]) -> None:
        """X [#n | /pat/[r]] += text — append text to one value."""
        key = _norm(m.group("key"))
        async with event.bot.db.session() as sess:
            fact = await _resolve(sess, key)
            if fact is None:
                await event.reply(f"i don't know about {key}")
                return
            values = _select_values(fact, m.group("idx"), m.group("pat"), m.group("r"))
            if len(values) != 1:
                if len(values) > 1:
                    await event.reply("pattern matches multiple values — be more specific")
                else:
                    await event.reply("no value selected — use #n or /pattern/")
                return
            values[0].value = values[0].value + m.group("suffix")
        await event.reply("got it")

    # ------------------------------ modify: ``~= s/foo/bar/`` and ``~= y///``

    @match(_MODIFY_RE, addressed=True)
    async def modify(self, event: Event, m: re.Match[str]) -> None:
        """X [#n | /pat/[r]] ~= s/foo/bar/[gir] | y/abc/xyz/ — substitute/translate."""
        key = _norm(m.group("key"))
        op = m.group("op")
        parts, flags = _parse_sed_expr(m.group("rest"))
        if parts is None:
            await event.reply("that operation makes no sense. try s/foo/bar/")
            return
        async with event.bot.db.session() as sess:
            fact = await _resolve(sess, key)
            if fact is None:
                await event.reply(f"i don't know about {key}")
                return
            values = _select_values(fact, m.group("idx"), m.group("pat"), m.group("r"))
            if len(values) != 1:
                if len(values) > 1:
                    await event.reply("pattern matches multiple values — be more specific")
                else:
                    await event.reply("no value selected — use #n or /pattern/")
                return
            target = values[0]
            search, replace = parts
            try:
                if op == "s":
                    target.value = _do_subst(target.value, search, replace, flags)
                else:  # op == "y"
                    target.value = _do_translate(target.value, search, replace)
            except (ValueError, re.error) as exc:
                await event.reply(f"that operation makes no sense: {exc}")
                return
        await event.reply("got it")

    # ------------------------------ search

    @command("search")
    async def search(self, event: Event, args: str) -> None:
        """search <query> — substring search across factoid values."""
        q = args.strip()
        if not q:
            await event.reply("usage: search <query>")
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
        await event.reply(
            " | ".join(f"{key} = {val[:60]}" for key, val in rows),
            address=False,
        )

    # ------------------------------ meta: last set factoid

    @match(_LAST_RE, addressed=True)
    async def last_set_query(self, event: Event, _m: re.Match[str]) -> None:
        if self._last_set is None:
            await event.reply("nobody has taught me anything recently")
        else:
            await event.reply(f"it was: {self._last_set}")


# -------------------------------------------------------------- sed helpers


def _parse_sed_expr(rest: str) -> tuple[tuple[str, str] | None, str]:
    """Parse the body of a ``s/.../.../[flags]`` or ``y/.../.../[flags]`` expr.

    Returns ``((search, replace), flags)`` or ``(None, flags)`` if malformed.
    Handles backslash-escaped separators inside the parts.
    """
    if not rest:
        return None, ""
    sep = rest[0]
    parts: list[list[str]] = [[]]
    i = 1
    while i < len(rest):
        c = rest[i]
        if c == "\\" and i + 1 < len(rest):
            nxt = rest[i + 1]
            if nxt in {sep, "\\"}:
                parts[-1].append(nxt)
                i += 2
                continue
            parts[-1].append(c)
            i += 1
            continue
        if c == sep:
            parts.append([])
            i += 1
            continue
        parts[-1].append(c)
        i += 1
    joined = ["".join(p) for p in parts]
    if len(joined) < 3:
        return None, ""
    search, replace = joined[0], joined[1]
    flags = joined[2] if len(joined) > 2 else ""
    return (search, replace), flags


def _do_subst(text: str, search: str, replace: str, flags: str) -> str:
    raw_regex = "r" in flags
    insensitive = "i" in flags
    count = 0 if "g" in flags else 1
    if not raw_regex:
        pattern = re.escape(search)
        # Backslashes in non-regex replace should pass through literally.
        replace_text = replace.replace("\\", "\\\\")
    else:
        pattern = search
        replace_text = replace
    re_flags = re.IGNORECASE if insensitive else 0
    if not raw_regex and not re.search(pattern, text, re_flags):
        raise ValueError(f"couldn't find {search!r} in {text!r}")
    return re.sub(pattern, replace_text, text, count=count, flags=re_flags)


def _do_translate(text: str, source: str, dest: str) -> str:
    if len(source) != len(dest):
        raise ValueError("translation source and dest must be the same length")
    table = str.maketrans(source, dest)
    return text.translate(table)


PLUGINS = [Factoids]
