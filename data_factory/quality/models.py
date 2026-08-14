"""Common contracts for current and future data-quality checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class CheckStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


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

    def run(self) -> QualityReport: ...


def run_checks(checks: list[QualityCheck]) -> list[QualityReport]:
    """Run checks through one stable interface."""
    return [check.run() for check in checks]
