"""NVR reader agent: pluggable sources for RTSP streams, exported clip folders, and simulation.

Credentials are never stored in code or config files. An RTSP URL is read from an environment
variable named in the camera config, so `rtsp_env="CAM_BACKDOOR_URL"` means the URL lives in
os.environ["CAM_BACKDOOR_URL"].
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .audit import AuditLog
from .models import DetectorEvent


class ConfigError(ValueError):
    pass


class CameraOffline(ConnectionError):
    pass


@dataclass(frozen=True)
class CameraConfig:
    name: str
    zone: str
    source: str                 # rtsp | folder | simulated
    rtsp_env: str = ""          # env var holding the RTSP URL
    folder: str = ""            # export folder of .mp4 clips
    sample_every_s: int = 5     # 1 frame every N seconds
    audio_enabled: bool = False  # off by default; must be opted in

    def validate(self) -> None:
        if not self.name or not self.zone:
            raise ConfigError("camera needs a name and a zone")
        if self.source not in {"rtsp", "folder", "simulated"}:
            raise ConfigError(f"{self.name}: unknown source {self.source!r}")
        if self.source == "rtsp":
            if not self.rtsp_env:
                raise ConfigError(f"{self.name}: rtsp source needs rtsp_env")
            if "://" in self.rtsp_env:
                raise ConfigError(f"{self.name}: put the URL in an env var, not in config")
        if self.source == "folder" and not self.folder:
            raise ConfigError(f"{self.name}: folder source needs folder")
        if self.sample_every_s < 1:
            raise ConfigError(f"{self.name}: sample_every_s must be >= 1")


@dataclass(frozen=True)
class Frame:
    camera: str
    zone: str
    ts: int
    ref: str      # path or URI of the sampled frame; never contains credentials


class FrameSource(Protocol):
    def frames(self, start_ts: int, end_ts: int) -> list[Frame]: ...


def mask_url(url: str) -> str:
    """rtsp://user:pass@host/x -> rtsp://***@host/x"""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        return f"{scheme}://***@{rest.split('@', 1)[1]}"
    return url


class RtspSource:
    """Samples one frame every N seconds with ffmpeg. Not run in tests (needs a live stream)."""

    def __init__(self, cam: CameraConfig, out_dir: str = "/tmp/nvr-frames", env=os.environ, runner=subprocess.run):
        self.cam, self.out_dir, self.env, self.runner = cam, out_dir, env, runner

    def url(self) -> str:
        url = self.env.get(self.cam.rtsp_env, "")
        if not url:
            raise ConfigError(f"{self.cam.name}: env var {self.cam.rtsp_env} is not set")
        return url

    def command(self, seconds: int) -> list[str]:
        out = Path(self.out_dir) / self.cam.name / "frame_%05d.jpg"
        cmd = ["ffmpeg", "-rtsp_transport", "tcp", "-i", self.url(), "-t", str(seconds),
               "-vf", f"fps=1/{self.cam.sample_every_s}"]
        if not self.cam.audio_enabled:
            cmd.append("-an")
        return [*cmd, "-y", str(out)]

    def frames(self, start_ts: int, end_ts: int) -> list[Frame]:
        if shutil.which("ffmpeg") is None and self.runner is subprocess.run:
            raise CameraOffline("ffmpeg not installed")
        cmd = self.command(end_ts - start_ts)
        Path(self.out_dir, self.cam.name).mkdir(parents=True, exist_ok=True)
        res = self.runner(cmd, capture_output=True, timeout=end_ts - start_ts + 30)
        if res.returncode != 0:
            raise CameraOffline(f"{self.cam.name}: stream unreachable ({mask_url(self.url())})")
        files = sorted(Path(self.out_dir, self.cam.name).glob("frame_*.jpg"))
        return [Frame(self.cam.name, self.cam.zone, start_ts + i * self.cam.sample_every_s, str(f))
                for i, f in enumerate(files)]


class FolderSource:
    """Reads clips from an NVR export folder. Expects names like <camera>_<unix_ts>.mp4."""

    def __init__(self, cam: CameraConfig):
        self.cam = cam

    def frames(self, start_ts: int, end_ts: int) -> list[Frame]:
        root = Path(self.cam.folder)
        if not root.is_dir():
            raise CameraOffline(f"{self.cam.name}: export folder missing")
        out = []
        for p in sorted(root.glob("*.mp4")):
            try:
                ts = int(p.stem.rsplit("_", 1)[1])
            except (IndexError, ValueError):
                continue
            if start_ts <= ts < end_ts:
                out.append(Frame(self.cam.name, self.cam.zone, ts, str(p)))
        return out


class SimulatedSource:
    def __init__(self, cam: CameraConfig, offline: bool = False):
        self.cam, self.offline = cam, offline

    def frames(self, start_ts: int, end_ts: int) -> list[Frame]:
        if self.offline:
            raise CameraOffline(f"{self.cam.name}: simulated outage")
        return [Frame(self.cam.name, self.cam.zone, t, f"sim://{self.cam.name}/{t}")
                for t in range(start_ts, end_ts, self.cam.sample_every_s * 60)]


def build_source(cam: CameraConfig, **kw) -> FrameSource:
    cam.validate()
    if cam.source == "rtsp":
        return RtspSource(cam, **kw)
    if cam.source == "folder":
        return FolderSource(cam)
    return SimulatedSource(cam, **kw)


@dataclass
class ReadResult:
    frames: list[Frame] = field(default_factory=list)
    offline: list[str] = field(default_factory=list)


class NvrReaderAgent:
    def __init__(self, sources: dict[str, FrameSource], audit: AuditLog):
        self.sources, self.audit = sources, audit

    def read(self, start_ts: int, end_ts: int) -> ReadResult:
        r = ReadResult()
        for name, src in self.sources.items():
            try:
                r.frames.extend(src.frames(start_ts, end_ts))
            except (CameraOffline, ConfigError) as e:
                r.offline.append(name)
                self.audit.append("nvr_reader", "camera_offline", str(e))
        self.audit.append("nvr_reader", "read", f"{len(r.frames)} frames, {len(r.offline)} offline")
        return r


def detector_events_from(frames: list[Frame], detector) -> list[DetectorEvent]:
    """Hand sampled frames to any Detector implementation."""
    return detector.detect(frames)
