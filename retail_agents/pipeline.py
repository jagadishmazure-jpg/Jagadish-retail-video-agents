"""End-to-end synthetic demo."""
from __future__ import annotations

from .agents import (
    DetectionAgent,
    GateDenied,
    ReportAgent,
    ReviewGate,
    TillMatchingAgent,
    TriageAgent,
)
from .audit import AuditLog
from .detector import SyntheticDetector, generate_day
from .guardrails import purge_expired

STORE = "Northbrook Corner Market, store 12 (fictional)"


def run_demo(seed: int = 7) -> dict:
    audit = AuditLog()
    det_events, pos = generate_day(seed)
    events = SyntheticDetector(det_events).detect()
    inc = DetectionAgent(audit).run(events)
    inc = TillMatchingAgent(audit).run(inc, pos)
    inc = TriageAgent(audit).run(inc)
    gate = ReviewGate(audit, managers={"mgr.priya"})
    by_id = {i.incident_id: i for i in inc}
    denied = []
    # 1) unapproved attempt to label theft is denied
    sweet = next(i for i in inc if i.type.value == "sweethearting")
    try:
        gate.apply(None, sweet, "confirm_theft", now=8000)
    except GateDenied as e:
        denied.append(str(e))
    # 2) manager reviews and confirms
    t = gate.issue("mgr.priya", sweet, "confirm_theft", now=8000, note="Watched clip and till log, confirmed")
    gate.apply(t, sweet, "confirm_theft", now=8100)
    # 3) reuse of the same token is denied
    try:
        gate.apply(t, sweet, "confirm_theft", now=8200)
    except GateDenied as e:
        denied.append(str(e))
    # 4) a concealment alert is cleared by the manager
    conceal = next(i for i in inc if i.type.value == "concealment" and i.status == "needs_review")
    t2 = gate.issue("mgr.priya", conceal, "clear", now=4000, note="customer paid at self-checkout")
    gate.apply(t2, conceal, "clear", now=4100)
    report = ReportAgent(audit).run(STORE, inc)
    _keep, drop = purge_expired([{"id": "c1", "kind": "unflagged_clip", "age_days": 4},
                                {"id": "c2", "kind": "reviewed_clip", "age_days": 10}])
    audit.append("retention", "purge", f"purged {len(drop)} clip(s)")
    return {"events": len(events), "pos": len(pos), "incidents": inc, "report": report,
            "denied": denied, "audit_entries": len(audit.entries), "audit_ok": audit.verify(),
            "purged": len(drop), "by_id": by_id}


def main() -> None:
    r = run_demo()
    print(f"detector events: {r['events']}  pos events: {r['pos']}  incidents: {len(r['incidents'])}")
    for i in r["incidents"]:
        print(f"  {i.incident_id} {i.type.value:22} {i.zone:17} status={i.status:15} score={i.score} links={len(i.pos_links)}")
    print("gate denials:", r["denied"])
    print(r["report"])
    print(f"clips purged by retention: {r['purged']}")
    print(f"audit entries: {r['audit_entries']}  chain valid: {r['audit_ok']}")


if __name__ == "__main__":
    main()
