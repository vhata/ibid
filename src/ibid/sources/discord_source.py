"""Discord source — wraps ``discord.py`` as a :class:`Source`.

Lives in ``discord_source.py`` rather than ``discord.py`` to avoid clashing
with the upstream ``discord`` package on import.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import discord

from ibid.event import Event
from ibid.sources.base import Source

if TYPE_CHECKING:
    from ibid.config import DiscordConfig
    from ibid.core import Bot

log = logging.getLogger("ibid.sources.discord")


class DiscordSource(Source):
    """Discord transport powered by ``discord.py``."""

    def __init__(self, dcfg: DiscordConfig, bot: Bot) -> None:
        super().__init__("discord", bot)
        self._cfg = dcfg
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        self._client = discord.Client(intents=intents)
        self._client.event(self.on_ready)
        self._client.event(self.on_message)
        self._channel_cache: dict[str, discord.abc.Messageable] = {}

    # discord.py event handlers — names are part of its contract.
    async def on_ready(self) -> None:
        user = self._client.user
        log.info("[discord] connected as %s (id=%s)", user, user.id if user else "?")

    async def on_message(self, message: discord.Message) -> None:
        if self._client.user is None or message.author.id == self._client.user.id:
            return
        if message.author.bot:
            return

        guild_id = message.guild.id if message.guild else None
        channel_id = message.channel.id

        if self._cfg.guilds and (guild_id is None or guild_id not in self._cfg.guilds):
            return
        if self._cfg.channels and channel_id not in self._cfg.channels:
            return

        is_private = isinstance(message.channel, discord.DMChannel)
        bot_user = self._client.user
        is_mentioned = bot_user in message.mentions if bot_user else False

        # Strip the bot mention(s) from the body.
        raw = message.content
        text = raw
        if bot_user is not None:
            for pat in (f"<@{bot_user.id}>", f"<@!{bot_user.id}>"):
                text = text.replace(pat, "").strip()

        # Honour command-prefixes too (e.g. ``!hello``).
        addressed_by_prefix = False
        for prefix in self.bot.config.bot.command_prefixes:
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
                addressed_by_prefix = True
                break

        is_addressed = is_private or is_mentioned or addressed_by_prefix

        target = str(channel_id) if not is_private else str(message.author.id)
        self._channel_cache[target] = message.channel

        event = Event(
            network=self.name,
            nick=message.author.display_name,
            user=str(message.author.id),
            host=None,
            target=target,
            raw_text=raw,
            text=text,
            is_private=is_private,
            is_addressed=is_addressed,
            is_action=False,
            source=self,
            bot=self.bot,
        )
        await self.bot.dispatch(event)

    async def run(self) -> None:
        try:
            await self._client.start(self._cfg.token)
        except discord.LoginFailure as exc:
            log.error("[discord] login failed: %s", exc)

    async def stop(self) -> None:
        await self._client.close()

    async def send_message(self, target: str, text: str) -> None:
        chan = await self._resolve(target)
        if chan is None:
            log.warning("[discord] cannot resolve target %s", target)
            return
        # discord enforces 2000 chars / message; split conservatively.
        for chunk in _chunks(text, 1900):
            await chan.send(chunk)

    async def send_action(self, target: str, text: str) -> None:
        # Discord has no /me; emit italic for parity.
        await self.send_message(target, f"_{text}_")

    async def _resolve(self, target: str) -> discord.abc.Messageable | None:
        if target in self._channel_cache:
            return self._channel_cache[target]
        try:
            tid = int(target)
        except ValueError:
            return None
        chan: Any = self._client.get_channel(tid)
        if chan is None:
            try:
                user = await self._client.fetch_user(tid)
            except (discord.NotFound, discord.HTTPException):
                return None
            chan = await user.create_dm()
        if chan is not None:
            self._channel_cache[target] = chan
        result: discord.abc.Messageable | None = chan
        return result


def _chunks(text: str, n: int) -> list[str]:
    if not text:
        return [""]
    return [text[i : i + n] for i in range(0, len(text), n)]
