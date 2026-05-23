"""Unit and currency conversion.

Units delegate to ``pint`` (handles SI, imperial, time, energy, ...).
Currency hits ``open.er-api.com`` (free, no key required) and is cached
for an hour so we don't hammer the upstream.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Any

import httpx
import pint

from ibid.plugin import Plugin, command

if TYPE_CHECKING:
    from ibid.event import Event

log = logging.getLogger("ibid.plugin.convert")

# Match "convert <number> <from-unit> to <to-unit>" with the verb optional.
_UNIT_RE = re.compile(
    r"^\s*(?:convert\s+)?(?P<value>-?\d+(?:[.,]\d+)?)\s*(?P<src>[\w\s/.\-^*²³]+?)\s+"
    r"(?:to|in|into)\s+(?P<dst>[\w\s/.\-^*²³]+?)\s*$",
    re.IGNORECASE,
)
# Match "<amount> <CCY> to <CCY>" (3-letter codes).
_CURRENCY_RE = re.compile(
    r"^\s*(?P<amount>-?\d+(?:[.,]\d+)?)\s+(?P<src>[A-Za-z]{3})\s+"
    r"(?:to|in|into)\s+(?P<dst>[A-Za-z]{3})\s*$",
)

# pint's UnitRegistry isn't generic-parameterised on the user side, so we
# pin the annotation with Any to keep mypy happy under --strict.
_UREG: Any = pint.UnitRegistry()
_UREG.formatter.default_format = "~P"  # pretty short-form

_CURRENCY_CACHE: dict[str, tuple[float, dict[str, float]]] = {}
_CACHE_TTL = 3600.0


async def _get_rates(base: str, http_timeout: float, ua: str) -> dict[str, float]:
    """Return a {currency_code: rate-vs-base} dict, cached for ``_CACHE_TTL``."""
    base = base.upper()
    now = time.monotonic()
    cached = _CURRENCY_CACHE.get(base)
    if cached is not None and now - cached[0] < _CACHE_TTL:
        return cached[1]

    url = f"https://open.er-api.com/v6/latest/{base}"
    headers = {"user-agent": ua}
    async with httpx.AsyncClient(headers=headers, timeout=http_timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    if data.get("result") != "success":
        raise RuntimeError(f"upstream rates error: {data.get('error-type', 'unknown')}")
    rates: dict[str, float] = data["rates"]
    _CURRENCY_CACHE[base] = (now, rates)
    return rates


class Convert(Plugin):
    name = "convert"

    @command("convert")
    async def convert(self, event: Event, args: str) -> None:
        """convert <amount> <unit> to <unit> — unit or currency conversion."""
        text = args.strip()
        if not text:
            await event.reply(
                "usage: convert 5 miles to km   OR   convert 100 USD to GBP",
            )
            return

        # Currency first — it's the more specific format.
        cm = _CURRENCY_RE.match(text)
        if cm is not None:
            await self._currency(
                event,
                float(cm.group("amount").replace(",", ".")),
                cm.group("src"),
                cm.group("dst"),
            )
            return

        um = _UNIT_RE.match("convert " + text)
        if um is None:
            await event.reply("can't parse — try: convert 5 miles to km")
            return
        try:
            value = float(um.group("value").replace(",", "."))
        except ValueError:
            await event.reply("bad number")
            return
        src = um.group("src").strip()
        dst = um.group("dst").strip()
        try:
            quantity = _UREG.Quantity(value, src)
            result = quantity.to(dst)
        except pint.errors.UndefinedUnitError as exc:
            await event.reply(f"i don't know that unit: {exc}")
        except pint.errors.DimensionalityError as exc:
            await event.reply(f"can't convert: {exc}")
        except Exception as exc:
            await event.reply(f"conversion failed: {exc}")
        else:
            magnitude = result.magnitude
            rendered = f"{magnitude:.6g}" if isinstance(magnitude, float) else str(magnitude)
            await event.reply(f"{rendered} {result.units:~P}")

    async def _currency(self, event: Event, amount: float, src: str, dst: str) -> None:
        src = src.upper()
        dst = dst.upper()
        try:
            rates = await _get_rates(
                src, event.bot.config.http.timeout_seconds, event.bot.config.http.user_agent
            )
        except httpx.HTTPError as exc:
            await event.reply(f"currency lookup failed: {exc}")
            return
        except (RuntimeError, KeyError, ValueError) as exc:
            await event.reply(f"currency lookup failed: {exc}")
            return
        if dst not in rates:
            await event.reply(f"unknown currency code: {dst}")
            return
        converted = amount * rates[dst]
        await event.reply(f"{amount:.2f} {src} = {converted:.2f} {dst}")


PLUGINS = [Convert]
