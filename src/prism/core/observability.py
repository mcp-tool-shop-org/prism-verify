"""Tiny, dependency-free observability primitives shared across prism.

The single source of truth for the per-request correlation id. The HTTP layer (and any provider
that wants its logs to correlate to a verify call) imports ``request_id`` / ``get_request_id`` /
``set_request_id`` / ``reset_request_id`` / ``bind_request_id`` from HERE — so log lines emitted at
any depth of the engine carry the same id without threading it through every signature.

Library discipline: this module NEVER calls ``logging.basicConfig`` or attaches handlers. The
application (CLI / HTTP server) owns handler configuration; library code only emits records.

stdlib only (``contextvars`` + ``logging``); no third-party imports, no I/O at import time.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

__all__ = [
    "request_id",
    "get_request_id",
    "set_request_id",
    "reset_request_id",
    "bind_request_id",
    "engine_logger",
    "routing_logger",
]

# Default "-" (not None) so log ``extra={"request_id": get_request_id()}`` is always a plain string,
# never None — greppable and uniform whether or not a caller bound an id.
request_id: ContextVar[str] = ContextVar("prism_request_id", default="-")


def get_request_id() -> str:
    """The current request id, or ``"-"`` if none has been bound on this context."""
    return request_id.get()


def set_request_id(value: str) -> Token[str]:
    """Bind ``value`` as the current request id; returns a token for ``reset_request_id``."""
    return request_id.set(value)


def reset_request_id(token: Token[str]) -> None:
    """Restore the request id to what it was before the matching ``set_request_id``."""
    request_id.reset(token)


@contextmanager
def bind_request_id(value: str) -> Iterator[str]:
    """Bind ``value`` for the duration of the ``with`` block, restoring the prior id on exit.

    Exception-safe: the prior id is restored even if the block raises.
    """
    token = request_id.set(value)
    try:
        yield value
    finally:
        request_id.reset(token)


# Module loggers. Library code logs against these; the app configures handlers/levels. Kept here so
# every prism module reaches for the same named loggers (greppable, consistent hierarchy).
engine_logger = logging.getLogger("prism.engine")
routing_logger = logging.getLogger("prism.routing")
