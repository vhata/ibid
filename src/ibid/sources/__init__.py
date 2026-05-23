"""Transport-agnostic sources (IRC, Discord, ...).

Plugins talk to a ``Source`` instead of an IRC client directly so they
work across networks. Each concrete source is responsible for:
  - connecting / reconnecting to its protocol
  - turning incoming protocol messages into :class:`ibid.event.Event` objects
    and dispatching them through the bot
  - sending messages, notices, and actions out
"""

from ibid.sources.base import Source

__all__ = ["Source"]
