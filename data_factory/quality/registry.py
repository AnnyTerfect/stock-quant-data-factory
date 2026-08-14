"""Discovery of the available quality checks.

Adding a check means writing it under :mod:`data_factory.quality.checks` and
listing its spec in ``_BUILTIN_SPECS`` — no command-line code has to change.
"""

from __future__ import annotations

from data_factory.quality.checks.price_consistency import SPEC as PRICE_CONSISTENCY_SPEC
from data_factory.quality.models import CheckSpec

_BUILTIN_SPECS = (PRICE_CONSISTENCY_SPEC,)

_SPECS: dict[str, CheckSpec] = {}


def register(spec: CheckSpec) -> CheckSpec:
    """Make ``spec`` discoverable by name."""
    if spec.name in _SPECS:
        raise ValueError(f"质量检查名称重复: {spec.name}")
    _SPECS[spec.name] = spec
    return spec


def get(name: str) -> CheckSpec:
    """Look up a registered spec, reporting the alternatives when missing."""
    try:
        return _SPECS[name]
    except KeyError:
        raise KeyError(f"未知的质量检查 {name!r}，可用: {sorted(_SPECS)}") from None


def specs() -> tuple[CheckSpec, ...]:
    """Every registered spec, ordered by name."""
    return tuple(_SPECS[name] for name in sorted(_SPECS))


def names() -> tuple[str, ...]:
    return tuple(sorted(_SPECS))


def _register_builtins() -> None:
    for spec in _BUILTIN_SPECS:
        register(spec)


_register_builtins()
