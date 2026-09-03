#!/usr/bin/env python3
"""Render the red-black lesson shots from the narration in audio/rbt.

Each shot pairs its recordings with exactly the media the manuscript embeds
for that passage: the manuscript's own SVG figures, its performance table,
and its videos.  Nothing else is invented.  SVG figures are converted to RGBA
PNG by rsvg-convert and composited onto the black canvas; no transparent
video is ever produced.
"""
from __future__ import annotations

import argparse
import functools
import json
import math
import subprocess
import sys
import wave
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "avl"))
import engine as avl  # noqa: E402

ASR_JSON = ROOT / "outputs" / "rbt-prep" / "rbt-asr.json"
OUT = ROOT / "outputs" / "rbt-video"
WIDTH, HEIGHT, FPS = avl.WIDTH, avl.HEIGHT, avl.FPS
SVG_CACHE = Path("/tmp/opencode/rbt-svg")

# Batch 1: intro and the encoding chapter.  Batch 2: insertion.  Batch 3: deletion.
# The user dropped the shot for recording 3 (二叉化 paragraph) and the shot
# for recording 11 (transition): their numbering gaps are intentional.
SHOT_AUDIO: dict[int, list[int]] = {
    1: [1],
    3: [5],
    4: [7],
    6: [13],
    7: [17],
    8: [21, 29],
    9: [33],
    10: [41],
    11: [45],
    12: [47],
    13: [49],
    14: [55],
    15: [57],
    16: [61],
    17: [65],
    18: [67],
    19: [69],
    20: [75],
    21: [79],
    22: [83],
    23: [89],
    24: [95],
    25: [97],
    26: [99],
    27: [101],
    28: [105],
    29: [107],
    30: [111],
    31: [115],
}


def load_asr() -> dict[int, dict]:
    payload = json.loads(ASR_JSON.read_text(encoding="utf-8"))
    return {item["recording_index"]: item for item in payload["files"]}


class Recording:
    def __init__(self, index: int, offset: float, payload: dict):
        self.index = index
        self.offset = offset
        self.path = Path(payload["audio"])
        with wave.open(str(self.path), "rb") as handle:
            self.duration = handle.getnframes() / handle.getframerate()
        self.segments = payload["segments"]


def shot_recordings(shot: int, asr: dict[int, dict]) -> list[Recording]:
    items = []
    offset = 0.0
    for index in SHOT_AUDIO[shot]:
        recording = Recording(index, offset, asr[index])
        items.append(recording)
        offset += recording.duration
    return items


def shot_duration(recordings: list[Recording]) -> float:
    return sum(item.duration for item in recordings)


# ---------------------------------------------------------------- SVG assets
def svg_png(name: str, zoom: float = 3.0) -> Image.Image:
    """Convert an SVG asset to RGBA PNG with rsvg-convert (the dedicated
    conversion layer), then hand the transparent raster to the compositor."""
    SVG_CACHE.mkdir(parents=True, exist_ok=True)
    stem = f"{Path(name).stem}@{zoom:g}"
    target = SVG_CACHE / f"{stem}.png"
    marker = SVG_CACHE / f"{stem}.ready"
    source = ROOT / "assets" / name
    signature = f"{source.stat().st_size}:{source.stat().st_mtime_ns}"
    if not marker.exists() or marker.read_text(encoding="utf-8") != signature:
        subprocess.run(
            ["rsvg-convert", "--zoom", str(zoom), str(source), "-o", str(target)],
            check=True,
        )
        marker.write_text(signature, encoding="utf-8")
    return _cached_png(str(target))


@functools.lru_cache(maxsize=64)
def _cached_png(path: str) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


def fit(frame: Image.Image, max_width: float, max_height: float) -> Image.Image:
    scale = min(max_width / frame.width, max_height / frame.height)
    size = (max(1, round(frame.width * scale)), max(1, round(frame.height * scale)))
    return frame.resize(size, Image.Resampling.LANCZOS)


def paste_center(image: Image.Image, frame: Image.Image, cx: float, cy: float, alpha: float = 1.0) -> None:
    box = (round(cx - frame.width / 2), round(cy - frame.height / 2))
    if alpha >= 0.999:
        image.paste(frame, box, frame)
        return
    transparent = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    faded = Image.blend(transparent, frame, alpha)
    image.paste(faded, box, faded)


# ------------------------------------------------------------- text helpers
def reading_block(draw: ImageDraw.ImageDraw, text: str | list[str], *, y_center: float, size: int = 40,
                  width: float = 1500.0, color=avl.INK) -> None:
    """Left-aligned lines whose block sits at the horizontal center.  A string
    is wrapped mechanically; a list is displayed verbatim so line breaks stay
    under the caller's semantic control."""
    lines = text if isinstance(text, list) else avl.wrap_lines(text, size, width)
    line_height = size + 24
    block_width = max(avl.text_w(line, size) for line in lines)
    x = (WIDTH - block_width) / 2
    top = y_center - (len(lines) - 1) * line_height / 2
    for index, line in enumerate(lines):
        avl.draw_text(draw, (x, top + index * line_height), line, size=size, fill=color, anchor="lm")


def one_line(draw: ImageDraw.ImageDraw, text: str, *, y: float, size: int = 38, color=avl.SOFT) -> None:
    avl.draw_text(draw, (WIDTH / 2, y), text, size=size, fill=color)


def title_line(draw: ImageDraw.ImageDraw, text: str, *, y: float, size: int, color=avl.INK) -> None:
    avl.draw_text(draw, (WIDTH / 2, y), text, size=size, fill=color)


# ------------------------------------------------------------- table drawing
TABLE_HEADER = ("结构", "操作", "时间", "峰值节点数", "载荷大小", "单节点大小")
TABLE_ROWS = (
    ("传统四阶 B 树", "插入 10,000,000 个键", "11602.998 ms", "5,592,056", "32 B", "152 B"),
    ("红黑树", "插入 10,000,000 个键", "7346.296 ms", "10,000,000", "32 B", "64 B"),
    ("传统四阶 B 树", "查找 20,000,000 次", "6150.532 ms", "5,592,056", "32 B", "152 B"),
    ("红黑树", "查找 20,000,000 次", "6836.989 ms", "10,000,000", "32 B", "64 B"),
    ("传统四阶 B 树", "删除 10,000,000 个键", "11232.327 ms", "5,592,056", "32 B", "152 B"),
    ("红黑树", "删除 10,000,000 个键", "11017.106 ms", "10,000,000", "32 B", "64 B"),
)


