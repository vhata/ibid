"""URL info — when a link is posted, fetch its ``<title>`` and report.

Limits bytes downloaded, honours redirects, gives up gracefully on errors.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import httpx
from selectolax.parser import HTMLParser

from ibid.plugin import Plugin, match

if TYPE_CHECKING:
    from ibid.event import Event

log = logging.getLogger("ibid.plugin.urlinfo")

_URL_RE = re.compile(r"https?://[^\s<>\"\']+", re.IGNORECASE)


class URLInfo(Plugin):
    name = "url"

    @match(_URL_RE)
    async def grab(self, event: Event, m: re.Match[str]) -> None:
        url = m.group(0)
        title = await fetch_title(
            url,
            timeout=event.bot.config.http.timeout_seconds,
            ua=event.bot.config.http.user_agent,
            max_bytes=event.bot.config.http.max_bytes,
        )
        if title:
            await event.reply(f"title: {title}", address=False)


async def fetch_title(
    url: str,
    *,
    timeout: float,
    ua: str,
    max_bytes: int,
) -> str | None:
    """Return the trimmed ``<title>`` of ``url``, or ``None`` on any failure.

    Limits the body read to ``max_bytes`` to avoid ingesting huge pages.
    """
    headers = {"user-agent": ua, "accept": "text/html, application/xhtml+xml"}
    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            async with client.stream("GET", url) as resp:
                ctype = resp.headers.get("content-type", "")
                if "html" not in ctype.lower():
                    return None
                chunks: list[bytes] = []
                read = 0
                async for chunk in resp.aiter_bytes(chunk_size=4096):
                    chunks.append(chunk)
                    read += len(chunk)
                    if read >= max_bytes:
                        break
                body = b"".join(chunks).decode("utf-8", errors="replace")
    except (httpx.HTTPError, ValueError):
        return None

    tree = HTMLParser(body)
    title_node = tree.css_first("title")
    if title_node is None:
        return None
    title = (title_node.text() or "").strip()
    title = re.sub(r"\s+", " ", title)
    if not title:
        return None
    if len(title) > 200:
        title = title[:197] + "..."
    return title


PLUGINS = [URLInfo]
