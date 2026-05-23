# ibid

A modern, async, plugin-driven chat bot — Discord-first, IRC alongside.
Born 2008, rewritten for 2026.

The original ibid was a multi-protocol Twisted-based bot with dozens of
plugins, written for Python 2.x. This rewrite preserves the spirit
(plugin-driven, factoid-centric, hackable) on a Python 3.12+ async
foundation with modern tooling. The legacy source is kept under `legacy/`
for reference and is no longer wired into the build.

## Features

- **Discord** (primary) — `discord.py` 2.x, mentions / `!cmd` prefix / DMs
  all count as addressing
- **IRC** (alongside) — async client with TLS, SASL PLAIN, auto-reconnect
- Plugin system with `@command`, `@match`, and `@always` decorators
- Per-event async SQLAlchemy 2.x sessions; SQLite by default
- TOML config validated by Pydantic
- Legacy MySQL importer for ibid 0.2 data (factoids, karma, seen, memos)
- Bundled plugins:
  - `factoid` — `remember X is Y`, `X?`, `forget X`, `search X`
  - `karma` — `thing++` / `thing--` with reason tracking
  - `seen` — last-seen tracker per nick/channel
  - `memo` — leave a message for a nick, delivered on next speak
  - `calc` — safe arithmetic evaluator (handles `2+3*4`, `sqrt(2)`, ...)
  - `choose` — `choose a, b or c`, `coin`, `roll 2d20`
  - `url` — fetches `<title>` of pasted URLs
  - `core` — addressing, help, version
  - `strings` — `hex`, `base64`, `rot13`, `md5`/`sha256`, `urlencode`, ...
  - `ascii` — `figlet <text>` (ASCII art via pyfiglet)
  - `insult` — `insult <person>` (Shakespearean abuse generator)
  - `quotes` — `addquote`, `quote`, `searchquote`, `delquote`
  - `convert` — `convert 5 miles to km`, `convert 100 USD to GBP`
  - `geography` — `coords <place>`, `timezone <place>` (OSM Nominatim)
  - `remind` — `remind me in 5 minutes about X` (survives restarts)
  - `websearch` — `search <query>` (DuckDuckGo Instant Answer API)

## Quickstart (Discord)

1. Create a bot at <https://discord.com/developers/applications>.
   Enable the **Message Content** privileged intent.
2. Copy the token; you'll paste it into `ibid.toml`.
3. Invite the bot to your server with the `bot` scope and at least
   `Send Messages` + `Read Message History`.

```bash
# Python 3.12+ required
uv sync                          # or: pip install -e '.[dev]'
cp ibid.example.toml ibid.toml   # edit token, plugin list, etc.
python -m ibid run               # connect and listen
```

In Discord, talk to the bot one of three ways:
- DM it directly — every message is treated as a command
- `@ibid hello` — at-mention
- `!hello` — command prefix (configurable; see `command_prefixes`)

## Quickstart (IRC, alongside Discord or solo)

Add `[[networks]]` blocks to `ibid.toml`:

```toml
[[networks]]
name = "libera"
host = "irc.libera.chat"
port = 6697
tls = true
channels = ["#ibid-test"]
# Optional: sasl_user / sasl_pass / nickserv_password / password
```

Address with `ibid: cmd`, `ibid, cmd`, `!cmd`, or DM.

## Configuration

See `ibid.example.toml` for the full schema with comments. The minimum
viable Discord config is:

```toml
[bot]
nick = "ibid"

[discord]
token = "your-bot-token-here"
```

## Importing legacy data

Drop a `mysqldump` of the old ibid schema next to the bot:

```bash
python -m ibid.import_legacy spinach-YYYYMMDD-HHMMSS.sql \
    --db sqlite+aiosqlite:///ibid.db
```

This copies factoids, karma, seen records, and undelivered memos into the
new schema. Replays the verb split (`"are red"` → verb `"are"`, value
`"red"`), preserves `<reply>`/`<action>` markers, and dedupes
collisions on `(network, nick)` for seen.

## Plugins

A plugin is a module under `src/ibid/plugins/`. It exports `PLUGINS` —
a list of `Plugin` subclasses with handler methods decorated for dispatch:

```python
from ibid.plugin import Plugin, command, match
from ibid.event import Event

class Hello(Plugin):
    name = "hello"

    @command("hello")
    async def greet(self, event: Event, args: str) -> None:
        await event.reply(f"hi {event.nick}")

    @match(r"\bbye\b")
    async def farewell(self, event: Event, m) -> None:
        await event.reply("cheers!")

PLUGINS = [Hello]
```

Add the module to `BUNDLED` in `src/ibid/plugins/__init__.py`. Disable
shipped plugins with `[plugins] disabled = [...]` in `ibid.toml`.

## Development

```bash
uv sync
ruff check . && ruff format --check .
mypy src tests
pytest
```

CI (GitHub Actions) runs the same checks on Python 3.12 and 3.13.

## Legacy

The pre-2026 Python 2.7 codebase is preserved under `legacy/`. It is not
buildable as-is on modern Python, but the git history through `b8bdd307`
shows its full evolution from 2008–2011. Many of the legacy plugins
targeted services that no longer exist (USACO, gcalc, SOAPpy-based RPC,
SILC chat) or have radically changed APIs.

## License

MIT (see `COPYING`). Copyright 2008–2026 the Ibid Developers.
