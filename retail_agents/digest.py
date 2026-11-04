"""Hourly digest agent: groups the last hour of text by zone and highlights triage alerts."""
from __future__ import annotations

import html
from dataclasses import dataclass

from .audit import AuditLog
from .describe import TextEvent, clock
from .guardrails import redact
from .models import Incident


@dataclass
class Digest:
    subject: str
    text: str
    html: str
    alert_count: int
    line_count: int


class HourlyDigestAgent:
    def __init__(self, audit: AuditLog, site: str, store_open=(10, 0), data_label: str = "synthetic data"):
        self.audit, self.site, self.store_open, self.data_label = audit, site, store_open, data_label

    def build(self, start_ts: int, end_ts: int, events: list[TextEvent], incidents: list[Incident],
              offline: list[str] | None = None) -> Digest:
        offline = offline or []
        hour = [e for e in events if start_ts <= e.ts < end_ts]
        alerts = sorted([i for i in incidents if start_ts <= i.ts < end_ts and i.status == "needs_review"],
                        key=lambda i: -i.score)
        span = f"{clock(self.store_open, start_ts)}-{clock(self.store_open, end_ts)}"
        subject = f"[{self.site}] Hourly digest {span}: {len(alerts)} alert(s)"
        lines = [f"Hourly digest for {self.site} ({self.data_label})", f"Window: {span}", ""]
        if alerts:
            lines.append("ALERTS (a manager must review; these are not accusations):")
            for i in alerts:
                lines.append(f"  ! {clock(self.store_open, i.ts)} {i.type.value} in {i.zone}, "
                             f"score {i.score}: {'; '.join(i.reasons)}")
            lines.append("")
        if offline:
            lines += [f"CAMERAS OFFLINE: {', '.join(offline)}", ""]
        if not hour:
            lines.append("Quiet hour: no activity recorded.")
        zones: dict[str, list[TextEvent]] = {}
        for e in sorted(hour, key=lambda e: e.ts):
            zones.setdefault(e.zone, []).append(e)
        for z, evs in zones.items():
            lines.append(f"{z} ({len(evs)}):")
            lines += [f"  - {e.text}" for e in evs]
        lines += ["", "No faces are recognised. People are shown blurred. Audio is off unless enabled."]
        text = redact("\n".join(lines))
        body = "".join(f"<p>{html.escape(x)}</p>" if not x.startswith("  ") else
                       f"<li>{html.escape(x.strip())}</li>" for x in text.splitlines() if x)
        page = f"<html><body><h2>{html.escape(subject)}</h2>{body}</body></html>"
        self.audit.append("digest", "build", f"{subject}; {len(hour)} lines")
        return Digest(subject, text, page, len(alerts), len(hour))
