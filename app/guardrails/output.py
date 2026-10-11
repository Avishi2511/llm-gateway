import re

from app.guardrails.types import Action, CheckResult, GuardrailDecision


class OutputGuardrails:
    """Checks generated text before it is returned. Never reports matched text."""

    def __init__(self, *, canary: str | None, block_patterns: list[str]):
        self.canary = re.compile(re.escape(canary), re.IGNORECASE) if canary else None
        self.block_patterns = [re.compile(p, re.IGNORECASE) for p in block_patterns]

    def check(self, text: str) -> GuardrailDecision:
        if self.canary and self.canary.search(text):
            return GuardrailDecision([CheckResult("output_canary", Action.BLOCK)])
        for i, pattern in enumerate(self.block_patterns):
            if pattern.search(text):
                return GuardrailDecision([CheckResult(f"output_pattern_{i}", Action.BLOCK)])
        return GuardrailDecision()
