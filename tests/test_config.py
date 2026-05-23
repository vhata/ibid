from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from ibid.config import Config


def write_toml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "ibid.toml"
    p.write_text(body, encoding="utf-8")
    return p


def test_minimal_config(tmp_path: Path) -> None:
    p = write_toml(tmp_path, "")
    cfg = Config.load(p)
    assert cfg.bot.nick == "ibid"
    assert cfg.networks == []


def test_full_config(tmp_path: Path) -> None:
    p = write_toml(
        tmp_path,
        """
[bot]
nick = "robot"
addressed_only = true

[plugins]
disabled = ["karma"]

[[networks]]
name = "libera"
host = "irc.libera.chat"
port = 6697
channels = ["#ibid-test"]
""",
    )
    cfg = Config.load(p)
    assert cfg.bot.nick == "robot"
    assert cfg.bot.addressed_only is True
    assert cfg.plugins.disabled == ["karma"]
    assert len(cfg.networks) == 1
    assert cfg.networks[0].channels == ["#ibid-test"]


def test_unknown_keys_rejected(tmp_path: Path) -> None:
    p = write_toml(tmp_path, "[bot]\nfrobnicate = true\n")
    with pytest.raises(ValidationError):
        Config.load(p)


def test_env_overrides_discord_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IBID_DISCORD_TOKEN", "from-env-secret")
    p = write_toml(tmp_path, "")
    cfg = Config.load(p)
    assert cfg.discord is not None
    assert cfg.discord.token == "from-env-secret"


def test_env_overrides_db_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IBID_DB_URL", "sqlite+aiosqlite:////data/ibid.db")
    p = write_toml(tmp_path, "")
    cfg = Config.load(p)
    assert cfg.bot.db_url == "sqlite+aiosqlite:////data/ibid.db"


def test_env_token_overrides_toml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IBID_DISCORD_TOKEN", "from-env")
    p = write_toml(
        tmp_path,
        """
[discord]
token = "from-toml"
""",
    )
    cfg = Config.load(p)
    assert cfg.discord is not None
    assert cfg.discord.token == "from-env"


def test_invalid_port_rejected(tmp_path: Path) -> None:
    p = write_toml(
        tmp_path,
        """
[[networks]]
name = "x"
host = "irc.example.org"
port = 0
""",
    )
    with pytest.raises(ValidationError):
        Config.load(p)
