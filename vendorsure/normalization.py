"""Deterministic normalization helpers for VendorSure comparisons."""

from __future__ import annotations

import re
import unicodedata
from typing import Optional


_LEGAL_SUFFIXES = (
    "private limited",
    "pvt ltd",
    "limited",
    "ltd",
    "llp",
)


def normalize_text(value: Optional[str]) -> str:
    """Lowercase, remove punctuation, and collapse whitespace.

    Punctuation becomes a separator rather than joining neighboring words.
    This makes ``Apex-Components`` compare consistently with
    ``Apex Components`` while retaining the original value elsewhere.
    """

    if value is None:
        return ""

    normalized = unicodedata.normalize("NFKC", str(value)).lower()
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    normalized = re.sub(r"_", " ", normalized)
    return " ".join(normalized.split())


def normalize_name(value: Optional[str]) -> str:
    """Normalize a legal or trade name without fuzzy matching."""

    normalized = normalize_text(value)

    # Remove a legal suffix only when it is at the end.  Repeating the loop
    # handles values such as "Example Private Limited LLP" deterministically.
    changed = True
    while normalized and changed:
        changed = False
        for suffix in _LEGAL_SUFFIXES:
            suffix_pattern = rf"(?:^|\s){re.escape(suffix)}$"
            candidate = re.sub(suffix_pattern, "", normalized).strip()
            if candidate != normalized:
                normalized = candidate
                changed = True
                break

    return normalized


def normalize_identifier(value: Optional[str]) -> str:
    """Normalize an identifier for exact comparison."""

    if value is None:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", str(value)).upper()


def normalize_email(value: Optional[str]) -> str:
    """Normalize an email address for exact comparison."""

    if value is None:
        return ""
    return str(value).strip().lower()


def names_match(first: Optional[str], second: Optional[str]) -> bool:
    """Compare names exactly after deterministic normalization."""

    return bool(normalize_name(first)) and normalize_name(first) == normalize_name(second)