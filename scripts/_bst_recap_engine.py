"""Internal rendering and media helpers for the final BST recap."""

from __future__ import annotations

import json
import math
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
AUDIO_DIR = ROOT / "audio" / "bst"
MANUSCRIPT = ROOT / "回顾一下二叉搜索树.md"
ORIGINAL_ANIMATION = ROOT / "assets" / "bst-increasing.webm"
WIDTH = 1920
HEIGHT = 1080
FPS = 60

BLACK = (0, 0, 0)
INK = (248, 250, 252)
MUTED_INK = (190, 200, 216)
SKY_BLUE = (56, 189, 248)
NODE_FILL = (59, 91, 165)
NODE_RIM = (143, 169, 232)
GLOW_BLUE = (163, 188, 247)
GLOW_WHITE = (255, 255, 255)
GLOW_RED = (255, 112, 112)
WHITE = INK
SOFT_WHITE = MUTED_INK
GREEN = SKY_BLUE
GOLD = GLOW_WHITE
RED = GLOW_RED

SANS_FONT = "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"
SERIF_FONT = "/usr/share/fonts/noto-cjk/NotoSerifCJK-Regular.ttc"
MONO_FONT = "/usr/share/fonts/TTF/DejaVuSansMono.ttf"

# The current take opens with the course context, then continues through the
# BST recap; the short second take supplies the red-black-tree conclusion.
FIRST_AUDIO = AUDIO_DIR / "recording-1788064438570538972-3-edited.wav"
SECOND_AUDIO = AUDIO_DIR / "recording-1788064552124411534-7-edited.wav"
AUDIO_FILES = (FIRST_AUDIO, SECOND_AUDIO)


def manuscript_text_block() -> str:
    source = MANUSCRIPT.read_text(encoding="utf-8")
    marker = "```text\n"
    start = source.index(marker) + len(marker)
    end = source.index("\n```", start)
    return source[start:end].rstrip()


ROUTE_TEXT = manuscript_text_block()
Point = tuple[float, float]
Edge = tuple[str, str]


@dataclass(frozen=True)
class Subtitle:
    start: float
    end: float
    text: str
    audio_file: str
    local_start: float
    local_end: float


FONT_CACHE: dict[tuple[str, int, int], ImageFont.FreeTypeFont] = {}
_TTC_SC_INDEX: dict[str, int] = {}


def _ttc_sc_index(path: str) -> int:
    """NotoSansCJK .ttc ships several faces (JP/KR/SC/TC...); PIL defaults to
    the first, which renders some characters in Japanese/Traditional forms.
    Resolve and cache the Simplified Chinese face index once."""
    if path not in _TTC_SC_INDEX:
        index = 0
        for candidate in range(16):
            try:
                probe = ImageFont.truetype(path, 20, index=candidate)
            except Exception:
                break
            name = " ".join(probe.getname())
            if "SC" in name:
                index = candidate
                break
        _TTC_SC_INDEX[path] = index
    return _TTC_SC_INDEX[path]


def font(path: str, size: int, index: int | None = None) -> ImageFont.FreeTypeFont:
    if index is None:
        index = _ttc_sc_index(path) if str(path).endswith(".ttc") else 0
    key = (path, size, index)
    if key not in FONT_CACHE:
        FONT_CACHE[key] = ImageFont.truetype(path, size, index=index)
    return FONT_CACHE[key]


def sans(size: int) -> ImageFont.FreeTypeFont:
    return font(SANS_FONT, size)


def serif(size: int) -> ImageFont.FreeTypeFont:
    return font(SERIF_FONT, size)


def mono(size: int) -> ImageFont.FreeTypeFont:
    return font(MONO_FONT, size)


def mono_cjk(size: int) -> ImageFont.FreeTypeFont:
    return font(SANS_FONT, size, index=7)


def selected_font(size: int, family: str) -> ImageFont.FreeTypeFont:
    return (
        sans(size)
        if family == "sans"
        else serif(size)
        if family == "serif"
        else mono_cjk(size)
        if family == "mono-cjk"
        else mono(size)
    )


def blend(color: tuple[int, int, int], opacity: float) -> tuple[int, int, int]:
    opacity = max(0.0, min(1.0, opacity))
    return tuple(round(channel * opacity) for channel in color)


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: Point,
    text: str,
    *,
    size: int,
    fill: tuple[int, int, int] = WHITE,
    family: str = "sans",
    anchor: str = "mm",
    spacing: int = 8,
    align: str = "center",
) -> None:
    draw.multiline_text(
        xy,
        text,
        font=selected_font(size, family),
        fill=fill,
        anchor=anchor,
        spacing=spacing,
        align=align,
    )


