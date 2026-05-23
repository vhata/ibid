"""Event — the per-message context plugins receive.

A source (IRC, Discord, ...) wraps each user-originated message in an
:class:`Event` that normalises the bits plugins actually want (who,
where, what, addressed?) and offers a convenient :meth:`reply` shortcut.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ibid.core import Bot
    from ibid.sources.base import Source

# Matches ``nick: text`` or ``nick, text`` (the colon may be ``:`` or ``,``).
_ADDRESS_RE = re.compile(r"^(?P<nick>[^\s,:]+)[:,]\s*(?P<rest>.*)$", re.DOTALL)


@dataclass(slots=True)
class Event:
    """A single dispatchable user message."""

    network: str  # source name (network identifier)
    nick: str  # display name of the sender
    user: str | None  # ident (IRC) or None on transports without one
    host: str | None  # host (IRC) or None on transports without one
    target: str  # channel name, or our nick / user id for direct
    raw_text: str  # body before any addressing strip
    text: str  # body with addressing prefix stripped, if addressed
    is_private: bool  # direct/DM rather than channel
    is_addressed: bool  # explicitly directed at the bot (mention, nick prefix, DM)
    is_action: bool  # /me-style action
    source: Source  # source instance for replies
    bot: Bot  # bot core (for DB, dispatcher access)

    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def reply_target(self) -> str:
        """Channel for public; sender for DMs."""
        return self.nick if self.is_private else self.target

    async def reply(self, text: str, *, address: bool = True, notice: bool = False) -> None:
        """Send a response to wherever this event came from.

        In channels the reply is prefixed with the sender's nick unless
        ``address=False``. DMs are never prefixed. ``notice=True`` uses the
        transport's notice channel (IRC NOTICE; fallback elsewhere).
        """
        payload = f"{self.nick}: {text}" if address and not self.is_private else text
        if notice:
            await self.source.send_notice(self.reply_target, payload)
        else:
            await self.source.send_message(self.reply_target, payload)

    async def action(self, text: str) -> None:
        await self.source.send_action(self.reply_target, text)


def detect_addressing(
    text: str, our_nicks: list[str], prefixes: list[str] | None = None
) -> tuple[bool, str]:
    """Return ``(is_addressed, stripped_text)``.

    Recognises three forms of addressing:
      1. A leading command prefix (``!cmd``) — strips the prefix.
      2. ``nick: text`` or ``nick, text`` — strips the nick + separator.
      3. Plain text — not addressed; returned trimmed.

    ``our_nicks`` is checked case-insensitively. Prefixes match
    case-sensitively (they're usually punctuation).
    """
    stripped = text.lstrip()
    if prefixes:
        for prefix in prefixes:
            if stripped.startswith(prefix):
                return True, stripped[len(prefix) :].strip()

    m = _ADDRESS_RE.match(text)
    if not m:
        return False, text.strip()
    candidate = m.group("nick").lower()
    if candidate in {n.lower() for n in our_nicks}:
        return True, m.group("rest").strip()
    return False, text.strip()
