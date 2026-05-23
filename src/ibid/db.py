"""Async SQLAlchemy 2.x layer.

A single declarative base ties all plugin tables together (so
``create_all`` produces the full schema). :class:`Database` owns the
engine and hands out sessions through an async context manager.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

log = logging.getLogger("ibid.db")


class Base(DeclarativeBase):
    """Declarative base shared by every plugin's models."""


class Database:
    """Async engine + session factory wrapper."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        self._engine: AsyncEngine = create_async_engine(url, echo=echo, future=True)
        self._sessionmaker = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )

    async def create_all(self) -> None:
        """Create any missing tables. Idempotent. Safe for repeated calls."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session, committing on success and rolling back on error."""
        sess = self._sessionmaker()
        try:
            yield sess
            await sess.commit()
        except Exception:
            await sess.rollback()
            raise
        finally:
            await sess.close()

    async def close(self) -> None:
        await self._engine.dispose()
