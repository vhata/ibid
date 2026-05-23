"""CLI entry point: ``python -m ibid run`` or just ``ibid run``."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import sys
from pathlib import Path

from ibid.config import Config
from ibid.core import Bot


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def _run(config_path: Path) -> int:
    config = Config.load(config_path)
    bot = Bot(config)
    await bot.setup()

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _on_signal() -> None:
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        # Signal handlers aren't supported on Windows — best effort.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _on_signal)

    run_task = asyncio.create_task(bot.run(), name="bot")
    stop_task = asyncio.create_task(stop.wait(), name="stop")
    done, pending = await asyncio.wait(
        {run_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    await bot.stop()
    for t in pending:
        t.cancel()
    for t in done:
        if t is run_task and t.exception() is not None:
            raise t.exception()  # type: ignore[misc]
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ibid", description="ibid chat bot")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="connect and start the bot")
    run_p.add_argument(
        "--config",
        "-c",
        default=os.environ.get("IBID_CONFIG", "ibid.toml"),
        type=Path,
        help="path to ibid.toml (default: $IBID_CONFIG or ./ibid.toml)",
    )
    run_p.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])

    args = parser.parse_args(argv)
    _configure_logging(args.log_level)

    if args.cmd == "run":
        if not args.config.exists():
            print(f"config not found: {args.config}", file=sys.stderr)
            return 2
        try:
            return asyncio.run(_run(args.config))
        except KeyboardInterrupt:
            return 130

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
