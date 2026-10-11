import re

from app.guardrails.patterns import EMAIL_RE, INJECTION_PATTERNS, PHONE_INTL_RE, PHONE_US_RE
from app.guardrails.types import Action, CheckResult, GuardrailDecision
from app.schemas import Message

EMAIL_PLACEHOLDER = "[REDACTED_EMAIL]"
PHONE_PLACEHOLDER = "[REDACTED_PHONE]"


def _intl_replacer(counter: list[int], redact: bool):
    def repl(match: re.Match[str]) -> str:
        digits = sum(c.isdigit() for c in match.group(0))
        if not 8 <= digits <= 15:
            return match.group(0)
        counter[0] += 1
        return PHONE_PLACEHOLDER if redact else match.group(0)

    return repl


def _redact_text(text: str, redact: bool) -> tuple[str, int, int]:
    """Return (new_text, email_count, phone_count). Text is unchanged when redact is False."""
    new, emails = EMAIL_RE.subn(EMAIL_PLACEHOLDER if redact else r"\g<0>", text)
    new, us_phones = PHONE_US_RE.subn(PHONE_PLACEHOLDER if redact else r"\g<0>", new)
    intl = [0]
    new = PHONE_INTL_RE.sub(_intl_replacer(intl, redact), new)
    return new, emails, us_phones + intl[0]


class InputGuardrails:
    """Pure functions of text and configuration. Results never contain matched text."""

    def __init__(self, *, redact_pii: bool, injection_enabled: bool, extra_block_patterns: list[str]):
        self.redact_pii = redact_pii
        self.injection_enabled = injection_enabled
        self.extra_block_patterns = [re.compile(p, re.IGNORECASE) for p in extra_block_patterns]

    def check(self, messages: list[Message]) -> GuardrailDecision:
        # Blocking checks run first and short-circuit; matched content never leaves this module.
        if self.injection_enabled:
            for check_id, pattern in INJECTION_PATTERNS:
                # The caller's own system messages are not scanned for injection.
                if any(pattern.search(m.content) for m in messages if m.role != "system"):
                    return GuardrailDecision([CheckResult(check_id, Action.BLOCK)])

        for i, pattern in enumerate(self.extra_block_patterns):
            if any(pattern.search(m.content) for m in messages):
                return GuardrailDecision([CheckResult(f"custom_pattern_{i}", Action.BLOCK)])

        total_emails = total_phones = 0
        new_messages: list[Message] = []
        for m in messages:
            text, emails, phones = _redact_text(m.content, self.redact_pii)
            total_emails += emails
            total_phones += phones
            new_messages.append(m.model_copy(update={"content": text}))

        checks: list[CheckResult] = []
        action = Action.REDACT if self.redact_pii else Action.ALLOW
        if total_emails:
            checks.append(CheckResult("pii_email", action, total_emails))
        if total_phones:
            checks.append(CheckResult("pii_phone", action, total_phones))
        return GuardrailDecision(checks, new_messages if self.redact_pii and checks else None)
