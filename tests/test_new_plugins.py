"""Tests for the second-batch plugins."""

from __future__ import annotations

from conftest import BotFixture


class TestStrings:
    async def test_hex_roundtrip(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!hex hello")
        await src.inject("!unhex 68656c6c6f")
        replies = [t for _, _, t in src.sent]
        assert any("68656c6c6f" in r for r in replies), replies
        assert any(r.endswith("hello") for r in replies), replies

    async def test_base64_roundtrip(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!base64 hello")
        await src.inject("!unbase64 aGVsbG8=")
        replies = [t for _, _, t in src.sent]
        assert any("aGVsbG8=" in r for r in replies), replies
        assert any(r.endswith("hello") for r in replies), replies

    async def test_rot13_involution(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!rot13 hello")
        replies = [t for _, _, t in src.sent]
        assert any(r.endswith("uryyb") for r in replies), replies

    async def test_md5(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!md5 hello")
        replies = [t for _, _, t in src.sent]
        # md5("hello") = 5d41402abc4b2a76b9719d911017c592
        assert any("5d41402abc4b2a76b9719d911017c592" in r for r in replies), replies

    async def test_sha256(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!sha256 hello")
        replies = [t for _, _, t in src.sent]
        # sha256("hello") starts with 2cf24d
        assert any(
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824" in r for r in replies
        ), replies

    async def test_urlencode(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!urlencode hello world")
        replies = [t for _, _, t in src.sent]
        assert any("hello%20world" in r for r in replies), replies

    async def test_length(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!length hello")
        replies = [t for _, _, t in src.sent]
        assert any("5 char" in r and "5 byte" in r for r in replies), replies


class TestAscii:
    async def test_figlet_basic(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!figlet hi")
        replies = [t for _, _, t in src.sent]
        # Output should be a code block containing rendered ASCII.
        assert any(r.startswith("```\n") and r.endswith("\n```") for r in replies), replies

    async def test_figlet_empty(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!figlet")
        replies = [t for _, _, t in src.sent]
        assert any("usage" in r for r in replies), replies


class TestInsult:
    async def test_targeted(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!insult bob")
        replies = [t for _, _, t in src.sent]
        # The insult line must mention the target somewhere.
        assert any("bob" in r for r in replies), replies

    async def test_empty(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!insult")
        replies = [t for _, _, t in src.sent]
        assert any("who?" in r for r in replies), replies


def test_insult_build() -> None:
    """The insult builder must always include the target verbatim."""
    from ibid.plugins.insult import build_insult

    for _ in range(50):
        line = build_insult("alice")
        assert "alice" in line


class TestQuotes:
    async def test_add_and_show(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject('!addquote "I came, I saw, I conquered"')
        await src.inject("!quote #1")
        replies = [t for _, _, t in src.sent]
        assert any("conquered" in r for r in replies), replies

    async def test_search(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!addquote the rain in Spain")
        await src.inject("!addquote falls mainly on the plain")
        src.sent.clear()
        await src.inject("!searchquote rain")
        replies = [t for _, _, t in src.sent]
        assert any("rain" in r for r in replies), replies

    async def test_count(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!quotecount")
        replies = [t for _, _, t in src.sent]
        assert any("0 quote" in r for r in replies), replies

    async def test_delete(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!addquote disposable")
        src.sent.clear()
        await src.inject("!delquote #1")
        await src.inject("!quote #1")
        replies = [t for _, _, t in src.sent]
        assert any("no quote" in r for r in replies), replies


class TestConvertUnits:
    """Unit conversion via pint — local, no network."""

    async def test_miles_to_km(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!convert 1 mile to km")
        replies = [t for _, _, t in src.sent]
        # 1 mile = 1.60934 km
        assert any("1.60934" in r or "1.609" in r for r in replies), replies

    async def test_celsius_to_fahrenheit(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!convert 100 degC to degF")
        replies = [t for _, _, t in src.sent]
        assert any("212" in r for r in replies), replies

    async def test_unknown_unit(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!convert 5 zorks to qux")
        replies = [t for _, _, t in src.sent]
        assert any("unit" in r.lower() for r in replies), replies


class TestRemindParser:
    """We can't easily test the firing without a clock, but verify parsing."""

    async def test_remind_me_in_5_minutes(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!remind me in 5 minutes to take a break", nick="alice")
        replies = [t for _, _, t in src.sent]
        assert any("will ping you" in r for r in replies), replies

    async def test_remind_unparseable(self, bot: BotFixture) -> None:
        _, src = bot
        await src.inject("!remind me in galactic eons to do something")
        replies = [t for _, _, t in src.sent]
        # Either an unparseable-time message or a usage hint is OK.
        assert any("can't" in r or "usage" in r for r in replies), replies


class TestWebSearchModule:
    """No HTTP — just smoke-test the module imports."""

    def test_module_imports(self) -> None:
        from ibid.plugins import websearch

        assert websearch.WebSearch is not None


class TestGeographyModule:
    """No network — just smoke-test the imports."""

    def test_module_imports(self) -> None:
        from ibid.plugins import geography

        assert geography.Geography is not None
