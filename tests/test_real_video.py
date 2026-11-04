import subprocess
import tempfile
import unittest
from pathlib import Path

from retail_agents.backends.onnx_detector import frames_to_events
from retail_agents.nvr import CameraConfig, CameraOffline, FolderSource, Frame, sample_clip

try:
    import numpy  # noqa: F401
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


def counts(p=0, v=0, b=0, top=0.8):
    return {"persons": p, "vehicles": v, "bags": b, "top": top}


class FrameEventTests(unittest.TestCase):
    def test_scene_count_only_when_something_seen(self):
        fr = [Frame("c", "entrance", 0, "a"), Frame("c", "entrance", 5, "b")]
        ev = frames_to_events(fr, [counts(), counts(p=2)])
        self.assertEqual([e.label for e in ev], ["scene_count"])
        self.assertEqual(ev[0].attrs["persons"], 2)

    def test_queue_only_in_lanes(self):
        ev = frames_to_events([Frame("c", "lane-1", 0, "a"), Frame("d", "entrance", 0, "b")],
                              [counts(p=7), counts(p=9)])
        self.assertEqual([e.label for e in ev].count("queue"), 1)

    def test_vehicle_persistence(self):
        fr = [Frame("c", "fire-lane", t, str(t)) for t in (0, 200, 300, 400)]
        ev = frames_to_events(fr, [counts(v=1), counts(v=1), counts(v=1), counts()])
        stopped = [e.attrs["stopped_s"] for e in ev if e.label == "vehicle"]
        self.assertEqual(stopped, [300])

    def test_vehicle_reset_when_gone(self):
        fr = [Frame("c", "fire-lane", t, str(t)) for t in (0, 100, 400)]
        ev = frames_to_events(fr, [counts(v=1), counts(), counts(v=1)])
        self.assertFalse(any(e.label == "vehicle" for e in ev))

    def test_no_identity_fields(self):
        ev = frames_to_events([Frame("c", "z", 0, "a")], [counts(p=1)])
        self.assertEqual(set(ev[0].attrs), {"persons", "vehicles", "bags"})


class SampleClipTests(unittest.TestCase):
    def test_sample_clip_timestamps(self):
        with tempfile.TemporaryDirectory() as d:
            def ok(cmd, **kw):
                out = Path(cmd[-1]).parent
                for i in range(3):
                    (out / f"f_{i:05d}.jpg").write_bytes(b"x")
                return subprocess.CompletedProcess(cmd, 0)
            fr = sample_clip(Frame("cam", "z", 1000, "/x/cam_1000.mp4"), 5, d, runner=ok)
        self.assertEqual([f.ts for f in fr], [1000, 1005, 1010])

    def test_sample_clip_decode_failure(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(CameraOffline):
            sample_clip(Frame("cam", "z", 0, "/x/bad.mp4"), 5, d,
                        runner=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1))

    def test_folder_filters_other_cameras(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ["cam-a_100.mp4", "cam-b_100.mp4"]:
                Path(d, n).write_bytes(b"")
            fr = FolderSource(CameraConfig("cam-a", "z", "folder", folder=d)).frames(0, 1000)
        self.assertEqual([Path(f.ref).name for f in fr], ["cam-a_100.mp4"])


@unittest.skipUnless(HAS_NUMPY, "numpy not installed (optional detector extra)")
class DecodeTests(unittest.TestCase):
    def test_decode_nms(self):
        import numpy as np

        from retail_agents.backends.onnx_detector import decode
        out = np.full((1, 3549, 85), -20.0, dtype=np.float32)
        out[0, :, 4:] = 0.0
        out[0, [10, 40], 0:2] = 0.0
        out[0, [10, 40], 2:4] = 1.0
        out[0, [10, 40], 4] = 0.9
        out[0, [10, 40], 5] = 1.0   # person class score
        dets = decode(out, 416, 0.35)
        self.assertEqual(len(dets), 2)  # far-apart cells -> both kept
        self.assertTrue(all(c == 0 for c, _ in dets))

    def test_decode_merges_overlap(self):
        import numpy as np

        from retail_agents.backends.onnx_detector import decode
        out = np.full((1, 3549, 85), -20.0, dtype=np.float32)
        out[0, :, 4:] = 0.0
        out[0, [10, 11], 0:2] = 0.0
        out[0, [10, 11], 2:4] = 2.0
        out[0, [10, 11], 4] = 0.9
        out[0, [10, 11], 5] = 1.0
        self.assertEqual(len(decode(out, 416, 0.35)), 1)


if __name__ == "__main__":
    unittest.main()
