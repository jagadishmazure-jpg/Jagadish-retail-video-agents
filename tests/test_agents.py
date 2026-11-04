import unittest

from retail_agents.agents import (
    DetectionAgent,
    GateDenied,
    ReportAgent,
    ReviewGate,
    TillMatchingAgent,
    TriageAgent,
)
from retail_agents.audit import AuditLog
from retail_agents.detector import SyntheticDetector, generate_day
from retail_agents.guardrails import (
    BiometricViolation,
    blur_placeholder,
    check_no_biometrics,
    is_expired,
    purge_expired,
    redact,
)
from retail_agents.models import DetectorEvent, Incident, IncidentType, PosEvent
from retail_agents.pipeline import run_demo


def ev(label, zone="aisle-1", ts=100, conf=0.9, **a):
    return DetectorEvent("D1", "cam-x", zone, ts, label, conf, a)


def inc(t=IncidentType.SWEETHEARTING, zone="lane-2", ts=100, conf=0.9, iid="I1"):
    return Incident(iid, t, zone, ts, conf, "clip://x")


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.d = DetectionAgent(AuditLog())

    def cases(self):
        return [
            (ev("item_to_bag"), IncidentType.CONCEALMENT),
            (ev("item_passed_unscanned"), IncidentType.SWEETHEARTING),
            (ev("item_on_belt", scanned=False), IncidentType.UNSCANNED_ITEM),
            (ev("person", after_hours=True), IncidentType.AFTER_HOURS_INTRUSION),
            (ev("person", ts=60000), IncidentType.AFTER_HOURS_INTRUSION),
            (ev("person", dwell_s=700), IncidentType.LOITERING),
            (ev("queue", count=7), IncidentType.CROWDING),
            (ev("liquid_on_floor"), IncidentType.SPILL),
            (ev("person_on_floor", still_s=31), IncidentType.PERSON_DOWN),
            (ev("zone_empty", empty_s=900), IncidentType.UNATTENDED_ZONE),
            (ev("drawer_open_no_customer"), IncidentType.CASH_DRAWER),
            (ev("vehicle", zone="fire-lane", stopped_s=301), IncidentType.RESTRICTED_VEHICLE),
        ]

    def test_every_type(self):
        for e, t in self.cases():
            with self.subTest(t=t):
                self.assertEqual(self.d.classify(e).type, t)

    def test_all_eleven_types_covered(self):
        self.assertEqual({t for _, t in self.cases()}, set(IncidentType))

    def test_below_thresholds_ignored(self):
        for e in [ev("queue", count=6), ev("person", dwell_s=100), ev("person_on_floor", still_s=5),
                  ev("zone_empty", empty_s=10), ev("vehicle", zone="lot", stopped_s=900),
                  ev("item_on_belt", scanned=True), ev("unknown_label")]:
            self.assertIsNone(self.d.classify(e))

    def test_clip_is_blurred(self):
        self.assertIn("persons=blurred", self.d.classify(ev("item_to_bag")).clip_ref)

    def test_biometric_fields_rejected(self):
        with self.assertRaises(BiometricViolation):
            self.d.classify(ev("person", face_embedding=[0.1]))

    def test_stub_detector_interface(self):
        d, _ = generate_day()
        self.assertEqual(len(SyntheticDetector(d).detect([object()])), len(d))

    def test_generator_deterministic(self):
        self.assertEqual(generate_day(3), generate_day(3))


class TillTests(unittest.TestCase):
    def test_links_risky_events_in_window(self):
        i = inc()
        pos = [PosEvent("P1", "lane-2", 130, "void", 5.0), PosEvent("P2", "lane-2", 120, "sale", 5.0),
               PosEvent("P3", "lane-2", 300, "refund", 5.0), PosEvent("P4", "lane-1", 110, "no_sale")]
        TillMatchingAgent(AuditLog()).run([i], pos)
        self.assertEqual(len(i.pos_links), 1)
        self.assertTrue(i.pos_links[0].startswith("P1:void"))

    def test_non_lane_not_linked(self):
        i = inc(zone="aisle-5")
        TillMatchingAgent(AuditLog()).run([i], [PosEvent("P1", "aisle-5", 100, "void")])
        self.assertEqual(i.pos_links, [])

    def test_all_risky_kinds(self):
        i = inc()
        pos = [PosEvent(f"P{k}", "lane-2", 100, k) for k in TillMatchingAgent.RISKY]
        TillMatchingAgent(AuditLog()).run([i], pos)
        self.assertEqual(len(i.pos_links), 5)


