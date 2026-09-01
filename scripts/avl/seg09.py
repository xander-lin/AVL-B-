"""AVL recap segment seg09 (scene s8-factor)."""
from PIL import Image, ImageDraw

from engine import *  # noqa: F401,F403


SCENE_ID = "s8-factor"


TEXT_PROGRAM_NOTE = (
    "补充说明：人眼判断时只需观察哪一侧更高，但实际编写代码时，代码没有眼，需要引入平衡因子来判断树高。",
    "平衡因子就是左子树高度减去右子树高度。",
    "AVL 树要求每个节点的平衡因子只取 -1、0、1。",
)
TEXT_LEFT_HEAVY = (
    "- 根节点的平衡因子 > 1，左边沉。再读左孩子的平衡因子：左孩子的平衡因子 >= 0，左边失衡；"
    "左孩子的平衡因子 < 0，说明中间失衡，先对左孩子左旋，再对根节点右旋。"
)
TEXT_RIGHT_HEAVY = (
    "- 根节点的平衡因子 < -1，右边沉。再读右孩子的平衡因子：右孩子的平衡因子 <= 0，右边失衡；"
    "右孩子的平衡因子 > 0，说明中间失衡，先对右孩子右旋，再对根节点左旋。"
)
TEXT_FOUR_NAMES = (
    "传统教材把这两个问题排列组合成左左、右右、左右、右左四个名字，我们其实不过是先分成是两边沉还是中间沉两种情况，"
    "每种情况内部再各分左右。"
)


def _wrapped_lines(text: str, size: int = 39, width: float = 1660.0) -> list[str]:
    """Wrap the original manuscript text without changing its wording."""
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and text_w(candidate, size) > width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _draw_text_page(draw: ImageDraw.ImageDraw, text: str, *, top: float = 270.0) -> None:
    lines = _wrapped_lines(text)
    line_height = 58.0
    start = top - (len(lines) - 1) * line_height / 2.0
    for index, line_text in enumerate(lines):
        draw_text(draw, (960, start + index * line_height), line_text, size=39, fill=INK)


def _draw_program_note(draw: ImageDraw.ImageDraw) -> None:
    """Keep each manuscript sentence intact as one centered line."""
    line_height = 78.0
    first_y = 350.0
    for index, sentence in enumerate(TEXT_PROGRAM_NOTE):
        size = 39
        while size > 26 and text_w(sentence, size) > 1760.0:
            size -= 1
        draw_text(draw, (960, first_y + index * line_height), sentence, size=size, fill=INK)


def draw(image: Image.Image, t: float, tl: Timeline) -> None:
    draw = ImageDraw.Draw(image)
    title_start = tl.program_title_start or tl.gs(25, 0)
    audio_start = tl.program_audio_start or tl.gs(25, 0)
    if title_start <= t < audio_start:
        draw_chapter_title(image, "编程")
    elif t < tl.gs(26, 0):
        _draw_program_note(draw)
    elif t < tl.gs(26, 1):
        _draw_text_page(draw, TEXT_LEFT_HEAVY)
    elif t < tl.gs(27, 0):
        _draw_text_page(draw, TEXT_RIGHT_HEAVY)
    else:
        _draw_text_page(draw, TEXT_FOUR_NAMES)


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
