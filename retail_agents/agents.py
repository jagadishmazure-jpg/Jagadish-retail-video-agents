"""The five agents: detection, till matching, triage, human review gate, report."""
from __future__ import annotations

from dataclasses import dataclass, field

from .audit import AuditLog
from .guardrails import blur_placeholder, check_no_biometrics
from .models import (
    LOSS_TYPES,
    SAFETY_TYPES,
    DetectorEvent,
    Incident,
    IncidentType,
    PosEvent,
)

STORE_CLOSE_TS = 50400  # 22:00 if day starts at 08:00
MIN_CONFIDENCE = 0.60
QUEUE_LIMIT = 6
LOITER_S = 600
UNATTENDED_S = 900
PERSON_DOWN_S = 30
VEHICLE_STOP_S = 300


# ---------------------------------------------------------------- 1. detection
class DetectionAgent:
    """Maps raw detector events to typed incidents with fixed, documented rules."""

    def __init__(self, audit: AuditLog):
        self.audit = audit
        self._n = 0

    def _new(self, e: DetectorEvent, t: IncidentType, why: str) -> Incident:
        self._n += 1
        return Incident(f"I{self._n:03d}", t, e.zone, e.ts, e.confidence,
                        blur_placeholder(e.camera_id, e.ts), [f"{e.event_id}: {why}"])

    def classify(self, e: DetectorEvent) -> Incident | None:
        check_no_biometrics(e.attrs)
        a = e.attrs
        if e.label == "item_to_bag":
            return self._new(e, IncidentType.CONCEALMENT, "item moved into bag")
        if e.label == "item_passed_unscanned":
            return self._new(e, IncidentType.SWEETHEARTING, "cashier passed item without scan")
        if e.label == "item_on_belt" and a.get("scanned") is False:
            return self._new(e, IncidentType.UNSCANNED_ITEM, "item left belt with no scan")
        if e.label == "person" and (a.get("after_hours") or e.ts > STORE_CLOSE_TS):
            return self._new(e, IncidentType.AFTER_HOURS_INTRUSION, "person seen after close")
        if e.label == "person" and a.get("dwell_s", 0) >= LOITER_S:
            return self._new(e, IncidentType.LOITERING, f"dwell {a['dwell_s']}s")
        if e.label == "queue" and a.get("count", 0) > QUEUE_LIMIT:
            return self._new(e, IncidentType.CROWDING, f"queue of {a['count']}")
        if e.label == "liquid_on_floor":
            return self._new(e, IncidentType.SPILL, "liquid on floor")
        if e.label == "person_on_floor" and a.get("still_s", 0) >= PERSON_DOWN_S:
            return self._new(e, IncidentType.PERSON_DOWN, f"still {a['still_s']}s")
        if e.label == "zone_empty" and a.get("empty_s", 0) >= UNATTENDED_S:
            return self._new(e, IncidentType.UNATTENDED_ZONE, f"empty {a['empty_s']}s")
        if e.label == "drawer_open_no_customer":
            return self._new(e, IncidentType.CASH_DRAWER, "drawer open, no customer present")
        if e.label == "vehicle" and e.zone in {"fire-lane", "loading-dock"} \
                and a.get("stopped_s", 0) >= VEHICLE_STOP_S:
            return self._new(e, IncidentType.RESTRICTED_VEHICLE, f"stopped {a['stopped_s']}s")
        return None

    def run(self, events: list[DetectorEvent]) -> list[Incident]:
        out = [i for e in events if (i := self.classify(e))]
        self.audit.append("detection", "classify", f"{len(events)} events -> {len(out)} incidents")
        return out


# ------------------------------------------------------------ 2. till matching
class TillMatchingAgent:
    RISKY = frozenset({"void", "refund", "no_sale", "discount", "drawer_open"})

    def __init__(self, audit: AuditLog, window_s: int = 60):
        self.audit, self.window_s = audit, window_s

    def run(self, incidents: list[Incident], pos: list[PosEvent]) -> list[Incident]:
        links = 0
        for inc in incidents:
            if not inc.zone.startswith("lane-"):
                continue
            for p in pos:
                if p.lane == inc.zone and p.kind in self.RISKY and abs(p.ts - inc.ts) <= self.window_s:
                    inc.pos_links.append(f"{p.pos_id}:{p.kind}:{p.amount:.2f}@{p.ts}")
                    links += 1
        self.audit.append("till_matching", "join", f"{links} POS links within {self.window_s}s")
        return incidents


# ------------------------------------------------------------------ 3. triage
BASE_RISK = {
    IncidentType.CONCEALMENT: 0.60, IncidentType.SWEETHEARTING: 0.45,
    IncidentType.UNSCANNED_ITEM: 0.40, IncidentType.AFTER_HOURS_INTRUSION: 0.70,
    IncidentType.LOITERING: 0.20, IncidentType.CROWDING: 0.30, IncidentType.SPILL: 0.60,
    IncidentType.PERSON_DOWN: 0.90, IncidentType.UNATTENDED_ZONE: 0.30,
    IncidentType.CASH_DRAWER: 0.45, IncidentType.RESTRICTED_VEHICLE: 0.40,
}
# Known false positives agreed with the store: (zone, type)
KNOWN_FALSE_POSITIVES = {("entrance", IncidentType.SPILL): "entrance mat glare"}