class TriageTests(unittest.TestCase):
    def t(self):
        return TriageAgent(AuditLog())

    def test_low_confidence_suppressed(self):
        i = inc(conf=0.5)
        self.t().run([i])
        self.assertEqual(i.status, "suppressed")

    def test_known_false_positive(self):
        i = inc(IncidentType.SPILL, zone="entrance")
        self.t().run([i])
        self.assertEqual(i.status, "suppressed")
        self.assertIn("known false positive", i.reasons[0])

    def test_dedupe(self):
        a, b = inc(iid="A", ts=100), inc(iid="B", ts=120)
        self.t().run([a, b])
        self.assertEqual(b.status, "duplicate")

    def test_not_dupe_outside_window(self):
        a, b = inc(iid="A", ts=100), inc(iid="B", ts=200)
        self.t().run([a, b])
        self.assertNotEqual(b.status, "duplicate")

    def test_pos_link_raises_score_and_explains(self):
        a, b = inc(iid="A"), inc(iid="B", zone="lane-3")
        b.pos_links = ["P1:void"]
        self.t().run([a, b])
        self.assertGreater(b.score, a.score)
        self.assertTrue(any("linked till" in r for r in b.reasons))

    def test_safety_always_reviewed(self):
        i = inc(IncidentType.CROWDING, zone="lane-1", conf=0.7)
        self.t().run([i])
        self.assertEqual(i.status, "needs_review")

    def test_low_risk_logged(self):
        i = inc(IncidentType.LOITERING, zone="entrance")
        self.t().run([i])
        self.assertEqual(i.status, "logged")


class GateTests(unittest.TestCase):
    def setUp(self):
        self.audit = AuditLog()
        self.g = ReviewGate(self.audit, managers={"mgr.a"}, ttl_s=60)
        self.i = inc()
        self.i.status = "needs_review"

    def deny(self, fn, msg):
        with self.assertRaises(GateDenied) as c:
            fn()
        self.assertIn(msg, str(c.exception))

    def test_happy_path(self):
        t = self.g.issue("mgr.a", self.i, "confirm_theft", now=0, note="confirmed on clip")
        self.g.apply(t, self.i, "confirm_theft", now=10)
        self.assertEqual(self.i.label, "theft_confirmed_by_manager")

    def test_clear_path(self):
        t = self.g.issue("mgr.a", self.i, "clear", now=0)
        self.g.apply(t, self.i, "clear", now=10)
        self.assertEqual(self.i.status, "cleared")

    def test_no_token(self):
        self.deny(lambda: self.g.apply(None, self.i, "confirm_theft", 0), "no approval")

    def test_unknown_token(self):
        self.deny(lambda: self.g.apply("T9999", self.i, "confirm_theft", 0), "unknown token")

    def test_unauthorised_manager(self):
        self.deny(lambda: self.g.issue("cashier.b", self.i, "confirm_theft", 0), "not authorised")

    def test_unknown_decision(self):
        self.deny(lambda: self.g.issue("mgr.a", self.i, "ban_customer", 0), "unknown decision")

    def test_expired(self):
        t = self.g.issue("mgr.a", self.i, "confirm_theft", 0)
        self.deny(lambda: self.g.apply(t, self.i, "confirm_theft", 61), "expired")

    def test_reuse(self):
        t = self.g.issue("mgr.a", self.i, "clear", 0)
        self.g.apply(t, self.i, "clear", 1)
        self.i.status = "needs_review"
        self.deny(lambda: self.g.apply(t, self.i, "clear", 2), "already used")

    def test_scope_wrong_incident(self):
        other = inc(iid="I2"); other.status = "needs_review"
        t = self.g.issue("mgr.a", other, "confirm_theft", 0)
        self.deny(lambda: self.g.apply(t, self.i, "confirm_theft", 1), "scope mismatch")

    def test_scope_wrong_decision(self):
        t = self.g.issue("mgr.a", self.i, "clear", 0)
        self.deny(lambda: self.g.apply(t, self.i, "confirm_theft", 1), "scope mismatch")

    def test_not_reviewable(self):
        self.i.status = "suppressed"
        t = self.g.issue("mgr.a", self.i, "confirm_theft", 0)
        self.deny(lambda: self.g.apply(t, self.i, "confirm_theft", 1), "not reviewable")

    def test_theft_not_allowed_for_safety(self):
        s = inc(IncidentType.SPILL, iid="S"); s.status = "needs_review"
        t = self.g.issue("mgr.a", s, "confirm_theft", 0)
        self.deny(lambda: self.g.apply(t, s, "confirm_theft", 1), "not allowed")

    def test_unclear_note(self):
        for note in ["yes, wait, no", "not sure", "maybe theft"]:
            t = self.g.issue("mgr.a", self.i, "confirm_theft", 0, note=note)
            self.deny(lambda t=t: self.g.apply(t, self.i, "confirm_theft", 1), "not a clear yes")

    def test_denials_audited_and_no_label(self):
        try:
            self.g.apply(None, self.i, "confirm_theft", 0)
        except GateDenied:
            pass
        self.assertEqual(self.i.label, "unverified")
        self.assertEqual(self.audit.entries[-1]["action"], "deny")


