"""IRC source — wraps :class:`ibid.irc.client.IRCClient` as a :class:`Source`."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from ibid.event import Event, detect_addressing
from ibid.irc.client import IRCClient, IRCConfig
from ibid.irc.protocol import Message
from ibid.sources.base import Source

if TYPE_CHECKING:
    from ibid.config import NetworkConfig
    from ibid.core import Bot

log = logging.getLogger("ibid.sources.irc")

_ACTION_RE = re.compile(r"^\x01ACTION (.*)\x01$", re.DOTALL)


class IRCSource(Source):
    """IRC transport. One instance per network."""

    def __init__(self, net: NetworkConfig, bot: Bot) -> None:
        super().__init__(net.name, bot)
        self._client = IRCClient(
            IRCConfig(
                name=net.name,
                host=net.host,
                port=net.port,
                tls=net.tls,
                nick=bot.config.bot.nick,
                realname=bot.config.bot.realname,
                username=bot.config.bot.username,
                channels=net.channels,
                password=net.password,
                sasl_user=net.sasl_user,
                sasl_pass=net.sasl_pass,
                nickserv_password=net.nickserv_password,
                reconnect_initial_delay=net.reconnect_initial_delay,
                reconnect_max_delay=net.reconnect_max_delay,
                ping_interval=net.ping_interval,
                pong_timeout=net.pong_timeout,
            ),
            self._on_message,
        )

    async def run(self) -> None:
        await self._client.run()

    async def stop(self) -> None:
        await self._client.quit("shutting down")

    async def send_message(self, target: str, text: str) -> None:
        await self._client.send_privmsg(target, text)

    async def send_notice(self, target: str, text: str) -> None:
        await self._client.send_notice(target, text)

    async def send_action(self, target: str, text: str) -> None:
        await self._client.send_action(target, text)

    async def _on_message(self, _client: IRCClient, msg: Message) -> None:
        if msg.command != "PRIVMSG" or len(msg.params) < 2:
            return
        if msg.prefix is None:
            return

        target, body = msg.params[0], msg.params[1]
        is_action = False
        action_match = _ACTION_RE.match(body)
        if action_match:
            body = action_match.group(1)
            is_action = True

        is_private = not target.startswith(("#", "&", "+", "!"))
        our_nicks = [self._client.nick, *self.bot.config.bot.nick_aliases]
        is_addressed, stripped = detect_addressing(
            body,
            our_nicks,
            self.bot.config.bot.command_prefixes,
        )
        if is_private:
            is_addressed = True
            if not stripped:
                stripped = body.strip()

        event = Event(
            network=self.name,
            nick=msg.prefix.nick,
            user=msg.prefix.user,
            host=msg.prefix.host,
            target=target,
            raw_text=body,
            text=stripped,
            is_private=is_private,
            is_addressed=is_addressed,
            is_action=is_action,
            source=self,
            bot=self.bot,
        )
        await self.bot.dispatch(event)
