"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from prism.lenses.registry import clear_registry


@pytest.fixture(autouse=True)
def _clean_lens_registry():
    """Isolate the module-global lens registry between tests.

    The registry is process-global (lenses/registry.py); without this, a test
    that registers the default lenses would leak them into every later test.
    """
    clear_registry()
    yield
    clear_registry()
