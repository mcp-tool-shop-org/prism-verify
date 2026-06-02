"""RFC 9457 ``application/problem+json`` errors for the prism HTTP surface.

Every 4xx/5xx is a problem document with a stable ``type`` URI and prism's existing structured
error fields (``code``/``retryable``) as extension members — so the CLI's structured-error shape
(Hard Gate B) becomes a wire standard without losing prism-specific diagnostics. See ``design/05``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from prism.core.types import RefusalReason, VerifyError

PROBLEM_BASE = "https://prism-verify.dev/problems/"
PROBLEM_MEDIA_TYPE = "application/problem+json"

# RefusalReason -> (HTTP status, problem slug). A retryable availability fault is 503; a
# malformed/uncheckable artifact is 422.
_REASON_STATUS: dict[RefusalReason, tuple[int, str]] = {
    RefusalReason.VERIFIER_UNAVAILABLE: (503, "verifier-unavailable"),
    RefusalReason.BUDGET_EXCEEDED: (503, "budget-exceeded"),
    RefusalReason.STRIP_VERIFICATION_FAILED: (422, "strip-verification-failed"),
    RefusalReason.LENS_COLLAPSE: (422, "lens-collapse"),
    RefusalReason.INVALID_ARTIFACT: (422, "invalid-artifact"),
}


class ProblemError(Exception):
    """Raised inside request handling; rendered as problem+json by the installed handler."""

    def __init__(
        self,
        status: int,
        slug: str,
        title: str,
        detail: str,
        *,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.slug = slug
        self.title = title
        self.detail = detail
        self.headers = headers or {}
        self.extra = extra or {}


def problem_response(
    status: int,
    slug: str,
    title: str,
    detail: str,
    *,
    headers: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": PROBLEM_BASE + slug,
        "title": title,
        "status": status,
        "detail": detail,
    }
    if extra:
        body.update(extra)
    return JSONResponse(
        status_code=status, content=body, media_type=PROBLEM_MEDIA_TYPE, headers=headers or {}
    )


def verify_error_response(err: VerifyError) -> JSONResponse:
    """Render a core ``VerifyError`` (an ANDON refusal) as a problem document."""
    status, slug = _REASON_STATUS.get(err.reason, (422, "verify-error"))
    headers = {"Retry-After": "2"} if (err.retryable and status >= 500) else {}
    return problem_response(
        status,
        slug,
        err.reason.value,
        err.detail,
        headers=headers,
        extra={"code": err.reason.value, "retryable": err.retryable},
    )


def install_problem_handler(app: FastAPI) -> None:
    """Register the problem+json exception handler on a FastAPI app."""

    @app.exception_handler(ProblemError)
    async def _handle(_request: Request, exc: ProblemError) -> JSONResponse:
        return problem_response(
            exc.status,
            exc.slug,
            exc.title,
            exc.detail,
            headers=exc.headers,
            extra=exc.extra,
        )
