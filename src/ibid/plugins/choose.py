"""Choose / decide — pick from a list, flip a coin, roll a die."""

from __future__ import annotations

import random
import re
from typing import TYPE_CHECKING

from ibid.plugin import Plugin, command

if TYPE_CHECKING:
    from ibid.event import Event

_OR_RE = re.compile(r"\s+or\s+|,\s*", re.IGNORECASE)
_DIE_RE = re.compile(r"^\s*(?P<count>\d+)?\s*d\s*(?P<sides>\d+)\s*$", re.IGNORECASE)


class Choose(Plugin):
    name = "choose"

    @command("choose", "pick", "decide")
    async def choose(self, event: Event, args: str) -> None:
        """choose <a>, <b>, or <c> — pick one at random."""
        opts = [o.strip() for o in _OR_RE.split(args) if o.strip()]
        if len(opts) < 2:
            await event.reply("give me at least two options")
            return
        await event.reply(random.choice(opts))

    @command("coin", "flip", addressed=True)
    async def coin(self, event: Event, _args: str) -> None:
        """coin — heads or tails."""
        await event.reply(random.choice(["heads", "tails"]))

    @command("roll", "dice")
    async def roll(self, event: Event, args: str) -> None:
        """roll [NdM] — roll N M-sided dice (default 1d6)."""
        spec = args.strip() or "1d6"
        m = _DIE_RE.match(spec)
        if not m:
            await event.reply("usage: roll [NdM]  e.g. 2d20")
            return
        count = int(m.group("count") or 1)
        sides = int(m.group("sides"))
        if not 1 <= count <= 100 or not 2 <= sides <= 10_000:
            await event.reply("be reasonable")
            return
        rolls = [random.randint(1, sides) for _ in range(count)]
        if count == 1:
            await event.reply(str(rolls[0]))
        else:
            await event.reply(f"{rolls} = {sum(rolls)}")


PLUGINS = [Choose]
