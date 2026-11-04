import email
import os
import smtplib
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from retail_agents.audit import AuditLog
from retail_agents.describe import AudioDisabled, DescribeAgent, StubDescriber, StubSpeechToText, TextEvent
from retail_agents.digest import HourlyDigestAgent
from retail_agents.guardrails import BiometricViolation
from retail_agents.mailer import EmailSender, SendFailed, SmtpConfig, purge_outbox
from retail_agents.models import DetectorEvent, Incident, IncidentType
from retail_agents.nvr import (
    CameraConfig,
    CameraOffline,
    ConfigError,
    FolderSource,
    NvrReaderAgent,
    RtspSource,
    SimulatedSource,
    build_source,
    mask_url,
)
from retail_agents.restaurant_demo import run
from retail_agents.scheduler import cron_due, run_loop

ENV = {"DIGEST_SMTP_HOST": "smtp.example.invalid", "DIGEST_SMTP_PORT": "587", "DIGEST_SMTP_USER": "u",
       "DIGEST_SMTP_PASSWORD": "p", "DIGEST_TO": "a@example.invalid, b@example.invalid"}


class ConfigTests(unittest.TestCase):
    def test_valid(self):
        CameraConfig("c", "z", "rtsp", rtsp_env="CAM_URL").validate()

    def test_missing_name(self):
        with self.assertRaises(ConfigError):
            CameraConfig("", "z", "simulated").validate()

    def test_unknown_source(self):
        with self.assertRaises(ConfigError):
            CameraConfig("c", "z", "usb").validate()

    def test_rtsp_needs_env(self):
        with self.assertRaises(ConfigError):
            CameraConfig("c", "z", "rtsp").validate()

    def test_hardcoded_url_rejected(self):
        with self.assertRaises(ConfigError):
            CameraConfig("c", "z", "rtsp", rtsp_env="rtsp://u:p@h/s").validate()

    def test_folder_needs_path(self):
        with self.assertRaises(ConfigError):
            CameraConfig("c", "z", "folder").validate()

    def test_bad_sample_rate(self):
        with self.assertRaises(ConfigError):
            CameraConfig("c", "z", "simulated", sample_every_s=0).validate()

    def test_audio_off_by_default(self):
        self.assertFalse(CameraConfig("c", "z", "simulated").audio_enabled)


class RtspTests(unittest.TestCase):
    cam = CameraConfig("door", "back-door", "rtsp", rtsp_env="CAM_DOOR", sample_every_s=10)

    def test_env_missing(self):
        with self.assertRaises(ConfigError):
            RtspSource(self.cam, env={}).url()

    def test_command_samples_and_strips_audio(self):
        cmd = RtspSource(self.cam, env={"CAM_DOOR": "rtsp://u:p@10.0.0.5/s1"}).command(60)
        self.assertIn("fps=1/10", cmd)
        self.assertIn("-an", cmd)

    def test_offline_stream_masks_credentials(self):
        def fail(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 1)
        with tempfile.TemporaryDirectory() as d:
            src = RtspSource(self.cam, out_dir=d, env={"CAM_DOOR": "rtsp://u:secret@10.0.0.5/s1"}, runner=fail)
            with self.assertRaises(CameraOffline) as c:
                src.frames(0, 60)
        self.assertNotIn("secret", str(c.exception))

    def test_frames_from_runner(self):
        with tempfile.TemporaryDirectory() as d:
            def ok(cmd, **kw):
                for i in range(3):
                    Path(d, "door", f"frame_{i:05d}.jpg").write_bytes(b"x")
                return subprocess.CompletedProcess(cmd, 0)
            src = RtspSource(self.cam, out_dir=d, env={"CAM_DOOR": "rtsp://h/s"}, runner=ok)
            self.assertEqual([f.ts for f in src.frames(100, 130)], [100, 110, 120])

    def test_mask(self):
        self.assertEqual(mask_url("rtsp://u:p@h/x"), "rtsp://***@h/x")


