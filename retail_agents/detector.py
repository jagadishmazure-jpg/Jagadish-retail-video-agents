"""Stub detector interface plus a seeded synthetic event generator.

A real object detection model (for example a transformer or single-stage detector on an
edge GPU) would implement `Detector.detect` and return the same DetectorEvent
records. Nothing here processes real video.
"""
from __future__ import annotations

import random
from collections.abc import Iterable
from typing import Protocol

from .models import DetectorEvent, PosEvent


class Detector(Protocol):
    def detect(self, frames: Iterable[object]) -> list[DetectorEvent]: ...


class SyntheticDetector:
    """Replays a pre-built list of events; ignores frames."""

    def __init__(self, events: list[DetectorEvent]):
        self._events = list(events)

    def detect(self, frames: Iterable[object] = ()) -> list[DetectorEvent]:
        return list(self._events)


def generate_day(seed: int = 7) -> tuple[list[DetectorEvent], list[PosEvent]]:
    """A deterministic synthetic store day with one scenario per incident type,
    plus noise and planted false positives."""
    rng = random.Random(seed)
    d: list[DetectorEvent] = []
    p: list[PosEvent] = []
    n = 0

    def ev(cam, zone, ts, label, conf, **attrs):
        nonlocal n
        n += 1
        d.append(DetectorEvent(f"D{n:03d}", cam, zone, ts, label, conf, attrs))

    # store open 08:00 (ts 0) to 22:00 (ts 50400)
    ev("cam-aisle5", "aisle-5", 3600, "item_to_bag", 0.91, dwell_s=40)
    ev("cam-lane2", "lane-2", 7200, "item_passed_unscanned", 0.84, scanned=False)
    p.append(PosEvent("P001", "lane-2", 7230, "discount", 18.50, "CSH-A"))
    ev("cam-lane3", "lane-3", 9000, "item_on_belt", 0.88, scanned=False)
    ev("cam-lane3", "lane-3", 9002, "item_on_belt", 0.86, scanned=False)  # duplicate
    ev("cam-backdoor", "backroom", 52000, "person", 0.93, after_hours=True)
    ev("cam-entry", "entrance", 15000, "person", 0.80, dwell_s=900)
    ev("cam-lane1", "lane-1", 20000, "queue", 0.95, count=9)
    ev("cam-aisle2", "aisle-2", 22000, "liquid_on_floor", 0.89)
    ev("cam-aisle7", "aisle-7", 23000, "person_on_floor", 0.92, still_s=45)
    ev("cam-pharm", "pharmacy-counter", 25000, "zone_empty", 0.97, empty_s=1200)
    ev("cam-lane4", "lane-4", 30000, "drawer_open_no_customer", 0.90)
    p.append(PosEvent("P002", "lane-4", 29990, "no_sale", 0.0, "CSH-B"))
    p.append(PosEvent("P003", "lane-4", 30020, "refund", 64.00, "CSH-B"))
    ev("cam-lot", "fire-lane", 33000, "vehicle", 0.87, stopped_s=600)
    # planted false positives
    ev("cam-aisle5", "aisle-5", 34000, "item_to_bag", 0.42, dwell_s=5)        # low confidence
    ev("cam-entry", "entrance", 36000, "liquid_on_floor", 0.81)               # known mat glare
    ev("cam-lane1", "lane-1", 38000, "queue", 0.90, count=3)                  # short queue
    # routine POS noise
    for i in range(20):
        lane = f"lane-{rng.randint(1, 4)}"
        p.append(PosEvent(f"S{i:03d}", lane, rng.randint(0, 50400), "sale",
                          round(rng.uniform(3, 120), 2), f"CSH-{rng.choice('ABC')}"))
    p.append(PosEvent("P004", "lane-2", 7215, "void", 12.99, "CSH-A"))
    return d, sorted(p, key=lambda e: e.ts)
