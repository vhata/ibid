"""Core plugin: help, version, ping."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

from ibid import __version__
from ibid.plugin import Plugin, command

if TYPE_CHECKING:
    from ibid.event import Event


class Core(Plugin):
    """Universal commands every bot needs."""

    name = "core"

    @command("ping")
    async def ping(self, event: Event, _args: str) -> None:
        await event.reply("pong")

    @command("version", "about")
    async def version(self, event: Event, _args: str) -> None:
        await event.reply(f"ibid {__version__}")

    @command("help")
    async def help_cmd(self, event: Event, args: str) -> None:
        topic = args.strip().lower()
        if not topic:
            names = sorted(self._discover_commands(event))
            await event.reply(
                "available commands: " + ", ".join(names) + "\n"
                "say `help <name>` for details on one."
            )
            return

        for plugin in event.bot.plugins:
            for spec, fn in plugin.iter_handlers():
                if spec.kind != "command":
                    continue
                if topic in {alias.lower() for alias in spec.aliases}:
                    doc = inspect.getdoc(fn) or "(no help text)"
                    aliases = ", ".join(sorted(spec.aliases))
                    await event.reply(f"{aliases}: {doc}")
                    return
        await event.reply(f"no command named {topic!r}", address=True)

    def _discover_commands(self, event: Event) -> set[str]:
        out: set[str] = set()
        for plugin in event.bot.plugins:
            for spec, _fn in plugin.iter_handlers():
                if spec.kind == "command":
                    out.update(spec.aliases)
        return out


PLUGINS = [Core]