class FolderAndSimTests(unittest.TestCase):
    def test_folder_window(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ["cam_100.mp4", "cam_5000.mp4", "junk.mp4", "cam_200.txt"]:
                Path(d, n).write_bytes(b"")
            fr = FolderSource(CameraConfig("cam", "z", "folder", folder=d)).frames(0, 1000)
        self.assertEqual([f.ts for f in fr], [100])

    def test_folder_missing_is_offline(self):
        with self.assertRaises(CameraOffline):
            FolderSource(CameraConfig("c", "z", "folder", folder="/nope/x")).frames(0, 1)

    def test_reader_continues_when_one_camera_offline(self):
        a = AuditLog()
        good = CameraConfig("g", "z", "simulated")
        srcs = {"g": build_source(good), "bad": SimulatedSource(good, offline=True)}
        r = NvrReaderAgent(srcs, a).read(0, 3600)
        self.assertEqual(r.offline, ["bad"])
        self.assertEqual(len(r.frames), 12)
        self.assertTrue(any(e["action"] == "camera_offline" for e in a.entries))


class DescribeTests(unittest.TestCase):
    def test_sentence(self):
        e = DetectorEvent("x", "c", "back-door", 8 * 3600 + 300, "carry_out", 0.9, {"persons": 1, "items": 2})
        self.assertEqual(StubDescriber().describe(e), "18:05 back-door: 1 person(s) carried 2 box(es) out")

    def test_unknown_label_and_missing_attr(self):
        d = StubDescriber()
        self.assertIn("forklift moving", d.describe(DetectorEvent("x", "c", "dock", 0, "forklift_moving", 0.9)))
        self.assertIn("queue", d.describe(DetectorEvent("x", "c", "lane", 0, "queue", 0.9)))

    def test_biometric_rejected(self):
        with self.assertRaises(BiometricViolation):
            StubDescriber().describe(DetectorEvent("x", "c", "z", 0, "person", 0.9, {"face": 1}))

    def test_audio_disabled_by_default(self):
        a = AuditLog()
        with self.assertRaises(AudioDisabled):
            DescribeAgent(a, StubDescriber(), StubSpeechToText()).audio(0, "z", "c", "clip1")
        self.assertEqual(a.entries[-1]["action"], "deny_audio")

    def test_audio_needs_engine(self):
        with self.assertRaises(AudioDisabled):
            DescribeAgent(AuditLog(), StubDescriber(), None, audio_enabled=True).audio(0, "z", "c", "x")

    def test_audio_opt_in_redacts(self):
        stt = StubSpeechToText({"a1": "call me at 404-555-0101"})
        t = DescribeAgent(AuditLog(), StubDescriber(), stt, audio_enabled=True).audio(0, "z", "c", "a1")
        self.assertEqual(t.text, "call me at [PHONE]")


class DigestTests(unittest.TestCase):
    def agent(self):
        return HourlyDigestAgent(AuditLog(), "Test Site")

    def test_empty_hour(self):
        d = self.agent().build(0, 3600, [], [])
        self.assertIn("Quiet hour", d.text)
        self.assertEqual((d.alert_count, d.line_count), (0, 0))

    def test_window_filter_and_grouping(self):
        ev = [TextEvent(10, "a", "c", "visual", "x1"), TextEvent(20, "b", "c", "visual", "x2"),
              TextEvent(4000, "a", "c", "visual", "late")]
        d = self.agent().build(0, 3600, ev, [])
        self.assertIn("a (1):", d.text)
        self.assertNotIn("late", d.text)

    def test_alerts_only_needs_review(self):
        i1 = Incident("I1", IncidentType.SPILL, "z", 10, 0.9, "c", status="needs_review", score=0.5)
        i2 = Incident("I2", IncidentType.SPILL, "z", 20, 0.9, "c", status="suppressed")
        d = self.agent().build(0, 3600, [], [i1, i2])
        self.assertEqual(d.alert_count, 1)
        self.assertIn("not accusations", d.text)

    def test_pii_redacted_and_html_escaped(self):
        ev = [TextEvent(1, "z", "c", "visual", "<b> mail x@example.invalid")]
        d = self.agent().build(0, 3600, ev, [])
        self.assertNotIn("x@example.invalid", d.text)
        self.assertIn("&lt;b&gt;", d.html)

    def test_offline_listed(self):
        self.assertIn("CAMERAS OFFLINE: cam-1", self.agent().build(0, 3600, [], [], ["cam-1"]).text)


class FakeSMTP:
    fails = 0
    sent: list = []  # noqa: RUF012

    def __init__(self, host, port, timeout=0):
        if FakeSMTP.fails > 0:
            FakeSMTP.fails -= 1
            raise smtplib.SMTPServerDisconnected("down")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, u, p):
        pass

    def send_message(self, m):
        FakeSMTP.sent.append(m)


