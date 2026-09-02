"""Time-driven illustration for the general-order B-tree lesson shot."""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT = 1920, 1080
WHITE = (248, 250, 252)
BLUE = (163, 188, 247)
RIM = (143, 169, 232)
FILL = (59, 91, 165)
SHADOW = (23, 31, 51)
RED = (255, 112, 112)
GOLD = (245, 185, 65)
FONT = "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"
MONO = "/usr/share/fonts/TTF/DejaVuSansMono.ttf"


def _font(size: int, *, mono: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(MONO if mono else FONT, size)


def _ease(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _between(t: float, start: float, end: float) -> float:
    return _ease((t - start) / max(end - start, 0.001))


def _text(draw: ImageDraw.ImageDraw, value: str, xy: tuple[float, float], size: int, *, fill=WHITE, anchor: str = "mm", mono: bool = False) -> None:
    draw.text(xy, value, font=_font(size, mono=mono), fill=fill, anchor=anchor)


def _text_only(t: float, entries: tuple[tuple[float, str], ...], *, size: int = 42) -> Image.Image:
    """Show only the supplied manuscript text, revealing complete lines in order."""
    image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    visible = [(start, value) for start, value in entries if t >= start]
    line_height = size + 30
    first_y = 540.0 - (len(visible) - 1) * line_height / 2
    for index, (start, value) in enumerate(visible):
        _text(draw, value, (960, first_y + index * line_height), size, fill=WHITE)
    return image


def _node(draw: ImageDraw.ImageDraw, keys: tuple[str, ...], center: tuple[float, float], *, cell: float = 104.0, height: float = 84.0, border=BLUE, opacity: float = 1.0) -> None:
    if not keys or opacity <= 0:
        return
    x, y = center
    width = cell * len(keys)
    left, top = x - width / 2, y - height / 2
    rgba = lambda color: tuple(round(channel * opacity) for channel in color)
    # Opaque nested bodies deliberately avoid a player-dependent alpha path.
    draw.rounded_rectangle((left - 18, top - 18, left + width + 18, top + height + 18), radius=24, fill=rgba(SHADOW))
    draw.rounded_rectangle((left - 10, top - 10, left + width + 10, top + height + 10), radius=18, fill=rgba(border))
    draw.rounded_rectangle((left, top, left + width, top + height), radius=10, fill=rgba(FILL), outline=rgba(RIM), width=3)
    for index in range(1, len(keys)):
        divider = left + index * cell
        draw.line((divider, top + 4, divider, top + height - 4), fill=rgba(WHITE), width=3)
    for index, key in enumerate(keys):
        _text(draw, key, (left + cell * (index + 0.5), y + 1), 31, fill=rgba(WHITE), mono=True)


def _edge(draw: ImageDraw.ImageDraw, a: tuple[float, float], b: tuple[float, float], opacity: float = 1.0) -> None:
    if opacity <= 0:
        return
    rail = tuple(round(channel * opacity) for channel in BLUE)
    core = tuple(round(channel * opacity) for channel in WHITE)
    draw.line((*a, *b), fill=rail, width=14)
    draw.line((*a, *b), fill=core, width=6)


def _caption(draw: ImageDraw.ImageDraw, value: str, y: int, *, opacity: float = 1.0) -> None:
    color = tuple(round(channel * opacity) for channel in WHITE)
    _text(draw, value, (960, y), 37, fill=color)


def _ceiling(draw: ImageDraw.ImageDraw, x: float, y: float, value: str, *, fill=WHITE, size: int = 34) -> float:
    """Draw ceiling brackets explicitly because the CJK font lacks those glyphs."""
    font = _font(size)
    height = size * 0.62
    width = draw.textlength(value, font=font)
    bracket = 13.0
    top = y - height / 2
    bottom = y + height / 2
    draw.line((x, top, x, bottom), fill=fill, width=2)
    draw.line((x, top, x + bracket, top), fill=fill, width=2)
    draw.text((x + bracket + 3, y), value, font=font, fill=fill, anchor="lm")
    right = x + bracket + 5 + width
    draw.line((right, top, right, bottom), fill=fill, width=2)
    draw.line((right - bracket, top, right, top), fill=fill, width=2)
    return right + 5


def _minimum_formula(draw: ImageDraw.ImageDraw, x: float, y: float, *, example: bool = False) -> None:
    """Write the lesson's ceiling formula without substituting ASCII notation."""
    prefix = ""
    value = "8 / 2" if example else "m / 2"
    suffix = " − 1 = 3" if example else " − 1 个关键字"
    font = _font(30 if example else 34)
    draw.text((x, y), prefix, font=font, fill=WHITE, anchor="lm")
    x += draw.textlength(prefix, font=font)
    x = _ceiling(draw, x, y, value, size=30 if example else 34)
    draw.text((x, y), suffix, font=font, fill=WHITE, anchor="lm")


def render(t: float) -> Image.Image:
    """Render the manuscript text at one stable size in a central reading column."""
    image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    left = 340.0
    size = 36
    visible = [
        (0.0, "阶数决定容量，不改变机制", 220),
        (8.38, "每个节点最多有 m − 1 个关键字 m 个孩子", 300),
        (13.60, "每个节点至少有 ⌈m/2⌉ − 1 个关键字 ⌈m/2⌉ 个孩子", 370),
        (21.00, "最多 m-1 关键字。再插入一个变成 m 个但是", 470),
        (21.00, "上溢出还要推举出一个,又变成m-1个", 520),
        (31.20, "分裂时是对 m -1 关键字平分为两半。考虑到奇偶问题。", 620),
        (31.20, "最终可以是 ⌈m/2⌉ − 1", 670),
        (43.00, '上溢出之后，分裂完，两个孩子刚好就是"最低"的容量。', 770),
    ]
    for start, value, y in visible:
        if t < start:
            continue
        if "⌈" in value:
            _draw_formula_text(draw, value, y, size=size, fill=WHITE, left=left)
        else:
            _text(draw, value, (left, y), size, fill=WHITE, anchor="lm")
    return image


def _draw_formula_text(
    draw: ImageDraw.ImageDraw,
    value: str,
    y: float,
    *,
    size: int,
    fill,
    left: float | None = None,
) -> None:
    """Draw source text with hand-built ceiling/floor brackets, preserving every character."""
    font = _font(size)
    tokens: list[tuple[str, str]] = []
    cursor = 0
    while cursor < len(value):
        if value[cursor] in ("⌈", "⌊"):
            opening = value[cursor]
            closing = "⌉" if opening == "⌈" else "⌋"
            end = value.index(closing, cursor + 1)
            tokens.append((opening, value[cursor + 1:end]))
            cursor = end + 1
        else:
            end = cursor + 1
            while end < len(value) and value[end] not in ("⌈", "⌊"):
                end += 1
            tokens.append(("text", value[cursor:end]))
            cursor = end

    bracket_width = 24.0
    widths = [
        bracket_width * 2 + draw.textlength(content, font=font)
        if kind in ("⌈", "⌊")
        else draw.textlength(content, font=font)
        for kind, content in tokens
    ]
    x = 960.0 - sum(widths) / 2.0 if left is None else left
    top = y - size * 0.38
    bottom = y + size * 0.38
    for (kind, content), width in zip(tokens, widths):
        if kind == "text":
            draw.text((x, y), content, font=font, fill=fill, anchor="lm")
            x += width
            continue
        horizontal = top if kind == "⌈" else bottom
        draw.line((x + 3, top, x + 3, bottom), fill=fill, width=2)
        draw.line((x + 3, horizontal, x + 21, horizontal), fill=fill, width=2)
        x += bracket_width
        draw.text((x, y), content, font=font, fill=fill, anchor="lm")
        x += draw.textlength(content, font=font)
        draw.line((x + 3, top, x + 3, bottom), fill=fill, width=2)
        draw.line((x - 15, horizontal, x + 3, horizontal), fill=fill, width=2)
        x += bracket_width


def _page(draw: ImageDraw.ImageDraw, center: tuple[float, float], *, width: float = 550.0, height: float = 260.0, title: str = "页", filled: int = 0, total: int = 8, active: int | None = None) -> None:
    x, y = center
    left, top = x - width / 2, y - height / 2
    draw.rounded_rectangle((left, top, left + width, top + height), radius=22, outline=BLUE, width=5)
    _text(draw, title, (left + 30, top + 30), 27, anchor="lm", fill=WHITE)
    cell_w = (width - 54) / total
    cell_y = y + 26
    for index in range(total):
        cell_left = left + 27 + index * cell_w
        border = GOLD if index == active else (RIM if index < filled else SHADOW)
        fill = FILL if index < filled else (16, 22, 36)
        draw.rounded_rectangle((cell_left, cell_y - 36, cell_left + cell_w - 8, cell_y + 36), radius=7, fill=fill, outline=border, width=3)


def _disk(draw: ImageDraw.ImageDraw, center: tuple[float, float]) -> None:
    x, y = center
    for offset, color in ((-42, SHADOW), (-21, RIM), (0, BLUE)):
        draw.ellipse((x - 100, y - 56 + offset, x + 100, y + 56 + offset), fill=color, outline=WHITE if offset == 0 else color, width=3)
    _text(draw, "外存", (x, y - 4), 31)


def _arrow(draw: ImageDraw.ImageDraw, start: tuple[float, float], end: tuple[float, float], *, color=GOLD, width: int = 7) -> None:
    draw.line((*start, *end), fill=color, width=width)
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    tip = end
    left = (end[0] - ux * 21 + px * 12, end[1] - uy * 21 + py * 12)
    right = (end[0] - ux * 21 - px * 12, end[1] - uy * 21 - py * 12)
    draw.polygon((tip, left, right), fill=color)


def render_external_io(t: float) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    _text(draw, "外存读取的规律", (86, 72), 40, anchor="lm")
    _disk(draw, (960, 285))
    _edge(draw, (890, 355), (495, 530), 1.0)
    _edge(draw, (1030, 355), (1425, 530), 1.0)
    _page(draw, (470, 625), width=500, height=235, title="一两个字节", filled=1, total=8)
    _page(draw, (1450, 625), width=700, height=235, title="一大段数据", filled=8, total=8)
    _text(draw, "一次读取", (585, 430), 34, fill=WHITE)
    _text(draw, "一次读取", (1335, 430), 34, fill=WHITE)
    if t < 12.8:
        _text(draw, "读取时间几乎相同", (960, 870), 49, fill=WHITE)
    else:
        _text(draw, "读取一样多的数据，读取次数越少越好", (960, 870), 44, fill=WHITE)
    return image


def render_page_tree(t: float) -> Image.Image:
    return _text_only(t, (
        (0.0, "这正是 B 树被发明出来的场景"),
        (3.08, "磁盘一次寻址读写一整页，把一整页做成一个大节点，"),
        (6.04, "树的层数就约等于寻址次数。"),
        (8.64, "几百阶的 B 树只要三四层就能覆盖上亿条数据."),
    ), size=40)


def render_concurrent_writes(t: float) -> Image.Image:
    return _text_only(t, ((0.0, "还有一点就是 B 树的并发写入改造比较简单"),), size=44)


def render_cost_transition(t: float) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    _text(draw, "B 树的代价", (960, 500), 62, fill=WHITE)
    _text(draw, "空间利用率与节点内部工作", (960, 595), 34)
    return image


def render_costs(t: float) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    _text(draw, "B 树的代价", (86, 72), 40, anchor="lm")
    if t < 15.0:
        _page(draw, (960, 510), width=1200, height=300, title="节点内部是数组", filled=5, total=10)
        _text(draw, "插入 · 分裂 · 删除 · 合并之后", (960, 735), 34)
        if t >= 9.2:
            _text(draw, "节点不一定恰好装满", (960, 840), 43, fill=WHITE)
            _text(draw, "空槽", (1320, 570), 32, fill=WHITE)
        return image
    _page(draw, (960, 510), width=1400, height=300, title="更大的节点", filled=10, total=12, active=min(11, max(0, int((t - 15.0) * 2))))
    _text(draw, "节点内部工作也变多了", (960, 825), 43, fill=WHITE)
    return image


def render_memory_transition(t: float) -> Image.Image:
    return _text_only(t, (
        (0.0, "这B树确实不错。"),
        (5.74, "可对于内存几乎没有页代价,有没有性能更强空间还不浪费的数据结构呢？"),
        (11.5, "有的"),
    ), size=40)
