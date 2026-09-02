#!/usr/bin/env python3
"""Render the source-code B-tree insertion animation as an opaque MP4."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image

import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_tree_media as media  # noqa: E402


OUTPUT = ROOT / "assets" / "btree-insert-paced.mp4"
FPS = 30
ZOOM = 2
WIDTH, HEIGHT = 1588, 1080
AUDIO_DURATION = 41.80952380952381

# Audio time -> source frame time.  The source animation remains the authority
# for every movement; these anchors only retime source stages to the spoken
# key names and promotion words.
KEYFRAMES = (
    (0.00, 0), (5.44, 0),
    (5.90, 10), (6.38, 36), (7.82, 62), (9.04, 88),
    (10.00, 114), (14.84, 160),
    (15.62, 160), (16.78, 178), (17.86, 204), (18.76, 230),
    (19.50, 256), (21.86, 324),
    (23.56, 324), (24.86, 340), (25.74, 354), (26.48, 366),
    (27.48, 392), (29.16, 458),
    (30.28, 458), (31.20, 488), (32.00, 514), (32.84, 540),
    (33.68, 566), (34.76, 634),
    (35.56, 634), (39.42, 646), (40.28, 692),
    (AUDIO_DURATION, 731),
)


def capture(_filename: str, frames: list[str], **_kwargs: object) -> None:
    with tempfile.TemporaryDirectory(prefix="btree-insert-mp4-", dir=ROOT) as temp_name:
        temp = Path(temp_name)
        svg_dir = temp / "svg"
        png_dir = temp / "png"
        svg_dir.mkdir()
        png_dir.mkdir()

        rendered: list[Path] = []
        for index, frame in enumerate(frames):
            svg_path = svg_dir / f"frame-{index:05d}.svg"
            raw_path = temp / f"raw-{index:05d}.png"
            opaque_path = png_dir / f"frame-{index:05d}.png"
            svg_path.write_text(frame, encoding="utf-8")
            subprocess.run(
                ["rsvg-convert", "--zoom", str(ZOOM), str(svg_path), "--output", str(raw_path)],
                check=True,
            )
            with Image.open(raw_path).convert("RGBA") as source:
                # The source SVG canvas is larger than the reference crop.
                # Crop the union of visible pixels after all frames are rendered.
                rendered.append(raw_path)

        bbox: tuple[int, int, int, int] | None = None
        for path in rendered:
            with Image.open(path).convert("RGBA") as frame:
                current = frame.getchannel("A").getbbox()
            if current is not None:
                bbox = current if bbox is None else (
                    min(bbox[0], current[0]), min(bbox[1], current[1]),
                    max(bbox[2], current[2]), max(bbox[3], current[3]),
                )
        if bbox is None:
            raise RuntimeError("source renderer produced no visible frames")
        left, top, right, bottom = bbox
        if right - left != WIDTH or bottom - top != HEIGHT:
            raise RuntimeError(f"unexpected source crop {right-left}x{bottom-top}, expected {WIDTH}x{HEIGHT}")

        opaque_frames: list[Path] = []
        for index, raw_path in enumerate(rendered):
            with Image.open(raw_path).convert("RGBA") as source:
                cropped = source.crop((left, top, right, bottom))
                background = Image.new("RGBA", (WIDTH, HEIGHT), "black")
                background.alpha_composite(cropped)
                target = png_dir / f"frame-{index:05d}.png"
                background.convert("RGB").save(target)
                opaque_frames.append(target)

        def source_frame_at(seconds: float) -> int:
            for (start, source_start), (end, source_end) in zip(KEYFRAMES, KEYFRAMES[1:]):
                if seconds <= end:
                    fraction = (seconds - start) / max(1e-9, end - start)
                    return min(
                        len(opaque_frames) - 1,
                        max(0, round(source_start + fraction * (source_end - source_start))),
                    )
            return len(opaque_frames) - 1

        paced_dir = temp / "paced"
        paced_dir.mkdir()
        output_frames = round(AUDIO_DURATION * FPS)
        for output_index in range(output_frames):
            seconds = output_index / FPS
            source_index = source_frame_at(seconds)
            subprocess.run(
                ["cp", str(opaque_frames[source_index]), str(paced_dir / f"frame-{output_index:05d}.png")],
                check=True,
            )

        temporary = OUTPUT.with_suffix(".tmp.mp4")
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                "-i", str(paced_dir / "frame-%05d.png"), "-an",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p", "-color_range", "tv", "-movflags", "+faststart",
                str(temporary),
            ],
            check=True,
        )
        temporary.replace(OUTPUT)
    print(OUTPUT)


media.render_webm = capture  # type: ignore[assignment]
media.btree_insert()
