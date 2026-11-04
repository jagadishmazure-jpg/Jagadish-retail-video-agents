"""Download sample clips and the optional detector model listed in data/SAMPLES.md.

Each file is checked against its SHA-256. Videos are re-encoded to 640 px MP4 with audio removed and saved as
data/samples/export/<camera>_<unix_ts>.mp4 so the NVR export-folder source can read them.
"""
import hashlib
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "samples" / "raw"
EXPORT = ROOT / "data" / "samples" / "export"
MODEL = ROOT / "data" / "samples" / "model.onnx"
BASE_TS = 1_800_000_000  # fixed synthetic clock so runs are repeatable


def manifest() -> list[dict]:
    text = (ROOT / "data" / "SAMPLES.md").read_text()
    body = text.split("MANIFEST START")[1].split("MANIFEST END")[0]
    rows = [r for r in body.splitlines() if r.startswith("| ") and not r.startswith("| camera")]
    keys = ["camera", "zone", "license", "author", "sha256", "url"]
    return [dict(zip(keys, [c.strip() for c in r.strip("|").split("|")], strict=True)) for r in rows]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def download(url: str, dest: Path, digest: str) -> None:
    if not (dest.exists() and sha256(dest) == digest):
        req = urllib.request.Request(url, headers={"User-Agent": "retail-video-agents-sample-fetch/0.1"})
        with urllib.request.urlopen(req, timeout=120) as r:
            dest.write_bytes(r.read())
    if sha256(dest) != digest:
        sys.exit(f"checksum mismatch for {dest.name}")


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    EXPORT.mkdir(parents=True, exist_ok=True)
    for i, row in enumerate(manifest()):
        if row["camera"] == "model":
            download(row["url"], MODEL, row["sha256"])
            print(f"model ok ({row['license']})")
            continue
        raw = RAW / f"{row['camera']}.webm"
        download(row["url"], raw, row["sha256"])
        out = EXPORT / f"{row['camera']}_{BASE_TS + i * 600}.mp4"
        if not out.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-t", "60", "-an",
                            "-vf", "scale=640:-2", "-c:v", "libx264", "-preset", "veryfast", str(out)], check=True)
        print(f"{row['camera']} ok -> {out.name} ({row['license']})")


if __name__ == "__main__":
    main()
