"""Import legacy ibid data from a MySQL dump.

Reads a ``mysqldump``-style ``.sql`` file (the format the spinach instance
shipped in) and copies factoids/karma/seen/memos into the new schema.

Run with::

    python -m ibid.import_legacy spinach-20151117-115729.sql --db sqlite+aiosqlite:///ibid.db

The parser is small but pragmatic — it understands MySQL string escapes
(``\\'``, ``\\n``, ``\\t``, ``\\\\``, etc.) and multi-row ``INSERT`` syntax. It
does not parse the schema; it trusts that the columns are in the canonical
order this dump uses.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from ibid.db import Database
from ibid.plugins.factoid import Factoid, FactoidValue
from ibid.plugins.karma import Karma
from ibid.plugins.memo import Memo
from ibid.plugins.seen import SeenRow

log = logging.getLogger("ibid.import")

KNOWN_VERBS = ("is", "are", "was", "were", "has", "have", "does", "can", "should", "would")


# ---------------------------------------------------------------- parsing

# Locate ``INSERT INTO `table` VALUES (...),(...),... ;`` blocks. We
# stream over the file so we never hold the whole dump in memory twice.
_INSERT_HEAD = re.compile(r"^INSERT INTO `([^`]+)` VALUES\s*", re.IGNORECASE)


def _unescape(s: str) -> str:
    """Reverse MySQL's string escapes inside a SQL string literal."""
    out: list[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            mapped = {
                "n": "\n",
                "r": "\r",
                "t": "\t",
                "0": "\x00",
                "\\": "\\",
                "'": "'",
                '"': '"',
                "b": "\b",
                "Z": "\x1a",
            }.get(n, n)
            out.append(mapped)
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _parse_values(payload: str) -> Iterator[list[Any]]:
    """Yield each tuple from an INSERT VALUES payload.

    ``payload`` looks like ``(1,'foo','b\\'ar',NULL),(2,'x',NULL,NULL)``.
    We hand-roll the tokeniser because regex-on-strings-with-escapes is a
    quick route to grief.
    """
    i = 0
    n = len(payload)
    while i < n:
        # Skip leading whitespace, commas between tuples.
        while i < n and payload[i] in " ,\t\r\n":
            i += 1
        if i >= n:
            break
        if payload[i] != "(":
            # End of statement (``;`` or trailing whitespace).
            break
        i += 1  # past '('

        row: list[Any] = []
        while True:
            # Skip leading whitespace inside the tuple.
            while i < n and payload[i] in " \t":
                i += 1
            c = payload[i]
            if c == "'":
                # quoted string
                i += 1
                start = i
                buf: list[str] = []
                while i < n:
                    if payload[i] == "\\" and i + 1 < n:
                        buf.append(payload[i : i + 2])
                        i += 2
                        continue
                    if payload[i] == "'":
                        break
                    buf.append(payload[i])
                    i += 1
                row.append(_unescape("".join(buf)))
                if i < n and payload[i] == "'":
                    i += 1  # closing quote
                _ = start  # for debugging if needed
            elif c == "N" and payload[i : i + 4] == "NULL":
                row.append(None)
                i += 4
            elif c == "(" or c == ")":
                # End of tuple.
                pass
            else:
                # numeric / unquoted literal
                start = i
                while i < n and payload[i] not in ",)":
                    i += 1
                tok = payload[start:i].strip()
                if not tok:
                    pass
                elif tok in ("TRUE", "FALSE"):
                    row.append(tok == "TRUE")
                else:
                    try:
                        if "." in tok or "e" in tok or "E" in tok:
                            row.append(float(tok))
                        else:
                            row.append(int(tok))
                    except ValueError:
                        row.append(tok)
            # Skip separator.
            while i < n and payload[i] in " \t":
                i += 1
            if i < n and payload[i] == ",":
                i += 1
                continue
            if i < n and payload[i] == ")":
                i += 1
                yield row
                break
            # Malformed; bail to the next tuple.
            break


def iter_table_rows(path: Path, table: str) -> Iterator[list[Any]]:
    """Yield raw row tuples for ``table`` from a MySQL dump."""
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        buffer = ""
        in_insert = False
        for line in fh:
            if not in_insert:
                m = _INSERT_HEAD.match(line)
                if m and m.group(1) == table:
                    in_insert = True
                    # Trim ``INSERT INTO \`table\` VALUES`` prefix to leave tuples.
                    buffer = line[m.end() :]
                continue
            buffer += line
            if buffer.rstrip().endswith(";"):
                yield from _parse_values(buffer.rstrip().rstrip(";"))
                in_insert = False
                buffer = ""
        if in_insert and buffer:
            yield from _parse_values(buffer.rstrip().rstrip(";"))


# ----------------------------------------------------------------- map


def _split_verb(value: str) -> tuple[str, str]:
    """Pull a leading verb off a factoid value if present.

    The legacy bot stored ``factoid_values.value`` like ``"are red"``,
    ``"is something"``, or ``"<reply>something"``. Strip the verb so the
    new schema's ``(verb, value)`` columns mean what they say.
    """
    if value.startswith("<"):
        # ``<reply>`` / ``<action>`` flags keep their angle-bracket form as the
        # verb so the lookup formatter can spot them.
        end = value.find(">")
        if end > 0:
            return value[: end + 1], value[end + 1 :].lstrip()
    first, _, rest = value.partition(" ")
    if first.lower() in KNOWN_VERBS:
        return first.lower(), rest
    return "is", value


def _parse_dt(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                pass
    return datetime.utcnow()


# ----------------------------------------------------------------- main


async def run_import(dump: Path, db_url: str, *, network: str = "legacy") -> dict[str, int]:
    """Run the import. Returns counts per table for the caller to print."""
    db = Database(db_url)
    await db.create_all()
    stats = {"factoids": 0, "karma": 0, "memos": 0, "seen": 0}

    # Build identity lookup so memos/seen can pin to a nick.
    identity_nick: dict[int, str] = {}
    identity_source: dict[int, str] = {}
    for row in iter_table_rows(dump, "identities"):
        # (id, account_id, source, identity, created)
        ident_id, _account, source, identity_str, _created = (
            row[0],
            row[1],
            row[2],
            row[3],
            row[4] if len(row) > 4 else None,
        )
        identity_nick[int(ident_id)] = str(identity_str)
        identity_source[int(ident_id)] = str(source)

    # ---- factoids
    # name -> factoid_id
    name_for_factoid: dict[int, str] = {}
    for row in iter_table_rows(dump, "factoid_names"):
        # (id, name, factoid_id, identity_id, time, factpack, wild)
        _, name, factoid_id, *_ = row
        # The legacy schema stored multiple names per factoid; we use the
        # first one we see (good enough for lookups and avoids collisions).
        if int(factoid_id) not in name_for_factoid:
            name_for_factoid[int(factoid_id)] = str(name).strip().lower()

    factoid_values_by_id: dict[int, list[tuple[str, str, str | None, datetime]]] = {}
    for row in iter_table_rows(dump, "factoid_values"):
        # (id, value, factoid_id, identity_id, time, factpack)
        _, value, factoid_id, identity_id, time_raw, _factpack = row
        verb, val = _split_verb(str(value))
        author = identity_nick.get(int(identity_id)) if identity_id is not None else None
        factoid_values_by_id.setdefault(int(factoid_id), []).append(
            (verb, val, author, _parse_dt(time_raw)),
        )

    async with db.session() as sess:
        seen_keys: set[str] = set()
        for fid, values in factoid_values_by_id.items():
            key = name_for_factoid.get(fid)
            if not key or not key.strip():
                continue
            key = key.strip()[:200]
            if key in seen_keys:
                continue
            seen_keys.add(key)
            fact = Factoid(key=key, created_at=values[0][3])
            for verb, val, author, t in values:
                if not val.strip():
                    continue
                fact.values.append(
                    FactoidValue(
                        verb=verb[:16],
                        value=val,
                        author=(author or "legacy")[:100],
                        network=network,
                        created_at=t,
                    )
                )
            if not fact.values:
                continue
            sess.add(fact)
            stats["factoids"] += 1

    # ---- karma
    async with db.session() as sess:
        for row in iter_table_rows(dump, "karma"):
            # (id, subject, changes, value, time)
            _, subject, _changes, value, time_raw = row
            sess.add(
                Karma(
                    thing=str(subject).lower(),
                    score=int(value),
                    updated_at=_parse_dt(time_raw),
                )
            )
            stats["karma"] += 1

    # ---- memos (only undelivered ones — historic delivered ones aren't useful)
    async with db.session() as sess:
        for row in iter_table_rows(dump, "memos"):
            # (id, from_id, to_id, memo, private, delivered, time)
            _, from_id, to_id, body, _private, delivered, time_raw = row
            if delivered:
                continue
            sender = identity_nick.get(int(from_id), "unknown")
            recipient = identity_nick.get(int(to_id), "unknown")
            sess.add(
                Memo(
                    network=identity_source.get(int(to_id), network),
                    sender=sender,
                    recipient=recipient,
                    recipient_lower=recipient.lower(),
                    body=str(body),
                    delivered=False,
                    created_at=_parse_dt(time_raw),
                )
            )
            stats["memos"] += 1

    # ---- seen (one row per identity in the legacy schema; use latest)
    seen_latest: dict[int, tuple[str, str, datetime]] = {}
    for row in iter_table_rows(dump, "seen"):
        # (id, identity_id, type, channel, value, time, count)
        _, ident_id, sx_type, channel, value, time_raw, _count = row
        if sx_type != "message":
            continue
        t = _parse_dt(time_raw)
        prev = seen_latest.get(int(ident_id))
        if prev is None or t > prev[2]:
            seen_latest[int(ident_id)] = (str(channel or ""), str(value or ""), t)

    async with db.session() as sess:
        seen_pairs: set[tuple[str, str]] = set()
        for ident_id, (chan, text, t) in seen_latest.items():
            nick = identity_nick.get(ident_id)
            if nick is None:
                continue
            src = identity_source.get(ident_id, network)
            pair = (src, nick.lower())
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            sess.add(
                SeenRow(
                    network=src,
                    nick=nick,
                    nick_lower=nick.lower(),
                    target=chan or "",
                    text=text[:500],
                    at=t,
                )
            )
            stats["seen"] += 1

    await db.close()
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import legacy ibid MySQL dump")
    parser.add_argument("dump", type=Path, help="Path to mysqldump .sql file")
    parser.add_argument(
        "--db",
        default="sqlite+aiosqlite:///ibid.db",
        help="SQLAlchemy URL for the destination DB",
    )
    parser.add_argument("--network", default="legacy", help="Network label for imported rows")
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    if not args.dump.exists():
        print(f"dump not found: {args.dump}", file=sys.stderr)
        return 2
    stats = asyncio.run(run_import(args.dump, args.db, network=args.network))
    for k, v in stats.items():
        print(f"imported {v} {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
