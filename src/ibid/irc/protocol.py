"""IRC wire protocol — message parsing and formatting.

Implements RFC 1459/2812 messages plus IRCv3 message tags. Pure functions
and dataclasses; no I/O. The client layer (`ibid.irc.client`) wraps this
with a transport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self


@dataclass(frozen=True, slots=True)
class Prefix:
    """Source of a message: nickname, user, host (or a server name as nick)."""

    nick: str
    user: str | None = None
    host: str | None = None

    @classmethod
    def parse(cls, raw: str) -> Self:
        """Parse a prefix without its leading ``:``.

        IRC prefixes have three forms:
          - ``servername``                 → nick="servername"
          - ``nick!user@host``             → all three set
          - ``nick@host`` / ``nick``       → user omitted
        """
        nick = raw
        user: str | None = None
        host: str | None = None
        if "@" in nick:
            nick, host = nick.split("@", 1)
        if "!" in nick:
            nick, user = nick.split("!", 1)
        return cls(nick=nick, user=user, host=host)


@dataclass(slots=True)
class Message:
    """A parsed IRC line.

    ``params`` includes both middle and trailing parameters; the trailing
    parameter (the one allowed to contain spaces) is always the last entry.
    Formatting decides which parameters need the leading ``:`` based on
    content, not on a flag here.
    """

    command: str
    params: list[str] = field(default_factory=list)
    prefix: Prefix | None = None
    tags: dict[str, str] = field(default_factory=dict)


# IRCv3 tag-value escape map (the wire form is the *key*, decoded is the *value*).
_TAG_UNESCAPE = {
    r"\:": ";",
    r"\s": " ",
    r"\\": "\\",
    r"\r": "\r",
    r"\n": "\n",
}


def _unescape_tag_value(raw: str) -> str:
    """Reverse the IRCv3 message-tag escape sequence."""
    out: list[str] = []
    i = 0
    while i < len(raw):
        if raw[i] == "\\" and i + 1 < len(raw):
            esc = raw[i : i + 2]
            if esc in _TAG_UNESCAPE:
                out.append(_TAG_UNESCAPE[esc])
            else:
                # Unknown escape → drop the backslash, keep the char (per spec).
                out.append(raw[i + 1])
            i += 2
        else:
            out.append(raw[i])
            i += 1
    return "".join(out)


def _parse_tags(raw: str) -> dict[str, str]:
    """Parse the ``@key=val;key2=val2`` block (no leading ``@``)."""
    tags: dict[str, str] = {}
    if not raw:
        return tags
    for pair in raw.split(";"):
        if not pair:
            continue
        if "=" in pair:
            key, value = pair.split("=", 1)
            tags[key] = _unescape_tag_value(value)
        else:
            tags[pair] = ""
    return tags


def parse_message(line: str) -> Message:
    """Parse a single IRC line into a :class:`Message`.

    Strips a trailing CR/LF if present. Empty lines raise ``ValueError``.
    """
    stripped = line.rstrip("\r\n")
    if not stripped.strip():
        raise ValueError("empty IRC line")

    tags: dict[str, str] = {}
    prefix: Prefix | None = None
    rest = stripped

    if rest.startswith("@"):
        space = rest.find(" ")
        if space == -1:
            raise ValueError(f"message has only tags, no command: {line!r}")
        tags = _parse_tags(rest[1:space])
        rest = rest[space + 1 :].lstrip(" ")

    if rest.startswith(":"):
        space = rest.find(" ")
        if space == -1:
            raise ValueError(f"message has prefix but no command: {line!r}")
        prefix = Prefix.parse(rest[1:space])
        rest = rest[space + 1 :].lstrip(" ")

    if not rest:
        raise ValueError(f"message has no command: {line!r}")

    # Trailing param starts with ``:`` and may contain anything (including spaces).
    trailing: str | None = None
    if " :" in rest:
        head, trailing = rest.split(" :", 1)
    elif rest.startswith(":"):
        # Pure trailing with no middle params, e.g. ``PRIVMSG :foo`` — rare but legal.
        head, trailing = "", rest[1:]
    else:
        head = rest

    tokens = [tok for tok in head.split(" ") if tok]
    if not tokens:
        raise ValueError(f"message has no command after prefix: {line!r}")

    command = tokens[0].upper()
    params = tokens[1:]
    if trailing is not None:
        params.append(trailing)

    return Message(command=command, params=params, prefix=prefix, tags=tags)


def _needs_trailing_marker(param: str, is_last: bool) -> bool:
    """A parameter must be the trailing one (with ``:``) if it contains a space,
    is empty, or starts with ``:``. Non-last params can never carry these.
    """
    if not is_last:
        return False
    return param == "" or " " in param or param.startswith(":")


def format_message(msg: Message) -> str:
    """Serialise a :class:`Message` back to a single IRC line ending in CRLF.

    Raises ``ValueError`` if any parameter contains a CR or LF, or if any
    middle parameter is empty or contains a space (those have to ride in the
    trailing slot).
    """
    parts: list[str] = []
    if msg.prefix is not None:
        # Round-trip only emits the prefix verbatim; servers — not clients —
        # set prefixes on outbound messages.
        prefix = msg.prefix.nick
        if msg.prefix.user is not None:
            prefix += f"!{msg.prefix.user}"
        if msg.prefix.host is not None:
            prefix += f"@{msg.prefix.host}"
        parts.append(f":{prefix}")

    parts.append(msg.command.upper())

    for i, p in enumerate(msg.params):
        if "\r" in p or "\n" in p:
            raise ValueError(f"IRC parameter contains CR/LF: {p!r}")
        last = i == len(msg.params) - 1
        if _needs_trailing_marker(p, last):
            parts.append(f":{p}")
        elif not last and (p == "" or " " in p):
            raise ValueError(f"non-trailing IRC parameter cannot contain space or be empty: {p!r}")
        else:
            parts.append(p)

    return " ".join(parts) + "\r\n"
