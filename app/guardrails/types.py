from dataclasses import dataclass, field
from enum import Enum

from app.schemas import Message


class Action(str, Enum):
    ALLOW = "allow"
    REDACT = "redact"
    BLOCK = "block"


_SEVERITY = {Action.ALLOW: 0, Action.REDACT: 1, Action.BLOCK: 2}


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one check. Deliberately carries no matched text, only a count."""

    check_id: str
    action: Action
    count: int = 1


@dataclass
class GuardrailDecision:
    checks: list[CheckResult] = field(default_factory=list)
    # Transformed messages when input was redacted; None means "use the original".
    messages: list[Message] | None = None

    @property
    def action(self) -> Action:
        """Overall action: the strongest of the individual checks (block > redact > allow)."""
        return max((c.action for c in self.checks), key=_SEVERITY.__getitem__, default=Action.ALLOW)

    @property
    def check_ids(self) -> list[str]:
        return [c.check_id for c in self.checks]
