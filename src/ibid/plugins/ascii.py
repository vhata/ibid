"""ASCII art — figlet text rendering."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyfiglet

from ibid.plugin import Plugin, command

if TYPE_CHECKING:
    from ibid.event import Event

# Generated text gets sent in a code block on Discord and as multiline
# privmsgs on IRC. Keep things sane.
MAX_WIDTH = 80
DEFAULT_FONT = "standard"


class Ascii(Plugin):
    name = "ascii"

    @command("figlet")
    async def figlet(self, event: Event, args: str) -> None:
        """figlet <text> — render text as ASCII art."""
        text = args.strip()
        if not text:
            await event.reply("usage: figlet <text>")
            return
        try:
            rendered = pyfiglet.figlet_format(text[:60], font=DEFAULT_FONT, width=MAX_WIDTH)
        except pyfiglet.FontNotFound:
            await event.reply("figlet: default font missing — something's wrong with pyfiglet")
            return
        rendered = rendered.rstrip()
        if not rendered:
            await event.reply("(empty)")
            return
        # Wrap in a code block so Discord doesn't mangle the alignment.
        await event.reply(f"```\n{rendered}\n```", address=False)

    @command("figlet-fonts", "figfonts")
    async def fonts(self, event: Event, _args: str) -> None:
        """figlet-fonts — list a sample of available fonts."""
        fonts = sorted(pyfiglet.FigletFont.getFonts())[:30]
        await event.reply("first 30 fonts: " + ", ".join(fonts))

    @command("figlet-with")
    async def figlet_with(self, event: Event, args: str) -> None:
        """figlet-with <font> <text> — render with a specific figlet font."""
        head, _, text = args.partition(" ")
        font = head.strip()
        text = text.strip()
        if not font or not text:
            await event.reply("usage: figlet-with <font> <text>")
            return
        try:
            rendered = pyfiglet.figlet_format(text[:60], font=font, width=MAX_WIDTH).rstrip()
        except pyfiglet.FontNotFound:
            await event.reply(f"no font named {font!r}")
            return
        if not rendered:
            await event.reply("(empty)")
            return
        await event.reply(f"```\n{rendered}\n```", address=False)


PLUGINS = [Ascii]
