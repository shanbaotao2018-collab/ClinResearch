from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


class PotentialPHIError(ValueError):
    """Raised before potentially identifying clinical data reaches the model workflow."""


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")),
    ("phone_number", re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")),
    ("chinese_national_id", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    (
        "clinical_identifier_label",
        re.compile(r"(?:MRN|medical record number|病历号|住院号|门诊号|身份证号|手机号)\s*[:：#]?\s*\S+", re.I),
    ),
)


def redact_public_contact_emails(text: str) -> str:
    """Remove author/contact addresses from public-paper source text before PHI screening.

    Open-access HTML frequently includes a corresponding author's email address in
    metadata. It is not patient data, but storing it is unnecessary for evidence
    extraction and would otherwise make the conservative PHI guard reject the
    entire paper.
    """
    email_pattern = next(pattern for label, pattern in _PATTERNS if label == "email")
    # JATS/XML full text often wraps correspondence in <email> tags. Remove the
    # entire element first so markup cannot split an address around the regex.
    text = re.sub(
        r"<email\b[^>]*>.*?</email\s*>",
        "[redacted-public-contact-email]",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return email_pattern.sub("[redacted-public-contact-email]", text)


def _flatten(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [item for nested in value.values() for item in _flatten(nested)]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [item for nested in value for item in _flatten(nested)]
    return [str(value)]


def assert_no_phi(value: Any) -> None:
    """Reject obvious identifiers; this is a guardrail, not a substitute for formal de-identification."""
    detected: set[str] = set()
    for text in _flatten(value):
        for label, pattern in _PATTERNS:
            if pattern.search(text):
                detected.add(label)
    if detected:
        labels = ", ".join(sorted(detected))
        raise PotentialPHIError(
            f"Potential PHI detected ({labels}). Submit only de-identified or aggregate research data."
        )


def assert_deidentified_attestation(attestation: str) -> None:
    if attestation != "deidentified_or_aggregate":
        raise PotentialPHIError(
            "data_attestation must be 'deidentified_or_aggregate' before this workflow can run."
        )
