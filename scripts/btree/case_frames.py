#!/usr/bin/env python3
"""Regenerate deletion case one/two traditional animations without burned-in captions."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_tree_media as media

OUT = ROOT / "outputs" / "btree-prep" / "case-nocaption"
WIDTH, HEIGHT = 1100, 660
ROOT_C = (550.0, 120.0)
LEFT_C = (300.0, 370.0)
RIGHT_C = (820.0, 370.0)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    media.render_webm(
        "btree-case1-traditional-nocaption",
        media.btree_classic_plain_frames(WIDTH, HEIGHT, ROOT_C, LEFT_C, RIGHT_C),
        fps=30,
        transparent=True,
        output_path=OUT / "btree-case1-traditional-nocaption.webm",
    )
    media.render_webm(
        "btree-case2-traditional-nocaption",
        media.btree_classic_lend_frames(WIDTH, HEIGHT, ROOT_C, LEFT_C, RIGHT_C),
        fps=30,
        transparent=True,
        output_path=OUT / "btree-case2-traditional-nocaption.webm",
    )
    media.render_webm(
        "btree-case1-ours-grid",
        media.btree_parallel_grid_frames(
            [
                media.btree_borrow_frames(WIDTH, HEIGHT, ROOT_C, LEFT_C, RIGHT_C, (550.0, 370.0), promoted=promoted)
                for promoted in ("30", "40", "60")
            ],
            panel_width=WIDTH,
            panel_height=HEIGHT,
            titles=("推举 30", "推举 40", "推举 60"),
            columns=3,
        ),
        fps=30,
        transparent=True,
        crop=False,
        output_path=OUT / "btree-case1-ours-grid.webm",
    )
    media.render_webm(
        "btree-case2-ours-grid",
        media.btree_parallel_grid_frames(
            [
                media.btree_lend_frames(WIDTH, HEIGHT, ROOT_C, LEFT_C, RIGHT_C, (550.0, 370.0), promoted=promoted)
                for promoted in ("50", None)
            ],
            panel_width=WIDTH,
            panel_height=HEIGHT,
            titles=("推举 50", "不推举"),
            columns=2,
        ),
        fps=30,
        transparent=True,
        crop=False,
        output_path=OUT / "btree-case2-ours-grid.webm",
    )


if __name__ == "__main__":
    main()
