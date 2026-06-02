"""prism HTTP/FastAPI surface (v0.4).

``create_app()`` builds the FastAPI app. It is imported lazily so a base install (without the
``[http]`` extra / FastAPI) can still ``import prism.http`` — FastAPI is only required when the
app is actually constructed.
"""

from __future__ import annotations

from typing import Any

__all__ = ["create_app"]


def __getattr__(name: str) -> Any:
    if name == "create_app":
        from prism.http.app import create_app

        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
