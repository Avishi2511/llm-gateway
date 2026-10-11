"""Compiled patterns used by the guardrails. Kept in one place so they are easy to review.

These are heuristics, not complete detection: they trade recall for a low false-positive rate.
"""
import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")

# US-style numbers need separators between groups, e.g. (555) 010-0100, 555-010-0100, 555.010.0100.
# A bare run of 10 digits is intentionally NOT matched (order numbers, IDs, timestamps).
PHONE_US_RE = re.compile(
    r"(?<![\w.+])(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}(?!\w)"
)
# International numbers must start with '+' and have 8-15 digits in total (checked in input.py).
PHONE_INTL_RE = re.compile(r"(?<![\w.])\+\d{1,3}(?:[\s.-]?\(?\d{1,4}\)?){2,5}(?!\w)")

# Small list of high-confidence prompt-injection phrases (id, pattern).
INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "injection_ignore_instructions",
        re.compile(
            r"\b(?:ignore|disregard|forget|override)\s+(?:(?:all|any|the|your|my)\s+)*"
            r"(?:previous|prior|above|earlier|preceding|system)\s+"
            r"(?:instructions?|prompts?|rules|directives|messages?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "injection_reveal_prompt",
        re.compile(
            r"\b(?:reveal|show|print|repeat|display|leak|output)\s+(?:me\s+)?(?:all\s+)?(?:your|the)\s+"
            r"(?:(?:hidden|secret|initial|original)\s+instructions|system\s+(?:prompt|message))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "injection_jailbreak_persona",
        re.compile(
            r"\byou\s+are\s+now\s+(?:dan|in\s+developer\s+mode)\b"
            r"|\bdeveloper\s+mode\s+(?:enabled|activated)\b"
            r"|\bdo\s+anything\s+now\b",
            re.IGNORECASE,
        ),
    ),
]
