"""Error types for driftless.

Errors are kept small and user-facing. The CLI catches `DriftlessError`
and renders `.message` without a traceback, so messages must be actionable.
"""

from __future__ import annotations


class DriftlessError(Exception):
    """Base class for expected, user-facing failures."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class ContractError(DriftlessError):
    """The driftless.yml contract is missing, unparseable, or invalid."""


class WorkflowNotFoundError(DriftlessError):
    """A referenced workflow does not exist in the contract."""


class HarnessError(DriftlessError):
    """The user's workflow command failed to run or produced no output."""
