"""Privacy guardrails: no biometrics, redaction, retention, blur placeholders."""
from __future__ import annotations

import re

FORBIDDEN_KEYS = {"face", "face_embedding", "faceprint", "biometric", "person_id",
                  "identity", "name", "gait", "voiceprint", "license_plate_owner"}

_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[CARD]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[EMAIL]"),
    (re.compile(r"\(?\b\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}\b"), "[PHONE]"),
]

RETENTION_DAYS = {"unflagged_clip": 3, "reviewed_clip": 30, "theft_confirmed_clip": 90}


class BiometricViolation(ValueError):
    pass


def check_no_biometrics(attrs: dict) -> None:
    bad = FORBIDDEN_KEYS.intersection(k.lower() for k in attrs)
    if bad:
        raise BiometricViolation(f"biometric/identity fields rejected: {sorted(bad)}")


def redact(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


def blur_placeholder(camera_id: str, ts: int) -> str:
    """People are always represented as blurred boxes; no crops of faces are kept."""
    return f"clip://{camera_id}/{ts}?persons=blurred"


def is_expired(kind: str, age_days: int) -> bool:
    if kind not in RETENTION_DAYS:
        raise KeyError(f"unknown retention class: {kind}")
    return age_days > RETENTION_DAYS[kind]


def purge_expired(clips: list[dict]) -> tuple[list[dict], list[dict]]:
    keep, drop = [], []
    for c in clips:
        (drop if is_expired(c["kind"], c["age_days"]) else keep).append(c)
    return keep, drop
