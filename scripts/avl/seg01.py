"""AVL recap segment seg01 (scene s1-def): definition page."""
from PIL import Image, ImageDraw

from engine import *  # noqa: F401,F403


SCENE_ID = "s1-def"


def draw(image: Image.Image, t: float, tl: Timeline) -> None:
    draw_ = ImageDraw.Draw(image)
    draw_mixed(draw_, 960, 330, [("AVL", ORANGE), (" 树", INK)], size=84)
    draw_mixed(draw_, 960, 470, [("AVL", ORANGE), (" 树是一棵自平衡二叉搜索树", SOFT)], size=40)
    draw_text(draw_, (960, 570), "任意节点左右子树高度差最大为 1", size=38, fill=INK)
    draw_text(draw_, (960, 720), "由 Adelson-Velsky 与 Landis 提出", size=34, fill=FAINT)


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
