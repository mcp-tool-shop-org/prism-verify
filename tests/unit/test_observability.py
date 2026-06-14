"""Tests for the shared observability primitives (the cross-agent log-correlation contract).

The HTTP layer and providers import ``request_id`` / ``get_request_id`` / ``set_request_id`` /
``reset_request_id`` / ``bind_request_id`` from here, so this pins the public API names + behavior:
a "-" default, set/reset round-trips, and an exception-safe ``bind_request_id`` contextmanager.
Plus a light check that routing emits a breaker-OPEN log at its decision point (W1, caplog).
"""

from __future__ import annotations

import asyncio
import logging
from contextvars import Token

import pytest

from prism.core.observability import (
    bind_request_id,
    engine_logger,
    get_request_id,
    request_id,
    reset_request_id,
    routing_logger,
    set_request_id,
)
from prism.core.routing import CIRCUIT_BREAKER_THRESHOLD, FamilyRouter
from prism.core.types import ModelFamily


class TestRequestIdContextVar:
    def test_default_is_dash(self) -> None:
        # A fresh context yields "-", never None, so log extras are always plain strings.
        assert get_request_id() == "-"

    def test_set_then_get(self) -> None:
        token = set_request_id("req-abc")
        try:
            assert get_request_id() == "req-abc"
            assert isinstance(token, Token)
        finally:
            reset_request_id(token)

    def test_reset_restores_prior_value(self) -> None:
        outer = set_request_id("outer")
        inner = set_request_id("inner")
        assert get_request_id() == "inner"
        reset_request_id(inner)
        assert get_request_id() == "outer"
        reset_request_id(outer)
        assert get_request_id() == "-"

    def test_contextvar_object_is_exported(self) -> None:
        # Other agents may read the ContextVar directly; pin its identity + default.
        assert request_id.get() == get_request_id()


class TestBindRequestId:
    def test_bind_sets_and_restores(self) -> None:
        assert get_request_id() == "-"
        with bind_request_id("bound") as value:
            assert value == "bound"
            assert get_request_id() == "bound"
        assert get_request_id() == "-"

    def test_bind_restores_on_exception(self) -> None:
        with pytest.raises(RuntimeError):
            with bind_request_id("bound"):
                assert get_request_id() == "bound"
                raise RuntimeError("boom")
        # Even though the block raised, the prior id is restored.
        assert get_request_id() == "-"

    def test_bind_is_async_safe(self) -> None:
        async def main() -> None:
            with bind_request_id("async-id"):
                assert get_request_id() == "async-id"
            assert get_request_id() == "-"

        asyncio.run(main())


class TestLoggers:
    def test_module_loggers_have_expected_names(self) -> None:
        assert engine_logger.name == "prism.engine"
        assert routing_logger.name == "prism.routing"


class TestRoutingBreakerLogging:
    """W1: the router logs circuit-breaker state transitions at its decision points."""

    def test_breaker_open_is_logged_once_with_request_id(self, caplog) -> None:
        router = FamilyRouter()
        route = router.select_verifier(ModelFamily.ANTHROPIC)
        token = set_request_id("trip-1")
        try:
            with caplog.at_level(logging.WARNING, logger="prism.routing"):
                for _ in range(CIRCUIT_BREAKER_THRESHOLD):
                    router.report_failure(route.family, route.model_id)
        finally:
            reset_request_id(token)
        opens = [r for r in caplog.records if r.message == "circuit_open"]
        # Exactly one OPEN transition log (subsequent failures while already-open do not re-log).
        assert len(opens) == 1
        assert opens[0].request_id == "trip-1"
        assert opens[0].family == route.family.value

    def test_breaker_closed_recovery_is_logged(self, caplog) -> None:
        router = FamilyRouter()
        route = router.select_verifier(ModelFamily.ANTHROPIC)
        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            router.report_failure(route.family, route.model_id)
        with caplog.at_level(logging.INFO, logger="prism.routing"):
            router.report_success(route.family, route.model_id)  # OPEN -> CLOSED
        closed = [r for r in caplog.records if r.message == "circuit_closed"]
        assert len(closed) == 1