class ReportTests(unittest.TestCase):
    def test_report_simple_and_no_accusation(self):
        a = inc(IncidentType.PERSON_DOWN, zone="aisle-7"); a.status = "needs_review"; a.score = 0.8
        txt = ReportAgent(AuditLog()).run("Test Store", [a])
        self.assertIn("Safety first", txt)
        self.assertIn("Only a manager can label theft", txt)
        self.assertIn("synthetic", txt)


class GuardrailTests(unittest.TestCase):
    def test_redact(self):
        s = redact("call 313-555-0199 or a@example.invalid ssn 123-45-6789 card 4111 1111 1111 1111")
        for raw in ["313-555-0199", "a@example.invalid", "123-45-6789", "4111"]:
            self.assertNotIn(raw, s)

    def test_biometric_ok(self):
        check_no_biometrics({"count": 3})

    def test_biometric_case_insensitive(self):
        with self.assertRaises(BiometricViolation):
            check_no_biometrics({"Face": 1})

    def test_retention(self):
        self.assertTrue(is_expired("unflagged_clip", 4))
        self.assertFalse(is_expired("theft_confirmed_clip", 90))
        with self.assertRaises(KeyError):
            is_expired("forever", 1)
        keep, drop = purge_expired([{"kind": "reviewed_clip", "age_days": 31}])
        self.assertEqual((len(keep), len(drop)), (0, 1))

    def test_blur(self):
        self.assertTrue(blur_placeholder("c", 1).endswith("persons=blurred"))


class AuditTests(unittest.TestCase):
    def test_chain_and_tamper(self):
        a = AuditLog()
        a.append("x", "y", "email me at a@example.invalid")
        a.append("x", "z", "ok")
        self.assertTrue(a.verify())
        self.assertIn("[EMAIL]", a.entries[0]["detail"])
        a.entries[0]["detail"] = "changed"
        self.assertFalse(a.verify())

    def test_reorder_detected(self):
        a = AuditLog()
        for k in range(3):
            a.append("x", "y", str(k))
        a.entries[0], a.entries[1] = a.entries[1], a.entries[0]
        self.assertFalse(a.verify())


class DemoTests(unittest.TestCase):
    def test_demo_end_to_end(self):
        r = run_demo()
        self.assertTrue(r["audit_ok"])
        self.assertEqual(r["denied"], ["no approval", "token already used"])
        statuses = [i.status for i in r["incidents"]]
        self.assertEqual(statuses.count("confirmed_theft"), 1)
        self.assertEqual({i.type for i in r["incidents"]}, set(IncidentType))


if __name__ == "__main__":
    unittest.main()