@functools.lru_cache(maxsize=1)
def render_table() -> Image.Image:
    size = 34
    font = avl.sans(size)
    pad_x = 42.0
    probe = Image.new("RGB", (8, 8))
    measure = ImageDraw.Draw(probe)
    cells = [TABLE_HEADER, *[list(row) for row in TABLE_ROWS]]
    right_aligned = {1, 2, 3, 4, 5}
    widths = []
    for column in range(6):
        widest = max(measure.textlength(row[column], font=font) for row in cells)
        widths.append(widest + pad_x * 2)
    header_h, row_h = 92.0, 84.0
    table_w = sum(widths)
    table_h = header_h + row_h * len(TABLE_ROWS)
    image = Image.new("RGBA", (round(table_w), round(table_h)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    x = 0.0
    for index, column in enumerate(widths):
        center = x + column / 2
        anchor = "rm" if index in right_aligned else "lm"
        px = x + column - pad_x if index in right_aligned else x + pad_x
        avl.draw_text(draw, (px, header_h / 2), TABLE_HEADER[index], size=size, anchor=anchor)
        for row_index, row in enumerate(TABLE_ROWS):
            y = header_h + row_h * row_index + row_h / 2
            color = avl.INK if row[0] == "红黑树" else avl.SOFT
            avl.draw_text(draw, (px, y), row[index], size=size, anchor=anchor, fill=color)
        x += column
    ink = avl.blend(avl.INK, 0.9) + (255,)
    faint = (70, 78, 92, 255)
    draw.line((0, header_h, table_w, header_h), fill=ink, width=3)
    draw.line((0, table_h, table_w, table_h), fill=ink, width=3)
    for row_index in range(1, len(TABLE_ROWS)):
        y = header_h + row_h * row_index
        draw.line((0, y, table_w, y), fill=faint, width=2)
    return image


def draw_table(image: Image.Image, t: float, *, appear: float = 0.0) -> None:
    alpha = avl.ease((t - appear) / 0.5) if appear > 0 else 1.0
    if alpha <= 0.01:
        return
    table = render_table()
    if table.width > 1840:
        scale = 1840 / table.width
        table = table.resize((round(table.width * scale), round(table.height * scale)), Image.Resampling.LANCZOS)
    paste_center(image, table, WIDTH / 2, 470.0, alpha)
    avl.draw_text(
        ImageDraw.Draw(image),
        (WIDTH / 2 - table.width / 2, 130.0),
        "（内存，固定 CPU 频率，非递归）",
        size=30,
        fill=avl.SOFT,
        anchor="lm",
        opacity=alpha,
    )


# ------------------------------------------------------------------- drawers
def draw_shot01(image: Image.Image, t: float) -> None:
    title_line(ImageDraw.Draw(image), "红黑树是 4 阶 B 树的二叉编码", y=540.0, size=72)


def draw_shot02(image: Image.Image, t: float) -> None:
    reading_block(ImageDraw.Draw(image),
                  "二叉化，把原本的数组也变成了一个一个的节点，通过节点与指针解决了"
                  " 4 阶 B 树空间利用率的问题。并且所有操作都是对二叉树节点的操作，"
                  "没有内部是数组这个概念了，语义更统一，性能也更高了。", y_center=540.0)


def draw_shot03(image: Image.Image, t: float) -> None:
    draw_table(image, t, appear=0.05)


def draw_shot04(image: Image.Image, t: float) -> None:
    draw_table(image, t)
    one_line(ImageDraw.Draw(image), "这里我们使用的是 32B 大小的载荷。越大的载荷，B 树空间浪费越明显。", y=940.0)


def draw_shot05(image: Image.Image, t: float) -> None:
    reading_block(ImageDraw.Draw(image),
                  "接下来我们就来看看它是如何进行二叉化的。但在这之前，"
                  "最好先观看我对 AVL 树以及 B 树的讲解，否则推举、旋转之类的操作可能听不懂。",
                  y_center=540.0)


def draw_shot06(image: Image.Image, t: float) -> None:
    title_line(ImageDraw.Draw(image), "从 2-3-4 节点到红黑节点", y=540.0, size=64)


ENCODING_STEPS = (
    ("rb-encoding-single.svg", "[b] 直接编码成黑色节点 b", 0.0, 5.58),
    ("rb-encoding-pair.svg", "[a,b] 可以选 a 或 b 作为黑色主体，另一个关键字作为红色孩子", 5.58, 19.18),
    ("rb-encoding-triple.svg", "[a,b,c] 可以编码为黑色主体 b，左侧红色孩子 a，右侧红色孩子 c", 19.18, 1e9),
)


def draw_shot07(image: Image.Image, t: float) -> None:
    current = next(step for step in ENCODING_STEPS if step[2] <= t < step[3])
    index = ENCODING_STEPS.index(current)
    fade = 0.4
    alpha = avl.ease((t - current[2]) / fade) if index > 0 else 1.0
    if index > 0 and alpha < 0.999:
        previous = ENCODING_STEPS[index - 1]
        paste_center(image, fit(svg_png(previous[0]), 1500, 560), WIDTH / 2, 610.0)
    paste_center(image, fit(svg_png(current[0]), 1500, 560), WIDTH / 2, 610.0, alpha)
    avl.draw_top_key(ImageDraw.Draw(image), current[1], y=300.0, size=42)
    avl.draw_corner_label(image, "每一个 B 树节点内部只有一个是黑节点")


OVERFLOW_ROW_SWITCH = 11.861 + 5.37  # “……拿第三个举例” into recording 29

# shot09: the morph plays WITH the narration (starting at the narration onset)
# so voice and animation stay synchronized, then holds the terminal tree.
MORPH_START = 0.12
MORPH_PLAY = 8.0
SHOT_TAIL = {9: MORPH_PLAY}


def draw_shot08(image: Image.Image, t: float) -> None:
    fade = 0.4
    if t < OVERFLOW_ROW_SWITCH:
        paste_center(image, fit(svg_png("rb-encoding-overflow.svg"), 1760, 640), WIDTH / 2, 580.0)
        alpha = 1.0
    else:
        alpha = avl.ease((t - OVERFLOW_ROW_SWITCH) / fade)
        if alpha < 0.999:
            paste_center(image, fit(svg_png("rb-encoding-overflow.svg"), 1760, 640), WIDTH / 2, 580.0)
        paste_center(image, fit(svg_png("rb-encoding-overflow-3.svg"), 1100, 620), WIDTH / 2, 580.0, alpha)
    avl.draw_top_key(ImageDraw.Draw(image),
                     "一个 4 个关键字的节点如何表示呢？也就是刚好符合上溢出的情况",
                     y=170.0, size=42)


def asset_frames(name: str, *, scale: str | None = None) -> list[Path]:
    """Extract an alpha_mode=1 WebM to RGBA PNGs.

    The native vp9 decoder discards the auxiliary alpha plane, so extraction
    must pin libvpx-vp9 and request an alpha-capable output format.
    """
    source = ROOT / "assets" / name
    target = Path("/tmp/opencode/rbt-frames") / Path(name).stem / (scale or "native")
    marker = target / ".ready"
    signature = f"{source.stat().st_size}:{source.stat().st_mtime_ns}:{scale or ''}"
    if not marker.exists() or marker.read_text(encoding="utf-8") != signature:
        target.mkdir(parents=True, exist_ok=True)
        for old in target.glob("*.png"):
            old.unlink()
        command = ["ffmpeg", "-y", "-loglevel", "error", "-c:v", "libvpx-vp9", "-i", str(source)]
        if scale:
            command += ["-vf", f"scale={scale}"]
        command += ["-pix_fmt", "rgba", str(target / "%06d.png")]
        subprocess.run(command, check=True)
        marker.write_text(signature, encoding="utf-8")
    frames = sorted(target.glob("*.png"))
    assert frames, name
    return frames


def morph_frames() -> list[Path]:
    return asset_frames("rb-encoding.webm")


def draw_shot09(image: Image.Image, t: float) -> None:
    frames = morph_frames()
    count = len(frames)
    if t < MORPH_START:
        index = 0
    elif t >= MORPH_START + MORPH_PLAY:
        index = count - 1
    else:
        index = min(count - 1, round((t - MORPH_START) / MORPH_PLAY * (count - 1)))
    frame = _cached_png(str(frames[index]))
    paste_center(image, avl._fit_source(frame, 1640, 840), WIDTH / 2, 570.0)


def draw_properties_header(image: Image.Image) -> None:
    title_line(ImageDraw.Draw(image), "红黑树有四个性质：左根右，根叶黑，不红红，黑路同", y=110.0, size=44)


def draw_shot10(image: Image.Image, t: float) -> None:
    draw_properties_header(image)
    reading_block(ImageDraw.Draw(image), "左根右是二叉搜索树就有的特性。4 阶 B 树二叉编码后，"
                                         "它是二叉搜索树，符合二叉搜索树的特性——左根右。",
                  y_center=620.0)


def draw_shot11(image: Image.Image, t: float) -> None:
    draw_properties_header(image)
    draw = ImageDraw.Draw(image)
    title_line(draw, "黑路同", y=320.0, size=56)
    reading_block(draw, [
        "黑路同是我们通过 4 阶 B 树观察到的特性，这个特性同时保证了对 B 树的下溢出调整。",
        "B 树的所有叶节点高度相同，故而黑色节点的高度都相同——黑路同。",
        "4 阶 B 树最少一个关键字，删除黑色节点下溢出，不满足黑路同。",
    ], y_center=690.0, size=38)


def draw_shot12(image: Image.Image, t: float) -> None:
    draw_properties_header(image)
    draw = ImageDraw.Draw(image)
    title_line(draw, "不红红", y=320.0, size=56)
    reading_block(draw, [
        "不红红是为了 B 树的上溢出调整。",
        "容量为 3 的 B 树节点插入红节点，违反不红红，上溢出。",
        "黑节点的左右被染成红色，红色节点中间始终隔着一个黑节点——不红红。",
    ], y_center=690.0, size=38)


def draw_shot13(image: Image.Image, t: float) -> None:
    draw_properties_header(image)
    draw = ImageDraw.Draw(image)
    title_line(draw, "根叶黑", y=320.0, size=56)
    reading_block(draw, [
        "根叶黑是为了红黑染色语义的完备性，能大幅简化对红黑树插入删除规则的描述。",
        "这让每个节点都有叔叔。",
    ], y_center=680.0)


# ------------------------------------------------- insertion chapter (batch 2)
# rb_insert() in generate_tree_media.py builds 1550 frames @30fps.  These are
# the frame ranges of each narration-relevant insertion phase inside the video.
INSERT_SEGMENTS = {
    "52": (36, 182),      # 父黑直挂
    "54": (182, 430),     # 插入、窝回、单旋、变色（LL/RR）
    "22": (430, 712),     # 插入、窝回、双旋、变色（LR/RL）
    "37": (712, 1256),    # 插入、窝回、38/40/49 逐层推举（上溢出）
    "50": (1256, 1550),   # 插入 50，52 推举后变色
}
INSERT_BIG_Y = 400.0

# 录音是一条一条的，镜头内可以在句子边界插入静音给读者反应时间：
# (镜头 -> [(录音内容时间点, 停顿时长)])。停顿处画面冻结，让画中画/图示
# 先出现被看见，解说随后才开始。
AUDIO_PAUSES: dict[int, list[tuple[float, float]]] = {
    15: [(14.97, 2.0)],   # 画中画先出现，读者先看结构，再听“插入54后……”
    16: [(9.63, 2.0)],
    17: [(25.44, 1.6)],   # 解集图先出现，再听“它肯定是解集中的一种”
}


def pause_total(shot: int) -> float:
    return sum(dur for _, dur in AUDIO_PAUSES.get(shot, []))


def content_time(shot: int, t: float) -> float:
    """Map shot time back to narration-content time; frozen at each pause."""
    acc = 0.0
    for at, dur in AUDIO_PAUSES.get(shot, []):
        split_shot = at + acc
        if t < split_shot:
            return t
        if t < split_shot + dur:
            return at
        t -= dur
        acc += dur
    return t

# 旁白讲到哪一段，大视频就播到哪一段；该段播完后播放对应的画中画演示。
# 画中画放在插入位置的另一侧、与操作行同一水平高度，紧贴操作区方便左右对比。
INSERT_SHOT_PACING = {
    # shot,        seg range,      big window,  pip name,          pip start, pip center
    15: ((36, 430), 14.97, "rb-ll-rr.webm", 14.97, (820.0, 560.0)),    # 插入点在右 → 画中画紧贴其左
    16: ((430, 712), 282 / 30, "rb-lr-rl.webm", 282 / 30, (740.0, 560.0)),  # 插入点在左 → 画中画紧贴其右
    17: ((712, 1256), 544 / 30, "rb-overflow.webm", 544 / 30, (1100.0, 560.0)),
    19: ((1256, 1550), None, None, None, None),  # natural pace, no PiP
}


def insert_frame(index: int) -> Image.Image:
    frames = asset_frames("rb-insert-v4.webm", scale="1880:-2")
    index = max(0, min(index, len(frames) - 1))
    return _cached_png(str(frames[index]))


def draw_pip(image: Image.Image, name: str, t: float, pip_start: float, center: tuple[float, float],
             alpha: float = 1.0) -> None:
    if alpha <= 0.01:
        return
    frames = asset_frames(name)
    index = max(0, min(int((t - pip_start) * 30.0), len(frames) - 1))
    frame = fit(_cached_png(str(frames[index])), 560, 480)
    px, py = center
    x, y = round(px - frame.width / 2), round(py - frame.height / 2)
    # the PiP card gets a pure black background so the transparent regions of
    # the demo never show the big video through
    if alpha >= 0.999:
        card = frame
        outline = (70, 78, 92)
    else:
        card = Image.blend(Image.new("RGBA", frame.size, (0, 0, 0, 0)), frame, alpha)
        outline = avl.blend((70, 78, 92), alpha)
    draw = ImageDraw.Draw(image)
    draw.rectangle((x, y, x + card.width, y + card.height), fill=(0, 0, 0))
    image.paste(card, (x, y), card)
    draw.rectangle((x - 2, y - 2, x + card.width + 1, y + card.height + 1),
                   outline=outline, width=2)


@functools.lru_cache(maxsize=1)
def _audio_durations() -> dict[int, float]:
    asr = load_asr()
    return {shot: shot_duration(shot_recordings(shot, asr)) for shot in SHOT_AUDIO}


def draw_insert_shot(image: Image.Image, shot: int, t: float) -> None:
    (seg_start, seg_end), big_window, pip_name, pip_start, pip_center = INSERT_SHOT_PACING[shot]
    ct = content_time(shot, t)
    if big_window is None:
        src = seg_start + min(ct * 30.0, seg_end - 1 - seg_start)
        paste_center(image, insert_frame(int(src)), WIDTH / 2, INSERT_BIG_Y)
        return
    span = seg_end - seg_start
    if ct < big_window:
        src = seg_start + (ct / big_window) * span
        paste_center(image, insert_frame(min(int(src), seg_end - 1)), WIDTH / 2, INSERT_BIG_Y)
        return
    paste_center(image, insert_frame(seg_end - 1), WIDTH / 2, INSERT_BIG_Y)
    if pip_name is not None and ct >= pip_start:
        # 无下一个调整时，画中画一直留到镜头结束：播完保持末帧，最后 1.2s 渐隐。
        duration = _audio_durations()[shot] + pause_total(shot)
        alpha = 1.0 if t <= duration - 1.2 else avl.ease((duration - t) / 1.2)
        draw_pip(image, pip_name, ct, pip_start, pip_center, alpha)
    if shot == 17 and ct >= 25.44:
        # “红黑树不管如何推举，肯定仍然是所有推举解集中的一种”——
        # 下方空白处的点与集合关系图：圈代表解集，点代表红黑树采用的那个解。
        alpha = avl.ease((ct - 25.44) / 0.6)
        draw_solution_set(image, alpha)


def draw_solution_set(image: Image.Image, alpha: float) -> None:
    if alpha <= 0.01:
        return
    draw = ImageDraw.Draw(image)
    ink = avl.blend(avl.INK, alpha)
    soft = avl.blend(avl.SOFT, alpha)
    center = (700.0, 912.0)
    rx, ry = 160.0, 90.0
    box = (center[0] - rx, center[1] - ry, center[0] + rx, center[1] + ry)
    draw.ellipse(box, outline=ink, width=4)
    dot = (center[0], center[1] - 25.0)
    red = avl.blend((220, 38, 38), alpha)
    draw.ellipse((dot[0] - 13, dot[1] - 13, dot[0] + 13, dot[1] + 13), fill=red)
    avl.draw_text(draw, (900, center[1]), "推举解集", size=30, fill=soft, anchor="lm")
    avl.draw_text(draw, (center[0], center[1] + 40), "红黑树采用的解", size=24, fill=soft)


def draw_shot14(image: Image.Image, t: float) -> None:
    draw = ImageDraw.Draw(image)
    title_line(draw, "插入：分裂在二叉接口中的表现", y=430.0, size=64)
    reading_block(draw, "B 树的每个节点组都已经有黑节点，所以我们插入时肯定插入的是红节点。",
                  y_center=650.0)


# Recording 67 explains the recolour rules on the repeatedly-promoting case,
# so the shot replays the 37-cascade's promote/recolor moments instead of a
# text slide.  Each cue maps a narration window to a source frame range
# (f0 == f1 means hold that state).
SHOT18_CUES = (
    (0.00, 0.66, 850, 850),
    (0.66, 3.33, 852, 932),    # 38 推举并变红，36/39 变黑
    (3.33, 10.20, 932, 932),
    (10.20, 12.87, 962, 1042),  # 40 推举并变红，35/45 变黑
    (12.87, 17.50, 1042, 1042),
    (17.50, 21.03, 1072, 1178),  # 49 升新根：先红，落定变黑，30/70 变黑
    (21.03, 23.60, 1178, 1255),
    (23.60, 32.47, 1255, 1255),
)


def draw_shot18(image: Image.Image, t: float) -> None:
    cue = SHOT18_CUES[-1]
    for item in SHOT18_CUES:
        if t < item[1]:
            cue = item
            break
    start, end, f0, f1 = cue
    span = max(end - start, 1e-6)
    index = round(f0 + min(max((t - start) / span, 0.0), 1.0) * (f1 - f0))
    paste_center(image, insert_frame(index), WIDTH / 2, INSERT_BIG_Y)


INSERT_RULES_SVG = ROOT / "assets" / "rb-insert-rules.svg"
INSERT_RULES_SOURCE = """<svg xmlns="http://www.w3.org/2000/svg" width="1720" height="560" viewBox="0 0 1720 560">
  <style>
    text{font-family:"Noto Sans CJK SC",system-ui,sans-serif;fill:#F8FAFC;text-anchor:middle;dominant-baseline:middle}
  </style>
  <text x="860" y="56" font-size="40" font-weight="600">编程时插入的规则</text>
  <text x="560" y="300" font-size="36" font-weight="600" style="text-anchor:end">违反不红红</text>
  <text x="560" y="350" font-size="26" fill="#8A8A8A" style="text-anchor:end">（有叔叔结点）</text>
  <path d="M 655 178
           C 626 196 620 240 620 308
           C 620 320 612 327 596 330
           C 612 333 620 340 620 352
           C 620 420 626 464 655 482"
        stroke="#F8FAFC" stroke-width="4" fill="none" stroke-linecap="round"/>
  <rect x="720" y="205" width="240" height="70" rx="14" fill="#DC2626" opacity="0.18"/>
  <rect x="720" y="205" width="240" height="70" rx="14" fill="none" stroke="#F87171" stroke-width="2"/>
  <text x="840" y="241" font-size="30" fill="#F87171">叔叔是红色</text>
  <path d="M 972 240 L 1006 240" stroke="#F8FAFC" stroke-width="3"/>
  <path d="M 1000 233 L 1012 240 L 1000 247" stroke="#F8FAFC" stroke-width="3" fill="none"/>
  <text x="1028" y="241" font-size="30" style="text-anchor:start">叔父爷变色，以爷节点的位置继续向上判断</text>
  <rect x="720" y="385" width="240" height="70" rx="14" fill="#111827" stroke="#64748B" stroke-width="2"/>
  <text x="840" y="421" font-size="30">叔叔是黑色</text>
  <path d="M 972 420 L 1006 420" stroke="#F8FAFC" stroke-width="3"/>
  <path d="M 1000 413 L 1012 420 L 1000 427" stroke="#F8FAFC" stroke-width="3" fill="none"/>
  <text x="1028" y="421" font-size="30" style="text-anchor:start">旋转（LL、RR、LR、RL），然后变色</text>
</svg>
"""


def ensure_insert_rules_svg() -> None:
    if not INSERT_RULES_SVG.exists() or INSERT_RULES_SVG.read_text(encoding="utf-8") != INSERT_RULES_SOURCE:
        INSERT_RULES_SVG.write_text(INSERT_RULES_SOURCE, encoding="utf-8")


def draw_shot20(image: Image.Image, t: float) -> None:
    ensure_insert_rules_svg()
    paste_center(image, fit(svg_png("rb-insert-rules.svg", zoom=2.0), 1720, 620), WIDTH / 2, 540.0)


# ------------------------------------------------- deletion chapter (batch 3)
def draw_shot21(image: Image.Image, t: float) -> None:
    draw = ImageDraw.Draw(image)
    if t < 18.04:
        title_line(draw, "删除：下溢的二叉表示", y=380.0, size=64)
        reading_block(draw, [
            "有两个孩子的，转化为删除直接前驱或后继，变成 0 个孩子的删除。",
            "也就是说，转化为对最后一层的操作。",
        ], y_center=600.0, size=40)
        return
    title_line(draw, "有一个孩子：一红一黑，红孩子顶替并染黑", y=110.0, size=40)
    frames = asset_frames("rb-delete-one-child.webm")
    # 35.24s “就是一红一黑……”开始播放 3.0s 顶替动画
    if t < 35.24:
        index = 0
    elif t < 38.24:
        index = min(int((t - 35.24) * 30.0), len(frames) - 1)
    else:
        index = len(frames) - 1
    paste_center(image, fit(_cached_png(str(frames[index])), 1560, 740), WIDTH / 2, 580.0)


def draw_shot22(image: Image.Image, t: float) -> None:
    draw = ImageDraw.Draw(image)
    title_line(draw, "删除红色叶节点：黑高不变，无需任何调整", y=110.0, size=40)
    frames = asset_frames("rb-delete-zero-child.webm")
    # 10.0s “如果删除的是红色节点……”开始播放 2.8s 红叶消失
    if t < 10.0:
        index = 0
    elif t < 12.8:
        index = min(int((t - 10.0) * 30.0), len(frames) - 1)
    else:
        index = len(frames) - 1
    paste_center(image, fit(_cached_png(str(frames[index])), 1400, 740), WIDTH / 2, 580.0)


def draw_shot23(image: Image.Image, t: float) -> None:
    title_line(ImageDraw.Draw(image), "删除黑色叶节点：首领回家重新推举（解集）", y=90.0, size=40)
    paste_center(image, fit(svg_png("rb-delete-decision-tree.svg", zoom=2.0), 1760, 720), WIDTH / 2, 570.0)


def draw_shot24(image: Image.Image, t: float) -> None:
    draw = ImageDraw.Draw(image)
    title_line(draw, "反向叔父爷变色（首领回家）", y=280.0, size=56)
    reading_block(draw, [
        "推举的时候是推举的黑节点，推上去后一定把它变成红色，两个孩子变成黑色。",
        "拉回来的时候，一定把它再变成黑色的，然后它的两个孩子变成红色的。",
        "完全就是逆过程——反向叔父爷变色。",
    ], y_center=620.0, size=38)


def draw_shot25(image: Image.Image, t: float) -> None:
    reading_block(ImageDraw.Draw(image), [
        "接下来的删除操作，我与 up 主蓝不过海的不一样。",
        "接下来的这些例子与 up 主蓝不过海的删除版本完全一致，方便对比学习。",
    ], y_center=540.0, size=42)


# 双版本并列播放与动作对齐配置：
# (shot -> (title, rb_name, bt_name, [ (t_start, t_end, (rb_f0, rb_f1), (bt_f0, bt_f1)), ... ]))
DUAL_DELETE_CONFIG = {
    26: (
        "兄弟是黑色：兄弟至少有一个红孩子",
        "rb-delete-case1-far-red.webm",
        "rb-delete-case1-btree.webm",
        (
            (0.75, 3.03, (0, 23), (0, 84)),            # “首领 7 回家”：右侧折回，左侧结构不动
            (5.61, 7.65, (24, 66), (84, 152)),         # “5 和 9 变成红色”
            (7.87, 12.57, (66, 108), (152, 206)),      # “删除 9”
            (12.85, 16.09, (108, 246), (206, 250)),    # “旋转操作” / B 树连线切换
            (16.97, 19.11, (246, 288), (250, 294)),    # “重新染色”：5黑、2/7红
            (20.73, 26.99, (288, 330), (294, 358)),    # “重新推举”：5红、2/7黑
            (27.53, 30.43, (330, 383), (358, 467)),    # “5再次变成黑色”
        ),
    ),
    27: (
        "兄弟是黑色：兄弟至少有一个红孩子",
        "rb-delete-case2-near-red.webm",
        "rb-delete-case2-btree.webm",
        (
            (1.01, 9.29, (0, 66), (0, 84)),            # “7回家……5和9变成红色”
            (10.41, 11.43, (66, 108), (84, 138)),      # 同步删除 9
            (11.73, 15.83, (108, 304), (138, 180)),    # “旋转调整”：双旋 / B 树整理成员行
            (16.59, 17.77, (304, 344), (180, 222)),    # “重新染色”：6黑、5/7红
            (21.81, 28.17, (344, 438), (222, 270)),    # “可以推举就推举，拉下来再推上去”
            (40.47, 43.27, (438, 495), (270, 371)),    # “根节点，染黑”
        ),
    ),
    28: (
        "兄弟是黑色：兄弟的孩子都是黑色",
        "rb-delete-case3-black-parent.webm",
        "rb-delete-case3-btree.webm",
        (
            (0.27, 8.27, (0, 104), (0, 114)),          # “8回家……6、9变成红色，删除 9”
            (11.41, 19.72, (104, 146), (114, 220)),    # “首领15回家……18变成红色”
            (22.84, 27.44, (146, 290), (220, 220)),    # “15、18、27进行旋转操作”
            (28.20, 33.02, (290, 338), (220, 290)),    # “18变黑，15、27变红”
            (34.04, 39.14, (338, 473), (290, 498)),    # “进行重新推举”并完成根染黑
        ),
    ),
    29: (
        "兄弟是黑色：兄弟的孩子都是黑色",
        "rb-delete-case4-red-parent.webm",
        "rb-delete-case4-btree.webm",
        (
            (2.59, 4.79, (0, 72), (0, 138)),           # “反向叔父爷变色”
            (4.79, 8.89, (72, 189), (138, 251)),       # “删除 28”
        ),
    ),
    30: (
        "兄弟是红色",
        "rb-delete-case5-red-sibling.webm",
        "rb-delete-case5-btree.webm",
        (
            (24.20, 30.66, (0, 190), (0, 120)),        # 15/18换位：15黑、18红、17改挂18
            (32.84, 35.88, (190, 328), (120, 311)),    # “18首领回家”：18黑、17/27红并删除 27
        ),
    ),
}


def draw_dual_delete_shot(image: Image.Image, shot: int, t: float) -> None:
    title, rb_name, bt_name, cues = DUAL_DELETE_CONFIG[shot]
    draw = ImageDraw.Draw(image)
    title_line(draw, title, y=70.0, size=40)
    avl.draw_text(draw, (480, 130), "传统红黑树形式", size=30, fill=avl.SOFT)
    avl.draw_text(draw, (1440, 130), "4 阶 B 树二叉编码", size=30, fill=avl.SOFT)
    draw.line((960, 170, 960, 990), fill=(45, 52, 64), width=2)

    rb_frames = asset_frames(rb_name)
    bt_frames = asset_frames(bt_name)

    # Gaps between spoken actions are intentional holds. Never begin the
    # next source action before its spoken interval starts.
    if t < cues[0][0]:
        rb_idx, bt_idx = cues[0][2][0], cues[0][3][0]
    else:
        rb_idx, bt_idx = cues[-1][2][1], cues[-1][3][1]
        for item_index, item in enumerate(cues):
            t0, t1, (rf0, rf1), (bf0, bf1) = item
            if t < t0:
                previous = cues[item_index - 1]
                rb_idx, bt_idx = previous[2][1], previous[3][1]
                break
            if t <= t1 or item_index == len(cues) - 1:
                span = max(t1 - t0, 1e-6)
                k = min(max((t - t0) / span, 0.0), 1.0)
                rb_idx = round(rf0 + k * (rf1 - rf0))
                bt_idx = round(bf0 + k * (bf1 - bf0))
                break

    rb_idx = max(0, min(rb_idx, len(rb_frames) - 1))
    bt_idx = max(0, min(bt_idx, len(bt_frames) - 1))

    paste_center(image, fit(_cached_png(str(rb_frames[rb_idx])), 880, 780), 480.0, 580.0)
    paste_center(image, fit(_cached_png(str(bt_frames[bt_idx])), 880, 780), 1440.0, 580.0)


# ------------------------------------------------------------- final comparison table
FINAL_TABLE_HEADER = ("对比项", "红黑树", "B 树")
FINAL_TABLE_ROWS = (
    ("主战场", "内存", "磁盘、SSD"),
    ("一次访问拿回多少", "一次指针跳转，一个小节点、一个关键字", "一次 I/O，读入一整页、成百上千个关键字"),
    ("形态", "高而瘦：每个节点最多两个孩子", "矮而宽：上亿条目通常也只有三四层"),
    ("查找 / 插入 / 删除", "高度约 log2 n（十亿条目约 30 层，纳秒级）", "高度约 log_m n（十亿条目仅三四层，毫秒级 I/O）"),
    ("代表用户", "std::map、Java TreeMap、Linux 内核 CFS", "数据库索引（MySQL InnoDB）、文件系统"),
)


@functools.lru_cache(maxsize=1)
def render_final_table() -> Image.Image:
    size = 30
    font = avl.sans(size)
    pad_x = 36.0
    probe = Image.new("RGB", (8, 8))
    measure = ImageDraw.Draw(probe)
    cells = [FINAL_TABLE_HEADER, *[list(row) for row in FINAL_TABLE_ROWS]]
    widths = [
        max(measure.textlength(row[column], font=font) for row in cells) + pad_x * 2
        for column in range(3)
    ]
    header_h, row_h = 80.0, 84.0
    table_w = sum(widths)
    table_h = header_h + row_h * len(FINAL_TABLE_ROWS)
    image = Image.new("RGBA", (round(table_w), round(table_h)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    x = 0.0
    for index, column in enumerate(widths):
        px = x + pad_x
        avl.draw_text(draw, (px, header_h / 2), FINAL_TABLE_HEADER[index], size=size, anchor="lm")
        for row_index, row in enumerate(FINAL_TABLE_ROWS):
            y = header_h + row_h * row_index + row_h / 2
            color = avl.INK if index == 1 else avl.SOFT
            avl.draw_text(draw, (px, y), row[index], size=26 if len(row[index]) > 20 else size,
                          anchor="lm", fill=color)
        x += column
    ink = avl.blend(avl.INK, 0.9) + (255,)
    faint = (70, 78, 92, 255)
    draw.line((0, header_h, table_w, header_h), fill=ink, width=3)
    draw.line((0, table_h, table_w, table_h), fill=ink, width=3)
    for row_index in range(1, len(FINAL_TABLE_ROWS)):
        y = header_h + row_h * row_index
        draw.line((0, y, table_w, y), fill=faint, width=2)
    return image


def draw_shot31(image: Image.Image, t: float) -> None:
    title_line(ImageDraw.Draw(image), "最后对比一下红黑树和 B 树", y=70.0, size=40)
    table = render_final_table()
    paste_center(image, table, WIDTH / 2, 450.0)
    one_line(ImageDraw.Draw(image),
             "两个高度写成大 O 时都是 O(log n)，B 树层数小，但每层代价差红黑树几个数量级。",
             y=870.0, size=36)


DRAWERS = {
    1: draw_shot01,
    2: draw_shot02,
    3: draw_shot03,
    4: draw_shot04,
    5: draw_shot05,
    6: draw_shot06,
    7: draw_shot07,
    8: draw_shot08,
    9: draw_shot09,
    10: draw_shot10,
    11: draw_shot11,
    12: draw_shot12,
    13: draw_shot13,
    14: draw_shot14,
    15: lambda image, t: draw_insert_shot(image, 15, t),
    16: lambda image, t: draw_insert_shot(image, 16, t),
    17: lambda image, t: draw_insert_shot(image, 17, t),
    18: draw_shot18,
    19: lambda image, t: draw_insert_shot(image, 19, t),
    20: draw_shot20,
    21: draw_shot21,
    22: draw_shot22,
    23: draw_shot23,
    24: draw_shot24,
    25: draw_shot25,
    26: lambda image, t: draw_dual_delete_shot(image, 26, t),
    27: lambda image, t: draw_dual_delete_shot(image, 27, t),
    28: lambda image, t: draw_dual_delete_shot(image, 28, t),
    29: lambda image, t: draw_dual_delete_shot(image, 29, t),
    30: lambda image, t: draw_dual_delete_shot(image, 30, t),
    31: draw_shot31,
}


# ---------------------------------------------------------------- subtitles
SUBTITLES: dict[int, tuple[tuple[float, float, str], ...]] = {
    1: (
        (0.43, 5.93, "红黑树是 4 阶 B 树的二叉编码。"),
        (7.23, 13.47, "上一节我们讲到了 B 树，它是自下向上生长，解决了索引质量的问题。"),
        (14.03, 18.33, "B 树中 4 阶 B 树很特殊，它能够进行二叉编码。"),
        (19.01, 24.15, "而其中最鼎鼎大名的二叉编码方案就是红黑颜色体系。"),
    ),
    3: ((0.96, 4.86, "我在我的电脑上粗略的测试了一下，结果是这样的。"),),
    4: ((0.53, 8.09, "这里我们使用的是 32B 大小的载荷。越大的载荷，B 树空间浪费越明显。"),),
    6: (
        (0.00, 4.40, "从 2-3-4 节点到红黑节点。"),
        (5.00, 8.50, "每一个 B 树节点内部只有一个是黑节点。"),
    ),
    7: (
        (0.88, 4.58, "B 树的 b 直接编码成黑色节点 b。"),
        (5.58, 11.04, "B 树节点 [a,b] 可以选 a 或 b 作为黑色主体，"),
        (11.04, 13.72, "另一个关键字作为红色孩子。"),
        (13.72, 19.18, "普通红黑树允许两种方向，选 a 选 b 都可以。"),
        (19.18, 23.28, "B 树节点 [a,b,c] 可以编码为黑色主体 b，"),
        (23.90, 27.70, "左侧红色孩子 a，右侧红色孩子 c。"),
    ),
    8: (
        (0.43, 4.19, "一个 4 个关键字的节点如何表示呢？"),
        (4.25, 6.55, "也就是刚好符合上溢出的情况。"),
        (7.61, 8.63, "是这样的。"),
        (11.91, 14.39, "这四种情况都有可能。"),
        (14.39, 18.49, "后两种情况，我们拿第三个举例。"),
        (18.49, 24.89, "它是这样的：C 连接 A，A 连接 B，然后 C 还连接 D。"),
    ),
    9: ((0.27, 4.47, "一棵完整的 B 树变成红黑树，就像下边这样。"),),
    10: (
        (0.43, 6.35, "红黑树有四个性质：左根右，根叶黑，不红红，黑路同。"),
        (7.37, 10.90, "左根右是二叉搜索树就有的特性。"),
        (11.39, 14.87, "4 阶 B 树二叉编码后，它是二叉搜索树，"),
        (15.75, 18.60, "符合二叉搜索树的特性——左根右。"),
    ),
    11: (
        (0.56, 5.16, "黑路同是我们通过 4 阶 B 树观察到的特性，"),
        (5.54, 9.28, "这个特性同时保证了对 B 树的下溢出调整。"),
        (10.86, 13.22, "B 树的所有叶结点高度相同，"),
        (13.52, 17.02, "故而黑色节点的高度都相同——黑路同。"),
        (18.64, 20.66, "4 阶 B 树最少一个关键字，"),
        (21.20, 24.56, "删除黑色节点下溢出，不满足黑路同。"),
    ),
    12: (
        (0.00, 3.22, "不红红是为了 B 树的上溢出调整。"),
        (4.10, 9.04, "容量为 3 的 B 树节点插入红节点，违反不红红，上溢出。"),
        (10.24, 12.72, "黑节点的左右被染成红色，"),
        (13.34, 16.50, "红色节点中间始终隔着一个黑节点，"),
        (17.78, 19.24, "所以是不红红。"),
    ),
    13: (
        (1.01, 3.60, "根叶黑是语义完备性。"),
        (4.25, 8.20, "根叶黑是为了红黑染色语义的完备性，"),
        (8.57, 12.60, "能大幅简化对红黑树插入删除规则的描述，"),
        (13.25, 15.10, "这样每个节点都有叔叔。"),
    ),
    14: (
        (0.34, 11.01, "插入。B 树的每个节点组都已经有黑节点，所以我们插入时肯定插入的是红节点。"),
    ),
    15: (
        (0.43, 5.65, "插入 52，在黑节点 51 的左边，没有问题。"),
        (5.65, 10.51, "插入 54，违反不红红，进行了相应调整。"),
        (11.39, 14.43, "它其实对应的就是旋转操作。"),
        (14.97, 19.67, "插入 54 后，51 这个节点属于两边失衡。"),
        (19.67, 21.91, "进行相应的旋转操作。"),
        (21.91, 27.03, "旋转完之后重新变色，使它符合我们红黑树的要求。"),
    ),
    16: (
        (0.69, 5.51, "插入 22，违反了不红红，进行相应的调整。"),
        (5.51, 8.97, "实际对应的是中间失衡的旋转操作。"),
        (9.63, 17.19, "对于杠杆 21-23，左孩子是空，中间是 22，右孩子也是空，中间更重。"),
        (17.19, 21.25, "进行相应的旋转，旋转完之后进行变色。"),
    ),
    17: (
        (0.46, 6.56, "插入 37，违反不红红，对四阶 B 树来说是上溢出。"),
        (7.30, 15.28, "对于上溢出，红黑树在推举的时候，由于二叉编码化所带来的额外的连接关系，"),
        (15.52, 20.92, "我们只能够推举含有两个孩子的节点，也就是黑节点。"),
        (21.54, 24.22, "我们不能指定上中位或者下中位。"),
        (25.44, 32.56, "但是红黑树不管如何推举，它肯定仍然是所有推举解集中的一种。"),
        (33.28, 41.20, "之后在删除中，我们也会看到红黑树哪个首领回家以及重新推举谁身不由己。"),
        (41.70, 47.18, "根据它的连接关系它只能这样或那样，但是它肯定是解集中的一种。"),
    ),
    18: (
        (0.66, 7.12, "注意，我们推举上去之后，一定要把这个黑色节点变成红色。"),
        (7.86, 12.66, "就像我们红黑树插入的时候，一定插入的是红节点一样。"),
        (13.02, 17.80, "如果第一次插入，插入的位置是根的话，再把红变成黑的。"),
        (18.34, 22.92, "如果推举上去的是新根的话，再把推举上去的变成黑的。"),
        (24.20, 29.48, "而推举上去的是红的，它的两个孩子顺势变成黑的。"),
        (29.48, 31.96, "也就是传说中的叔父爷变色。"),
    ),
    19: (
        (0.59, 7.57, "最后我们插入 50，推举黑节点，不违反不红红，不需要调整。"),
    ),
    20: (
        (0.00, 14.00, "但是红黑树已经二叉编码化了，不像 B 树那些节点原生就是在同一层的，"
                      "红黑树再判断哪些节点是同一层就有点得不偿失了。"),
        (14.70, 28.42, "刚刚我们所讲的那些道理是这么个道理，但是实际编程时不能这样写。"
                       "编程时插入的规则就是：如果违反不红红，也就是说有叔叔节点，"),
        (30.15, 42.59, "那么违反不红红内部还可以再分两种情况。第一种，叔叔是红色，"
                       "叔父爷变色，以爷节点的位置继续向上判断。"),
        (43.53, 49.23, "第二种，叔叔是黑色，进行相应的旋转操作，然后进行变色。"),
    ),
    21: (
        (0.56, 7.08, "删除还是第一步先像二叉搜索树一样。"),
        (7.72, 14.42, "有两个孩子转化为删除直接前驱或后继，变成只有 0 个孩子的删除。"),
        (15.04, 18.04, "也就是说，转化为对最后一层的操作。"),
        (19.06, 22.46, "有一个孩子的，直接用那一个孩子顶替。"),
        (22.46, 29.94, "根据 4 阶 B 树的定义，除了最后一层那些节点，都是最少有一个关键字两个孩子。"),
        (31.22, 34.58, "那最后一层那些节点，谁能有一个孩子呢？"),
        (35.24, 39.16, "就是一红一黑，这个红相当于黑的孩子。"),
        (39.16, 43.68, "我们把黑删掉之后，红色重新变成黑色就行了。"),
        (43.68, 45.44, "就只有这两种情况。"),
    ),
    22: (
        (1.30, 8.50, "OK，两个孩子的转化成 0 个孩子的，一个孩子的刚刚也讲过了。"),
        (8.50, 12.50, "那么对于 0 个孩子的删除情况，如果删除的是红色节点，"),
        (12.50, 17.76, "黑高不变，删除后无需任何调整。"),
    ),
    23: (
        (1.20, 8.84, "如果删除的是黑色节点，那么按照 B 树来说，可以首领回家重新推举。"),
        (9.08, 13.62, "B 树中，首领回家重新推举得到的是一个解集。"),
        (14.70, 21.96, "B 树始终采用的是解集中的最优解，红黑树的调整仍然是解集中的一个解。"),
        (22.66, 29.54, "只不过由于二叉编码问题，对于某些场景，红黑树的解与 B 树的解不一样。"),
        (29.54, 36.10, "红黑树也是尽量采用最优解，但有时候只能这样或者那样调整，那就没办法。"),
    ),
    24: (
        (0.14, 7.50, "推举的时候是推举的黑节点，推上去后一定把它变成红色，两个孩子变成黑色。"),
        (7.50, 14.50, "拉回来的时候，一定把它再变成黑色的，然后它的两个孩子变成红色的。"),
        (14.50, 21.20, "完全就是逆过程——反向叔父爷变色。"),
    ),
    25: (
        (0.18, 6.50, "接下来的删除操作，我与 up 主蓝不过海的不一样，"),
        (6.50, 13.08, "所以接下来的这些例子与 up 主蓝不过海的删除版本完全一致，方便对比学习。"),
    ),
    26: (
        (0.75, 7.65, "首领 7 回家，7 从黑色变成黑色，5 和 9 变成红色。"),
        (7.87, 12.57, "删除 9，违反了不红红，是中间失衡。"),
        (12.85, 16.09, "进行对应的旋转操作，进行调整。"),
        (16.97, 19.11, "之后再重新染色。"),
        (20.73, 26.99, "之后重新推举，5 推举上去变成红色，2、7 变成黑色。"),
        (27.53, 30.43, "因为 5 是根，5 再次变成黑色。"),
    ),
    27: (
        (1.01, 11.43, "要删除 9，首领 7 回家，7 从黑色变成黑色，5 和 9 变成红色，违反不红红。"),
        (11.73, 17.77, "然后发现是中间失衡，旋转调整，重新染色。"),
        (18.59, 21.81, "之后是三个节点可以推举。"),
        (21.81, 28.17, "和 B 树一样，可以推举就推举，拉下来再推上去。"),
        (28.45, 34.71, "相当于父节点肯定原来是多少关键字，现在还是多少关键字，不会下溢出。"),
        (35.33, 39.31, "位置关系也都不变，尽量减少调整面。"),
        (40.47, 43.27, "推举后 6 是根节点，染黑。"),
    ),
    28: (
        (0.27, 8.27, "要删除 9，首领 8 回家，8 从黑色变成黑色，6、9 变成红色。"),
        (9.33, 12.77, "上层节点下溢出，首领 15 回家。"),
        (15.04, 19.72, "15 从黑色变成黑色，空节点和 18 变成红色。"),
        (20.48, 22.38, "现在违反不红红。"),
        (22.84, 27.44, "15、18、27 进行旋转操作。"),
        (28.20, 30.02, "左旋 18 变成黑色。"),
        (30.62, 33.02, "15、27 是红色。"),
        (34.04, 36.44, "可以推举，那么进行重新推举。"),
    ),
    29: (
        (0.85, 8.89, "这个例子，还是反向叔父爷变色，删除 28 后发现并不违反不红红，结束。"),
    ),
    30: (
        (0.00, 12.00, "最后这个例子，我们发现父节点那一层它有一个红节点，而我们需要首领 18 回家，"),
        (12.00, 23.52, "那父节点这一层不可能没有黑节点，并且按 B 树逻辑，18 回家的话，它的两个孩子是 17 和 27，首领回家一定是两个孩子拉着它。"),
        (24.20, 30.00, "所以把 15 染成黑色，把 18 变成红色，交换一下位置。"),
        (30.00, 35.88, "然后就是 18 首领回家之后正常操作。"),
    ),
    31: (
        (0.94, 12.55, "最后对比一下红黑树和 B 树，两个高度写成大 O 时都是 O(log n)，"),
        (13.11, 17.97, "B 树层数小，但每层代价差红黑树几个数量级。"),
    ),
}


def stamp(seconds: float) -> str:
    millis = round(seconds * 1000.0)
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{millis:03d}"


def write_srt(path: Path, shot: int, duration: float) -> None:
    shifts = AUDIO_PAUSES.get(shot, [])
    entries = []
    for index, (start, end, text) in enumerate(SUBTITLES[shot], start=1):
        shift = sum(dur for at, dur in shifts if start >= at)
        start += shift
        end += shift
        entries.append(f"{index}\n{stamp(start)} --> {stamp(min(end, duration))}\n{text}\n")
    path.write_text("\n".join(entries), encoding="utf-8")


# ------------------------------------------------------------------ render
def draw_frame(shot: int, t: float) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), avl.BLACK)
    DRAWERS[shot](image, t)
    return image


def encode_video(shot: int, path: Path, duration: float) -> None:
    frame_count = math.ceil(duration * FPS)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.mp4")
    process = subprocess.Popen(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s:v", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "pipe:0", "-an",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(temporary),
        ],
        stdin=subprocess.PIPE,
    )
    assert process.stdin is not None
    try:
        for index in range(frame_count):
            process.stdin.write(draw_frame(shot, min(index / FPS, duration - 1e-5)).tobytes())
    finally:
        process.stdin.close()
    if process.wait() != 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"shot {shot} encode failed")
    temporary.replace(path)


