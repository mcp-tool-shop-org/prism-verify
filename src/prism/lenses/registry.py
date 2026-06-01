"""Lens registry — discovery and registration of verification lenses."""

from __future__ import annotations

from prism.lenses.base import Lens

_REGISTRY: dict[str, Lens] = {}


def register_lens(lens: Lens) -> None:
    """Register a lens instance."""
    _REGISTRY[lens.name] = lens


def get_lens(name: str) -> Lens | None:
    """Get a registered lens by name."""
    return _REGISTRY.get(name)


def get_all_lenses() -> list[Lens]:
    """Get all registered lenses."""
    return list(_REGISTRY.values())


def resolve_lenses(names: list[str] | str) -> list[Lens]:
    """Resolve lens names to instances.

    Args:
        names: List of lens names, or "auto" for all registered lenses.

    Returns:
        List of Lens instances.

    Raises:
        ValueError: If a named lens is not registered.
    """
    if names == "auto":
        lenses = get_all_lenses()
        if not lenses:
            raise ValueError("No lenses registered")
        return lenses

    resolved = []
    for name in names:
        lens = get_lens(name)
        if lens is None:
            available = list(_REGISTRY.keys())
            raise ValueError(f"Unknown lens '{name}'. Available: {available}")
        resolved.append(lens)

    return resolved


def clear_registry() -> None:
    """Remove all registered lenses. Primarily for test isolation."""
    _REGISTRY.clear()