def draw_text_width(text: str, size: int, family: str) -> float:
    return selected_font(size, family).getlength(text)


def line(
    draw: ImageDraw.ImageDraw,
    start: Point,
    end: Point,
    color: tuple[int, int, int],
    width: int = 5,
) -> None:
    draw.line((round(start[0]), round(start[1]), round(end[0]), round(end[1])), fill=color, width=width)


def trimmed_segment(start: Point, end: Point, radius: float) -> tuple[Point, Point]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    distance = math.hypot(dx, dy) or 1.0
    ux, uy = dx / distance, dy / distance
    return (
        (start[0] + ux * radius, start[1] + uy * radius),
        (end[0] - ux * radius, end[1] - uy * radius),
    )


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def ease(value: float) -> float:
    value = clamp(value)
    return 0.5 - 0.5 * math.cos(math.pi * value)


def lerp(start: float, end: float, value: float) -> float:
    return start + (end - start) * value


def lerp_point(start: Point, end: Point, value: float) -> Point:
    return lerp(start[0], end[0], value), lerp(start[1], end[1], value)


def draw_height_marker(
    draw: ImageDraw.ImageDraw,
    x: float,
    top: float,
    bottom: float,
    label: str,
    color: tuple[int, int, int],
) -> None:
    line(draw, (x, top), (x, bottom), blend(color, 0.8), 4)
    line(draw, (x - 12, top), (x + 12, top), blend(color, 0.8), 4)
    line(draw, (x - 12, bottom), (x + 12, bottom), blend(color, 0.8), 4)
    draw_text(draw, (x, top - 32), label, size=26, fill=color, family="sans")


def small_balanced_positions(origin_x: float, origin_y: float, scale: float = 1.0) -> dict[str, Point]:
    return {
        "20": (origin_x, origin_y),
        "10": (origin_x - 135 * scale, origin_y + 120 * scale),
        "30": (origin_x + 135 * scale, origin_y + 120 * scale),
        "40": (origin_x + 210 * scale, origin_y + 240 * scale),
    }


BALANCED_EDGES: tuple[Edge, ...] = (("20", "10"), ("20", "30"), ("30", "25"), ("30", "40"))
CHAIN_EDGES: tuple[Edge, ...] = (("10", "20"), ("20", "30"), ("30", "40"))
ORIGINAL_KEYS = ("10", "20", "30", "40")
ORIGINAL_EDGE_BY_KEY: dict[str, Edge] = {
    "20": ("10", "20"),
    "30": ("20", "30"),
    "40": ("30", "40"),
}
ORIGINAL_ANIMATION_DURATION = 7.0
INTRO_END = 9.78
TITLE_END = 12.32
ORDERED_TREE_START = 12.32
QUERY_ROUTE_START = 15.80
EFFICIENT_SHAPE_START = 18.40
CHAIN_STATIC_START = 23.42
CHAIN_ANIMATION_START = 29.02
CHAIN_ANIMATION_END = 37.80
CHAIN_ANIMATION_DURATION = CHAIN_ANIMATION_END - CHAIN_ANIMATION_START
HEIGHT_COMPARE_START = 37.80
ROUTE_TEXT_START = 41.36


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def assert_inputs() -> None:
    for path in AUDIO_FILES:
        if not path.exists():
            raise FileNotFoundError(path)
    if not ORIGINAL_ANIMATION.exists():
        raise FileNotFoundError(ORIGINAL_ANIMATION)
    for path in (SANS_FONT, SERIF_FONT, MONO_FONT):
        if not Path(path).exists():
            raise FileNotFoundError(path)


def make_subtitles(first_duration: float) -> list[Subtitle]:
    first = (
        (0.50, 3.90, "这个视频是对接下来几个视频"),
        (3.90, 8.70, "AVL 树、B 树、红黑树的介绍引入性视频"),
        (9.78, 12.32, "回顾一下二叉搜索树"),
        (12.32, 15.80, "二叉搜索树是一棵有序的二叉树"),
        (15.80, 18.40, "有序，让它可用于查询"),
        (18.40, 23.42, "树形使它在数据合适的情况下可以高效查询"),
        (23.42, 26.34, "但是它存在退化问题"),
        (26.34, 29.02, "当输入本来就是有序的"),
        (29.02, 32.36, "普通二叉搜索树就会退化成链"),
        (32.36, 37.80, "树高从原本希望的对数级，变成线性级"),
        (37.80, 41.36, "输入越有序，退化越严重"),
        (41.36, 43.24, "后续出现了两种树"),
        (43.24, 45.90, "能够有效解决这个问题"),
        (46.46, 48.02, "AVL 树"),
        (48.02, 53.36, "使用旋转操作修补维护树的形状"),
        (53.36, 54.14, "B 树"),
        (54.14, 56.02, "放弃二叉节点"),
        (56.02, 59.04, "允许一个节点保存多个关键字"),
        (59.04, 61.18, "并自底向上生长"),
    )
    second = (
        (0.00, 6.34, "而 B 树中的四阶 B 树进行二叉编码化，则孕育出了红黑树"),
    )
    result: list[Subtitle] = []
    for start, end, text in first:
        result.append(Subtitle(start, end, text, FIRST_AUDIO.name, start, end))
    for start, end, text in second:
        result.append(Subtitle(first_duration + start, first_duration + end, text, SECOND_AUDIO.name, start, end))
    return result


