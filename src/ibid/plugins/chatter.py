"""Canned conversational responses — greetings, thanks, praise, criticism.

Ported from the legacy ``factoid.StaticFactoid`` processor. These are
the bot-personality lines that don't rely on stored factoids: things
that should "just work" the moment the bot is in a channel.

Each rule has a list of regex patterns and a list of response templates.
The first rule whose patterns match the event text wins; one response is
chosen at random and ``$who``-substituted via the factoid plugin's
substituter so the same placeholder format works everywhere.
"""

from __future__ import annotations

import random
import re
from typing import TYPE_CHECKING

from ibid.plugin import Plugin, always
from ibid.plugins.factoid import _substitute

if TYPE_CHECKING:
    from ibid.event import Event


# The original ibid set. Ordered roughly by likelihood so the bot's voice
# stays varied — "hi" gets a different rotation each time.
GREETINGS = (
    "lo", "ello", "hello", "hi", "hi there", "howdy", "hey", "heya",
    "hiya", "hola", "salut", "bonjour", "sup", "wussup", "hoezit",
    "wotcha", "wotcher", "yo", "word", "good day", "wasup", "wassup",
    "howzit", "howsit", "buon giorno", "hoe lyk it", "hoe gaan dit",
    "good morning", "morning", "afternoon", "evening",
)

# Build a single regex covering every greeting plus its space-stripped form
# (so "good morning" matches "goodmorning" too).
_GREETING_ALTS = sorted(
    {*GREETINGS, *(g.replace(" ", "") for g in GREETINGS if " " in g)},
    key=len, reverse=True,  # longest-match-first
)
_GREETING_RE = re.compile(r"\b(" + "|".join(re.escape(g) for g in _GREETING_ALTS) + r")\b",
                          re.IGNORECASE)


RULES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    # Greetings — match a greeting word, respond with a random greeting.
    (_GREETING_RE, GREETINGS),
    # Reward — "botsnack" / "bot snack"
    (
        re.compile(r"\bbot(\s+|-)?snack\b", re.IGNORECASE),
        ("thanks, $who", "$who: thankyou!", ":)"),
    ),
    # Praise — "good bot", "good girl", "you rock", "you rule", "you are cool"
    (
        re.compile(
            r"\bgood(\s+fuckin[']?g?)?\s+(lad|bo(t|y)|g([ui]|r+)rl)\b"
            r"|\byou\s+(rock|rocks|rewl|rule|are\s+so+\s+co+l)\b",
            re.IGNORECASE,
        ),
        ("thanks, $who", "$who: thankyou!", ":)"),
    ),
    # Thanks — "thanks", "thank you", "ta", "shot"
    (
        re.compile(r"\bthank(s|\s*you)\b|^\s*ta\s*$|^\s*shot\s*$", re.IGNORECASE),
        (
            "no problem, $who", "$who: my pleasure", "sure thing, $who",
            "no worries, $who", "$who: np", "no probs, $who",
            "$who: no problemo", "$who: not at all",
        ),
    ),
    # Criticism — "bad bot", "stupid bot", "botsmack" / "botslap"
    (
        re.compile(
            r"\b((kak|bad|st(u|oo)pid|dumb)(\s+fuckin[']?g?)?\s+(bo(t|y)|g([ui]|r+)rl))"
            r"|(bot(\s|-)?s(mack|lap))\b",
            re.IGNORECASE,
        ),
        ("*whimper*", "sorry, $who :(", ":(", "*cringe*"),
    ),
)


class Chatter(Plugin):
    name = "chatter"

    @always(addressed=True)
    async def respond(self, event: Event) -> None:
        text = event.text.strip()
        if not text:
            return
        for pattern, responses in RULES:
            if pattern.search(text):
                line = _substitute(random.choice(responses), event)
                await event.reply(line, address=False)
                return


PLUGINS = [Chatter]
