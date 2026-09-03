#!/usr/bin/env python3
"""Concatenate all red-black tree lesson shots into a single complete video."""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIDEO_DIR = ROOT / "outputs" / "rbt-video"
CONCAT_DIR = VIDEO_DIR / "concat"

# All active shots in lesson order (shots 02 & 05 were intentionally dropped by user):
ALL_SHOTS = [
    1, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13,
    14, 15, 16, 17, 18, 19, 20,
    21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31,
]

TIMING = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2},\d{3}) --> (?P<end>\d{2}:\d{2}:\d{2},\d{3})"
)


def duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def parse_stamp(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    whole, millis = seconds.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(whole) + int(millis) / 1000


def stamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{millis:03d}"


def shifted_srt(path: Path, offset: float, number_start: int) -> tuple[list[str], int]:
    blocks = [block.strip() for block in path.read_text(encoding="utf-8").split("\n\n") if block.strip()]
    entries: list[str] = []
    number = number_start
    for block in blocks:
        lines = block.splitlines()
        timing = next((line for line in lines if TIMING.fullmatch(line)), None)
        if timing is None:
            raise ValueError(f"invalid subtitle block in {path}: {block!r}")
        match = TIMING.fullmatch(timing)
        assert match is not None
        start = parse_stamp(match.group("start")) + offset
        end = parse_stamp(match.group("end")) + offset
        text_index = lines.index(timing) + 1
        text = "\n".join(lines[text_index:])
        entries.append(f"{number}\n{stamp(start)} --> {stamp(end)}\n{text}\n")
        number += 1
    return entries, number


def concat_shots(output_name: str = "rbt-full", shots: list[int] | None = None) -> None:
    CONCAT_DIR.mkdir(parents=True, exist_ok=True)
    shot_list = shots or ALL_SHOTS
    files = [VIDEO_DIR / f"shot{s:02d}.mp4" for s in shot_list]
    subtitles = [VIDEO_DIR / f"shot{s:02d}.srt" for s in shot_list]
    missing = [path for path in [*files, *subtitles] if not path.exists()]
    if missing:
        raise FileNotFoundError("missing shot inputs: " + ", ".join(map(str, missing)))

    list_path = CONCAT_DIR / f"{output_name}.txt"
    list_path.write_text("".join(f"file '{path}'\n" for path in files), encoding="utf-8")
    output = VIDEO_DIR / f"{output_name}.mp4"
    temporary = output.with_suffix(".tmp.mp4")
    print(f"Concatenating {len(files)} shots into {output}...")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(temporary),
        ],
        check=True,
    )
    temporary.replace(output)

    entries: list[str] = []
    offset = 0.0
    number = 1
    for video, subtitle in zip(files, subtitles):
        current, number = shifted_srt(subtitle, offset, number)
        entries.extend(current)
        offset += duration(video)
    srt_output = VIDEO_DIR / f"{output_name}.srt"
    srt_output.write_text("\n".join(entries), encoding="utf-8")

    dur = duration(output)
    print(f"Success! Output: {output} (duration={dur:.3f}s / {dur/60:.2f} mins)")
    print(f"Subtitles: {srt_output} ({number - 1} subtitle entries)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Concatenate red-black tree shots")
    parser.add_argument("--name", default="rbt-full", help="Output filename without extension")
    args = parser.parse_args()
    concat_shots(output_name=args.name)


if __name__ == "__main__":
    main()
