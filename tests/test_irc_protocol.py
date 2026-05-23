from __future__ import annotations

import pytest

from ibid.irc.protocol import Message, format_message, parse_message


class TestParseMessage:
    def test_simple_command(self) -> None:
        msg = parse_message("PING :server.example")
        assert msg.command == "PING"
        assert msg.params == ["server.example"]
        assert msg.prefix is None
        assert msg.tags == {}

    def test_lowercase_command_normalised(self) -> None:
        msg = parse_message("ping :server.example")
        assert msg.command == "PING"

    def test_numeric_command_preserved(self) -> None:
        msg = parse_message(":server 001 alice :Welcome to the network alice")
        assert msg.command == "001"
        assert msg.params == ["alice", "Welcome to the network alice"]

    def test_prefix_user_full(self) -> None:
        msg = parse_message(":alice!user@host.example PRIVMSG #ch :hi")
        assert msg.prefix is not None
        assert msg.prefix.nick == "alice"
        assert msg.prefix.user == "user"
        assert msg.prefix.host == "host.example"
        assert msg.command == "PRIVMSG"
        assert msg.params == ["#ch", "hi"]

    def test_prefix_servername(self) -> None:
        msg = parse_message(":irc.example.org NOTICE * :*** Looking up your hostname...")
        assert msg.prefix is not None
        assert msg.prefix.nick == "irc.example.org"
        assert msg.prefix.user is None
        assert msg.prefix.host is None

    def test_prefix_nick_only(self) -> None:
        msg = parse_message(":alice JOIN #ch")
        assert msg.prefix is not None
        assert msg.prefix.nick == "alice"
        assert msg.prefix.user is None
        assert msg.prefix.host is None

    def test_prefix_nick_host_no_user(self) -> None:
        msg = parse_message(":alice@host PRIVMSG #ch :hi")
        assert msg.prefix is not None
        assert msg.prefix.nick == "alice"
        assert msg.prefix.user is None
        assert msg.prefix.host == "host"

    def test_trailing_with_spaces(self) -> None:
        msg = parse_message("PRIVMSG #ch :hello there friend")
        assert msg.params == ["#ch", "hello there friend"]

    def test_trailing_with_colon_inside(self) -> None:
        msg = parse_message("PRIVMSG #ch :http://example.com/path")
        assert msg.params == ["#ch", "http://example.com/path"]

    def test_empty_trailing(self) -> None:
        msg = parse_message("PRIVMSG #ch :")
        assert msg.params == ["#ch", ""]

    def test_no_trailing(self) -> None:
        msg = parse_message("JOIN #channel")
        assert msg.params == ["#channel"]

    def test_multiple_middle_params(self) -> None:
        msg = parse_message("MODE #ch +o-v alice bob")
        assert msg.params == ["#ch", "+o-v", "alice", "bob"]

    def test_ircv3_tags(self) -> None:
        msg = parse_message("@time=2024-01-01T00:00:00.000Z;account=alice :alice PRIVMSG #ch :hi")
        assert msg.tags == {"time": "2024-01-01T00:00:00.000Z", "account": "alice"}
        assert msg.command == "PRIVMSG"
        assert msg.params == ["#ch", "hi"]

    def test_ircv3_tag_no_value(self) -> None:
        msg = parse_message("@bot :alice PRIVMSG #ch :hi")
        assert msg.tags == {"bot": ""}

    def test_ircv3_tag_escaped_value(self) -> None:
        msg = parse_message(r"@x=a\:b\sc\\d\r\ne :n!u@h PING :pong")
        assert msg.tags == {"x": "a;b c\\d\r\ne"}

    def test_crlf_stripped(self) -> None:
        assert parse_message("PING :x\r\n").params == ["x"]
        assert parse_message("PING :x\n").params == ["x"]
        assert parse_message("PING :x\r").params == ["x"]

    def test_extra_spaces_between_args(self) -> None:
        msg = parse_message("PRIVMSG    #ch  :  spaced  ")
        assert msg.params == ["#ch", "  spaced  "]

    def test_empty_line_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_message("")

    def test_only_whitespace_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_message("   ")

    def test_only_tags_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_message("@tag=value")


class TestFormatMessage:
    def test_format_simple(self) -> None:
        # Single safe param emits without the trailing `:` marker.
        out = format_message(Message(command="PING", params=["server.example"]))
        assert out == "PING server.example\r\n"

    def test_format_no_trailing_when_safe(self) -> None:
        out = format_message(Message(command="JOIN", params=["#channel"]))
        assert out == "JOIN #channel\r\n"

    def test_format_multiple_params_trailing_only_for_last(self) -> None:
        out = format_message(Message(command="PRIVMSG", params=["#ch", "hi there"]))
        assert out == "PRIVMSG #ch :hi there\r\n"

    def test_format_trailing_when_param_starts_with_colon(self) -> None:
        out = format_message(Message(command="PRIVMSG", params=["#ch", ":weird"]))
        assert out == "PRIVMSG #ch ::weird\r\n"

    def test_format_trailing_when_param_empty(self) -> None:
        out = format_message(Message(command="PRIVMSG", params=["#ch", ""]))
        assert out == "PRIVMSG #ch :\r\n"

    def test_format_command_uppercased(self) -> None:
        out = format_message(Message(command="ping", params=["x"]))
        assert out == "PING x\r\n"

    def test_format_rejects_newlines_in_params(self) -> None:
        with pytest.raises(ValueError):
            format_message(Message(command="PRIVMSG", params=["#ch", "two\nlines"]))

    def test_format_rejects_only_trailing_with_space(self) -> None:
        out = format_message(Message(command="QUIT", params=["my reason"]))
        assert out == "QUIT :my reason\r\n"


class TestRoundTrip:
    @pytest.mark.parametrize(
        "raw",
        [
            "PING :server.example",
            ":alice!user@host PRIVMSG #ch :hello world",
            "PRIVMSG #ch :http://example.com/path?x=1",
            "MODE #ch +o-v alice bob",
            "JOIN #channel",
            ":server 001 alice :Welcome to the network",
        ],
    )
    def test_round_trip(self, raw: str) -> None:
        msg = parse_message(raw)
        rendered = format_message(msg).rstrip("\r\n")
        # Re-parse the rendered form and compare structural equality.
        again = parse_message(rendered)
        assert again.prefix == msg.prefix
        assert again.command == msg.command
        assert again.params == msg.params
