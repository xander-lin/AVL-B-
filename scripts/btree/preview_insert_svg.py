#!/usr/bin/env python3
"""Export a few btree_insert source SVG frames before video encoding."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_tree_media as media  # noqa: E402


OUT = ROOT / "outputs" / "btree-prep" / "btree-insert-svg-preview"
INDICES = (0, 50, 100, 180, 300, 600, 731)


def capture(_filename: str, frames: list[str], **_kwargs: object) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for index in INDICES:
        if index >= len(frames):
            continue
        svg_path = OUT / f"frame-{index:04d}.svg"
        svg_path.write_text(frames[index], encoding="utf-8")
        png_path = svg_path.with_suffix(".png")
        media.run(
            ["rsvg-convert", "--zoom", "2", str(svg_path), "--output", str(png_path)],
            check=True,
        )
    print(f"exported {len(list(OUT.glob('*.svg')))} SVG frames to {OUT}")


media.render_webm = capture  # type: ignore[assignment]
media.btree_insert()
