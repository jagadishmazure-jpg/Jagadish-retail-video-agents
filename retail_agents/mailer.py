"""Email sender: dry-run by default (writes .eml to an outbox). Real SMTP only when explicitly enabled."""
from __future__ import annotations

import os
import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from .audit import AuditLog
from .digest import Digest
from .nvr import ConfigError


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    user: str
    password: str
    sender: str
    to: tuple[str, ...]

    @classmethod
    def from_env(cls, env=os.environ) -> SmtpConfig:
        need = ["DIGEST_SMTP_HOST", "DIGEST_SMTP_PORT", "DIGEST_SMTP_USER", "DIGEST_SMTP_PASSWORD",
                "DIGEST_TO"]
        missing = [k for k in need if not env.get(k)]
        if missing:
            raise ConfigError(f"missing env vars: {', '.join(missing)}")
        try:
            port = int(env["DIGEST_SMTP_PORT"])
        except ValueError as e:
            raise ConfigError("DIGEST_SMTP_PORT must be a number") from e
        to = tuple(a.strip() for a in env["DIGEST_TO"].split(",") if a.strip())
        return cls(env["DIGEST_SMTP_HOST"], port, env["DIGEST_SMTP_USER"], env["DIGEST_SMTP_PASSWORD"],
                   env.get("DIGEST_FROM", env["DIGEST_SMTP_USER"]), to)


class SendFailed(RuntimeError):
    pass


def to_message(d: Digest, sender: str, to: tuple[str, ...]) -> EmailMessage:
    m = EmailMessage()
    m["Subject"], m["From"], m["To"] = d.subject, sender, ", ".join(to)
    m.set_content(d.text)
    m.add_alternative(d.html, subtype="html")
    return m


class EmailSender:
    """dry_run=True (default) never opens a network connection."""

    def __init__(self, audit: AuditLog, outbox: str = "outbox", dry_run: bool = True,
                 config: SmtpConfig | None = None, smtp_factory=smtplib.SMTP, retries: int = 3,
                 backoff_s: float = 1.0, sleep=time.sleep):
        self.audit, self.outbox, self.dry_run = audit, Path(outbox), dry_run
        self.config, self.smtp_factory, self.retries = config, smtp_factory, retries
        self.backoff_s, self.sleep = backoff_s, sleep

    def send(self, d: Digest, stamp: str) -> str:
        if self.dry_run:
            cfg_to = self.config.to if self.config else ("manager@example.invalid",)
            msg = to_message(d, "digest@example.invalid", cfg_to)
            self.outbox.mkdir(parents=True, exist_ok=True)
            path = self.outbox / f"digest-{stamp}.eml"
            path.write_bytes(bytes(msg))
            self.audit.append("mailer", "dry_run", f"{d.subject} -> {path.name}")
            return str(path)
        if self.config is None:
            self.audit.append("mailer", "deny", "live send without SMTP config")
            raise ConfigError("live send needs SMTP config")
        msg = to_message(d, self.config.sender, self.config.to)
        last = None
        for attempt in range(1, self.retries + 1):
            try:
                with self.smtp_factory(self.config.host, self.config.port, timeout=20) as s:
                    s.starttls()
                    s.login(self.config.user, self.config.password)
                    s.send_message(msg)
                self.audit.append("mailer", "sent", f"{d.subject} to {len(self.config.to)} recipient(s), "
                                                    f"attempt {attempt}")
                return "sent"
            except (smtplib.SMTPException, OSError) as e:
                last = e
                self.audit.append("mailer", "retry", f"attempt {attempt} failed: {type(e).__name__}")
                if attempt < self.retries:
                    self.sleep(self.backoff_s * 2 ** (attempt - 1))
        self.audit.append("mailer", "failed", f"{d.subject} after {self.retries} attempts")
        raise SendFailed(f"gave up after {self.retries} attempts: {type(last).__name__}")


def purge_outbox(outbox: str, max_age_days: int = 30, now: float | None = None) -> int:
    """Retention for dry-run digests: delete .eml files older than max_age_days."""
    now = time.time() if now is None else now
    n = 0
    for p in Path(outbox).glob("*.eml"):
        if now - p.stat().st_mtime > max_age_days * 86400:
            p.unlink()
            n += 1
    return n
