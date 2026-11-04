# Threat model (STRIDE)
| Threat | Example | Control |
|---|---|---|
| Spoofing | Someone pretends to be a manager | Gate checks an authorised manager list; tokens are per manager |
| Tampering | Editing the audit log to hide a decision | SHA-256 hash chain; tamper and reorder tests |
| Repudiation | "I never approved that" | Every issue, apply and deny is logged with the manager name |
| Information disclosure | Faces or card numbers leak | No biometric fields, blurred placeholders, PII redaction, retention purge |
| Denial of service | Flood of false alerts | Confidence floor, dedupe, known false positive list |
| Elevation of privilege | Reusing an old approval for another alert | Single-use, scoped, expiring tokens |
| Wrongful accusation | Software labels a customer a thief | No auto-label; theft only on loss types with a clear manager yes |
