"""Addressing detection — the prefix/nick strip that decides commands."""

from __future__ import annotations

from ibid.event import detect_addressing


class TestPrefixAddressing:
    def test_bang_prefix(self) -> None:
        addressed, text = detect_addressing("!ping", ["ibid"], ["!"])
        assert addressed is True
        assert text == "ping"

    def test_bang_prefix_with_args(self) -> None:
        addressed, text = detect_addressing("!remember sky is blue", ["ibid"], ["!"])
        assert addressed is True
        assert text == "remember sky is blue"

    def test_no_prefix_no_address(self) -> None:
        addressed, text = detect_addressing("hello there", ["ibid"], ["!"])
        assert addressed is False
        assert text == "hello there"

    def test_multiple_prefixes_first_match(self) -> None:
        addressed, text = detect_addressing(".ping", ["ibid"], ["!", "."])
        assert addressed is True
        assert text == "ping"


class TestNickAddressing:
    def test_colon_form(self) -> None:
        addressed, text = detect_addressing("ibid: hello", ["ibid"])
        assert addressed is True
        assert text == "hello"

    def test_comma_form(self) -> None:
        addressed, text = detect_addressing("ibid, hello", ["ibid"])
        assert addressed is True
        assert text == "hello"

    def test_case_insensitive(self) -> None:
        addressed, text = detect_addressing("IBID: hi", ["ibid"])
        assert addressed is True
        assert text == "hi"

    def test_alias(self) -> None:
        addressed, text = detect_addressing("bot: hi", ["ibid", "bot"])
        assert addressed is True
        assert text == "hi"

    def test_unknown_nick_not_addressed(self) -> None:
        addressed, text = detect_addressing("alice: hi", ["ibid"])
        assert addressed is False
        assert text == "alice: hi"


class TestDiscordSourceImports:
    """Confirm the Discord source module loads cleanly (CI-level smoke)."""

    def test_module_importable(self) -> None:
        from ibid.sources.discord_source import DiscordSource

        assert DiscordSource is not None

    def test_chunker(self) -> None:
        from ibid.sources.discord_source import _chunks

        assert _chunks("", 5) == [""]
        assert _chunks("hello", 5) == ["hello"]
        assert _chunks("helloworld", 5) == ["hello", "world"]
        assert _chunks("abcdefghi", 4) == ["abcd", "efgh", "i"]
