"""Base class for transport sources."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ibid.core import Bot


class Source(abc.ABC):
    """Abstract source: a single chat-transport connection.

    Subclasses implement the transport (IRC connection, Discord gateway,
    in-memory test harness, ...) and call :meth:`Bot.dispatch` for every
    user-originated message.
    """

    name: str

    def __init__(self, name: str, bot: Bot) -> None:
        self.name = name
        self.bot = bot

    @abc.abstractmethod
    async def run(self) -> None:
        """Block until the source is stopped (handle reconnects internally)."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Disconnect cleanly."""

    @abc.abstractmethod
    async def send_message(self, target: str, text: str) -> None:
        """Send a regular message to ``target`` (channel or user id)."""

    async def send_notice(self, target: str, text: str) -> None:
        """Send a notice (out-of-band, no-reply-expected). Defaults to send_message."""
        await self.send_message(target, text)

    async def send_action(self, target: str, text: str) -> None:
        """Send an action / emote. Default formats as ``*text*``."""
        await self.send_message(target, f"*{text}*")
