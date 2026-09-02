#!/usr/bin/env python3
"""Build the narrated bridge from a four-order B-tree to a red-black tree."""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "assets" / "rb-encoding.webm"
AUDIO = ROOT / "audio" / "bst" / "recording-1788064552124411534-7-edited.wav"
OUT = ROOT / "outputs" / "rb-video"
WIDTH, HEIGHT, FPS = 1920, 1080, 60
NARRATION_END = 6.34
SUBTITLE = "而 B 树中的四阶 B 树进行二叉编码化，则孕育出了红黑树"


def duration(path: Path) -> float:
    with wave.open(str(path), "rb") as source:
        return source.getnframes() / source.getframerate()


def stamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, remain = divmod(millis, 3_600_000)
    minutes, remain = divmod(remain, 60_000)
    whole, millis = divmod(remain, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{millis:03d}"


def build() -> None:
    total = duration(AUDIO)
    source_duration = 13.9
    # Use the entire semantic morph during the spoken bridge, then retain the
    # completed binary encoding through the short recording tail.
    filter_graph = (
        f"[0:v]setpts=PTS-STARTPTS,"
        f"setpts=PTS*{NARRATION_END / source_duration:.9f},"
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,"
        f"tpad=stop_mode=clone:stop_duration={total - NARRATION_END:.6f}[v]"
    )
    # tpad makes the last legal frame available while -t below binds output to
    # the actual recording length.
    OUT.mkdir(parents=True, exist_ok=True)
    video = OUT / "segments" / "shot17.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    final = OUT / "shot17-rb-bridge.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(ASSET),
            "-filter_complex", filter_graph, "-map", "[v]", "-t", f"{total:.6f}",
            "-r", str(FPS), "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(video),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(AUDIO),
            "-map", "0:v:0", "-map", "1:a:0", "-t", f"{total:.6f}", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart", str(final),
        ],
        check=True,
    )
    (OUT / "shot17-rb-bridge.srt").write_text(
        f"1\n{stamp(0)} --> {stamp(NARRATION_END)}\n{SUBTITLE}\n",
        encoding="utf-8",
    )
    print(final)


if __name__ == "__main__":
    build()
