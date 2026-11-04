"""Optional real detector: an Apache-2.0 nano object detector in ONNX format, run on CPU.

Needs `pip install -r requirements-detector.txt` and `python3.12 scripts/fetch_samples.py`.
Only class counts leave this module (people, vehicles, bags). No face, crop or identity is produced.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..models import DetectorEvent
from ..nvr import Frame

# COCO class ids used by the model
PERSON, VEHICLES, BAGS = 0, {2, 3, 5, 7}, {24, 26, 28}
QUEUE_ZONES_PREFIX = "lane-"
QUEUE_MIN = 7  # matches DetectionAgent QUEUE_LIMIT + 1


def _letterbox(img, size: int):
    import numpy as np

    w, h = img.size
    r = min(size / w, size / h)
    resized = img.resize((int(w * r), int(h * r)))
    canvas = np.full((size, size, 3), 114, dtype=np.float32)
    # model expects BGR pixel values 0-255 with grey (114) padding, no normalisation (checked on sample frames)
    canvas[: resized.size[1], : resized.size[0]] = np.asarray(resized, dtype=np.float32)[..., ::-1]
    return np.ascontiguousarray(canvas.transpose(2, 0, 1)[None]), r


def decode(out, size: int, conf: float):
    """Decode raw (1, N, 85) model output into (class_id, score) pairs with class-aware NMS."""
    import numpy as np

    strides = [8, 16, 32]
    grids, exp = [], []
    for s in strides:
        g = size // s
        yv, xv = np.meshgrid(np.arange(g), np.arange(g), indexing="ij")
        grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
        exp.append(np.full((g * g, 1), s))
    grids, exp = np.concatenate(grids), np.concatenate(exp)
    p = out[0]
    xy = (p[:, :2] + grids) * exp
    wh = np.exp(p[:, 2:4]) * exp
    scores = p[:, 4:5] * p[:, 5:]
    cls = scores.argmax(1)
    sc = scores.max(1)
    keep = sc >= conf
    boxes = np.concatenate([xy - wh / 2, xy + wh / 2], 1)[keep]
    cls, sc = cls[keep], sc[keep]
    picked = []
    for c in set(cls.tolist()):
        idx = np.where(cls == c)[0]
        order = idx[np.argsort(-sc[idx])]
        while order.size:
            i = order[0]
            picked.append((int(c), float(sc[i])))
            if order.size == 1:
                break
            b = boxes[order[1:]]
            x1 = np.maximum(boxes[i, 0], b[:, 0]); y1 = np.maximum(boxes[i, 1], b[:, 1])
            x2 = np.minimum(boxes[i, 2], b[:, 2]); y2 = np.minimum(boxes[i, 3], b[:, 3])
            inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
            area = lambda bb: (bb[..., 2] - bb[..., 0]) * (bb[..., 3] - bb[..., 1])
            iou = inter / (area(boxes[i]) + area(b) - inter + 1e-9)
            order = order[1:][iou < 0.45]
    return picked


@dataclass
class OnnxDetector:
    model_path: str
    conf: float = 0.35
    size: int = 416
    stats: dict = field(default_factory=lambda: {"frames": 0, "infer_s": 0.0, "objects": 0})

    def __post_init__(self):
        import onnxruntime as ort

        self.sess = ort.InferenceSession(self.model_path, providers=["CPUExecutionProvider"])
        self.inp = self.sess.get_inputs()[0].name

    def counts(self, path: str) -> dict:
        from PIL import Image

        x, _ = _letterbox(Image.open(path).convert("RGB"), self.size)
        t = time.perf_counter()
        out = self.sess.run(None, {self.inp: x})[0]
        self.stats["infer_s"] += time.perf_counter() - t
        self.stats["frames"] += 1
        dets = decode(out, self.size, self.conf)
        self.stats["objects"] += len(dets)
        return {"persons": sum(c == PERSON for c, _ in dets),
                "vehicles": sum(c in VEHICLES for c, _ in dets),
                "bags": sum(c in BAGS for c, _ in dets),
                "top": max((s for _, s in dets), default=0.0)}

    def detect(self, frames: list[Frame]) -> list[DetectorEvent]:
        return frames_to_events(frames, [self.counts(f.ref) for f in frames])


def frames_to_events(frames: list[Frame], counts: list[dict]) -> list[DetectorEvent]:
    """Turn per-frame counts into DetectorEvents. Pure function, unit-tested without the model."""
    events: list[DetectorEvent] = []
    first_vehicle: dict[str, int] = {}
    for n, (f, c) in enumerate(zip(frames, counts, strict=True), 1):
        conf = round(c["top"], 3)
        if c["persons"] or c["vehicles"]:
            events.append(DetectorEvent(f"V{n:04d}", f.camera, f.zone, f.ts, "scene_count", conf,
                                        {"persons": c["persons"], "vehicles": c["vehicles"], "bags": c["bags"]}))
        if f.zone.startswith(QUEUE_ZONES_PREFIX) and c["persons"] >= QUEUE_MIN:
            events.append(DetectorEvent(f"Q{n:04d}", f.camera, f.zone, f.ts, "queue", conf, {"count": c["persons"]}))
        if c["vehicles"]:
            start = first_vehicle.setdefault(f.camera, f.ts)
            stopped = f.ts - start
            if stopped >= 300:
                events.append(DetectorEvent(f"W{n:04d}", f.camera, f.zone, f.ts, "vehicle", conf,
                                            {"stopped_s": stopped}))
        else:
            first_vehicle.pop(f.camera, None)
    return events
