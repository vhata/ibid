"""Geography — coordinates + timezone for a named place.

Uses ``geopy`` against OpenStreetMap's Nominatim service (free, no key)
for geocoding, and ``timezonefinder`` (pure-Python tz lookup from
lat/long) for timezone resolution. Nominatim rate-limits to 1 req/sec
per User-Agent — we set a polite UA per the config and don't burst.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder

from ibid.plugin import Plugin, command

if TYPE_CHECKING:
    from ibid.event import Event

log = logging.getLogger("ibid.plugin.geography")
_TF = TimezoneFinder()


def _build_geocoder(ua: str) -> Nominatim:
    return Nominatim(user_agent=ua, timeout=8)


class Geography(Plugin):
    name = "geography"

    @command("coords", "coordinates", "where")
    async def coords(self, event: Event, args: str) -> None:
        """coords <place> — look up latitude/longitude."""
        place = args.strip()
        if not place:
            await event.reply("usage: coords <place>")
            return
        loc = await self._lookup(place, event.bot.config.http.user_agent)
        if loc is None:
            await event.reply(f"can't find {place!r}")
            return
        await event.reply(
            f"{loc.address}: {loc.latitude:.4f}, {loc.longitude:.4f}",
        )

    @command("timezone", "tz")
    async def timezone(self, event: Event, args: str) -> None:
        """timezone <place> — local time, UTC offset, timezone name."""
        place = args.strip()
        if not place:
            await event.reply("usage: timezone <place>")
            return
        loc = await self._lookup(place, event.bot.config.http.user_agent)
        if loc is None:
            await event.reply(f"can't find {place!r}")
            return
        tz_name = _TF.timezone_at(lat=loc.latitude, lng=loc.longitude)
        if tz_name is None:
            await event.reply(f"{loc.address}: no timezone (open water?)")
            return
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            await event.reply(f"{loc.address}: unknown tz {tz_name!r}")
            return
        now = datetime.now(tz)
        await event.reply(
            f"{loc.address}: {now.strftime('%Y-%m-%d %H:%M')} {tz_name} "
            f"(UTC{now.strftime('%z')[:3]}:{now.strftime('%z')[3:]})",
        )

    async def _lookup(self, place: str, ua: str):  # type: ignore[no-untyped-def]
        geocoder = _build_geocoder(ua)
        try:
            # geopy is sync; run it in a worker so we don't block the loop.
            return await asyncio.to_thread(geocoder.geocode, place)
        except (GeocoderTimedOut, GeocoderUnavailable) as exc:
            self.log.warning("geocoder error: %s", exc)
            return None


PLUGINS = [Geography]
