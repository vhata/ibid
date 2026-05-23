"""Async IRC client.

Single-network client speaking IRC over a streaming transport (TLS or plain).
Hands every parsed message to a user-supplied async callback and exposes
``send_*`` helpers for the bot to talk back. Handles reconnect with
exponential backoff, idle-PING keepalives, and SASL PLAIN.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import random
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from ibid.irc.protocol import Message, format_message, parse_message

log = logging.getLogger("ibid.irc")

MessageHandler = Callable[["IRCClient", Message], Awaitable[None]]


@dataclass(slots=True)
class IRCConfig:
    """Connection-level settings for one IRC network."""

    name: str
    host: str
    port: int = 6697
    tls: bool = True
    nick: str = "ibid"
    realname: str = "ibid bot"
    username: str = "ibid"
    channels: list[str] = field(default_factory=list)
    password: str | None = None  # server PASS
    sasl_user: str | None = None
    sasl_pass: str | None = None
    nickserv_password: str | None = None
    reconnect_initial_delay: float = 5.0
    reconnect_max_delay: float = 300.0
    ping_interval: float = 60.0
    pong_timeout: float = 30.0


class IRCClient:
    """One IRC network connection.

    Use :meth:`run` to keep it alive with reconnect, or :meth:`run_once`
    for a single connection attempt (useful in tests).
    """

    def __init__(self, config: IRCConfig, handler: MessageHandler) -> None:
        self.config = config
        self.handler = handler
        self._writer: asyncio.StreamWriter | None = None
        self._connected = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._idle_ping_task: asyncio.Task[None] | None = None
        self._last_recv: float = 0.0
        self._stopping: bool = False
        self.nick: str = config.nick  # current nick (may change on collision)
        self._sasl_done = asyncio.Event()
        self._closed_event = asyncio.Event()

    # ------------------------------------------------------------------ public

    async def send_raw(self, msg: Message) -> None:
        """Send a fully-formed :class:`Message`. Caller handles escaping."""
        await self._connected.wait()
        line = format_message(msg).encode("utf-8", errors="replace")
        assert self._writer is not None
        async with self._send_lock:
            self._writer.write(line)
            await self._writer.drain()
        log.debug("[%s] >> %s", self.config.name, line.rstrip())

    async def send_privmsg(self, target: str, text: str) -> None:
        """Send ``text`` to a channel or nick, splitting long lines safely."""
        # IRC has a ~512-byte total-line limit; split conservatively per line.
        for line in text.splitlines() or [""]:
            await self.send_raw(Message(command="PRIVMSG", params=[target, line]))

    async def send_notice(self, target: str, text: str) -> None:
        for line in text.splitlines() or [""]:
            await self.send_raw(Message(command="NOTICE", params=[target, line]))

    async def send_action(self, target: str, text: str) -> None:
        # CTCP ACTION
        await self.send_privmsg(target, f"\x01ACTION {text}\x01")

    async def join(self, channel: str) -> None:
        await self.send_raw(Message(command="JOIN", params=[channel]))

    async def part(self, channel: str, reason: str = "") -> None:
        params = [channel] + ([reason] if reason else [])
        await self.send_raw(Message(command="PART", params=params))

    async def quit(self, reason: str = "bye") -> None:
        self._stopping = True
        with contextlib.suppress(ConnectionError, RuntimeError):
            await self.send_raw(Message(command="QUIT", params=[reason]))
        await self._close_transport()

    # ------------------------------------------------------------- lifecycle

    async def run(self) -> None:
        """Keep the connection alive across drops with exponential backoff."""
        delay = self.config.reconnect_initial_delay
        # mypy can't see through the concurrent mutation of self._stopping
        # by quit() — it narrows on every read. Treat the flag as opaque.
        while not self._stopping_flag():
            try:
                await self.run_once()
                if self._stopping_flag():
                    return
                log.info("[%s] disconnected cleanly; reconnecting", self.config.name)
            except (OSError, asyncio.IncompleteReadError, ssl.SSLError) as exc:
                log.warning("[%s] connection error: %s", self.config.name, exc)
            except Exception:
                log.exception("[%s] unexpected client error", self.config.name)
            if self._stopping_flag():
                return
            # Jitter prevents thundering herd against the server.
            sleep_for = delay * (0.5 + random.random())
            log.info("[%s] reconnecting in %.1fs", self.config.name, sleep_for)
            await asyncio.sleep(sleep_for)
            delay = min(delay * 2, self.config.reconnect_max_delay)

    def _stopping_flag(self) -> bool:
        return self._stopping

    async def run_once(self) -> None:
        """One connection lifecycle: connect, register, dispatch, until close."""
        ctx: ssl.SSLContext | None = None
        if self.config.tls:
            ctx = ssl.create_default_context()
        log.info(
            "[%s] connecting to %s:%d (tls=%s)",
            self.config.name,
            self.config.host,
            self.config.port,
            self.config.tls,
        )
        reader, writer = await asyncio.open_connection(
            host=self.config.host,
            port=self.config.port,
            ssl=ctx,
        )
        self._writer = writer
        self._connected.set()
        self._closed_event.clear()
        try:
            await self._register()
            self._idle_ping_task = asyncio.create_task(self._idle_ping_loop())
            await self._read_loop(reader)
        finally:
            if self._idle_ping_task is not None:
                self._idle_ping_task.cancel()
                self._idle_ping_task = None
            await self._close_transport()

    async def _close_transport(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            self._writer = None
        self._connected.clear()
        self._closed_event.set()

    # ------------------------------------------------------------- internals

    async def _register(self) -> None:
        c = self.config
        if c.password:
            await self.send_raw(Message(command="PASS", params=[c.password]))
        if c.sasl_user and c.sasl_pass:
            await self.send_raw(Message(command="CAP", params=["REQ", "sasl"]))
        await self.send_raw(Message(command="NICK", params=[c.nick]))
        await self.send_raw(Message(command="USER", params=[c.username, "0", "*", c.realname]))

    async def _idle_ping_loop(self) -> None:
        interval = self.config.ping_interval
        timeout = self.config.pong_timeout
        try:
            while not self._stopping:
                await asyncio.sleep(interval)
                now = asyncio.get_event_loop().time()
                if now - self._last_recv >= interval:
                    try:
                        await self.send_raw(Message(command="PING", params=["idle-ibid"]))
                    except (ConnectionError, RuntimeError):
                        return
                    await asyncio.sleep(timeout)
                    if asyncio.get_event_loop().time() - self._last_recv >= interval + timeout:
                        log.warning("[%s] ping timeout, closing", self.config.name)
                        await self._close_transport()
                        return
        except asyncio.CancelledError:
            pass

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        while True:
            raw = await reader.readline()
            if not raw:
                # EOF
                return
            self._last_recv = asyncio.get_event_loop().time()
            try:
                text = raw.decode("utf-8", errors="replace")
                msg = parse_message(text)
            except ValueError as exc:
                log.warning("[%s] bad line: %s (%r)", self.config.name, exc, raw)
                continue
            log.debug("[%s] << %s", self.config.name, text.rstrip())
            await self._handle_internal(msg)
            try:
                await self.handler(self, msg)
            except Exception:
                log.exception("[%s] handler raised", self.config.name)

    async def _handle_internal(self, msg: Message) -> None:
        """Handle protocol-level messages before user dispatch."""
        if msg.command == "PING":
            # Echo whatever they sent in their PING.
            await self.send_raw(Message(command="PONG", params=list(msg.params)))
        elif msg.command == "CAP" and len(msg.params) >= 2 and msg.params[1] == "ACK":
            if "sasl" in msg.params[-1]:
                await self.send_raw(Message(command="AUTHENTICATE", params=["PLAIN"]))
        elif msg.command == "AUTHENTICATE" and msg.params == ["+"]:
            await self._send_sasl_plain()
        elif msg.command in {"903", "904", "905", "906", "907"}:
            # SASL terminal numerics; finish the cap negotiation regardless.
            await self.send_raw(Message(command="CAP", params=["END"]))
            self._sasl_done.set()
        elif msg.command == "001":
            log.info("[%s] registered as %s", self.config.name, msg.params[0])
            self.nick = msg.params[0]
            await self._post_register()
        elif msg.command == "433":
            # Nick collision — pick a fallback.
            alt = f"{self.config.nick}_"
            log.warning("[%s] nick in use, trying %s", self.config.name, alt)
            await self.send_raw(Message(command="NICK", params=[alt]))
            self.nick = alt
        elif msg.command == "NICK" and msg.prefix and msg.prefix.nick == self.nick:
            self.nick = msg.params[0]

    async def _send_sasl_plain(self) -> None:
        user = self.config.sasl_user or ""
        pw = self.config.sasl_pass or ""
        token = f"{user}\x00{user}\x00{pw}".encode()
        await self.send_raw(
            Message(command="AUTHENTICATE", params=[base64.b64encode(token).decode("ascii")])
        )

    async def _post_register(self) -> None:
        if self.config.nickserv_password and not (self.config.sasl_user and self.config.sasl_pass):
            await self.send_privmsg("NickServ", f"IDENTIFY {self.config.nickserv_password}")
        for ch in self.config.channels:
            await self.join(ch)
