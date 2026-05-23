"""End-to-end-ish tests: drive the bot through its real plugin stack."""

from __future__ import annotations

from conftest import BotFixture


async def test_ping(bot: BotFixture) -> None:
    _, src = bot
    await src.inject("!ping")
    assert any("pong" in t for _, _, t in src.sent), src.sent


async def test_version(bot: BotFixture) -> None:
    _, src = bot
    await src.inject("!version")
    assert any(t.startswith("alice: ibid ") for _, _, t in src.sent), src.sent


class TestFactoid:
    async def test_remember_and_lookup(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!remember sky is blue")
        await src.inject("!sky?")
        # The lookup reply is not address-prefixed.
        replies = [t for _, _, t in src.sent]
        assert any("sky is blue" in r for r in replies), replies

    async def test_forget(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!remember sky is blue")
        await src.inject("!forget sky")
        await src.inject("!sky?")
        replies = [t for _, _, t in src.sent]
        assert any("don't know" in r for r in replies), replies

    async def test_search(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!remember sky is blue")
        await src.inject("!remember sea is also blue")
        await src.inject("!search blue")
        replies = [t for _, _, t in src.sent]
        joined = " ".join(replies)
        assert "sky" in joined and "sea" in joined, replies

    async def test_reply_verb_no_prefix(self, bot: BotFixture) -> None:
        b, src = bot
        # The `<reply>` verb means: respond with just the value, no key prefix.
        # We inject through the storage layer so we can pick the verb.
        async with b.db.session() as sess:
            from ibid.plugins.factoid import Factoid, FactoidValue

            f = Factoid(key="hello")
            f.values.append(FactoidValue(verb="<reply>", value="hi there", author="t"))
            sess.add(f)
        src.sent.clear()
        await src.inject("!hello?")
        replies = [t for _, _, t in src.sent]
        assert any(r == "hi there" for r in replies), replies

    async def test_bare_lookup_matches_addressed_message(self, bot: BotFixture) -> None:
        """Addressed messages that match a factoid key verbatim should fire."""
        b, src = bot
        async with b.db.session() as sess:
            from ibid.plugins.factoid import Factoid, FactoidValue

            f = Factoid(key="hi")
            f.values.append(FactoidValue(verb="<reply>", value="howdy partner", author="t"))
            sess.add(f)
        src.sent.clear()
        # No "?", no command — just an addressed bare word.
        await src.inject("!hi")
        replies = [t for _, _, t in src.sent]
        assert any(r == "howdy partner" for r in replies), replies

    async def test_who_substitution(self, bot: BotFixture) -> None:
        """``$who`` in a stored value should resolve to the speaker's nick."""
        b, src = bot
        async with b.db.session() as sess:
            from ibid.plugins.factoid import Factoid, FactoidValue

            f = Factoid(key="bye")
            f.values.append(FactoidValue(verb="<reply>", value="cheers $who", author="t"))
            sess.add(f)
        src.sent.clear()
        await src.inject("!bye?", nick="alice")
        replies = [t for _, _, t in src.sent]
        assert any("cheers alice" in r for r in replies), replies

    async def test_dollar_literal_left_alone(self, bot: BotFixture) -> None:
        """``$100`` (and other digit-led tokens) must NOT be substituted."""
        b, src = bot
        async with b.db.session() as sess:
            from ibid.plugins.factoid import Factoid, FactoidValue

            f = Factoid(key="prize")
            f.values.append(FactoidValue(verb="<reply>", value="$100", author="t"))
            sess.add(f)
        src.sent.clear()
        await src.inject("!prize?")
        replies = [t for _, _, t in src.sent]
        assert any(r == "$100" for r in replies), replies

    async def test_bare_lookup_silent_on_miss_unique(self, bot: BotFixture) -> None:
        """A bare-key miss must NOT emit 'i don't know' (the ? form does)."""
        _, src = bot
        await src.inject("!asdfqwerzxcv")  # nothing-like-a-known-greeting
        replies = [t for _, _, t in src.sent]
        assert not any("don't know" in r for r in replies), replies


class TestChatter:
    async def test_hi_gets_greeting(self, bot: BotFixture) -> None:
        from ibid.plugins.chatter import GREETINGS

        _, src = bot
        await src.inject("!hi")
        replies = [t for _, _, t in src.sent]
        # One of the canned greetings should appear in the reply.
        assert any(any(g in r for g in GREETINGS) for r in replies), replies

    async def test_botsnack_thanks(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!botsnack", nick="alice")
        replies = [t for _, _, t in src.sent]
        assert any("thanks" in r.lower() or ":)" in r for r in replies), replies

    async def test_thank_you(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!thank you")
        replies = [t for _, _, t in src.sent]
        # Acceptance set: any of the canned "you're welcome" responses.
        assert any(
            any(s in r.lower() for s in ("no problem", "pleasure", "sure thing",
                                          "no worries", "problemo", "not at all", "np"))
            for r in replies
        ), replies

    async def test_chatter_does_not_fire_on_unrelated(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!asdf qwer")
        # No reply at all from chatter (or anything else); the test is that
        # nothing greeting-like was sent.
        replies = [t for _, _, t in src.sent]
        from ibid.plugins.chatter import GREETINGS

        assert not any(any(g in r for g in GREETINGS) for r in replies), replies


class TestKarma:
    async def test_increment_and_show(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("tea++ # warming")
        await src.inject("tea++")
        await src.inject("tea--")
        src.sent.clear()
        await src.inject("!karma tea")
        replies = [t for _, _, t in src.sent]
        assert any("tea: 1" in r for r in replies), replies

    async def test_self_vote_blocked(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("alice++", nick="alice")
        replies = [t for _, _, t in src.sent]
        assert any("nice try" in r for r in replies), replies


class TestSeen:
    async def test_record_and_lookup(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("hello world", nick="bob")
        src.sent.clear()
        await src.inject("!seen bob")
        replies = [t for _, _, t in src.sent]
        assert any("bob" in r and "hello world" in r for r in replies), replies


class TestMemo:
    async def test_leave_and_deliver(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!tell carol hello when you get back", nick="alice")
        # Now carol speaks.
        src.sent.clear()
        await src.inject("hi everyone", nick="carol")
        replies = [t for _, _, t in src.sent]
        assert any("memo from alice" in r and "hello when you get back" in r for r in replies), (
            replies
        )


class TestCalc:
    async def test_basic(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!calc 2 + 3 * 4")
        replies = [t for _, _, t in src.sent]
        assert any("14" in r for r in replies), replies

    async def test_division_by_zero(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!calc 1/0")
        replies = [t for _, _, t in src.sent]
        assert any("division by zero" in r for r in replies), replies

    async def test_auto_calc_when_addressed(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!2 + 2")
        replies = [t for _, _, t in src.sent]
        assert any(r.endswith("4") for r in replies), replies


class TestChoose:
    async def test_choose(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!choose red, green or blue")
        replies = [t for _, _, t in src.sent]
        last = replies[-1]
        # Reply is prefixed "alice: <choice>".
        assert any(c in last for c in ("red", "green", "blue")), last
