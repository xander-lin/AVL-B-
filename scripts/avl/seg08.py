"""AVL recap segment seg08 (scene s7-proof)."""
from PIL import Image, ImageDraw

from engine import *  # noqa: F401,F403


SCENE_ID = "s7-proof"


def draw(image: Image.Image, t: float, tl: Timeline) -> None:
    draw = ImageDraw.Draw(image)
    rows = (
        (tl.gs(23, 0), "命题：增删之后，仍能通过旋转恢复 AVL"),
        (tl.gs(24, 0), "旋转条件：高度差 = 2"),
        (tl.gs(24, 2), "旋转对象：左 · 中 · 右三棵子树"),
        (tl.gs(24, 4), "结论：要么仍然平衡，要么一定能调整"),
    )
    for index, (start, row) in enumerate(rows):
        if t >= start:
            draw_text(draw, (960, 240 + index * 118), row, size=40, fill=INK)


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import engine

    tl = engine.prepare()
    engine.register(SCENE_ID, draw)
    t0, t1 = engine.scene_span(SCENE_ID)
    out_dir = engine.OUTPUT_DIR / "preview" / SCENE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    for i in range(8):
        when = t0 + (t1 - t0) * (i + 0.5) / 8
        engine.render_frame(when).save(out_dir / f"{i}.png")
    print(f"{SCENE_ID}: {len(list(out_dir.glob('*.png')))} previews -> {out_dir}")