def srt_timestamp(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000.0))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{millis:03d}"


def write_srt(path: Path, subtitles: Iterable[Subtitle]) -> None:
    chunks = []
    for index, subtitle in enumerate(subtitles, start=1):
        chunks.append(f"{index}\n{srt_timestamp(subtitle.start)} --> {srt_timestamp(subtitle.end)}\n{subtitle.text}\n")
    path.write_text("\n".join(chunks), encoding="utf-8")


def write_timeline(path: Path, subtitles: list[Subtitle], durations: list[float]) -> None:
    states = [
        (0.0, QUERY_ROUTE_START, "ordered-tree", "开场定格为有序的二叉树"),
        (QUERY_ROUTE_START, EFFICIENT_SHAPE_START, "query-route", "有序 -> 查询"),
        (EFFICIENT_SHAPE_START, CHAIN_STATIC_START, "efficient-shape", "树形与高效查询"),
        (CHAIN_STATIC_START, CHAIN_ANIMATION_START, "chain-static", "普通二叉搜索树就会退化成链（静态保持）"),
        (CHAIN_ANIMATION_START, CHAIN_ANIMATION_END, "chain-insertion", "原 bst-increasing 动画风格：递增插入退化成链"),
        (HEIGHT_COMPARE_START, ROUTE_TEXT_START, "height-compare", "对数级 -> 线性级（静态保持）"),
        (ROUTE_TEXT_START, sum(durations), "route-text", "原稿纯文本关系图（静态，无对应动画）"),
    ]
    payload = {
        "canvas": {"width": WIDTH, "height": HEIGHT, "fps": FPS},
        "source": MANUSCRIPT.name,
        "audio": [str(path) for path in AUDIO_FILES],
        "durations": durations,
        "total_duration": sum(durations),
        "subtitles": [subtitle.__dict__ for subtitle in subtitles],
        "route_text": ROUTE_TEXT,
        "visual_states": [
            {"start": start, "end": end, "id": state_id, "description": description}
            for start, end, state_id, description in states
        ],
        "notes": [
            "Numeric-prefix manuscript files are excluded; the two selected audio files are used as provided.",
            "Subtitles correct ASR homophones to the technical terms spoken in the recording.",
            "The final MP4 contains video and AAC audio only; subtitles stay sidecar.",
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def concat_audio(output_path: Path) -> float:
    list_path = output_path.with_suffix(".concat.txt")
    list_path.write_text("\n".join(f"file '{path}'" for path in AUDIO_FILES) + "\n", encoding="utf-8")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", str(output_path)],
            check=True,
        )
    finally:
        list_path.unlink(missing_ok=True)
    return probe_duration(output_path)


def encode_video(output_path: Path, narration_path: Path, duration: float, first_duration: float) -> None:
    frame_count = math.ceil(duration * FPS)
    with tempfile.TemporaryDirectory(prefix="bst-recap-", dir="/tmp/opencode") as temp_name:
        video_only = Path(temp_name) / "video-only.mp4"
        encoder = subprocess.Popen(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s:v", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "pipe:0", "-an",
                "-c:v", "libx264", "-preset", "medium", "-crf", "0", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(video_only),
            ],
            stdin=subprocess.PIPE,
        )
        assert encoder.stdin is not None
        try:
            for index in range(frame_count):
                timestamp = min(index / FPS, duration)
                encoder.stdin.write(render_frame(timestamp, first_duration, duration).tobytes())
        finally:
            encoder.stdin.close()
        if encoder.wait() != 0:
            raise RuntimeError("FFmpeg video encoding failed")
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-i", str(video_only), "-i", str(narration_path),
                "-map", "0:v:0", "-map", "1:a:0", "-t", f"{duration:.6f}", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart", str(output_path),
            ],
            check=True,
        )


def render_frame(t: float, first_duration: float, total_duration: float) -> Image.Image:
    raise RuntimeError("The final renderer must replace engine.render_frame before encoding")
