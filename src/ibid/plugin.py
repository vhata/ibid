"""Plugin framework.

A plugin is a subclass of :class:`Plugin` whose coroutine methods are
annotated with :func:`command`, :func:`match`, or :func:`always`. At dispatch
time the bot walks all loaded plugins, asks each handler whether it matches
the event, and awaits the handlers that do.

Handlers receive an :class:`ibid.event.Event` (and optional regex match
groups when using :func:`match`). They reply via ``event.reply(...)``.
"""

from __future__ import annotations

import inspect
import logging
import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ibid.event import Event

log = logging.getLogger("ibid.plugin")

HandlerFn = Callable[..., Awaitable[None]]


@dataclass(slots=True)
class HandlerSpec:
    """Metadata about a registered handler, set by the decorator."""

    kind: str  # "command" | "match" | "always"
    pattern: re.Pattern[str] | None
    aliases: tuple[str, ...]  # for "command" only
    addressed_only: bool  # require explicit addressing


def command(name: str, *aliases: str, addressed: bool = True) -> Callable[[HandlerFn], HandlerFn]:
    """Match an exact command word as the first token of the message body.

    Commands are case-insensitive. By default the bot must be explicitly
    addressed (``ibid: cmd`` or DM); pass ``addressed=False`` to listen to
    bare-channel use.
    """
    keys = (name, *aliases)
    pattern = re.compile(
        r"^\s*(?P<cmd>" + "|".join(re.escape(k) for k in keys) + r")\b\s*(?P<args>.*)$",
        re.IGNORECASE | re.DOTALL,
    )

    def decorate(fn: HandlerFn) -> HandlerFn:
        fn._ibid_handler = HandlerSpec(  # type: ignore[attr-defined]
            kind="command",
            pattern=pattern,
            aliases=keys,
            addressed_only=addressed,
        )
        return fn

    return decorate


def match(
    pattern: str | re.Pattern[str], *, addressed: bool = False
) -> Callable[[HandlerFn], HandlerFn]:
    """Match a regex anywhere in the event text.

    By default ``@match`` listens to all messages (passive watcher style —
    karma, URL grabber, seen). Pass ``addressed=True`` to require explicit
    addressing.
    """
    compiled = re.compile(pattern) if isinstance(pattern, str) else pattern

    def decorate(fn: HandlerFn) -> HandlerFn:
        fn._ibid_handler = HandlerSpec(  # type: ignore[attr-defined]
            kind="match",
            pattern=compiled,
            aliases=(),
            addressed_only=addressed,
        )
        return fn

    return decorate


def always(*, addressed: bool = False) -> Callable[[HandlerFn], HandlerFn]:
    """Call this handler for every event. Use sparingly."""

    def decorate(fn: HandlerFn) -> HandlerFn:
        fn._ibid_handler = HandlerSpec(  # type: ignore[attr-defined]
            kind="always",
            pattern=None,
            aliases=(),
            addressed_only=addressed,
        )
        return fn

    return decorate


class Plugin:
    """Plugin base class.

    Subclass and decorate coroutine methods. The constructor receives the
    bot instance, allowing plugins to read config or hit the DB.
    """

    #: Optional override; defaults to the module + class name.
    name: str = ""

    def __init__(self, bot: Any) -> None:  # quoted to avoid circular
        self.bot = bot
        if not self.name:
            self.name = f"{self.__class__.__module__}.{self.__class__.__name__}"
        self.log = logging.getLogger(f"ibid.plugin.{self.name}")

    async def setup(self) -> None:
        """Async one-shot setup (DB schema, prefetch, ...). Override as needed."""

    async def teardown(self) -> None:
        """Async teardown counterpart to :meth:`setup`."""

    def iter_handlers(self) -> Iterable[tuple[HandlerSpec, HandlerFn]]:
        """Yield ``(spec, bound_method)`` for every decorated coroutine."""
        for _name, member in inspect.getmembers(self, predicate=inspect.iscoroutinefunction):
            spec = getattr(member, "_ibid_handler", None)
            if spec is not None:
                yield spec, member


async def dispatch_event(
    event: Event,
    plugins: Iterable[Plugin],
    *,
    global_addressed_only: bool = False,
) -> None:
    """Walk plugins and invoke matching handlers.

    Each handler runs sequentially within a single event. Handlers raise
    their own errors; the caller (the bot core) catches and logs.
    """
    for plugin in plugins:
        for spec, fn in plugin.iter_handlers():
            should_address = spec.addressed_only or global_addressed_only
            if should_address and not event.is_addressed:
                continue

            if spec.kind == "always":
                await _safe_call(fn, event)
                continue

            assert spec.pattern is not None
            text = event.text if event.is_addressed else event.raw_text

            if spec.kind == "command":
                m = spec.pattern.match(text)
                if m is None:
                    continue
                await _safe_call(fn, event, m.group("args").strip())
            elif spec.kind == "match":
                m = spec.pattern.search(text)
                if m is None:
                    continue
                await _safe_call(fn, event, m)


async def _safe_call(fn: HandlerFn, *args: Any) -> None:
    sig = inspect.signature(fn)
    # Drop trailing optional args if the handler doesn't want them.
    accepted = len(sig.parameters)
    truncated = args[:accepted]
    try:
        await fn(*truncated)
    except Exception:
        log.exception("handler %s raised", getattr(fn, "__qualname__", fn))
