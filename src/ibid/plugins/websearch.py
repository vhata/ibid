"""Web search — DuckDuckGo Instant Answer API.

DDG's IA API returns an instant answer / abstract / topic list for a
query without needing an API key. We surface the best thing available
in this order: AnswerType + Answer, AbstractText (+ AbstractURL), the
first RelatedTopic, or a definition. No scraping — just JSON.

For raw "the bot can search" energy without the rate-limit games of
Google CSE etc., this is the right 2026 default.
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import TYPE_CHECKING, Any

import httpx

from ibid.plugin import Plugin, command

if TYPE_CHECKING:
    from ibid.event import Event

log = logging.getLogger("ibid.plugin.websearch")


async def ddg_search(
    query: str,
    *,
    timeout: float,
    ua: str,
) -> tuple[str, str | None] | None:
    """Return ``(answer_text, source_url_or_none)`` or ``None`` on miss."""
    params = {
        "q": query,
        "format": "json",
        "no_redirect": "1",
        "no_html": "1",
        "skip_disambig": "1",
    }
    url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(params)
    headers = {"user-agent": ua, "accept": "application/json"}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("DDG search failed: %s", exc)
        return None

    if data.get("Answer"):
        kind = data.get("AnswerType", "")
        prefix = f"[{kind}] " if kind else ""
        return f"{prefix}{data['Answer']}", data.get("AbstractURL") or None

    if data.get("AbstractText"):
        return str(data["AbstractText"]), data.get("AbstractURL") or None

    if data.get("Definition"):
        src = data.get("DefinitionURL") or data.get("DefinitionSource") or None
        return str(data["Definition"]), src

    topics = data.get("RelatedTopics") or []
    for topic in topics:
        # Top-level topics have Text; categories have a nested Topics list.
        text = topic.get("Text")
        if text:
            return str(text), topic.get("FirstURL") or None

    return None


class WebSearch(Plugin):
    name = "websearch"

    @command("search", "ddg", "g", addressed=True)
    async def search(self, event: Event, args: str) -> None:
        """search <query> — DuckDuckGo instant answer / abstract."""
        # Note: ``search`` also exists in the factoid plugin (substring search
        # over stored factoids). The factoid one only fires inside an
        # addressed context with a factoid match, so this remains useful.
        query = args.strip()
        if not query:
            await event.reply("usage: search <query>")
            return
        result = await ddg_search(
            query,
            timeout=event.bot.config.http.timeout_seconds,
            ua=event.bot.config.http.user_agent,
        )
        if result is None:
            await event.reply(
                f"no instant answer for {query!r} — "
                f"https://duckduckgo.com/?q={urllib.parse.quote(query)}",
            )
            return
        text, src = result
        if src:
            await event.reply(f"{text} — {src}")
        else:
            await event.reply(text)


PLUGINS = [WebSearch]
