"""String transforms — hex / base64 / rot13 / hash / urlencode."""

from __future__ import annotations

import base64
import binascii
import codecs
import hashlib
import urllib.parse
from typing import TYPE_CHECKING

from ibid.plugin import Plugin, command

if TYPE_CHECKING:
    from ibid.event import Event


class Strings(Plugin):
    name = "strings"

    @command("hex")
    async def to_hex(self, event: Event, args: str) -> None:
        """hex <text> — hex-encode UTF-8 bytes of <text>."""
        if not args:
            await event.reply("usage: hex <text>")
            return
        await event.reply(args.encode("utf-8").hex())

    @command("unhex", "fromhex")
    async def from_hex(self, event: Event, args: str) -> None:
        """unhex <hex> — decode a hex string to UTF-8 text."""
        text = args.strip().replace(" ", "")
        if not text:
            await event.reply("usage: unhex <hex>")
            return
        try:
            await event.reply(bytes.fromhex(text).decode("utf-8", errors="replace"))
        except ValueError as exc:
            await event.reply(f"not valid hex: {exc}")

    @command("base64", "b64")
    async def to_b64(self, event: Event, args: str) -> None:
        """base64 <text> — base64-encode."""
        if not args:
            await event.reply("usage: base64 <text>")
            return
        await event.reply(base64.b64encode(args.encode("utf-8")).decode("ascii"))

    @command("unbase64", "fromb64", "b64decode")
    async def from_b64(self, event: Event, args: str) -> None:
        """unbase64 <base64> — decode base64 to text."""
        text = args.strip()
        if not text:
            await event.reply("usage: unbase64 <base64>")
            return
        try:
            decoded = base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError) as exc:
            await event.reply(f"not valid base64: {exc}")
            return
        await event.reply(decoded.decode("utf-8", errors="replace"))

    @command("rot13")
    async def rot13(self, event: Event, args: str) -> None:
        """rot13 <text> — apply the rot13 cipher (involution)."""
        if not args:
            await event.reply("usage: rot13 <text>")
            return
        await event.reply(codecs.encode(args, "rot_13"))

    @command("urlencode", "url")
    async def urlencode(self, event: Event, args: str) -> None:
        """urlencode <text> — percent-encode for use in URLs."""
        if not args:
            await event.reply("usage: urlencode <text>")
            return
        await event.reply(urllib.parse.quote(args, safe=""))

    @command("urldecode")
    async def urldecode(self, event: Event, args: str) -> None:
        """urldecode <text> — reverse urlencode."""
        if not args:
            await event.reply("usage: urldecode <text>")
            return
        await event.reply(urllib.parse.unquote(args))

    @command("md5", "sha1", "sha256", "sha512")
    async def hash_cmd(self, event: Event, args: str) -> None:
        """md5/sha1/sha256/sha512 <text> — hex digest of UTF-8 bytes."""
        # The original command word lives in event.text — pull the first word.
        first = event.text.split(maxsplit=1)[0].lower()
        if first not in {"md5", "sha1", "sha256", "sha512"}:
            return
        if not args:
            await event.reply(f"usage: {first} <text>")
            return
        h = hashlib.new(first)
        h.update(args.encode("utf-8"))
        await event.reply(h.hexdigest())

    @command("upper")
    async def upper(self, event: Event, args: str) -> None:
        """upper <text> — uppercase."""
        await event.reply(args.upper() if args else "usage: upper <text>")

    @command("lower")
    async def lower(self, event: Event, args: str) -> None:
        """lower <text> — lowercase."""
        await event.reply(args.lower() if args else "usage: lower <text>")

    @command("reverse")
    async def reverse(self, event: Event, args: str) -> None:
        """reverse <text> — reverse the characters."""
        await event.reply(args[::-1] if args else "usage: reverse <text>")

    @command("length", "len")
    async def length(self, event: Event, args: str) -> None:
        """length <text> — count characters."""
        if not args:
            await event.reply("usage: length <text>")
            return
        await event.reply(f"{len(args)} char(s), {len(args.encode('utf-8'))} byte(s)")


PLUGINS = [Strings]
