"""Synthetic NVR-to-text hourly digest for a fictional Atlanta restaurant. Never sends real email."""
from __future__ import annotations

import tempfile

from .agents import DetectionAgent, TillMatchingAgent, TriageAgent
from .audit import AuditLog
from .describe import DescribeAgent, StubDescriber
from .detector import SyntheticDetector
from .digest import HourlyDigestAgent
from .mailer import EmailSender
from .models import DetectorEvent, PosEvent
from .nvr import CameraConfig, NvrReaderAgent, SimulatedSource, build_source, detector_events_from

SITE = "Peachtree Ember Kitchen, Atlanta (fictional)"
OPEN = (10, 0)
START, END = 8 * 3600, 9 * 3600  # 18:00-19:00

CAMERAS = [
    CameraConfig("cam-backdoor", "back-door", "simulated"),
    CameraConfig("cam-register", "lane-1", "simulated"),
    CameraConfig("cam-dining", "dining-room", "simulated"),
    CameraConfig("cam-patio", "patio", "simulated"),
]


def hour_events() -> list[DetectorEvent]:
    s = START
    raw = [
        ("cam-backdoor", "back-door", s + 300, "door_open", 0.95, {}),
        ("cam-backdoor", "back-door", s + 320, "carry_out", 0.88, {"persons": 1, "items": 2}),
        ("cam-dining", "dining-room", s + 900, "table_wait", 0.92, {"count": 6}),
        ("cam-register", "lane-1", s + 1500, "drawer_open_no_customer", 0.91, {}),
        ("cam-dining", "dining-room", s + 2100, "liquid_on_floor", 0.87, {}),
        ("cam-register", "lane-1", s + 2700, "queue", 0.93, {"count": 8}),
        ("cam-backdoor", "back-door", s + 3300, "door_open", 0.94, {}),
    ]
    return [DetectorEvent(f"R{i:02d}", c, z, t, lab, conf, a) for i, (c, z, t, lab, conf, a) in enumerate(raw, 1)]


def run(outbox: str | None = None) -> dict:
    audit = AuditLog()
    sources = {c.name: build_source(c) for c in CAMERAS}
    sources["cam-patio"] = SimulatedSource(CAMERAS[3], offline=True)  # simulated outage
    read = NvrReaderAgent(sources, audit).read(START, END)
    events = detector_events_from(read.frames, SyntheticDetector(hour_events()))
    pos = [PosEvent("T1", "lane-1", START + 1490, "no_sale", 0.0, "CSH-1"),
           PosEvent("T2", "lane-1", START + 1520, "refund", 42.75, "CSH-1")]
    incidents = TriageAgent(audit).run(TillMatchingAgent(audit).run(DetectionAgent(audit).run(events), pos))
    text = DescribeAgent(audit, StubDescriber(OPEN)).visual(events)
    digest = HourlyDigestAgent(audit, SITE, OPEN).build(START, END, text, incidents, read.offline)
    outbox = outbox or tempfile.mkdtemp(prefix="outbox-")
    path = EmailSender(audit, outbox=outbox).send(digest, "1800")
    return {"frames": len(read.frames), "offline": read.offline, "digest": digest, "eml": path,
            "audit_ok": audit.verify(), "audit_entries": len(audit.entries)}


def main() -> None:
    r = run()
    print(f"frames sampled: {r['frames']}  cameras offline: {r['offline']}")
    print(f"dry-run email written: {r['eml'].rsplit('/', 1)[-1]} (not sent)")
    print(f"audit entries: {r['audit_entries']}  chain valid: {r['audit_ok']}")
    print("Subject:", r["digest"].subject)
    print(r["digest"].text)


if __name__ == "__main__":
    main()
