"""Bot core — wires config, sources, plugins, and the DB together."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from ibid.config import Config
from ibid.db import Database
from ibid.plugin import Plugin, dispatch_event
from ibid.plugins import load_plugins
from ibid.sources.base import Source
from ibid.sources.irc import IRCSource

if TYPE_CHECKING:
    from ibid.event import Event

log = logging.getLogger("ibid.core")


class Bot:
    """Top-level orchestrator. One instance per running bot process."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.db = Database(config.bot.db_url)
        self.sources: list[Source] = []
        self.plugins: list[Plugin] = []

    async def setup(self) -> None:
        """Wire plugins, sources, and the DB schema. Must run before :meth:`run`."""
        # Load plugins first so their models are registered against ``Base``,
        # then create the schema so per-plugin ``setup()`` can hit the DB.
        self.plugins = load_plugins(self, self.config.plugins.disabled)
        await self.db.create_all()
        for plugin in self.plugins:
            await plugin.setup()

        for net in self.config.networks:
            self.sources.append(IRCSource(net, self))

        if self.config.discord is not None:
            # Lazy import — keeps discord.py optional at import time.
            from ibid.sources.discord_source import DiscordSource

            self.sources.append(DiscordSource(self.config.discord, self))

        if not self.sources:
            log.warning("no sources configured — bot will start but won't connect anywhere")

    def get_source(self, name: str) -> Source | None:
        """Return the source named ``name`` if it's attached, else ``None``."""
        for s in self.sources:
            if s.name == name:
                return s
        return None

    async def dispatch(self, event: Event) -> None:
        """Run an event through every loaded plugin's handlers."""
        await dispatch_event(
            event,
            self.plugins,
            global_addressed_only=self.config.bot.addressed_only,
        )

    async def run(self) -> None:
        """Run all sources concurrently until cancelled."""
        if not self.sources:
            # Idle forever so the process stays up for inspection / tests.
            await asyncio.Event().wait()
            return

        tasks = [asyncio.create_task(s.run(), name=f"source:{s.name}") for s in self.sources]
        try:
            await asyncio.gather(*tasks)
        finally:
            for plugin in self.plugins:
                try:
                    await plugin.teardown()
                except Exception:
                    log.exception("teardown failed for %s", plugin.name)
            await self.db.close()

    async def stop(self) -> None:
        """Stop all sources cleanly."""
        for s in self.sources:
            try:
                await s.stop()
            except Exception:
                log.exception("stop failed for %s", s.name)
