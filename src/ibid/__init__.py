"""ibid — an async, plugin-driven chat bot."""

from __future__ import annotations

import os

import certifi

__version__ = "0.3.0"


# macOS python.org installs ship without a CA bundle wired into Python's
# ssl module, so aiohttp / discord.py / httpx all fail with
# CERTIFICATE_VERIFY_FAILED. Point the standard env vars at certifi's
# bundle before any HTTP client builds its default SSLContext. We use
# setdefault so an explicitly-set value wins (corporate trust stores,
# debugging proxies, ...).
_ca_bundle = certifi.where()
os.environ.setdefault("SSL_CERT_FILE", _ca_bundle)
os.environ.setdefault("REQUESTS_CA_BUNDLE", _ca_bundle)
