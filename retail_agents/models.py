"""Typed records shared by every agent."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class IncidentType(str, Enum):
    CONCEALMENT = "concealment"
    SWEETHEARTING = "sweethearting"
    UNSCANNED_ITEM = "unscanned_item"
    AFTER_HOURS_INTRUSION = "after_hours_intrusion"
    LOITERING = "loitering"
    CROWDING = "crowding"
    SPILL = "spill"
    PERSON_DOWN = "person_down"
    UNATTENDED_ZONE = "unattended_zone"
    CASH_DRAWER = "cash_drawer"
    RESTRICTED_VEHICLE = "restricted_vehicle"


SAFETY_TYPES = {IncidentType.SPILL, IncidentType.PERSON_DOWN, IncidentType.CROWDING}
LOSS_TYPES = {
    IncidentType.CONCEALMENT, IncidentType.SWEETHEARTING, IncidentType.UNSCANNED_ITEM,
    IncidentType.CASH_DRAWER,
}


@dataclass(frozen=True)
class DetectorEvent:
    """One output from a detector on one frame window. No identity fields exist by design."""
    event_id: str
    camera_id: str
    zone: str            # e.g. "lane-2", "aisle-5", "backroom", "lot-north"
    ts: int              # seconds since store-day start
    label: str           # detector label, e.g. "person", "item_to_bag", "liquid_on_floor"
    confidence: float
    attrs: dict = field(default_factory=dict)  # counts, dwell seconds, scanned flag ...


@dataclass(frozen=True)
class PosEvent:
    pos_id: str
    lane: str
    ts: int
    kind: str            # sale, void, refund, no_sale, discount, drawer_open, scan
    amount: float = 0.0
    cashier_ref: str = ""   # pseudonymous token only


@dataclass
class Incident:
    incident_id: str
    type: IncidentType
    zone: str
    ts: int
    confidence: float
    clip_ref: str
    evidence: list[str] = field(default_factory=list)
    pos_links: list[str] = field(default_factory=list)
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    status: str = "open"   # open, suppressed, duplicate, needs_review, confirmed_theft, cleared, safety_ack
    label: str = "unverified"
