"""AVL recap segment seg02 (scene s2-contrast): original SVG."""
from PIL import Image, ImageDraw

from engine import *  # noqa: F401,F403


SCENE_ID = "s2-contrast"


def draw(image: Image.Image, t: float, tl: Timeline) -> None:
    draw_source_media(
        image,
        "avl-balance-contrast.svg",
        t,
        tl.gs(1, 0),
        loop=False,
        max_width=1450,
        max_height=780,
        x_center=960,
        y_center=540,
    )


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