def mux_audio(video: Path, output: Path, audio: Path, duration: float) -> None:
    # apad keeps the audio stream exactly as long as the video: an intra-file
    # silence gap makes some players pull the next segment's audio early.
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0", "-t", f"{duration:.6f}", "-c:v", "copy",
            "-af", "apad", "-c:a", "aac", "-b:a", "192k", "-ac", "2",
            "-movflags", "+faststart", str(output),
        ],
        check=True,
    )


def concat_audio(paths: list[Path], target: Path) -> None:
    if len(paths) == 1:
        subprocess.run(["cp", str(paths[0]), str(target)], check=True)
        return
    inputs: list[str] = []
    for path in paths:
        inputs += ["-i", str(path)]
    graph = "".join(f"[{index}:a]" for index in range(len(paths))) + f"concat=n={len(paths)}:v=0:a=1"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", graph, str(target)],
        check=True,
    )


def insert_pauses(source: Path, target: Path, pauses: list[tuple[float, float]]) -> None:
    """Split the narration at sentence boundaries and insert silence, so the
    reader gets reaction time while the visuals hold."""
    count = len(pauses) + 1
    parts = [f"[0:a]asplit={count}" + "".join(f"[src{i}]" for i in range(count))]
    concat_inputs = []
    prev = 0.0
    for index, (at, dur) in enumerate(pauses):
        parts.append(f"[src{index}]atrim={prev:.6f}:{at:.6f},asetpts=PTS-STARTPTS[seg{index}]")
        parts.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{dur:.6f}[sil{index}]")
        concat_inputs += [f"[seg{index}]", f"[sil{index}]"]
        prev = at
    parts.append(f"[src{count - 1}]atrim={prev:.6f},asetpts=PTS-STARTPTS[seg{count - 1}]")
    concat_inputs.append(f"[seg{count - 1}]")
    parts.append("".join(concat_inputs) + f"concat=n={2 * count - 1}:v=0:a=1[out]")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
         "-filter_complex", ";".join(parts), "-map", "[out]", str(target)],
        check=True,
    )


