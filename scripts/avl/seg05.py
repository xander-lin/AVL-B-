"""AVL recap segment seg05 (scene s4-middle)."""
from PIL import Image, ImageDraw

from engine import *  # noqa: F401,F403


SCENE_ID = "s4-middle"

RL_NAME = "avl-right-left.webm"
# Source tree-state phases (right-left double rotation) aligned to narration:
# 18-0 identify, 18-1 still analysing (lever + X weight), 18-2 the two
# rotations, 18-3 lever-identity conclusion. The analysis cue must NOT show
# the rotation already running.
RL_PHASES = {0: (0, 235), 1: (150, 234), 2: (235, 870), 3: (870, 1016)}
# "三个货物分别是 A、X 与 D" word window (global seconds).
GOODS_WINDOW = (331.9, 335.2)
# Source-pixel boxes at the identification frame (150): A, X subtree, D.
GOODS_BOXES = (
    (368, 430, 532, 594),    # A
    (748, 745, 1155, 1118),  # X subtree (x, B, C)
    (1348, 710, 1512, 874),  # D
)


def _rl_frame_index(t: float, tl: Timeline) -> int:
    cue = tl.cues[tl.find(t)]
    if cue.fi != 18:
        return 0
    frame_start, frame_end = RL_PHASES[cue.si]
    span = frame_end - frame_start
    if span <= 0:
        return frame_start
    frac = (t - cue.start) / (cue.end - cue.start)
    frac = max(0.0, min(1.0, frac))
    return int(round(frame_start + frac * span))


def _mark_goods(image: Image.Image) -> None:
    draw = ImageDraw.Draw(image)
    for box in GOODS_BOXES:
        mapped = (
            source_point(RL_NAME, (box[0], box[1])),
            source_point(RL_NAME, (box[2], box[3])),
        )
        ring(draw, (mapped[0][0], mapped[0][1], mapped[1][0], mapped[1][1]))


def _draw_hanging_node(
    draw: ImageDraw.ImageDraw,
    point: Point,
    *,
    connected: bool = True,
) -> None:
    """Draw the middle cargo, optionally detached from the yellow mount."""
    x, y = point
    glow_node(draw, (x, y), "", ORANGE, ORANGE_GLOW, radius=25)

    node_y = y + 380.0 if connected else y + 240.0
    if connected:
        line(draw, (x, y + 27.0), (x, node_y - 85.0), NODE_RIM, width=7)
        line(draw, (x, y + 27.0), (x, node_y - 85.0), INK, width=3)
    radius = 85.0
    for grow, share in ((18.0, 0.10), (11.0, 0.16), (6.0, 0.28), (3.0, 0.50)):
        draw.ellipse(
            (x - radius - grow, node_y - radius - grow, x + radius + grow, node_y + radius + grow),
            fill=blend(INDIGO_GLOW, share),
        )
    draw.ellipse(
        (x - radius, node_y - radius, x + radius, node_y + radius),
        fill=INDIGO,
        outline=NODE_RIM,
        width=4,
    )


def _draw_tilt(image: Image.Image, t: float, tl: Timeline) -> None:
    """天平倾斜演示：中间重 → 向左倾斜滑落 → 回平 → 向右倾斜滑落。"""
    draw = ImageDraw.Draw(image)
    if t < tl.gs(15, 1):
        draw_text(draw, (960, 200), "如果天平中间那个货物更重，会怎样？", size=40, fill=INK)
    if t < tl.gs(15, 3):
        u = ease((t - tl.gs(15, 2)) / max(tl.gs(15, 3) - tl.gs(15, 2), 1e-6))
        angle, cargo_t = -0.30 * u, 0.5 - 0.24 * u
    else:
        u = ease((t - tl.gs(15, 3)) / max(tl.gs(16, 0) - tl.gs(15, 3), 1e-6))
        angle, cargo_t = 0.30 * u, 0.5 + 0.24 * u
    draw_beam(draw, angle, 0.5)
    cargo_point = beam_points(angle, cargo_t)[2]
    _draw_hanging_node(draw, cargo_point)


def draw(image: Image.Image, t: float, tl: Timeline) -> None:
    if t < tl.gs(15, 0):
        draw_chapter_title(image, "例子二 · 中间失衡")
    elif t < tl.gs(16, 0):
        _draw_tilt(image, t, tl)
    elif t < tl.gs(17, 0):
        draw = ImageDraw.Draw(image)
        draw_text(draw, (960, 390), "那没办法，你需要先把中间的货物给移到两边，", size=38, fill=INK)
        draw_text(draw, (960, 500), "然后再通过抬起更重的那一端，来保持平衡。", size=38, fill=INK)
    elif t < tl.gs(18, 0):
        draw = ImageDraw.Draw(image)
        draw_text(draw, (960, 350), "所以是分两步，第一步把货物转移。", size=42, fill=INK)
        draw_text(draw, (960, 460), "第二步正常旋转天平。", size=42, fill=INK)
        draw_text(draw, (960, 570), "把货物转移也可以通过旋转来改变重心来实现：", size=36, fill=SOFT)
    else:
        draw_source_media(
            image,
            RL_NAME,
            t,
            tl.gs(18, 0),
            loop=False,
            source_caption=True,
            frame_index=_rl_frame_index(t, tl),
        )
        if GOODS_WINDOW[0] <= t <= GOODS_WINDOW[1]:
            _mark_goods(image)


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
