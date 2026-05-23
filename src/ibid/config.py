"""Typed configuration loaded from a TOML file.

The bot's runtime config is just a TOML document validated by Pydantic.
Defaults are conservative — ``ibid.example.toml`` documents the full schema.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HTTPConfig(BaseModel):
    """Shared HTTP-client settings used by URL-fetching plugins."""

    model_config = ConfigDict(extra="forbid")
    timeout_seconds: float = 8.0
    user_agent: str = "ibid/0.3 (+https://github.com/vhata/ibid)"
    max_bytes: int = 524288


class BotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nick: str = "ibid"
    realname: str = "ibid bot"
    username: str = "ibid"
    nick_aliases: list[str] = Field(default_factory=lambda: ["bot"])
    # Commands prefixed with one of these are always treated as addressed.
    # Discord users often prefer ``!cmd``; IRC users often prefer ``ibid:``.
    command_prefixes: list[str] = Field(default_factory=lambda: ["!"])
    addressed_only: bool = False
    db_url: str = "sqlite+aiosqlite:///ibid.db"


class PluginsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disabled: list[str] = Field(default_factory=list)


class DiscordConfig(BaseModel):
    """Discord transport. One bot identity per token."""

    model_config = ConfigDict(extra="forbid")
    token: str
    # Optional guild allow-list (guild snowflakes). Empty = all guilds.
    guilds: list[int] = Field(default_factory=list)
    # Optional channel allow-list (channel snowflakes). Empty = all channels.
    channels: list[int] = Field(default_factory=list)
    # If true, only mentions / DMs are dispatched (no passive @match).
    addressed_only: bool | None = None


class NetworkConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    host: str
    port: int = 6697
    tls: bool = True
    channels: list[str] = Field(default_factory=list)
    password: str | None = None
    sasl_user: str | None = None
    sasl_pass: str | None = None
    nickserv_password: str | None = None
    reconnect_initial_delay: float = 5.0
    reconnect_max_delay: float = 300.0
    ping_interval: float = 60.0
    pong_timeout: float = 30.0

    @field_validator("port")
    @classmethod
    def _port_in_range(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("port must be between 1 and 65535")
        return v


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bot: BotConfig = Field(default_factory=BotConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    http: HTTPConfig = Field(default_factory=HTTPConfig)
    networks: list[NetworkConfig] = Field(default_factory=list)
    discord: DiscordConfig | None = None

    @classmethod
    def load(cls, path: str | Path) -> Config:
        """Load and validate config from a TOML file.

        Two environment-variable overrides are applied after TOML loading
        so secrets and host-specific paths don't have to live in the file:

          - ``IBID_DISCORD_TOKEN`` — sets ``[discord] token`` (creates the
            ``[discord]`` block if the file didn't have one).
          - ``IBID_DB_URL`` — overrides ``[bot] db_url``.
        """
        p = Path(path)
        with p.open("rb") as fh:
            raw: dict[str, Any] = tomllib.load(fh)
        _apply_env_overrides(raw)
        return cls.model_validate(raw)


def _apply_env_overrides(raw: dict[str, Any]) -> None:
    discord_token = os.environ.get("IBID_DISCORD_TOKEN")
    if discord_token:
        section = raw.setdefault("discord", {})
        section["token"] = discord_token

    db_url = os.environ.get("IBID_DB_URL")
    if db_url:
        section = raw.setdefault("bot", {})
        section["db_url"] = db_url
