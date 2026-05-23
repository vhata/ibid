"""Small shared helpers."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Naive UTC ``datetime`` — fits SQLite's tz-less ``DATETIME``.

    We treat every stored datetime as UTC by convention. Naive over aware
    because SQLite drops tzinfo on round-trip; mixing aware writes with
    naive reads would only confuse :func:`datetime.__sub__`.
    """
    return datetime.now(UTC).replace(tzinfo=None)
