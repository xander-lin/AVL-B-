#!/usr/bin/env python3
"""Make a black-background MP4 from the exported B-tree SVG checkpoints."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "outputs" / "btree-prep" / "btree-insert-svg-preview"
OUTPUT = ROOT / "outputs" / "btree-prep" / "btree-insert-svg-preview.mp4"
INDICES = (0, 50, 100, 180, 300, 600, 731)
FPS = 30


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="btree-svg-mp4-", dir=ROOT) as temp_name:
        temp = Path(temp_name)
        for output_index, source_index in enumerate(INDICES):
            svg = SOURCE / f"frame-{source_index:04d}.svg"
            rendered = temp / f"rendered-{output_index:04d}.png"
            opaque = temp / f"frame-{output_index:04d}.png"
            subprocess.run(
                ["rsvg-convert", "--zoom", "2", str(svg), "--output", str(rendered)],
                check=True,
            )
            with Image.open(rendered).convert("RGBA") as frame:
                background = Image.new("RGBA", frame.size, "black")
                background.alpha_composite(frame)
                background.convert("RGB").save(opaque)
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-framerate", "1", "-loop", "1", "-i", str(temp / "frame-%04d.png"),
                "-t", str(len(INDICES)), "-an",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(OUTPUT),
            ],
            check=True,
        )
    print(OUTPUT)


if __name__ == "__main__":
    main()
