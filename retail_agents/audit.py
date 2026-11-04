"""SHA-256 hash-chained, append-only audit log with redaction."""
from __future__ import annotations

import hashlib
import json

from .guardrails import redact

GENESIS = "0" * 64


class AuditLog:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def append(self, actor: str, action: str, detail: str) -> dict:
        prev = self.entries[-1]["hash"] if self.entries else GENESIS
        body = {"seq": len(self.entries), "actor": actor, "action": action,
                "detail": redact(detail), "prev": prev}
        body["hash"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        self.entries.append(body)
        return body

    def verify(self) -> bool:
        prev = GENESIS
        for i, e in enumerate(self.entries):
            body = {k: v for k, v in e.items() if k != "hash"}
            if e["seq"] != i or e["prev"] != prev:
                return False
            if hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() != e["hash"]:
                return False
            prev = e["hash"]
        return True
