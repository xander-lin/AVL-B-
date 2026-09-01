"""AVL recap segment seg03 (scene s2-lever)."""
from PIL import Image, ImageDraw

from engine import *  # noqa: F401,F403
import engine as avl_engine


SCENE_ID = "s2-lever"

SETUP_TEXT = (
    "二叉树有一根天平，天平总共有三个挂载货物的地方。\n"
    "天平的左边、天平的中间、天平的右边。\n"
    "旋转时只用旋转天平，来平衡三个货物。"
)


def _source_point(name: str, point: tuple[float, float]) -> tuple[float, float]:
    """Map a point from the held source frame into the render canvas."""
    source = avl_engine._source_frames(name)[-1]
    with Image.open(source) as raw:
        frame = avl_engine._fit_source(raw.convert("RGBA"))
    scale = frame.width / raw.width
    return (
        (WIDTH - frame.width) / 2.0 + point[0] * scale,
        210 + (780 - frame.height) / 2.0 + point[1] * scale,
    )


def _ring(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float]) -> None:
    draw.ellipse(tuple(round(value) for value in box), outline=SKY_BLUE, width=7)
    inset = tuple(round(value + offset) for value, offset in zip(box, (9, 9, -9, -9)))
    draw.ellipse(inset, outline=INK, width=2)


def _draw_setup_text(image: Image.Image) -> None:
    """Keep the three-sentence scale setup as one readable visual block."""
    draw = ImageDraw.Draw(image)
    for y, line_text in zip((118, 168, 218), SETUP_TEXT.splitlines()):
        draw_text(draw, (960, y), line_text, size=30, fill=INK)


def _draw_balance_question(image: Image.Image) -> None:
    """Use two fixed lines so the question never wraps over the tree."""
    draw = ImageDraw.Draw(image)
    draw_text(draw, (960, 118), "关键问题来了：天平位置怎么找呢？", size=34, fill=INK)
    draw_text(draw, (960, 170), "哪边树高，哪边更重，哪边就是天平！", size=34, fill=INK)


def _mark_balance_and_cargoes(image: Image.Image, cue_index: int) -> None:
    """Select the 5--9 balance, then circle its three source subtrees."""
    draw = ImageDraw.Draw(image)
    name = "avl-example-left-rotation.webm"
    nodes = {
        5: _source_point(name, (379.5, 369.4)),
        9: _source_point(name, (659.5, 69.5)),
        3: _source_point(name, (149.5, 649.4)),
        6: _source_point(name, (609.5, 649.4)),
        14: _source_point(name, (929.3, 339.3)),
        17: _source_point(name, (1059.5, 609.4)),
    }
    if cue_index == 0:
        for key in (5, 9):
            x, y = nodes[key]
            _ring(draw, (x - 55, y - 55, x + 55, y + 55))
        x1, y1 = nodes[5]
        x2, y2 = nodes[9]
        line(draw, (x1, y1), (x2, y2), SKY_BLUE, width=9)
        draw_top_key(draw, "这里选中的 5—9 就是天平", y=74, size=34)
    elif cue_index == 1:
        x, y = nodes[3]
        _ring(draw, (x - 78, y - 78, x + 78, y + 78))
        draw_top_key(draw, "最左边挂载的子树是 3", y=74, size=34)
    elif cue_index == 2:
        x, y = nodes[6]
        _ring(draw, (x - 78, y - 78, x + 78, y + 78))
        draw_top_key(draw, "中间挂载的子树是 6", y=74, size=34)
    elif cue_index == 3:
        x1, y1 = nodes[14]
        x2, y2 = nodes[17]
        _ring(draw, (x1 - 92, y1 - 92, x2 + 92, y2 + 92))
        draw_top_key(draw, "最右边挂载的子树是 14→17", y=74, size=34)
    elif cue_index == 8:
        draw_text(
            draw,
            (960, 74),
            "左、中、右顺序不变，中序遍历顺序不变",
            size=31,
            fill=INK,
        )


def _mark_left_or_right_balance(image: Image.Image, cue_index: int) -> None:
    """Highlight the candidate balance while the narration names each one."""
    draw = ImageDraw.Draw(image)
    # These are the node centers after the source's 1450x1040 transparent
    # canvas is fitted into the 1920x1080 render canvas.
    nodes = {
        5: (918.0, 270.0),
        9: (1143.0, 480.0),
        3: (694.0, 480.0),
    }
    key = 3 if cue_index == 4 else 9
    for node_key in (5, key):
        x, y = nodes[node_key]
        _ring(draw, (x - 55, y - 55, x + 55, y + 55))
    x1, y1 = nodes[5]
    x2, y2 = nodes[key]
    line(draw, (x1, y1), (x2, y2), SKY_BLUE, width=9)


def _example_title_end(tl: Timeline) -> float:
    """End the title after the recorded "例子一，左右失衡" phrase."""
    item, _ = tl.sources[("new", "example-one")]
    words = item["segments"][0].get("words") or []
    if len(words) < 6:
        return tl.gs(3, 0)
    return tl.word_windows("new", "example-one", 0, len(words))[5][1]


def draw(image: Image.Image, t: float, tl: Timeline) -> None:
    title_start = tl.gs(3, 0)
    title_end = _example_title_end(tl)
    if t < title_start:
        draw = ImageDraw.Draw(image)
        draw_top_key(
            draw,
            "在失衡的时候，AVL 树通过旋转操作保持平衡。\n"
            "那么它是如何旋转的呢？两个例子带你彻底了解清楚。",
            y=360,
            size=38,
        )
    elif t < title_end:
        # Keep the title aligned with the spoken "例子一，左右失衡" phrase.
        draw_chapter_title(image, "例子一 · 左右失衡")
    elif t < tl.gs(5, 0):
        draw_source_media(image, "avl-example-one.svg", t, tl.gs(3, 0), loop=False)
        draw_corner_label(image, "例子一")
        if tl.gs(4, 1) <= t < tl.gs(5, 0):
            _draw_setup_text(image)
    else:
        if t >= tl.gs(7, 0):
            # Identifying the balance starts from the pre-rotation imbalance.
            draw_source_media(
                image,
                "avl-example-left-rotation.webm",
                tl.gs(5, 0),
                tl.gs(5, 0),
                loop=False,
                source_caption=True,
            )
        else:
            draw_source_media(
                image,
                "avl-example-left-rotation.webm",
                t,
                tl.gs(5, 0),
                loop=False,
                play_duration=tl.ge(5, 0) - tl.gs(5, 0),
                source_caption=True,
            )
        draw_corner_label(image, "例子一")
        cue = tl.cues[tl.find(t)]
        if cue.fi == 6:
            _mark_balance_and_cargoes(image, cue.si)
        elif cue.fi == 7:
            _draw_balance_question(image)
            if cue.si >= 4:
                # The final cue says "左边一撇 5-3，右边一撇 5-9".
                # Keep the corresponding candidate selected as each phrase is spoken.
                _mark_left_or_right_balance(
                    image,
                    4 if t - cue.start < 2.30 else 5,
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
