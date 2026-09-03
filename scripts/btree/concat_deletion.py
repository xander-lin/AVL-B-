#!/usr/bin/env python3
"""Concatenate the deletion chapter shots, then join before/deletion/after into one film."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from concat_sections import duration, shifted_srt

BTREE_VIDEO = ROOT / "outputs" / "btree-video"
DELETE_VIDEO = ROOT / "outputs" / "btree-delete-video"
CONCAT_DIR = DELETE_VIDEO / "concat"

DELETION_FILM = DELETE_VIDEO / "deletion.mp4"
FULL_FILM = BTREE_VIDEO / "btree-full.mp4"


def shot_number(path: Path) -> int:
    match = re.match(r"shot(\d+)", path.name)
    if match is None:
        raise ValueError(f"unexpected shot name: {path.name}")
    return int(match.group(1))


def concat_films(films: list[tuple[Path, Path]], output: Path, name: str) -> None:
    CONCAT_DIR.mkdir(parents=True, exist_ok=True)
    list_path = CONCAT_DIR / f"{name}.txt"
    list_path.write_text("".join(f"file '{video}'\n" for video, _ in films), encoding="utf-8")

    temporary = output.with_suffix(".tmp.mp4")
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-c", "copy", "-movflags", "+faststart", str(temporary),
        ],
        check=True,
    )
    temporary.replace(output)

    entries: list[str] = []
    offset = 0.0
    number = 1
    for video, subtitle in films:
        current, number = shifted_srt(subtitle, offset, number)
        entries.extend(current)
        offset += duration(video)
    output.with_suffix(".srt").write_text("\n".join(entries), encoding="utf-8")

    expected = sum(duration(video) for video, _ in films)
    print(f"{output} duration={duration(output):.6f}s expected={expected:.6f}s")


def main() -> None:
    videos = sorted(DELETE_VIDEO.glob("shot*.mp4"), key=shot_number)
    subtitles = [path.with_suffix(".srt") for path in videos]
    missing = [path for path in [*videos, *subtitles] if not path.exists()]
    if missing:
        raise FileNotFoundError("missing deletion shot: " + ", ".join(map(str, missing)))
    concat_films(list(zip(videos, subtitles)), DELETION_FILM, "deletion")

    full = [
        (BTREE_VIDEO / "before-deletion.mp4", BTREE_VIDEO / "before-deletion.srt"),
        (DELETION_FILM, DELETION_FILM.with_suffix(".srt")),
        (BTREE_VIDEO / "after-deletion.mp4", BTREE_VIDEO / "after-deletion.srt"),
        (BTREE_VIDEO / "ending.mp4", BTREE_VIDEO / "ending.srt"),
    ]
    missing = [path for path, _ in full if not path.exists()]
    if missing:
        raise FileNotFoundError("missing section film: " + ", ".join(map(str, missing)))
    concat_films(full, FULL_FILM, "btree-full")


if __name__ == "__main__":
    main()