def render(shot: int, asr: dict[int, dict]) -> None:
    recordings = shot_recordings(shot, asr)
    duration = shot_duration(recordings) + pause_total(shot) + SHOT_TAIL.get(shot, 0.0)
    stem = f"shot{shot:02d}"
    video_only = OUT / "segments" / f"{stem}.mp4"
    final = OUT / f"{stem}.mp4"
    encode_video(shot, video_only, duration)
    merged = OUT / "segments" / f"{stem}-narration.wav"
    concat_audio([item.path for item in recordings], merged)
    pauses = AUDIO_PAUSES.get(shot)
    if pauses:
        with_pauses = OUT / "segments" / f"{stem}-narration-paused.wav"
        insert_pauses(merged, with_pauses, pauses)
        merged = with_pauses
    mux_audio(video_only, final, merged, duration)
    write_srt(OUT / f"{stem}.srt", shot, duration)
    print(final)


def preview(shot: int, values: str) -> None:
    target = OUT / "preview" / f"shot{shot:02d}"
    target.mkdir(parents=True, exist_ok=True)
    asr = load_asr()
    duration = shot_duration(shot_recordings(shot, asr)) + pause_total(shot) + SHOT_TAIL.get(shot, 0.0)
    for value in values.split(","):
        when = min(float(value), duration - 1e-3)
        draw_frame(shot, when).save(target / f"t{when:07.2f}.png")
    print(target)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shot", type=int, choices=sorted(SHOT_AUDIO))
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--at", default="0.5,3.0,8.0,15.0,22.0")
    args = parser.parse_args()
    shots = sorted(SHOT_AUDIO) if args.all else [args.shot] if args.shot else []
    if not shots:
        parser.error("choose --shot N or --all")
    asr = load_asr()
    for shot in shots:
        if args.preview:
            preview(shot, args.at)
        else:
            render(shot, asr)


if __name__ == "__main__":
    main()
