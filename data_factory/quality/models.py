"""Common contracts for current and future data-quality checks."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class CheckStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


class DataScope(StrEnum):
    """Which copy of the data a check reads.

    ``SOURCE`` checks validate the upstream pickles, ``OUTPUT`` checks validate
    what :mod:`data_factory.processing` produced. Declaring it keeps the two
    kinds distinguishable once both exist.
    """

    SOURCE = "source"
    OUTPUT = "output"


@dataclass(frozen=True, slots=True)
class QualityIssue:
    code: str
    message: str
    status: CheckStatus = CheckStatus.FAIL
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Uniform result returned by every quality check."""

    check_name: str
    metrics: dict[str, float | int | str] = field(default_factory=dict)
    issues: tuple[QualityIssue, ...] = ()
    #: Pre-rendered supplementary text blocks (detail tables, samples, …).
    #: The check formats them because only it knows their shape; renderers stay
    #: generic and never reach into check-specific frames.
    details: tuple[str, ...] = ()

    @property
    def status(self) -> CheckStatus:
        statuses = {issue.status for issue in self.issues}
        if CheckStatus.FAIL in statuses:
            return CheckStatus.FAIL
        if CheckStatus.WARNING in statuses:
            return CheckStatus.WARNING
        return CheckStatus.PASS

    @property
    def passed(self) -> bool:
        return self.status is CheckStatus.PASS


@runtime_checkable
class QualityCheck(Protocol):
    """Extension point for independently runnable data checks."""

    @property
    def name(self) -> str: ...

    @property
    def scope(self) -> DataScope: ...

    def run(self) -> QualityReport: ...


@dataclass(frozen=True, slots=True)
class CheckOption:
    """One tunable input of a check, described without any CLI dependency."""

    name: str
    type: Callable[[str], Any]
    default: Any = None
    help: str = ""
    #: Explicit command-line flag; defaults to ``--<name-with-dashes>``.
    flag: str | None = None

    @property
    def command_flag(self) -> str:
        return self.flag or f"--{self.name.replace('_', '-')}"


@dataclass(frozen=True, slots=True)
class CheckSpec:
    """Everything a caller needs to discover, configure and build a check."""

    name: str
    scope: DataScope
    summary: str
    factory: Callable[..., QualityCheck]
    options: tuple[CheckOption, ...] = ()

    def defaults(self) -> dict[str, Any]:
        return {option.name: option.default for option in self.options}

    def build(self, values: Mapping[str, Any] | None = None) -> QualityCheck:
        """Instantiate the check, filling unset options with their defaults."""
        settings = self.defaults()
        unknown = set(values or {}).difference(settings)
        if unknown:
            raise KeyError(f"{self.name} 不支持的参数: {sorted(unknown)}")
        settings.update(values or {})
        return self.factory(**settings)


def run_checks(checks: Sequence[QualityCheck]) -> list[QualityReport]:
    """Run checks through one stable interface."""
    return [check.run() for check in checks]
