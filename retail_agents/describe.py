"""Transcribe/describe agent: turns audio (opt-in only) and detector events into text lines."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .audit import AuditLog
from .guardrails import check_no_biometrics, redact
from .models import DetectorEvent


class AudioDisabled(PermissionError):
    pass


class SpeechToText(Protocol):
    def transcribe(self, audio_ref: str) -> str: ...


class StubSpeechToText:
    """Stand-in for a local speech-to-text model. Returns canned text."""

    def __init__(self, canned: dict[str, str] | None = None):
        self.canned = canned or {}

    def transcribe(self, audio_ref: str) -> str:
        return self.canned.get(audio_ref, "")


class VisualDescriber(Protocol):
    def describe(self, e: DetectorEvent) -> str: ...


def clock(store_open_hhmm: tuple[int, int], ts: int) -> str:
    h, m = store_open_hhmm
    total = h * 60 + m + ts // 60
    return f"{(total // 60) % 24:02d}:{total % 60:02d}"


TEMPLATES = {
    "door_open": "{zone} door opened",
    "carry_out": "{zone}: {persons} person(s) carried {items} box(es) out",
    "queue": "{zone}: queue of {count}",
    "person": "{zone}: person seen",
    "liquid_on_floor": "{zone}: liquid on floor",
    "person_on_floor": "{zone}: person on the floor for {still_s}s",
    "drawer_open_no_customer": "{zone}: cash drawer open with no customer",
    "zone_empty": "{zone}: nobody at station for {empty_s}s",
    "vehicle": "{zone}: vehicle stopped {stopped_s}s",
    "table_wait": "{zone}: {count} guests waiting for a table",
    "scene_count": "{zone}: {persons} person(s), {vehicles} vehicle(s), {bags} bag(s) visible",
}


class StubDescriber:
    """Rule-based sentences from detector events. A local vision-language model can replace it later."""

    def __init__(self, store_open=(10, 0)):
        self.store_open = store_open

    def describe(self, e: DetectorEvent) -> str:
        check_no_biometrics(e.attrs)
        tpl = TEMPLATES.get(e.label, "{zone}: " + e.label.replace("_", " "))
        try:
            body = tpl.format(zone=e.zone, **e.attrs)
        except KeyError:
            body = f"{e.zone}: {e.label.replace('_', ' ')}"
        return f"{clock(self.store_open, e.ts)} {body}"


@dataclass(frozen=True)
class TextEvent:
    ts: int
    zone: str
    camera: str
    kind: str     # visual | audio
    text: str


class DescribeAgent:
    def __init__(self, audit: AuditLog, describer: VisualDescriber, stt: SpeechToText | None = None,
                 audio_enabled: bool = False):
        self.audit, self.describer, self.stt, self.audio_enabled = audit, describer, stt, audio_enabled

    def visual(self, events: list[DetectorEvent]) -> list[TextEvent]:
        out = [TextEvent(e.ts, e.zone, e.camera_id, "visual", redact(self.describer.describe(e)))
               for e in events]
        self.audit.append("describe", "visual", f"{len(out)} lines")
        return out

    def audio(self, ts: int, zone: str, camera: str, audio_ref: str) -> TextEvent:
        if not self.audio_enabled or self.stt is None:
            self.audit.append("describe", "deny_audio", f"{camera}: audio disabled")
            raise AudioDisabled("audio is off by default; enable explicitly after legal review")
        text = redact(self.stt.transcribe(audio_ref))
        self.audit.append("describe", "audio", f"{camera}: {len(text)} chars")
        return TextEvent(ts, zone, camera, "audio", text)
