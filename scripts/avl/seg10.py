"""AVL recap segment seg10 (scene s9-outro)."""
from PIL import Image, ImageDraw

from engine import *  # noqa: F401,F403


SCENE_ID = "s9-outro"


def draw(image: Image.Image, t: float, tl: Timeline) -> None:
    draw_source_text(image, "接下来是对应的 C 语言代码")
    draw_text(ImageDraw.Draw(image), (960, 540), "递归版实现", size=64, fill=INK)


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