class TriageAgent:
    def __init__(self, audit: AuditLog, dedupe_s: int = 30, review_threshold: float = 0.5):
        self.audit, self.dedupe_s, self.th = audit, dedupe_s, review_threshold

    def run(self, incidents: list[Incident]) -> list[Incident]:
        seen: dict[tuple, Incident] = {}
        for inc in sorted(incidents, key=lambda i: i.ts):
            key = (inc.zone, inc.type)
            if inc.confidence < MIN_CONFIDENCE:
                inc.status, inc.reasons = "suppressed", [f"confidence {inc.confidence:.2f} < {MIN_CONFIDENCE}"]
                continue
            if key in KNOWN_FALSE_POSITIVES:
                inc.status, inc.reasons = "suppressed", [f"known false positive: {KNOWN_FALSE_POSITIVES[key]}"]
                continue
            prev = seen.get(key)
            if prev and inc.ts - prev.ts <= self.dedupe_s:
                inc.status, inc.reasons = "duplicate", [f"duplicate of {prev.incident_id}"]
                continue
            seen[key] = inc
            score = BASE_RISK[inc.type]
            inc.reasons.append(f"base risk for {inc.type.value}: {score:.2f}")
            if inc.pos_links:
                bump = min(0.15 * len(inc.pos_links), 0.30)
                score += bump
                inc.reasons.append(f"+{bump:.2f} for {len(inc.pos_links)} linked till event(s)")
            score *= inc.confidence
            inc.reasons.append(f"x{inc.confidence:.2f} detector confidence")
            inc.score = round(min(score, 1.0), 3)
            inc.status = "needs_review" if inc.score >= self.th or inc.type in SAFETY_TYPES else "logged"
        kept = sum(i.status in {"needs_review", "logged"} for i in incidents)
        self.audit.append("triage", "score", f"{kept} kept of {len(incidents)}")
        return incidents


# ------------------------------------------------------- 4. human review gate
class GateDenied(PermissionError):
    pass


@dataclass
class Approval:
    token: str
    manager: str
    incident_id: str
    decision: str          # confirm_theft | clear
    expires_at: int
    note: str = ""
    used: bool = False


@dataclass
class ReviewGate:
    """Only a named, authorised manager can label an incident as theft.
    Tokens are single-use, scoped to one incident and decision, and expire."""
    audit: AuditLog
    managers: set[str]
    ttl_s: int = 900
    _tokens: dict[str, Approval] = field(default_factory=dict)
    _n: int = 0

    def issue(self, manager: str, incident: Incident, decision: str, now: int, note: str = "") -> str:
        if manager not in self.managers:
            self.audit.append("gate", "deny_issue", f"unauthorised {manager}")
            raise GateDenied("manager not authorised")
        if decision not in {"confirm_theft", "clear"}:
            raise GateDenied("unknown decision")
        self._n += 1
        tok = f"T{self._n:04d}"
        self._tokens[tok] = Approval(tok, manager, incident.incident_id, decision, now + self.ttl_s, note)
        self.audit.append("gate", "issue", f"{tok} {manager} {decision} {incident.incident_id}")
        return tok

    def apply(self, token: str | None, incident: Incident, decision: str, now: int) -> Incident:
        def deny(why: str):
            self.audit.append("gate", "deny", f"{incident.incident_id}: {why}")
            raise GateDenied(why)
        if not token:
            deny("no approval")
        a = self._tokens.get(token)
        if a is None:
            deny("unknown token")
        if a.used:
            deny("token already used")
        if now > a.expires_at:
            deny("token expired")
        if a.incident_id != incident.incident_id or a.decision != decision:
            deny("scope mismatch")
        if incident.status != "needs_review":
            deny(f"incident not reviewable (status {incident.status})")
        if decision == "confirm_theft" and incident.type not in LOSS_TYPES:
            deny("theft label not allowed for this incident type")
        low = a.note.lower()
        if decision == "confirm_theft" and any(w in low for w in ("not sure", "unsure", "maybe", "wait", "no,")):
            deny("approval note is not a clear yes")
        a.used = True
        if decision == "confirm_theft":
            incident.status, incident.label = "confirmed_theft", "theft_confirmed_by_manager"
        else:
            incident.status, incident.label = "cleared", "cleared_by_manager"
        self.audit.append("gate", "apply", f"{incident.incident_id} {decision} by {a.manager}")
        return incident


# ------------------------------------------------------------------ 5. report
class ReportAgent:
    def __init__(self, audit: AuditLog):
        self.audit = audit

    def run(self, store: str, incidents: list[Incident]) -> str:
        by = lambda s: [i for i in incidents if i.status == s]
        lines = [f"Daily summary for {store} (synthetic data)",
                 f"- Incidents found: {len(incidents)}",
                 f"- Waiting for a manager: {len(by('needs_review'))}",
                 f"- Confirmed theft by a manager: {len(by('confirmed_theft'))}",
                 f"- Cleared by a manager: {len(by('cleared'))}",
                 f"- Logged only (low risk): {len(by('logged'))}",
                 f"- Hidden as duplicates: {len(by('duplicate'))}",
                 f"- Hidden as likely false alarms: {len(by('suppressed'))}"]
        safety = [i for i in incidents if i.type in SAFETY_TYPES and i.status == "needs_review"]
        if safety:
            lines.append("Safety first: " + "; ".join(f"{i.type.value} in {i.zone}" for i in safety))
        top = sorted(by("needs_review"), key=lambda i: -i.score)[:3]
        for i in top:
            lines.append(f"Check {i.incident_id}: {i.type.value} in {i.zone}, score {i.score} "
                         f"({'; '.join(i.reasons)})")
        lines.append("No one is accused by this system. Only a manager can label theft.")
        self.audit.append("report", "daily", f"{len(lines)} lines")
        return "\n".join(lines)
