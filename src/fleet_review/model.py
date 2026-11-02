"""Shared result types and finding ids."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

OK = "ok"
ATTENTION = "attention"
SKIPPED = "skipped"


def finding_id(
    check: str, file: str, function: str, partner_file: str = "", partner_function: str = ""
) -> str:
    """Stable id: never depends on line numbers."""
    payload = json.dumps([check, file, function, partner_file, partner_function])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass
class CheckResult:
    name: str
    status: str = OK
    reason: str = ""
    detail: str = ""
    findings: list[dict[str, Any]] = field(default_factory=list)

    def finalize(self) -> CheckResult:
        if self.status != SKIPPED:
            self.status = ATTENTION if self.findings else OK
        return self

    @classmethod
    def skipped(cls, name: str, reason: str) -> CheckResult:
        return cls(name=name, status=SKIPPED, reason=reason)

    def summary_line(self) -> str:
        if self.status == SKIPPED:
            return f"{self.name}: skipped ({self.reason})"
        if self.status == ATTENTION:
            n = len(self.findings)
            return f"{self.name}: attention ({n} finding{'s' if n != 1 else ''})"
        return f"{self.name}: ok" + (f" ({self.detail})" if self.detail else "")
