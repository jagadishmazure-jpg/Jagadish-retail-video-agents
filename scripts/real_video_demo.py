"""Real-video demo: export-folder NVR source -> ffmpeg sampling -> ONNX detector on CPU -> hourly digest (dry-run).

  python3.12 scripts/fetch_samples.py
  python3.12 scripts/real_video_demo.py
Frames are deleted after detection. Nothing is emailed; a .eml file is written to outbox/.
"""
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from retail_agents.agents import DetectionAgent, TriageAgent
from retail_agents.audit import AuditLog
from retail_agents.backends.onnx_detector import OnnxDetector
from retail_agents.describe import DescribeAgent, StubDescriber
from retail_agents.digest import HourlyDigestAgent
from retail_agents.mailer import EmailSender
from retail_agents.nvr import CameraConfig, FolderSource, NvrReaderAgent, sample_clip

EXPORT = ROOT / "data" / "samples" / "export"
BASE = 1_800_000_000
EVERY_S = 5
CAMS = [CameraConfig(n, z, "folder", folder=str(EXPORT), sample_every_s=EVERY_S)
        for n, z in [("cam-store", "lane-1"), ("cam-kitchen", "kitchen"), ("cam-lot", "fire-lane"),
                     ("cam-entry", "entrance"), ("cam-patio", "patio")]]
CAMS[-1] = CameraConfig("cam-patio", "patio", "folder", folder=str(ROOT / "data" / "samples" / "missing"))


def main() -> None:
    audit = AuditLog()
    det = OnnxDetector(str(ROOT / "data" / "samples" / "model.onnx"))
    read = NvrReaderAgent({c.name: FolderSource(c) for c in CAMS}, audit).read(BASE, BASE + 3600)
    tmp = tempfile.mkdtemp(prefix="frames-")
    t0 = time.perf_counter()
    frames = [f for clip in read.frames for f in sample_clip(clip, EVERY_S, tmp)]
    t_sample = time.perf_counter() - t0
    events = det.detect(frames)
    shutil.rmtree(tmp)  # retention: sampled frames are not kept
    audit.append("retention", "purge_frames", f"deleted {len(frames)} sampled frames")
    incidents = TriageAgent(audit).run(DetectionAgent(audit).run(events))
    # clock: BASE maps to 18:00 for a 10:00 open
    shift = lambda ts: ts - BASE + 8 * 3600
    text = DescribeAgent(audit, StubDescriber((10, 0))).visual(
        [type(e)(e.event_id, e.camera_id, e.zone, shift(e.ts), e.label, e.confidence, e.attrs) for e in events])
    for i in incidents:
        i.ts = shift(i.ts)
    digest = HourlyDigestAgent(audit, "Peachtree Ember Kitchen, Atlanta (fictional)",
                               data_label="openly licensed sample clips, real detections").build(
        8 * 3600, 9 * 3600, text, incidents, read.offline)
    eml = EmailSender(audit, outbox=str(ROOT / "outbox")).send(digest, "real-1800")
    s = det.stats
    print("MEASURED on this machine:", platform.processor() or platform.machine(), f"python {platform.python_version()}")
    print(f"clips read: {len(read.frames)}  cameras offline: {read.offline}")
    print(f"frames sampled (1 per {EVERY_S}s): {len(frames)} in {t_sample:.2f}s")
    print(f"objects detected (conf>={det.conf}): {s['objects']}  detector events: {len(events)}")
    print(f"CPU inference: {s['infer_s']:.2f}s total, {s['frames'] / s['infer_s']:.1f} frames/s")
    print(f"incidents: {len(incidents)}  dry-run email: {Path(eml).name}  audit valid: {audit.verify()}")
    print("Subject:", digest.subject)
    print(digest.text)


if __name__ == "__main__":
    main()