class MailerTests(unittest.TestCase):
    def digest(self):
        return HourlyDigestAgent(AuditLog(), "S").build(0, 3600, [], [])

    def test_config_from_env(self):
        c = SmtpConfig.from_env(ENV)
        self.assertEqual(c.to, ("a@example.invalid", "b@example.invalid"))

    def test_missing_config(self):
        with self.assertRaises(ConfigError) as c:
            SmtpConfig.from_env({"DIGEST_SMTP_HOST": "h"})
        self.assertIn("DIGEST_SMTP_PASSWORD", str(c.exception))

    def test_bad_port(self):
        with self.assertRaises(ConfigError):
            SmtpConfig.from_env({**ENV, "DIGEST_SMTP_PORT": "abc"})

    def test_dry_run_default_writes_eml(self):
        with tempfile.TemporaryDirectory() as d:
            a = AuditLog()
            p = EmailSender(a, outbox=d, smtp_factory=None).send(self.digest(), "0100")
            msg = email.message_from_bytes(Path(p).read_bytes())
            self.assertTrue(msg.is_multipart())
            self.assertEqual(a.entries[-1]["action"], "dry_run")
            self.assertTrue(a.verify())

    def test_live_without_config_denied(self):
        with self.assertRaises(ConfigError):
            EmailSender(AuditLog(), dry_run=False).send(self.digest(), "x")

    def test_retry_then_success(self):
        FakeSMTP.fails, FakeSMTP.sent = 2, []
        waits = []
        s = EmailSender(AuditLog(), dry_run=False, config=SmtpConfig.from_env(ENV), smtp_factory=FakeSMTP,
                        sleep=waits.append)
        self.assertEqual(s.send(self.digest(), "x"), "sent")
        self.assertEqual((len(FakeSMTP.sent), waits), (1, [1.0, 2.0]))

    def test_retries_exhausted(self):
        FakeSMTP.fails, FakeSMTP.sent = 9, []
        a = AuditLog()
        s = EmailSender(a, dry_run=False, config=SmtpConfig.from_env(ENV), smtp_factory=FakeSMTP,
                        sleep=lambda _: None)
        with self.assertRaises(SendFailed):
            s.send(self.digest(), "x")
        self.assertEqual([e["action"] for e in a.entries[-4:]], ["retry", "retry", "retry", "failed"])
        self.assertNotIn("p", [e["detail"] for e in a.entries])

    def test_outbox_retention(self):
        with tempfile.TemporaryDirectory() as d:
            old, new = Path(d, "old.eml"), Path(d, "new.eml")
            old.write_text("x"); new.write_text("y")
            os.utime(old, (0, 0))
            self.assertEqual(purge_outbox(d, 30), 1)
            self.assertTrue(new.exists())


class SchedulerTests(unittest.TestCase):
    def test_hourly(self):
        self.assertTrue(cron_due("0 * * * *", datetime(2026, 11, 4, 18, 0)))
        self.assertFalse(cron_due("0 * * * *", datetime(2026, 11, 4, 18, 1)))

    def test_step_and_list(self):
        self.assertTrue(cron_due("*/15 9,18 * * *", datetime(2026, 11, 4, 18, 30)))

    def test_bad_expr(self):
        with self.assertRaises(ValueError):
            cron_due("0 *", datetime.now())

    def test_loop_runs_once_per_minute(self):
        times = iter([datetime(2026, 1, 1, 18, 0, 5), datetime(2026, 1, 1, 18, 0, 40),
                      datetime(2026, 1, 1, 18, 30), datetime(2026, 1, 1, 19, 0, 1)])
        ran = []
        n = run_loop("0 * * * *", ran.append, clock=lambda: next(times), sleep=lambda _: None, max_runs=2)
        self.assertEqual((n, len(ran)), (2, 2))


class RestaurantDemoTests(unittest.TestCase):
    def test_demo(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(outbox=d)
            self.assertTrue(Path(r["eml"]).exists())
        self.assertEqual(r["offline"], ["cam-patio"])
        self.assertEqual(r["digest"].alert_count, 3)
        self.assertIn("18:05 back-door: 1 person(s) carried 2 box(es) out", r["digest"].text)
        self.assertTrue(r["audit_ok"])


if __name__ == "__main__":
    unittest.main()
