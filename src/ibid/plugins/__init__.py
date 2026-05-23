"""Bundled plugin discovery.

Plugins are ordinary Python modules under this package. Each module
exposes a list ``PLUGINS`` of :class:`Plugin` subclasses. The bot
instantiates one of each at startup.

To add a plugin, write the module, append it to :data:`BUNDLED`, and
declare classes in its ``PLUGINS`` list.
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING

from ibid.plugin import Plugin

if TYPE_CHECKING:
    from ibid.core import Bot

log = logging.getLogger("ibid.plugins")

BUNDLED: list[str] = [
    "ibid.plugins.core",
    "ibid.plugins.factoid",
    "ibid.plugins.karma",
    "ibid.plugins.seen",
    "ibid.plugins.memo",
    "ibid.plugins.calc",
    "ibid.plugins.choose",
    "ibid.plugins.urlinfo",
    "ibid.plugins.strings",
    "ibid.plugins.ascii",
    "ibid.plugins.insult",
    "ibid.plugins.quotes",
    "ibid.plugins.convert",
    "ibid.plugins.geography",
    "ibid.plugins.remind",
    "ibid.plugins.websearch",
]


def load_plugins(bot: Bot, disabled: list[str]) -> list[Plugin]:
    """Import every bundled module and instantiate its ``PLUGINS`` classes."""
    instances: list[Plugin] = []
    disabled_set = set(disabled)

    for module_name in BUNDLED:
        short = module_name.rsplit(".", 1)[-1]
        if module_name in disabled_set or short in disabled_set:
            log.info("skipping disabled plugin %s", module_name)
            continue
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            log.exception("failed to import plugin %s", module_name)
            continue
        for cls in getattr(module, "PLUGINS", []):
            if not isinstance(cls, type) or not issubclass(cls, Plugin):
                log.warning("%s exports %r which is not a Plugin", module_name, cls)
                continue
            instances.append(cls(bot))
            log.info("loaded plugin %s.%s", module_name, cls.__name__)
    return instances
