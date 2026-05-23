"""Shared test fixtures: an in-memory Bot wired up with a FakeSource.

The FakeSource lets tests inject incoming messages and read back the
outbound traffic the plugins generated — no real IRC or Discord required.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ibid.config import BotConfig, Config, PluginsConfig
from ibid.core import Bot
from ibid.event import Event
from ibid.sources.base import Source

if TYPE_CHECKING:
    pass

# Type alias used by individual test files for the `bot` fixture's payload.
BotFixture = tuple[Bot, "FakeSource"]


class FakeSource(Source):
    """Source that captures sends in a list and accepts injected events."""

    def __init__(self, bot: Bot, *, name: str = "test") -> None:
        super().__init__(name, bot)
        self.sent: list[tuple[str, str, str]] = []  # (kind, target, text)

    async def run(self) -> None:
        # Idle until cancelled — tests drive incoming via inject().
        await asyncio.Event().wait()

    async def stop(self) -> None:
        pass

    async def send_message(self, target: str, text: str) -> None:
        self.sent.append(("message", target, text))

    async def send_notice(self, target: str, text: str) -> None:
        self.sent.append(("notice", target, text))

    async def send_action(self, target: str, text: str) -> None:
        self.sent.append(("action", target, text))

    async def inject(
        self,
        text: str,
        *,
        nick: str = "alice",
        channel: str = "#test",
        is_addressed: bool = False,
        is_private: bool = False,
    ) -> None:
        """Build an Event and run it through the dispatcher."""
        raw_text = text
        stripped = text
        # Mirror the addressing logic the real sources apply.
        if not is_private:
            for prefix in self.bot.config.bot.command_prefixes:
                if text.startswith(prefix):
                    stripped = text[len(prefix) :].strip()
                    is_addressed = True
                    break
            if not is_addressed:
                bot_nick = self.bot.config.bot.nick
                low = text.lower()
                for nick_alias in [bot_nick, *self.bot.config.bot.nick_aliases]:
                    pre = f"{nick_alias.lower()}: "
                    if low.startswith(pre):
                        stripped = text[len(pre) :].strip()
                        is_addressed = True
                        break

        if is_private:
            is_addressed = True

        event = Event(
            network=self.name,
            nick=nick,
            user=nick,
            host="test.local",
            target=nick if is_private else channel,
            raw_text=raw_text,
            text=stripped,
            is_private=is_private,
            is_addressed=is_addressed,
            is_action=False,
            source=self,
            bot=self.bot,
        )
        await self.bot.dispatch(event)


@pytest.fixture
async def bot(tmp_path: Path) -> AsyncIterator[tuple[Bot, FakeSource]]:
    """Yield a fully-set-up Bot plus an attached FakeSource.

    Uses a temp-file SQLite — ``:memory:`` gives each new connection its
    own database, which the multi-session plugin dispatch path won't tolerate.
    """
    db_path = tmp_path / "test.db"
    cfg = Config(
        bot=BotConfig(db_url=f"sqlite+aiosqlite:///{db_path}"),
        plugins=PluginsConfig(disabled=["url"]),  # url plugin makes real HTTP calls
    )
    bot = Bot(cfg)
    await bot.setup()
    source = FakeSource(bot)
    bot.sources.append(source)
    try:
        yield bot, source
    finally:
        await bot.db.close()
