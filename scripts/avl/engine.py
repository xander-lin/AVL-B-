"""Shared engine for the AVL recap video (palette, primitives, timeline,
ASR cues, AVL core, layouts, sims, media writers)."""
import bisect
import functools
import json
import math
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_CACHE = {}
LAYOUT_CACHE = {}

ROOT = Path(__file__).resolve().parents[2]
AUDIO_DIR = ROOT / "audio"
ASR_JSON = ROOT / "outputs" / "avl-prep" / "avl-asr-all.json"
NEW_ASR_JSON = ROOT / "outputs" / "avl-prep" / "avl-new-asr.json"
EXTRA_ASR_JSON = ROOT / "outputs" / "avl-prep" / "avl-extra-asr.json"
OUTPUT_DIR = ROOT / "outputs" / "avl-video"
WIDTH = 1920
HEIGHT = 1080
# Source assets and their overlay annotations share the full 1920px canvas.
# Keep the source center at x=960; constraining it to a left sub-area shifts
# the animation while coordinate-based rings and pointers stay behind.
MAIN_LEFT = 0
MAIN_RIGHT = WIDTH
FPS = 60
BLACK = (0, 0, 0)
INK = (248, 250, 252)
SOFT = (190, 200, 216)
FAINT = (128, 138, 158)
NODE_FILL = (59, 91, 165)
NODE_RIM = (143, 169, 232)
GLOW_BLUE = (163, 188, 247)
GLOW_WHITE = (255, 255, 255)
GLOW_RED = (255, 112, 112)
GLOW_ORANGE = (255, 169, 77)
SKY_BLUE = (56, 189, 248)
INDIGO = NODE_FILL
INDIGO_GLOW = GLOW_BLUE
GOLD = GLOW_WHITE
GOLD_GLOW = GLOW_WHITE
RED = GLOW_RED
RED_GLOW = GLOW_RED
GREEN = SKY_BLUE
GREEN_GLOW = SKY_BLUE
PURPLE = INK
PURPLE_GLOW = GLOW_WHITE
CYAN = GLOW_WHITE
CYAN_GLOW = GLOW_WHITE
ORANGE = GLOW_ORANGE
ORANGE_GLOW = GLOW_ORANGE
SANS_FONT = "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"
SERIF_FONT = "/usr/share/fonts/noto-cjk/NotoSerifCJK-Regular.ttc"
MONO_FONT = "/usr/share/fonts/TTF/DejaVuSansMono.ttf"

ASSET_DIR = ROOT / "assets"
SOURCE_CACHE_DIR = Path("/tmp/opencode/avl-original-assets")
SOURCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _source_asset_path(name: str) -> Path:
    path = ASSET_DIR / name
    assert path.exists(), path
    return path


def _source_frames(name: str) -> list[Path]:
    source = _source_asset_path(name)
    target = SOURCE_CACHE_DIR / source.stem
    marker = target / ".ready"
    signature = f"{source.stat().st_size}:{source.stat().st_mtime_ns}"
    if not marker.exists() or marker.read_text(encoding="utf-8") != signature:
        target.mkdir(parents=True, exist_ok=True)
        for old in target.glob("*.png"):
            old.unlink()
        if source.suffix == ".svg":
            subprocess.run(["rsvg-convert", "-o", str(target / "000001.png"), str(source)], check=True)
        else:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
                 str(target / "%06d.png")],
                check=True,
            )
        marker.write_text(signature, encoding="utf-8")
    frames = sorted(target.glob("*.png"))
    assert frames, name
    return frames


@functools.lru_cache(maxsize=48)
def _source_frame(path: str) -> Image.Image:
    with Image.open(path) as frame:
        return frame.convert("RGBA")


def _fit_source(frame: Image.Image, max_width: int = 1246, max_height: int = 780) -> Image.Image:
    scale = min(max_width / frame.width, max_height / frame.height)
    size = (max(1, round(frame.width * scale)), max(1, round(frame.height * scale)))
    return frame.resize(size, Image.Resampling.LANCZOS)


def main_paste_x(fitted_width: float) -> int:
    """Center a fitted source visual on the full render canvas."""
    return int(round((MAIN_LEFT + MAIN_RIGHT - fitted_width) / 2.0))


def draw_source_text(image: Image.Image, text: str, *, y: int = 150) -> None:
    draw = ImageDraw.Draw(image)
    size = 34
    while size > 22 and text_w(text, size) > 1740:
        size -= 1
    draw_text(draw, (120, y), text, size=size, fill=INK, anchor="lm")


def draw_chapter_title(image: Image.Image, title: str) -> None:
    """A centered section break; chapter titles are not subtitle text."""
    draw = ImageDraw.Draw(image)
    draw_text(draw, (960, 500), title, size=72, fill=INK)


def draw_corner_label(image: Image.Image, label: str) -> None:
    """Keep the active example visible without covering the source visual."""
    draw_text(ImageDraw.Draw(image), (86, 72), label, size=40, fill=INK, anchor="lm")


def wrap_lines(value: str, size: int, limit: float, *, family: str = "sans") -> list[str]:
    """Wrap long Chinese prose into readable lines without drawing a panel."""
    lines: list[str] = []
    for paragraph in value.split("\n"):
        current = ""
        for index, char in enumerate(paragraph):
            candidate = current + char
            if current and text_w(candidate, size, family) > limit:
                lines.append(current)
                current = char
            else:
                current = candidate
            if char in "，。；、？！：" and index + 1 < len(paragraph):
                lines.append(current)
                current = ""
        if current:
            lines.append(current)
    return lines or [""]


def draw_left_cue(
    draw: ImageDraw.ImageDraw,
    value: str,
    *,
    y: float = 430.0,
    width: float = 560.0,
    size: int = 34,
    active: bool = True,
    color: tuple[int, int, int] = SOFT,
) -> None:
    """Show the current spoken state in the left rail, with no text box."""
    lines = wrap_lines(value, size, width)
    line_height = size + 14
    top = y - (len(lines) - 1) * line_height / 2
    accent = SKY_BLUE if active else FAINT
    line(draw, (90, top - line_height * 0.55), (90, top + (len(lines) - 0.45) * line_height), accent, 5)
    for index, text in enumerate(lines):
        draw_text(draw, (130, top + index * line_height), text, size=size,
                  fill=INK if active else color, anchor="lm")


def draw_top_key(
    draw: ImageDraw.ImageDraw,
    value: str,
    *,
    y: float = 142.0,
    width: float = 1740.0,
    size: int = 42,
    color: tuple[int, int, int] = INK,
) -> float:
    """Draw a key definition or conclusion above the animated subject."""
    lines = wrap_lines(value, size, width)
    line_height = size + 16
    top = y - (len(lines) - 1) * line_height / 2
    for index, text in enumerate(lines):
        draw_text(draw, (960, top + index * line_height), text, size=size, fill=color)
    return top + len(lines) * line_height


def draw_source_media(
    image: Image.Image,
    name: str,
    t: float,
    start: float,
    *,
    loop: bool = False,
    play_duration: float | None = None,
    caption: str = "",
    source_caption: bool = False,
    frame_index: int | None = None,
    max_width: int = 1246,
    max_height: int = 780,
    y_center: int = 600,
    x_center: float | None = None,
) -> None:
    frames = _source_frames(name)
    if name.endswith(".svg"):
        index = 0
        frame_rate = 1.0
    else:
        frame_rate = 30.0
        elapsed = max(0.0, t - start)
        if frame_index is not None:
            index = frame_index
        elif play_duration is None:
            index = int(elapsed * frame_rate)
        else:
            assert play_duration > 0.0
            index = int(elapsed * len(frames) / play_duration)
        if loop:
            index %= len(frames)
        else:
            index = min(index, len(frames) - 1)
    frame = _fit_source(_source_frame(str(frames[index])), max_width, max_height)
    center = WIDTH / 2.0 if x_center is None else x_center
    x = round(center - frame.width / 2.0)
    y = y_center - frame.height // 2
    image.paste(frame, (x, y), frame)
    if caption and not source_caption:
        draw_source_text(image, caption)


def draw_source_caption(image: Image.Image, tl: "Timeline", t: float) -> None:
    cue = tl.cues[tl.find(t)]
    draw_source_text(image, cue.text)

def draw_plain_cue(image: Image.Image, tl: "Timeline", t: float) -> None:
    draw_source_caption(image, tl, t)
def source_point(name: str, point: tuple[float, float], frame_index: int = -1) -> tuple[float, float]:
    """Map a pixel from a source frame into the render canvas."""
    frame = _source_frame(str(_source_frames(name)[frame_index]))
    fitted = _fit_source(frame)
    scale = fitted.width / frame.width
    return (
        (WIDTH - fitted.width) / 2.0 + point[0] * scale,
        210 + (780 - fitted.height) / 2.0 + point[1] * scale,
    )
def ring(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float]) -> None:
    draw.ellipse(tuple(round(value) for value in box), outline=SKY_BLUE, width=7)
    inset = tuple(round(value + offset) for value, offset in zip(box, (9, 9, -9, -9)))
    draw.ellipse(inset, outline=INK, width=2)
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


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    key = (path, size)
    if key not in FONT_CACHE:
        index = _ttc_sc_index(path) if path.endswith(".ttc") else 0
        FONT_CACHE[key] = ImageFont.truetype(path, size, index=index)
    return FONT_CACHE[key]
def sans(size: int) -> ImageFont.FreeTypeFont:
    return _font(SANS_FONT, size)
def serif(size: int) -> ImageFont.FreeTypeFont:
    return _font(SERIF_FONT, size)
def mono(size: int) -> ImageFont.FreeTypeFont:
    return _font(MONO_FONT, size)
def blend(color: tuple[int, int, int], opacity: float) -> tuple[int, int, int]:
    opacity = max(0.0, min(1.0, opacity))
    return tuple(round(c * opacity) for c in color)
Point = tuple[float, float]
def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))
def ease(v: float) -> float:
    v = clamp(v)
    return 0.5 - 0.5 * math.cos(math.pi * v)
def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t
def lerp_pt(a: Point, b: Point, t: float) -> Point:
    return (lerp(a[0], b[0], t), lerp(a[1], b[1], t))
def line(draw: ImageDraw.ImageDraw, a: Point, b: Point, color, width: int = 5) -> None:
    draw.line(
        (round(a[0]), round(a[1]), round(b[0]), round(b[1])),
        fill=color,
        width=width,
    )
def trimmed(a: Point, b: Point, radius: float) -> tuple[Point, Point]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = math.hypot(dx, dy) or 1.0
    ux, uy = dx / d, dy / d
    return (
        (a[0] + ux * radius, a[1] + uy * radius),
        (b[0] - ux * radius, b[1] - uy * radius),
    )
def text_w(value: str, size: int, family="sans") -> float:
    font = sans(size) if family == "sans" else serif(size) if family == "serif" else mono(size)
    return font.getlength(value)
def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: Point,
    value: str,
    *,
    size: int,
    fill: tuple[int, int, int] = INK,
    family: str = "sans",
    anchor: str = "mm",
    opacity: float = 1.0,
) -> None:
    """Text appears instantly (no fade): any ramp below 0.5 hides it."""
    if opacity <= 0.5:
        return
    font = sans(size) if family == "sans" else serif(size) if family == "serif" else mono(size)
    draw.text(xy, value, font=font, fill=fill, anchor=anchor)
def draw_mixed(
    draw: ImageDraw.ImageDraw,
    cx: float,
    y: float,
    parts: list[tuple[str, tuple[int, int, int]]],
    *,
    size: int,
) -> None:
    """Draw one centered line whose segments carry different fills."""
    widths = [text_w(text, size) for text, _ in parts]
    x = cx - sum(widths) / 2.0
    font = sans(size)
    for (text, color), width in zip(parts, widths):
        draw.text((x, y), text, font=font, fill=color, anchor="lm")
        x += width
def glow_node(
    draw: ImageDraw.ImageDraw,
    p: Point,
    label: str,
    color: tuple[int, int, int],
    glow: tuple[int, int, int],
    *,
    opacity: float = 1.0,
    radius: float = 36.0,
    ring: tuple[int, int, int] | None = None,
    key_size: int = 30,
    fill: tuple[int, int, int] | None = None,
) -> None:
    """Node style copied from the approved bst-recap-v3 renderer."""
    if opacity <= 0.01:
        return
    x, y = p
    size = radius * 2.0
    for grow, share in ((18.0, 0.10), (11.0, 0.16), (6.0, 0.28), (3.0, 0.50)):
        draw.rounded_rectangle(
            (
                round(x - radius - grow),
                round(y - radius - grow),
                round(x + radius + grow),
                round(y + radius + grow),
            ),
            radius=round(28 + grow / 2),
            fill=blend(glow, opacity * share),
        )
    body = fill if fill is not None else color
    draw.rounded_rectangle(
        (round(x - radius), round(y - radius), round(x + radius), round(y + radius)),
        radius=round(size * 0.20),
        fill=blend(body, opacity),
        outline=blend(NODE_RIM, opacity),
        width=max(2, round(size * 0.035)),
    )
    if ring is not None and ring != GLOW_WHITE:
        draw.rounded_rectangle(
            (
                round(x - radius - 10),
                round(y - radius - 10),
                round(x + radius + 10),
                round(y + radius + 10),
            ),
            radius=round(size * 0.25),
            outline=blend(ring, opacity),
            width=4,
        )
    if label:
        font = mono(key_size)
        draw.text((x, y + 1), label, font=font, fill=blend(INK, opacity), anchor="mm")
def edge(
    draw: ImageDraw.ImageDraw,
    a: Point,
    b: Point,
    color: tuple[int, int, int],
    *,
    width: int = 8,
    opacity: float = 1.0,
    trim: float = 36.0,
) -> None:
    if opacity <= 0.01:
        return
    s, e = trimmed(a, b, trim)
    line(draw, s, e, blend(color, opacity), width)
def badge(
    draw: ImageDraw.ImageDraw,
    center: Point,
    value: str,
    fg: tuple[int, int, int],
    *,
    size: int = 28,
    opacity: float = 1.0,
    pad_x: float = 0.0,
    pad_y: float = 0.0,
) -> None:
    """Plain text label (original style): no pill, no fade — text just appears."""
    if opacity <= 0.5:
        return
    draw_text(draw, center, value, size=size, fill=fg)
def header(draw: ImageDraw.ImageDraw, label: str, accent: tuple[int, int, int]) -> None:
    line(draw, (120, 52), (120, 96), SKY_BLUE, 4)
    draw_text(draw, (142, 74), label, size=30, fill=SOFT, anchor="lm")
def wrap_text(value: str, size: int, limit: float) -> list[str]:
    if text_w(value, size) <= limit:
        return [value]
    best_split = 0
    best_cost = 1e18
    for i, ch in enumerate(value):
        if ch in "，。；、？！： ":
            w_left = text_w(value[: i + 1], size)
            w_right = text_w(value[i + 1 :], size)
            cost = abs(w_left - w_right)
            if w_left <= limit and w_right <= limit and cost < best_cost:
                best_cost = cost
                best_split = i + 1
    if best_split == 0:
        best_split = max(1, int(len(value) * limit / max(1.0, text_w(value, size))))
    return [value[:best_split].rstrip(), value[best_split:].lstrip()]
def caption_line(draw: ImageDraw.ImageDraw, value: str, y: float = 176.0) -> None:
    draw_left_cue(draw, value, y=430.0, width=560.0, size=31)
@dataclass
class Cue:
    index: int
    fi: int
    si: int
    start: float
    end: float
    text: str
def wave_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()
# Recording numbers are not unique: re-recorded files kept the old number in
# their names. Use explicit aliases as source identities and concatenate them
# in manuscript order, so duplicate suffixes cannot select the wrong take.
NEW_AUDIO_FILES = {
    "opening": "recording-1788000331306699796-3-edited.wav",
    "contrast": "recording-1787798723646035169-9-edited.wav",
    "rotation-intro": "recording-1787798741715384431-11-edited.wav",
    "example-one": "recording-1787798809121936435-13-edited.wav",
    "cargo": "recording-1787798936524547590-17-edited.wav",
    "balance-question": "recording-1787799076441819071-23-edited.wav",
    "balance-candidates": "recording-1787799165389328862-25-edited.wav",
    "imagery": "recording-1787799503125344009-31-edited.wav",
    "practical": "recording-1787800120347817062-45-edited.wav",
    "right-example": "recording-1787800680885616153-61-edited.wav",
    "middle-example": "recording-1787800403483363099-55-edited.wav",
    "two-step": "recording-1787800721454160489-65-edited.wav",
    "middle-detail": "recording-1787800858869749535-67-edited.wav",
    "height-note": "recording-1788000602351375498-19-edited.wav",
    "height-proof": "recording-1788000763594541794-29-edited.wav",
    "height-cases": "recording-1788000851903040880-33-edited.wav",
    "height-rule": "recording-1787801641300247333-77-edited.wav",
    "counterexample": "recording-1787801757426225360-81-edited.wav",
    "complete-intro": "recording-1788001245554901348-47-edited.wav",
    "walk-up": "recording-1788001635317250872-65-edited.wav",
    "insert-question": "recording-1788001729814341717-73-edited.wav",
    "insert-reason": "recording-1788001912765215025-81-edited.wav",
    "insert-stop": "recording-1788002177119615532-87-edited.wav",
    "insert-rule": "recording-1788002356100594229-91-edited.wav",
    "insert-steps-one": "recording-1787821421347699422-111-edited.wav",
    "insert-steps-two": "recording-1787821483307704295-115-edited.wav",
    "insert-steps-three": "recording-1787821552416389776-117-edited.wav",
    "insert-steps-four": "recording-1787917100342765072-118-edited.wav",
    "insert-steps-five": "recording-1787821567957193722-119-edited.wav",
    "insert-steps-six": "recording-1787821596945671394-121-edited.wav",
    "insert-steps-seven": "recording-1787821641387361925-123-edited.wav",
    "delete-title": "recording-1788002762805598256-107-edited.wav",
    "delete-rule": "recording-1788002649822142800-99-edited.wav",
    "delete-rule-tail": "recording-1788003087059102763-121-edited.wav",
    "delete-examples": "recording-1787830871591299378-137-edited.wav",
}
NEW_RECORDING_ORDER = (
    "opening", "contrast", "rotation-intro", "example-one", "cargo",
    "balance-question", "balance-candidates", "imagery", "practical",
    "right-example", "middle-example", "two-step", "middle-detail",
    "height-note", "height-proof", "height-cases", "height-rule",
    "counterexample", "complete-intro", "walk-up", "insert-question",
    "insert-reason", "insert-stop", "insert-rule", "insert-steps-one",
    "insert-steps-two", "insert-steps-three", "insert-steps-four",
    "insert-steps-five", "insert-steps-six", "insert-steps-seven",
    "delete-title", "delete-rule", "delete-rule-tail", "delete-examples",
)


class Timeline:
    def __init__(self) -> None:
        new_payload = json.loads(NEW_ASR_JSON.read_text(encoding="utf-8"))
        legacy_payload = json.loads(ASR_JSON.read_text(encoding="utf-8"))
        assert new_payload["model"] == legacy_payload["model"] == "medium"
        assert new_payload["language"] == legacy_payload["language"] == "zh"

        new_by_name = {Path(item["audio"]).name: item for item in new_payload["files"]}
        assert set(new_by_name) == set(NEW_AUDIO_FILES.values())
        extra_payload = (
            json.loads(EXTRA_ASR_JSON.read_text(encoding="utf-8"))
            if EXTRA_ASR_JSON.exists()
            else None
        )
        self.audio: list[Path] = []
        self.offsets: list[float] = []
        self.durations: list[float] = []
        sources: dict[tuple[str, int | str], tuple[dict, float]] = {}
        offset = 0.0
        self.program_title_start: float | None = None
        self.program_audio_start: float | None = None
        new_items = [(alias, new_by_name[NEW_AUDIO_FILES[alias]]) for alias in NEW_RECORDING_ORDER]
        if extra_payload is not None:
            new_items.append(("delete-to-root", extra_payload))
        for kind, items in (("new", new_items),
                            ("legacy", legacy_payload["files"][23:30])):
            for source_index, item_data in enumerate(items):
                if kind == "new":
                    index, item = item_data
                else:
                    index, item = source_index + 23, item_data
                path = Path(item["audio"])
                if not path.is_absolute():
                    path = ROOT / path
                if not path.exists() and kind == "legacy":
                    path = AUDIO_DIR / "avl" / "legacy" / path.name
                assert path.exists(), path
                wdur = wave_duration(path)
                assert abs(wdur - item["duration"]) <= 0.05, (path, wdur, item["duration"])
                if kind == "legacy" and index == 25:
                    # Hold the programming title in silence before its narration
                    # starts; all later source offsets move with the pause.
                    self.program_title_start = offset
                    pause_path = OUTPUT_DIR / "program-title-silence.wav"
                    with wave.open(str(path), "rb") as source:
                        params = source.getparams()
                    with wave.open(str(pause_path), "wb") as output:
                        output.setparams(params)
                        frame_width = params.sampwidth * params.nchannels
                        output.writeframes(b"\x00" * (round(2.0 * params.framerate) * frame_width))
                    self.audio.append(pause_path)
                    self.offsets.append(offset)
                    self.durations.append(2.0)
                    offset += 2.0
                    self.program_audio_start = offset
                sources[(kind, index)] = (item, offset)
                self.audio.append(path)
                self.offsets.append(offset)
                self.durations.append(wdur)
                offset += wdur
        self.total = offset
        self.sources = sources

        logical: list[tuple[int, float, float, str]] = []

        def source_segments(kind: str, index: int | str) -> list[tuple[float, float, str]]:
            item, source_offset = sources[(kind, index)]
            return [
                (source_offset + segment["start"], source_offset + segment["end"], segment["text"])
                for segment in item["segments"]
            ]

        def add(fi: int, entries: list[tuple[float, float, str]]) -> None:
            logical.extend((fi, start, end, text) for start, end, text in entries)

        def grouped(fi: int, kind: str, index: int | str, ranges: list[tuple[int, int]]) -> None:
            entries = source_segments(kind, index)
            add(fi, [
                (entries[start][0], entries[end - 1][1], "".join(item[2] for item in entries[start:end]))
                for start, end in ranges
            ])

        def combined(fi: int, parts: list[tuple[str, int | str]]) -> None:
            entries = [entry for kind, index in parts for entry in source_segments(kind, index)]
            add(fi, [(entries[0][0], entries[-1][1], "".join(entry[2] for entry in entries))])

        def split_segment(kind: str, index: int | str, segment_index: int, count: int) -> list[tuple[float, float, str]]:
            item, source_offset = sources[(kind, index)]
            segment = item["segments"][segment_index]
            words = segment.get("words") or []
            assert len(words) >= count
            chunks = []
            for chunk_index in range(count):
                first = len(words) * chunk_index // count
                last = len(words) * (chunk_index + 1) // count
                chunks.append((
                    source_offset + words[first]["start"],
                    source_offset + words[last - 1]["end"],
                    "".join(word["word"] for word in words[first:last]),
                ))
            return chunks

        def split_sources(parts: list[tuple[str, int | str]], count: int) -> list[tuple[float, float, str]]:
            words = []
            for kind, index in parts:
                item, source_offset = sources[(kind, index)]
                for segment in item["segments"]:
                    segment_words = segment.get("words") or []
                    if segment_words:
                        words.extend(
                            (source_offset + word["start"], source_offset + word["end"], word["word"])
                            for word in segment_words
                        )
                    else:
                        words.append((
                            source_offset + segment["start"],
                            source_offset + segment["end"],
                            segment["text"],
                        ))
            assert len(words) >= count
            return [
                (words[first][0], words[last - 1][1], "".join(word[2] for word in words[first:last]))
                for chunk_index in range(count)
                for first, last in ((
                    len(words) * chunk_index // count,
                    len(words) * (chunk_index + 1) // count,
                ),)
            ]

        combined(0, [("new", "opening")])
        combined(1, [("new", "contrast")])
        grouped(2, "new", "rotation-intro", [(0, 2), (2, 3)])
        add(3, source_segments("new", "example-one")[:2])
        add(4, [source_segments("new", "example-one")[2]] + split_segment("new", "example-one", 3, 3))
        add(5, source_segments("new", "cargo")[:1])
        add(6, split_segment("new", "cargo", 1, 4) + split_segment("new", "cargo", 2, 5))
        add(7, source_segments("new", "balance-question"))
        add(7, source_segments("new", "balance-candidates"))
        add(8, source_segments("new", "imagery")[:4])
        grouped(9, "new", "imagery", [(4, 6), (6, 8)])
        grouped(10, "new", "imagery", [(8, 12), (12, 18), (18, 23), (23, 25)])
        add(11, source_segments("new", "practical"))
        add(12, source_segments("new", "right-example")[:8])
        add(13, source_segments("new", "right-example")[8:16])
        add(14, source_segments("new", "middle-example")[:1])
        add(15, split_segment("new", "middle-example", 1, 4))
        add(16, source_segments("new", "middle-example")[2:3])
        grouped(17, "new", "two-step", [(0, 4)])
        grouped(18, "new", "middle-detail", [(0, 2), (2, 4), (4, 7), (7, 9)])

        # Current manuscript order after the second-rotation section. Keep
        # the insertion narration in one logical scene (fi=19), while using
        # explicit aliases for the physical recordings.
        # fi=19 is the complete insertion chapter. Its logical cue indexes
        # follow the current manuscript, while physical timing comes from the
        # explicitly aliased recordings above.
        add(19, source_segments("new", "height-note"))
        add(19, source_segments("new", "height-proof"))
        add(19, source_segments("new", "height-cases"))
        add(19, source_segments("new", "height-rule"))
        add(19, source_segments("new", "counterexample"))
        add(19, source_segments("new", "complete-intro"))
        add(19, source_segments("new", "walk-up"))
        add(19, source_segments("new", "insert-question"))
        add(19, source_segments("new", "insert-reason"))
        add(19, source_segments("new", "insert-stop"))
        add(19, source_segments("new", "insert-rule"))
        add(19, source_segments("new", "insert-steps-one"))
        add(19, source_segments("new", "insert-steps-two"))
        add(19, source_segments("new", "insert-steps-three"))
        add(19, source_segments("new", "insert-steps-four"))
        add(19, source_segments("new", "insert-steps-five"))
        add(19, source_segments("new", "insert-steps-six"))
        add(19, source_segments("new", "insert-steps-seven"))

        add(20, source_segments("new", "delete-title"))
        add(20, source_segments("new", "delete-rule"))
        add(20, source_segments("new", "delete-rule-tail"))
        add(21, source_segments("new", "delete-examples"))
        if extra_payload is not None:
            add(22, source_segments("new", "delete-to-root"))
        for fi in range(23, 30):
            add(fi, source_segments("legacy", fi))

        self.cues: list[Cue] = []
        logical_indices: dict[tuple[int, int], int] = {}
        per_file_index: dict[int, int] = {}
        for fi, gs, ge, source_text in logical:
            si = per_file_index.get(fi, 0)
            per_file_index[fi] = si + 1
            logical_indices[(fi, si)] = len(self.cues)
            self.cues.append(Cue(len(self.cues), fi, si, gs, ge, OVERRIDES.get((fi, si), source_text)))
        self.logical_indices = logical_indices
        self._starts = [cue.start for cue in self.cues]
        for i, cue in enumerate(self.cues[:-1]):
            assert cue.start < cue.end, (cue.fi, cue.si, cue.start, cue.end)
            if cue.end > self.cues[i + 1].start:
                next_cue = self.cues[i + 1]
                assert cue.fi == next_cue.fi, (cue.fi, cue.si, cue.end, next_cue.fi, next_cue.si, next_cue.start)
                cue.end = next_cue.start
        assert self.cues[-1].end <= self.total + 0.05

    def gs(self, fi: int, si: int) -> float:
        return self.cues[self.logical_indices[(fi, si)]].start

    def segment_start(self, kind: str, index: int | str, segment_index: int) -> float:
        """Absolute start of one physical ASR segment (bypasses logical cues)."""
        item, offset = self.sources[(kind, index)]
        return offset + item["segments"][segment_index]["start"]

    def segment_window(self, kind: str, index: int | str, segment_index: int) -> tuple[float, float]:
        """Absolute start/end of one physical ASR segment."""
        item, offset = self.sources[(kind, index)]
        segment = item["segments"][segment_index]
        return offset + segment["start"], offset + segment["end"]

    def word_windows(
        self, kind: str, index: int | str, segment_index: int, count: int
    ) -> list[tuple[float, float]]:
        """Split one ASR segment into evenly sized word-timed windows."""
        item, offset = self.sources[(kind, index)]
        words = item["segments"][segment_index].get("words") or []
        assert len(words) >= count
        return [
            (
                offset + words[len(words) * chunk // count]["start"],
                offset + words[len(words) * (chunk + 1) // count - 1]["end"],
            )
            for chunk in range(count)
        ]

    def ge(self, fi: int, si: int) -> float:
        return self.cues[self.logical_indices[(fi, si)]].end

    def win(self, fi: int, si: int) -> tuple[float, float]:
        cue = self.cues[self.logical_indices[(fi, si)]]
        return cue.start, cue.end

    def find(self, t: float) -> int:
        return max(0, bisect.bisect_right(self._starts, t + 1e-9) - 1)
def build_fi_si(tl: Timeline) -> None:
    FI_SI.clear()
    for cue in tl.cues:
        FI_SI[(cue.fi, cue.si)] = cue.index
FI_SI: "dict[tuple[int, int], int]" = {}
ACCENTS = {
    "s1-def": INDIGO,
    "s2-contrast": GOLD,
    "s2-lever": GOLD,
    "s3-imagery": CYAN,
    "s4-middle": PURPLE,
    "s5-insert": GREEN,
    "s6-delete": ORANGE,
    "s7-proof": INDIGO,
    "s8-factor": GOLD,
    "s9-outro": SOFT,
}
HEADERS = {
    "s1-def": "",
    "s2-contrast": "失衡与平衡",
    "s2-lever": "例一 · 左右失衡",
    "s3-imagery": "意象 · 天平",
    "s4-middle": "例二 · 中间失衡",
    "s5-insert": "插入 · 高度与回溯",
    "s6-delete": "删除 · 向上回溯修复",
    "s7-proof": "论证 · 为什么一定修得好",
    "s8-factor": "补充 · 平衡因子（写给代码）",
    "s9-outro": "接下来 · 对应的 C 语言代码",
}

# Each source-backed visual segment. The title page deliberately ends before
# the contrast-tree narration; trees begin in the following segment.
SCENES = [
    ("s1-def", 0, 0, 0, 0),
    ("s2-contrast", 1, 0, 1, 0),
    ("s2-lever", 2, 0, 7, 0),
    ("s3-imagery", 8, 0, 13, 0),
    ("s4-middle", 14, 0, 18, 3),
    ("s5-insert", 19, 0, 19, 20),
    ("s6-delete", 20, 0, 22, 0),
    ("s7-proof", 23, 0, 24, 4),
    ("s8-factor", 25, 0, 27, 0),
    ("s9-outro", 28, 0, 29, 1),
]

def scene_of(fi: int, si: int) -> str:
    scene_by_file = {
        0: "s1-def", 1: "s2-contrast",
        2: "s2-lever", 3: "s2-lever", 4: "s2-lever", 5: "s2-lever",
        6: "s2-lever", 7: "s2-lever",
        8: "s3-imagery", 9: "s3-imagery", 10: "s3-imagery", 11: "s3-imagery",
        12: "s3-imagery", 13: "s3-imagery",
        14: "s4-middle", 15: "s4-middle", 16: "s4-middle", 17: "s4-middle", 18: "s4-middle",
        19: "s5-insert", 20: "s6-delete", 21: "s6-delete", 22: "s6-delete",
        23: "s7-proof", 24: "s7-proof", 25: "s8-factor", 26: "s8-factor", 27: "s8-factor",
        28: "s9-outro", 29: "s9-outro",
    }
    return scene_by_file[fi]
class Node:
    __slots__ = ("key", "left", "right", "h")

    def __init__(self, key: int):
        self.key = key
        self.left: Node | None = None
        self.right: Node | None = None
        self.h = 1
def height_of(node: Node | None) -> int:
    return node.h if node is not None else 0
def update_h(node: Node) -> None:
    node.h = 1 + max(height_of(node.left), height_of(node.right))
def balance_factor(node: Node) -> int:
    return height_of(node.left) - height_of(node.right)
def rotate_right(node: Node) -> Node:
    pivot = node.left
    assert pivot is not None
    node.left = pivot.right
    pivot.right = node
    update_h(node)
    update_h(pivot)
    return pivot
def rotate_left(node: Node) -> Node:
    pivot = node.right
    assert pivot is not None
    node.right = pivot.left
    pivot.left = node
    update_h(node)
    update_h(pivot)
    return pivot
def avl_insert(node: Node | None, key: int, ev: list[tuple[int, str]]) -> Node:
    if node is None:
        return Node(key)
    if key < node.key:
        node.left = avl_insert(node.left, key, ev)
    elif key > node.key:
        node.right = avl_insert(node.right, key, ev)
    else:
        return node
    update_h(node)
    b = balance_factor(node)
    if b > 1:
        assert node.left is not None
        if balance_factor(node.left) < 0:
            ev.append((node.left.key, "left"))
            node.left = rotate_left(node.left)
        ev.append((node.key, "right"))
        node = rotate_right(node)
    elif b < -1:
        assert node.right is not None
        if balance_factor(node.right) > 0:
            ev.append((node.right.key, "right"))
            node.right = rotate_right(node.right)
        ev.append((node.key, "left"))
        node = rotate_left(node)
    return node
def bst_delete_plain(node: Node | None, key: int) -> Node | None:
    if node is None:
        return None
    if key < node.key:
        node.left = bst_delete_plain(node.left, key)
    elif key > node.key:
        node.right = bst_delete_plain(node.right, key)
    else:
        if node.left is None:
            return node.right
        if node.right is None:
            return node.left
        successor = node.right
        while successor.left is not None:
            successor = successor.left
        node.key = successor.key
        node.right = bst_delete_plain(node.right, successor.key)
    return node
def avl_delete(node: Node | None, key: int, ev: list[tuple[int, str]]) -> Node | None:
    if node is None:
        return None
    if key < node.key:
        node.left = avl_delete(node.left, key, ev)
    elif key > node.key:
        node.right = avl_delete(node.right, key, ev)
    else:
        if node.left is None:
            return node.right
        if node.right is None:
            return node.left
        successor = node.right
        while successor.left is not None:
            successor = successor.left
        node.key = successor.key
        node.right = avl_delete(node.right, successor.key, ev)
    update_h(node)
    b = balance_factor(node)
    if b > 1:
        left = node.left
        assert left is not None
        if balance_factor(left) < 0:
            node.left = rotate_left(left)
            ev.append((left.key, "left"))
        ev.append((node.key, "right"))
        node = rotate_right(node)
    elif b < -1:
        right = node.right
        assert right is not None
        if balance_factor(right) > 0:
            node.right = rotate_right(right)
            ev.append((right.key, "right"))
        ev.append((node.key, "left"))
        node = rotate_left(node)
    return node
def to_children(root: Node | None) -> tuple[int, dict[int, tuple[int | None, int | None]]]:
    children: dict[int, tuple[int | None, int | None]] = {}

    def visit(node: Node | None) -> None:
        if node is None:
            return
        children[node.key] = (
            node.left.key if node.left else None,
            node.right.key if node.right else None,
        )
        visit(node.left)
        visit(node.right)

    visit(root)
    assert root is not None
    return root.key, children
def from_children(snap: tuple[int, dict[int, tuple[int | None, int | None]]]) -> Node:
    root_key, children = snap
    nodes = {key: Node(key) for key in children}
    for key, (left, right) in children.items():
        nodes[key].left = nodes[left] if left else None
        nodes[key].right = nodes[right] if right else None

    def fix_heights(node: Node | None) -> int:
        if node is None:
            return 0
        node.h = 1 + max(fix_heights(node.left), fix_heights(node.right))
        return node.h

    root = nodes[root_key]
    fix_heights(root)
    return root
def inorder_keys(root: Node | None) -> list[int]:
    if root is None:
        return []
    return inorder_keys(root.left) + [root.key] + inorder_keys(root.right)
def assert_avl(snap: tuple[int, dict[int, tuple[int | None, int | None]]]) -> None:
    _, children = snap
    memo: dict[int, int] = {}

    def h(key: int | None) -> int:
        if key is None:
            return 0
        if key not in memo:
            left, right = children[key]
            memo[key] = 1 + max(h(left), h(right))
        return memo[key]

    for key in children:
        left, right = children[key]
        assert abs(h(left) - h(right)) <= 1, key
def rot_map(
    snap: tuple[int, dict[int, tuple[int | None, int | None]]],
    upper: int,
    direction: str,
) -> tuple[int, dict[int, tuple[int | None, int | None]]]:
    root, source = snap
    children = dict(source)
    left, right = children[upper]
    parent = None
    for candidate, (cl, cr) in source.items():
        if cl == upper or cr == upper:
            parent = candidate
            break
    if direction == "left":
        lower = right
        assert lower is not None
        lower_left, lower_right = children[lower]
        children[upper] = (left, lower_left)
        children[lower] = (upper, lower_right)
    else:
        lower = left
        assert lower is not None
        lower_left, lower_right = children[lower]
        children[upper] = (lower_right, right)
        children[lower] = (lower_left, upper)
    if parent is None:
        root = lower
    else:
        pl, pr = children[parent]
        children[parent] = (
            lower if pl == upper else pl,
            lower if pr == upper else pr,
        )
    return root, children
def edges_of(children: dict[int, tuple[int | None, int | None]]) -> set[tuple[int, int]]:
    return {
        (parent, child)
        for parent, (left, right) in children.items()
        for child in (left, right)
        if child is not None
    }
def attach_map(
    snap: tuple[int, dict[int, tuple[int | None, int | None]]],
    key: int,
) -> tuple[int, dict[int, tuple[int | None, int | None]]]:
    root, source = snap
    children = dict(source)
    path: list[int] = []
    current = root
    while True:
        path.append(current)
        if key == current:
            raise ValueError("duplicate key")
        nxt = children[current][0] if key < current else children[current][1]
        if nxt is None:
            children[current] = (
                key if key < current else children[current][0],
                key if key > current else children[current][1],
            )
            children[key] = (None, None)
            break
        current = nxt
    return root, children
def map_detach(
    snap: tuple[int, dict[int, tuple[int | None, int | None]]],
    key: int,
) -> tuple[int, dict[int, tuple[int | None, int | None]]]:
    """Remove a 0/1-child node by key (structural, no rebalance)."""
    root, source = snap
    children = dict(source)
    own = children.pop(key)
    assert own[0] is None or own[1] is None
    replacement = own[0] if own[0] is not None else own[1]
    if key == root:
        assert replacement is not None
        return replacement, children
    parent = None
    for candidate, (cl, cr) in children.items():
        if cl == key or cr == key:
            parent = candidate
            break
    assert parent is not None
    pl, pr = children[parent]
    children[parent] = (
        replacement if pl == key else pl,
        replacement if pr == key else pr,
    )
    return root, children
def layout_snap(
    snap: tuple[int, dict[int, tuple[int | None, int | None]]],
    rect: tuple[float, float, float, float],
    *,
    pad: float = 56.0,
    gap: float = 148.0,
    step_side: float = 186.0,
    y_step: float = 110.0,
    max_scale: float = 1.0,
) -> dict[int, Point]:
    root, children = snap
    cache_key = (root, tuple(sorted(children.items())), rect, pad, gap, step_side, y_step, max_scale)
    cached = LAYOUT_CACHE.get(cache_key)
    if cached is not None:
        return cached
    rel: dict[int, float] = {}
    depth_of: dict[int, int] = {}

    def build(key: int, depth: int) -> tuple[list[int], float, float, float]:
        rel[key] = 0.0
        depth_of[key] = depth
        left, right = children[key]
        if left is None and right is None:
            return [key], 0.0, 0.0, 0.0
        if right is None:
            members, lo, hi, center = build(left, depth + 1)
            assert left is not None
            delta = -step_side - center
            for member in members:
                rel[member] += delta
            return members + [key], min(lo + delta, 0.0), max(hi + delta, 0.0), 0.0
        if left is None:
            members, lo, hi, center = build(right, depth + 1)
            assert right is not None
            delta = step_side - center
            for member in members:
                rel[member] += delta
            return members + [key], min(lo + delta, 0.0), max(hi + delta, 0.0), 0.0
        lm, l_lo, l_hi, l_center = build(left, depth + 1)
        rm, r_lo, r_hi, r_center = build(right, depth + 1)
        shift = max(0.0, (l_hi + gap) - r_lo)
        if shift:
            for member in rm:
                rel[member] += shift
            r_lo += shift
            r_hi += shift
            r_center += shift
        center = (l_center + r_center) / 2.0
        for member in lm + rm:
            rel[member] -= center
        return (
            lm + rm + [key],
            min(l_lo - center, r_lo - center, 0.0),
            max(l_hi - center, r_hi - center, 0.0),
            0.0,
        )

    _, lo, hi, _ = build(root, 0)
    cx = (rect[0] + rect[2]) / 2.0
    max_depth = max(depth_of.values(), default=0)
    available_width = max(1.0, rect[2] - rect[0] - 2.0 * pad)
    available_height = max(1.0, rect[3] - rect[1] - 2.0 * pad)
    scale = min(
        max_scale if max_scale > 0.0 else 1.0,
        available_width / max(hi - lo, 1.0),
        available_height / max(max_depth * y_step, 1.0),
    )
    y0 = rect[1] + pad
    positions = {
        key: (cx + (x - (lo + hi) / 2.0) * scale, y0 + depth * y_step * scale)
        for key, (x, depth) in ((k, (rel[k], depth_of[k])) for k in rel)
    }
    LAYOUT_CACHE[cache_key] = positions
    return positions
def draw_map(
    draw: ImageDraw.ImageDraw,
    snap: tuple[int, dict[int, tuple[int | None, int | None]]],
    positions: dict[int, Point],
    *,
    color: tuple[int, int, int] = INDIGO,
    glow: tuple[int, int, int] = INDIGO_GLOW,
    edge_color: tuple[int, int, int] = INK,
    opacity: float = 1.0,
    radius: float = 36.0,
    highlight: set[int] | None = None,
    highlight_color: tuple[int, int, int] | None = None,
    dim: set[int] | None = None,
    labels: dict[int, str] | None = None,
    ring: dict[int, tuple[int, int, int]] | None = None,
    key_size: int = 30,
) -> None:
    children = snap[1]
    highlight_set = highlight or set()
    dim_set = dim or set()
    hl_color = highlight_color or GOLD_GLOW
    for parent, child in sorted(edges_of(children)):
        if parent not in positions or child not in positions:
            continue
        active = parent in highlight_set and child in highlight_set
        base_opacity = opacity * (0.28 if parent in dim_set or child in dim_set else 1.0)
        edge(
            draw,
            positions[parent],
            positions[child],
            hl_color if active else edge_color,
            width=9 if active else 7,
            opacity=base_opacity,
            trim=radius + 2,
        )
    for key in sorted(positions):
        node_opacity = opacity * (0.28 if key in dim_set else 1.0)
        glow_node(
            draw,
            positions[key],
            (labels or {}).get(key, str(key)),
            color,
            glow,
            opacity=node_opacity,
            radius=radius,
            ring=ring.get(key) if ring else None,
            key_size=key_size,
        )


def _draw_rot_step(
    draw: ImageDraw.ImageDraw,
    upper: int,
    direction: str,
    pre: tuple,
    post: tuple,
    u: float,
    rect: tuple[float, float, float, float],
) -> None:
    pre_pos = layout_snap(pre, rect)
    post_pos = layout_snap(post, rect)
    k = ease(clamp((u - 0.08) / 0.84))
    left, right = pre[1][upper]
    lower = right if direction == "left" else left
    assert lower is not None
    shared = set(pre_pos) & set(post_pos)
    positions = {key: lerp_pt(pre_pos[key], post_pos[key], k) for key in shared}
    pre_edges = edges_of(pre[1])
    post_edges = edges_of(post[1])
    lever_pair = {upper, lower}
    for pair in sorted(pre_edges | post_edges):
        a, b = pair
        if a not in positions or b not in positions:
            continue
        if pair in pre_edges and pair in post_edges:
            alpha = 1.0
        elif pair in pre_edges:
            alpha = clamp(1.0 - k * 2.4)
        else:
            alpha = clamp(k * 2.4 - 1.4)
        hot = set(pair) == lever_pair and 0.03 < k < 0.97
        edge(draw, positions[a], positions[b], GOLD_GLOW if hot else INK,
             width=10 if hot else 7,
             opacity=max(alpha, 0.95) if hot else alpha, trim=38)
    for key, point in positions.items():
        glow_node(draw, point, str(key), INDIGO,
                  GLOW_WHITE if key in lever_pair else INDIGO_GLOW,
                  radius=37)
    word = "左旋" if direction == "left" else "右旋"
    badge_y = rect[3] + 44 if rect[3] + 84 <= HEIGHT else rect[1] - 44
    badge(draw, ((rect[0] + rect[2]) / 2, badge_y),
          f"旋转 {upper}—{lower} · {word}", GOLD, size=29, pad_x=17)
def draw_path_walk(
    draw: ImageDraw.ImageDraw,
    snap: tuple[int, dict[int, tuple[int | None, int | None]]],
    positions: dict[int, Point],
    key: int,
    progress: float,
    radius: float,
) -> list[int]:
    """Highlight the search path towards `key`; returns visited nodes."""
    children = snap[1]
    path: list[int] = []
    current = snap[0]
    while True:
        path.append(current)
        if key == current:
            break
        left, right = children[current]
        nxt = left if key < current else right
        assert nxt is not None
        current = nxt
    visible = clamp(progress) * (len(path) - 1)
    full = int(visible)
    for i in range(min(full + 1, len(path))):
        node = path[i]
        glow_node(
            draw,
            positions[node],
            str(node),
            CYAN,
            CYAN_GLOW,
            opacity=0.85 if i <= full else 0.0,
            radius=radius,
        )
    for i in range(full):
        edge(
            draw,
            positions[path[i]],
            positions[path[i + 1]],
            CYAN_GLOW,
            width=8,
            opacity=0.8,
            trim=radius + 2,
        )
    return path
KEYS5 = (1, 3, 7, 6, 4, 5, 2, 0, -2, -1)
FLY_SI = {1: 42, 3: 42, 7: 42, 6: 50, 4: 51, 5: 56, 2: 59, 0: 65, -2: 66, -1: 72}
ROT_SI = {
    7: [(48, (1, "left"))],
    4: [(54, (7, "right"))],
    5: [(58, (6, "right")), (58, (3, "left"))],
    2: [(62, (1, "left")), (63, (3, "right"))],
    -2: [(69, (1, "right"))],
    -1: [(78, (2, "right"))],
}
INS_ROTS_EXPECTED = {key: [entry[1] for entry in ROT_SI[key]] for key in ROT_SI}
STAGE5 = (220.0, 300.0, 1700.0, 1010.0)
QUEUE_Y = 150.0
INSERT_CANONICAL_X: dict[int, float] = {}
def insert_layout(snap: tuple[int, dict[int, tuple[int | None, int | None]]]) -> dict[int, Point]:
    """Use final-tree x anchors so inserting a leaf never reflows old edges."""
    root, children = snap
    if not INSERT_CANONICAL_X:
        fallback = layout_snap(snap, STAGE5, pad=44.0, gap=42.0, step_side=68.0, y_step=92.0)
        return fallback
    depth_of: dict[int, int] = {}

    def visit(key: int, depth: int) -> None:
        depth_of[key] = depth
        left, right = children[key]
        if left is not None:
            visit(left, depth + 1)
        if right is not None:
            visit(right, depth + 1)

    visit(root, 0)
    return {
        key: (INSERT_CANONICAL_X[key], 356.0 + depth * 132.0)
        for key, depth in depth_of.items()
    }


@dataclass
class Step:
    kind: str  # fly | rot
    params: tuple
    pre: tuple | None
    post: tuple | None
@dataclass
class Beat:
    fi: int
    si: int
    steps: list[Step]
    state_after: tuple | None
def build_insert_beats() -> list[Beat]:
    root: Node | None = None
    pending_rot_ops: dict[int, list[tuple[int, tuple[int, str]]]] = {}
    for key in KEYS5:
        ev: list[tuple[int, str]] = []
        root = avl_insert(root, key, ev)
        expected = INS_ROTS_EXPECTED.get(key, [])
        assert ev == expected, (key, ev, expected)
        pending_rot_ops[key] = [(si, entry) for si, entry in ROT_SI.get(key, [])]
    # replay staged states on the children map
    snap: tuple[int, dict[int, tuple[int | None, int | None]]] | None = None
    beat_steps: dict[tuple[int, int], list[Step]] = {}
    state_after: dict[int, tuple] = {}
    flies_done = 0
    for key in KEYS5:
        si_fly = FLY_SI[key]
        pre = snap
        if snap is None:
            post = (key, {key: (None, None)})
        else:
            post = attach_map(snap, key)
        beat_steps.setdefault((19, si_fly), []).append(Step("fly", (key,), pre, post))
        snap = post
        flies_done += 1
        state_after[si_fly] = snap
        for si_rot, entry in pending_rot_ops[key]:
            u, d = entry
            nxt = rot_map(snap, u, d)
            beat_steps.setdefault((19, si_rot), []).append(Step("rot", (u, d), snap, nxt))
            snap = nxt
            state_after[si_rot] = snap
    # fill static states for every cue in scene 5
    beats: list[Beat] = []
    current: tuple | None = None
    flies_seen = 0
    for si in range(79):
        steps = beat_steps.get((19, si), [])
        for step in steps:
            if step.kind == "fly":
                flies_seen += 1
        if steps:
            current = steps[-1].post
        beats.append(Beat(19, si, steps, current))
        setattr(beats[-1], "flies_done", flies_seen)
    return beats


SAMPLE_ORDER = (3, 10, 8, 7, 5, 1, 11, 6, 9, 4, 12, 2)
DEL_KEYS = (9, 7, 3)
STAGE6 = (760.0, 300.0, 1860.0, 1000.0)


def delete_layout(snap: tuple[int, dict[int, tuple[int | None, int | None]]]) -> dict[int, Point]:
    return layout_snap(snap, STAGE6, pad=38.0, gap=180.0, step_side=214.0, y_step=146.0)
def build_delete_sim() -> tuple[
    tuple[int, dict[int, tuple[int | None, int | None]]],
    dict[int, dict[str, tuple]],
]:
    root: Node | None = None
    for key in SAMPLE_ORDER:
        root = avl_insert(root, key, [])
    initial = to_children(root)
    per_key: dict[int, dict[str, tuple]] = {}
    for key in DEL_KEYS:
        working = from_children(initial)
        raw_node = bst_delete_plain(from_children(initial), key)
        assert raw_node is not None
        raw = to_children(raw_node)
        ev: list[tuple[int, str]] = []
        final_node = avl_delete(from_children(initial), key, ev)
        assert final_node is not None
        final = to_children(final_node)
        # fold rotations onto raw and require equality with the full pass
        folded = raw
        for upper, direction in ev:
            folded = rot_map(folded, upper, direction)
        assert folded == final, (key, folded, final)
        assert_avl(final)
        assert inorder_keys(final_node) == sorted(inorder_keys(final_node))
        per_key[key] = {"old": initial, "raw": raw, "rots": tuple(ev), "final": final}
        initial = final
    return per_key[9]["old"], per_key
BEAM_C = (960.0, 468.0)
BEAM_HALF = 330.0
def beam_points(angle: float, middle_t: float) -> tuple[Point, Point, Point]:
    d = (math.cos(angle), math.sin(angle))
    left = (BEAM_C[0] - BEAM_HALF * d[0], BEAM_C[1] - BEAM_HALF * d[1])
    right = (BEAM_C[0] + BEAM_HALF * d[0], BEAM_C[1] + BEAM_HALF * d[1])
    mount = (
        left[0] + 2 * BEAM_HALF * middle_t * d[0],
        left[1] + 2 * BEAM_HALF * middle_t * d[1],
    )
    return left, right, mount
def draw_beam(
    draw: ImageDraw.ImageDraw,
    angle: float,
    middle_t: float,
    *,
    opacity: float = 1.0,
    cargos: dict[str, tuple[Point, tuple[int, int, int], tuple[int, int, int]]] | None = None,
    ropes: list[Point] | None = None,
    lever_glow: bool = False,
) -> tuple[Point, Point]:
    """Balance beam exactly like the original assets: white beam, blue clamp
    tick at the mount, blue rope; ends are ordinary blue nodes."""
    left, right, mount = beam_points(angle, middle_t)
    edge(draw, left, right, INK, width=9, opacity=opacity, trim=6)
    for end in (left, right):
        glow_node(draw, end, "", INDIGO, GLOW_WHITE if lever_glow else INDIGO_GLOW, opacity=opacity, radius=26)
    draw_text(draw, (left[0], left[1]), "5", size=30, family="mono")
    draw_text(draw, (right[0], right[1]), "9", size=30, family="mono")
    for anchor in (ropes or []):
        line(draw, anchor[0], anchor[1], blend((7, 89, 133), opacity), 9)
        line(draw, anchor[0], anchor[1], blend((143, 169, 232), opacity), 4)
    for label, (point, color, glow_color) in (cargos or {}).items():
        glow_node(draw, point, label, color, glow_color, opacity=opacity, radius=34)
    return left, right
def phase(t: float, a: float, b: float, cuts: tuple[float, ...]) -> tuple[int, float]:
    span = max(b - a, 1e-6)
    u = clamp((t - a) / span)
    edges = [0.0, *cuts, 1.0]
    for i in range(len(edges) - 1):
        if u <= edges[i + 1] or i == len(edges) - 2:
            local = (u - edges[i]) / max(edges[i + 1] - edges[i], 1e-6)
            return i, clamp(local)
    return len(edges) - 2, 1.0
EX_START = {"5": (430.0, 140.0), "3": (280.0, 280.0), "9": (580.0, 280.0), "6": (500.0, 420.0), "14": (660.0, 420.0), "17": (725.0, 550.0)}
EX_WAIT = {"3": (130.0, 480.0), "6": (320.0, 530.0), "14": (720.0, 460.0), "17": (785.0, 555.0)}
EX_FINAL = {"9": (425.0, 135.0), "5": (285.0, 285.0), "3": (170.0, 425.0), "6": (400.0, 425.0), "14": (560.0, 270.0), "17": (625.0, 405.0)}
EX_SCALE = 1.58
EX_OFF = (390.0, 110.0)
def ex_map(values: dict[str, Point]) -> dict[str, Point]:
    return {(k): ((v[0]) * EX_SCALE + EX_OFF[0], (v[1]) * EX_SCALE + EX_OFF[1]) for k, v in values.items()}
EX_START_T = ex_map(EX_START)
EX_WAIT_T = ex_map({**{k: v for k, v in EX_WAIT.items()}})
EX_FINAL_T = ex_map(EX_FINAL)
EX_ROTATED_T = {**EX_WAIT_T, "5": EX_FINAL_T["5"], "9": EX_FINAL_T["9"]}
EX_EDGES_FULL = (("5", "3"), ("5", "9"), ("9", "6"), ("9", "14"), ("14", "17"))
EX_MID_A = ((505.0) * EX_SCALE + EX_OFF[0], (210.0) * EX_SCALE + EX_OFF[1])
EX_MID_B = ((355.0) * EX_SCALE + EX_OFF[0], (210.0) * EX_SCALE + EX_OFF[1])
STEP_WEIGHT = {"fly": 1.3, "rot": 1.0, "show": 0.6, "fade": 1.2, "swap": 1.0}
def step_windows(count: int, kinds: list[str]) -> list[tuple[float, float]]:
    weights = [STEP_WEIGHT[kind] for kind in kinds]
    total = sum(weights) + 0.12 * max(count - 1, 0)
    cursor = 0.0
    windows: list[tuple[float, float]] = []
    for weight in weights:
        start = cursor / total
        cursor += weight
        end = cursor / total
        cursor += 0.12
        windows.append((start, end))
    return windows
QUEUE_SLOTS = {key: (240.0 + index * 128.0, QUEUE_Y) for index, key in enumerate(KEYS5)}
@dataclass
class DStep:
    kind: str  # show | fade | rot | swap
    params: tuple
    pre: tuple
    post: tuple
@dataclass
class DBeat:
    si: int
    steps: list[DStep]
    state_after: tuple
def build_delete_beats() -> dict[int, DBeat]:
    initial, per = build_delete_sim()
    beats: dict[int, DBeat] = {}

    def beat(si: int, steps: list[DStep], state_after: tuple) -> None:
        beats[si] = DBeat(si, steps, state_after)

    d9 = per[9]
    rots9 = d9["rots"]
    assert rots9 == ((10, "left"), (8, "right")), rots9
    r1 = rot_map(d9["raw"], *rots9[0])
    r2 = rot_map(r1, *rots9[1])
    beat(0, [], initial)
    beat(1, [DStep("show", (), initial, initial)], initial)
    beat(2, [
        DStep("fade", (9,), d9["old"], d9["raw"]),
        DStep("rot", rots9[0], d9["raw"], r1),
    ], r1)
    beat(3, [], r1)
    beat(4, [DStep("rot", rots9[1], r1, r2)], r2)
    d7 = per[7]
    assert d7["rots"] == ()
    beat(5, [DStep("fade", (7,), d7["old"], d7["raw"])], d7["raw"])
    beat(6, [], d7["raw"])
    d3 = per[3]
    rots3 = d3["rots"]
    assert len(rots3) == 2, rots3
    q1 = rot_map(d3["raw"], *rots3[0])
    q2 = rot_map(q1, *rots3[1])
    beat(7, [DStep("swap", (3, 4), d3["old"], d3["old"])], d3["old"])
    beat(8, [
        DStep("fade", (3,), d3["old"], d3["raw"]),
        DStep("rot", rots3[0], d3["raw"], q1),
        DStep("rot", rots3[1], q1, q2),
    ], q2)
    beat(9, [], q2)
    beat(10, [], q2)
    return beats, initial, q2
def srt_timestamp(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000.0))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{millis:03d}"
def write_srt(path: Path, cues: list[Cue]) -> None:
    chunks = []
    for index, entry in enumerate(subtitle_entries(cues), start=1):
        chunks.append(
            f"{index}\n{srt_timestamp(max(0.0, entry['start']))} --> "
            f"{srt_timestamp(min(entry['end'], TL.total if TL else entry['end']))}\n"
            f"{entry['text']}\n"
        )
    path.write_text("\n".join(chunks), encoding="utf-8")


SETTING_BLOCK_TEXT = (
    "二叉树有一根天平，天平总共有三个挂载货物的地方。\n"
    "天平的左边、天平的中间、天平的右边。\n"
    "旋转时只用旋转天平，来平衡三个货物。"
)
MERGED_SUBTITLES = {
    (4, 1): {
        "sources": ((4, 1), (4, 2), (4, 3)),
        "text": SETTING_BLOCK_TEXT,
    },
}


def subtitle_entries(cues: list[Cue]) -> list[dict]:
    by_source = {(cue.fi, cue.si): cue for cue in cues}
    entries = []
    consumed: set[tuple[int, int]] = set()
    for cue in cues:
        source = (cue.fi, cue.si)
        if source in consumed:
            continue
        group = MERGED_SUBTITLES.get(source)
        if group is None:
            entries.append({
                "start": cue.start,
                "end": cue.end,
                "text": cue.text,
                "file_index": cue.fi,
                "segment_index": cue.si,
            })
            continue
        grouped = [by_source[item] for item in group["sources"]]
        entries.append({
            "start": min(item.start for item in grouped),
            "end": max(item.end for item in grouped),
            "text": group["text"],
            "file_index": cue.fi,
            "segment_index": cue.si,
        })
        consumed.update(group["sources"])
    return entries


def write_timeline(path: Path, tl: Timeline) -> None:
    states = []
    current_scene = None
    run_start = 0.0
    for index, cue in enumerate(tl.cues):
        scene = scene_of(cue.fi, cue.si)
        if scene != current_scene:
            if current_scene is not None:
                states.append({
                    "start": run_start,
                    "end": cue.start,
                    "id": current_scene,
                    "description": HEADERS[current_scene],
                })
            current_scene = scene
            run_start = cue.start if index > 0 else 0.0
    states.append({
        "start": run_start,
        "end": tl.total,
        "id": current_scene,
        "description": HEADERS[current_scene],
    })
    payload = {
        "canvas": {"width": WIDTH, "height": HEIGHT, "fps": FPS},
        "manuscript": "AVL树(命名来自他的两个作者).md",
        "audio": [str(path) for path in tl.audio],
        "durations": tl.durations,
        "total_duration": tl.total,
        "asr_model": "medium",
        "subtitles": [
            {
                "index": index,
                "start": entry["start"],
                "end": entry["end"],
                "text": entry["text"],
                "file_index": entry["file_index"],
                "segment_index": entry["segment_index"],
            }
            for index, entry in enumerate(subtitle_entries(tl.cues), start=1)
        ],
        "visual_states": states,
        "notes": [
            "35 current-manuscript WAVs + 1 delete-to-root WAV + 7 legacy WAVs, concatenated byte-preserved; no trimming/resampling.",
            "Subtitles are ASR-timed with typo corrections; wording follows the recording.",
            "Ten scenes; within a scene the page mutates progressively instead of switching.",
            "Right rail collects the four lesson experiences; it slides out when the code section starts.",
            "Tree logic (insert/delete/rotations) verified against an independent AVL core with assertions.",
            "Final MP4 contains video+AAC only; subtitles stay sidecar.",
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
def concat_audio(output_path: Path, files: list[Path]) -> float:
    list_path = output_path.with_suffix(".concat.txt")
    list_path.write_text("\n".join(f"file '{path}'" for path in files) + "\n", encoding="utf-8")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(list_path), "-c", "copy", str(output_path)],
            check=True,
        )
    finally:
        list_path.unlink(missing_ok=True)
    with wave.open(str(output_path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()
def encode_video(output_path: Path, narration: Path, duration: float) -> None:
    frame_count = math.ceil(duration * FPS)
    started = __import__("time").time()
    with tempfile.TemporaryDirectory(prefix="avl-video-", dir="/tmp/opencode") as temp_name:
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
                encoder.stdin.write(render_frame(timestamp).tobytes())
                if index % 300 == 0:
                    elapsed = __import__("time").time() - started
                    print(f"frame {index}/{frame_count} ({index / frame_count * 100:.1f}%) elapsed={elapsed:.0f}s", flush=True)
        finally:
            encoder.stdin.close()
        if encoder.wait() != 0:
            raise RuntimeError("FFmpeg video encoding failed")
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-i", str(video_only), "-i", str(narration),
                "-map", "0:v:0", "-map", "1:a:0", "-t", f"{duration:.6f}", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart",
                str(output_path),
            ],
            check=True,
        )


def render_video_segment(output_path: Path, start_frame: int, end_frame: int) -> None:
    """Render one source-backed scene into a reusable H.264 segment."""
    assert end_frame > start_frame
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.with_suffix(".tmp.mp4").open("wb"):
        pass
    temp_output = output_path.with_suffix(".tmp.mp4")
    encoder = subprocess.Popen(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo",
            "-pix_fmt", "rgb24", "-s:v", f"{WIDTH}x{HEIGHT}", "-r", str(FPS),
            "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "medium",
            "-crf", "0", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(temp_output),
        ],
        stdin=subprocess.PIPE,
    )
    assert encoder.stdin is not None
    try:
        for frame_index in range(start_frame, end_frame):
            encoder.stdin.write(render_frame(frame_index / FPS).tobytes())
    finally:
        encoder.stdin.close()
    if encoder.wait() != 0:
        temp_output.unlink(missing_ok=True)
        raise RuntimeError(f"segment encoding failed: {output_path.name}")
    temp_output.replace(output_path)


def concat_video_segments(output_path: Path, segments: list[Path]) -> None:
    """Join same-parameter H.264 segments without re-rendering their frames."""
    list_path = output_path.with_suffix(".segments.txt")
    list_path.write_text(
        "".join(f"file '{path}'\n" for path in segments), encoding="utf-8"
    )
    temp_output = output_path.with_suffix(".tmp.mp4")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(list_path), "-c", "copy", str(temp_output)],
            check=True,
        )
        temp_output.replace(output_path)
    finally:
        list_path.unlink(missing_ok=True)
        temp_output.unlink(missing_ok=True)


def mux_video_audio(output_path: Path, video_only: Path, narration: Path, duration: float) -> None:
    temp_output = output_path.with_suffix(".mux.tmp.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_only), "-i", str(narration),
         "-map", "0:v:0", "-map", "1:a:0", "-t", f"{duration:.6f}", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart",
         str(temp_output)],
        check=True,
    )
    temp_output.replace(output_path)


# ------------------------------------------------------------- runtime ----
TL: "Timeline | None" = None
INSERT_BEATS: "list[Beat]" = []
DELETE_BEATS: "dict[int, DBeat]" = {}
DELETE_FINAL = None
DRAWERS: "dict[str, object]" = {}


def register(scene_id: str, fn) -> None:
    DRAWERS[scene_id] = fn


# ------------------------------------------------------ experience strip ----
# The four experiences live in the empty top strip of the frame: one single
# row, appended left-to-right as each sentence is spoken, gone at code start.
EXP_ANCHORS = (
    ("cue", 4, 3),            # 旋转时只用旋转天平 87.888s
    ("cue", 7, 1),            # 哪边树高，哪边更重，哪边就是天平 134.271s
    ("cue", 19, 40),          # 完整插入规则
    ("cue", 20, 18),          # 删除停止条件
)
EXP_LINES = (
    ("旋转时只用旋转天平",),
    ("哪边树高，哪边更重，哪边就是天平",),
    ("插入后一直向上判断到根，一旦遇到失衡，调整一次就结束",),
    ("删除后一直向上判断到根，哪一层树高不再减小就结束",),
)
EXP_X0 = 24.0
EXP_Y = 40.0
EXP_SIZE = 24
EXP_SEP = 24.0
EXP_EXIT_HOLD = 0.5
EXP_EXIT_DUR = 1.2


def draw_experience_panel(image: Image.Image, tl: "Timeline", t: float) -> None:
    """Top strip: one single row of plain orange-gold sentences, pinned to the
    top and always centered as a group (one sentence → centered; two → the
    pair centered), sliding up and out at code start."""
    exit_start = tl.gs(28, 0)
    if t >= exit_start + EXP_EXIT_HOLD + EXP_EXIT_DUR:
        return
    dy = 0.0
    if t >= exit_start + EXP_EXIT_HOLD:
        dy = -ease((t - exit_start - EXP_EXIT_HOLD) / EXP_EXIT_DUR) * 90.0
    draw = ImageDraw.Draw(image)

    def anchor_start(anchor) -> float:
        if anchor[0] == "cue":
            return tl.gs(anchor[1], anchor[2])
        return tl.segment_start(anchor[1], anchor[2], anchor[3])

    anchor_starts = [anchor_start(anchor) for anchor in EXP_ANCHORS]
    visible = 0
    for start in anchor_starts:
        if t >= start:
            visible += 1
        else:
            break
    if visible == 0:
        return
    widths = [text_w(EXP_LINES[i][0], EXP_SIZE) for i in range(visible)]
    total = sum(widths) + EXP_SEP * (visible - 1)
    x = (WIDTH - total) / 2.0
    for index in range(visible):
        line_text = EXP_LINES[index][0]
        draw_text(draw, (x, EXP_Y + dy), line_text, size=EXP_SIZE, fill=ORANGE, anchor="lm")
        x += widths[index] + EXP_SEP


def prepare() -> "Timeline":
    global TL, INSERT_BEATS, DELETE_BEATS, DELETE_FINAL
    for font_path in (SANS_FONT, SERIF_FONT, MONO_FONT):
        assert Path(font_path).exists(), font_path
    tl = Timeline()
    build_fi_si(tl)
    TL = tl
    INSERT_BEATS = build_insert_beats()
    final_insert = INSERT_BEATS[-1].state_after
    assert final_insert is not None
    canonical = layout_snap(final_insert, STAGE5, pad=64.0, gap=150.0, step_side=182.0, y_step=132.0)
    INSERT_CANONICAL_X.update({key: point[0] for key, point in canonical.items()})
    DELETE_BEATS, _initial, DELETE_FINAL = build_delete_beats()
    return tl


def scene_span(scene_id: str) -> "tuple[float, float]":
    assert TL is not None
    order = [entry[0] for entry in SCENES]
    index = order.index(scene_id)
    _, f0, s0, _f1, _s1 = SCENES[index]
    if scene_id == "s8-factor" and TL.program_title_start is not None:
        start = TL.program_title_start
    else:
        start = 0.0 if index == 0 else TL.gs(f0, s0)
    if index + 1 < len(SCENES):
        next_scene, nf, ns, _, _ = SCENES[index + 1]
        end = TL.program_title_start if next_scene == "s8-factor" else TL.gs(nf, ns)
    else:
        end = TL.total
    return start, end


def render_frame(t: float) -> Image.Image:
    assert TL is not None
    image = Image.new("RGB", (WIDTH, HEIGHT), BLACK)
    if t >= TL.total:
        # the silent final code section lives beyond the narration track
        DRAWERS["s10-code"](image, t, TL)
        return image
    if (
        TL.program_title_start is not None
        and TL.program_audio_start is not None
        and TL.program_title_start <= t < TL.program_audio_start
    ):
        DRAWERS["s8-factor"](image, t, TL)
        draw_experience_panel(image, TL, t)
        return image
    cue = TL.cues[TL.find(t)]
    scene = scene_of(cue.fi, cue.si)
    DRAWERS[scene](image, t, TL)
    draw_experience_panel(image, TL, t)
    return image


# Corrected narration text per (file_index, segment_index); recovered from the
# accepted timeline so wording matches the shipped subtitles exactly.
OVERRIDES = {
    (0, 0): "AVL 树是一棵自平衡二叉搜索树，当不满足平衡条件的时候，它就修一修，调一调，让它重新满足平衡。这个平衡条件就是任意节点左右子树高度差，最大只能为 1。",
    (1, 0): "就比如像这样：左边两个子树，一个高度为 1，一个高度为 3，就是失衡。右边 6，它的两个子树高度都为 2。而 6 的左子树 5，5 的子树一个是 3 高度为 1，另一个是空，所以高度差是 1。",
    (2, 0): "在失衡的时候，AVL 树通过旋转操作保持平衡。那么它是如何旋转的呢？两个例子带你彻底了解清楚。",
    (2, 1): "只需要两个例子，我们就能彻底了解。",
    (3, 0): "我们眼前的这是一棵不符合 AVL 的树，对吧？",
    (3, 1): "5 的左子树 3 高度为 1，右子树 9、14、17 这一串高度为 3。",
    (4, 0): "有些同学可能知道一些旋转方法，但那些统统不要管，现在我来给你个新的设定。",
    (4, 1): "二叉树有一根天平，天平总共有三个挂载货物的地方。",
    (4, 2): "天平的左边，天平的中间，天平的右边。",
    (4, 3): "旋转时，只旋转天平，来平衡三个货物。",
    (5, 0): "你只要找到天平，然后把三个货物都摘下来，天平旋转完之后，再重新按照原样挂上去，像这样。",
    (6, 0): "这里选中的 5—9 就是天平",
    (6, 1): "最左边挂载的子树是 3",
    (6, 2): "中间挂载的子树是 6",
    (6, 3): "最右边挂载的子树是 14、17",
    (6, 4): "我们三个货物挂载的位置没变",
    (6, 5): "左边还在左边",
    (6, 6): "中间还在中间",
    (6, 7): "右边还在右边",
    (6, 8): "也因此中序遍历顺序是不变的",
    (7, 0): "关键问题来了，天平位置怎么找？哪边树高，哪边更重，哪边就是天平。这里的 14—17 树高更高，或者说它更重，那这一边的 5—9 就是天平，而不是 5—3。",
    (8, 0): "为什么这样找天平呢？",
    (8, 1): "为什么这种旋转就能管用呢？",
    (8, 2): "旋转实际是在干什么呢？",
    (8, 3): "这种操作实际对应的意象是这样的",
    (9, 0): "AVL 树不平衡的时候，是因为有一端更重，更重的那一端需要抬起来，",
    (9, 1): "所以天平原本应该倾斜到更重的那一边，这样旋转之后刚好把它抬起来。",
    (10, 0): "找到天平之后，其实就能明显看出是左中右三个货物，中间的货物由于重力会滑到天平倾斜的一边。",
    (10, 1): "在这里这个由插入造成的失衡里，天平一旋转，一边增加一层，另一边减少一层，原本的高度差 2 刚好变成 0。",
    (10, 2): "这是插入场景的结论。删除时旋转修复后，高度差也可能是 1，只要重新回到 AVL 允许的范围就行。",
    (10, 3): "而 AVL 树原本高度差最大就是 1，被打破平衡时又只能高度差为 2。",
    (11, 0): "意象是意象，实际操作时，我们找到天平，一旋转，货物左边还在左边，中间还在中间，右边还在右边，原路返回就行。",
    (12, 0): "我们再来看一个",
    (12, 1): "这个天平左中右都挂了一个货物",
    (12, 2): "天平本身就是平衡",
    (12, 3): "它本身就是一棵 AVL 树",
    (12, 4): "这时候能不能转",
    (12, 5): "能转",
    (12, 6): "刚好转成它的对称构型",
    (12, 7): "但是没有必要，没事转着玩",
    (13, 0): "然后这树高不是都一样吗？这怎么判断杠杆？其实还是看哪边重就行。因为一开始中间这个 B 它是滑溜到左边，那 AB 这一坨它更重。而我是想把中间这个 B 滑溜到 C 这边，那这就是一棵 AVL 树。所以实际上对不平衡的树调整时，你不会遇见这种情况，你就纯看树高就行。",
    (14, 0): "例子二，中间失衡。刚才的例子一是两边失衡，我们抬起一边放下一边，来保持平衡。",
    (15, 0): "那么如果天平中间那个货物更重怎么办？",
    (15, 1): "天平中间的货物更重",
    (15, 2): "天平往左倾斜，它滑到左边，导致左边更重",
    (15, 3): "天平往右倾斜，它滑到右边，导致右边更重",
    (16, 0): "那没办法，你需要先把中间的货物给移到两边，然后再通过抬起更重的那一端来保持平衡。",
    (17, 0): "所以是分两步，第一步把货物转移，第二步正常旋转天平。把货物转移也可以通过旋转来改变重心来实现。",
    (18, 0): "我们可以看到，首先我们发现右子树高度更高，是右边更重，判断杠杆是 z—y，所以三个货物分别是 A、X 与 D，判断不平衡原因是因为中间货物 X 更重导致的。",
    (18, 1): "第一次旋转，旋转 X 所在的子树，将这棵子树的重心从左边转移到右边。",
    (18, 2): "现在对于杠杆 z—x，恢复到两边货物更重的情况，进行第二次旋转即可。",
    (18, 3): "注意杠杆是一个形，是个形状，原本的 ZY 现在是 ZX，而不是固定的字母。",
    (19, 0): "接下来让我们看一次从 0 开始的完整插入",
    (19, 1): "插入 1，变成根",
    (19, 2): "插入 3，挂在 1 的右边",
    (19, 3): "插入 7，1 的右子树沉，天平是 1—3",
    (19, 4): "旋转完成修复",
    (19, 5): "插入 6，沿搜索路径挂在 7 的左边",
    (19, 6): "没有破坏平衡",
    (19, 7): "插入 4，7 的左边沉，旋转完成修复",
    (19, 8): "注意，找哪棵树不平衡的时候",
    (19, 9): "是向上找最近的一棵树",
    (19, 10): "插入 5，3 的右边沉",
    (19, 11): "先判断天平是 3—6",
    (19, 12): "再判断中间失衡，小天平是 4—6",
    (19, 13): "先右旋，化为两边失衡",
    (19, 14): "再正常调整",
    (19, 15): "插入 2，以 3 为根的这棵树",
    (19, 16): "右边是空，所以它失衡",
    (19, 17): "再判断中间失衡，两步调整",
    (19, 18): "插入 0，沿搜索路径挂在 1 的左边，不用动",
    (19, 19): "插入 -2，1 的左边沉，天平是 1—0，左边失衡",
    (19, 20): "插入 -1，2 的左边沉，天平是 2—0，左边失衡",
    (20, 0): "删除与二叉搜索树一样：零个或一个孩子的节点，直接用唯一的孩子或空位接替；只有两个孩子挡住直接接替时，才用右子树里最小的后继顶替，再删除替身原来所在的位置。",
    (21, 0): "我们来看几个例子。",
    (21, 1): "第一次删除 9，向上看。",
    (21, 2): "最近的 10 这棵树不平衡，进行调整。",
    (21, 3): "原来 10 的位置变成 11 了，沿 11 继续向上看。",
    (21, 4): "8 不平衡，进行调整。",
    (21, 5): "第二次删除 7，7 只有一个孩子，直接用它的孩子取代它。",
    (21, 6): "向上看 8，这棵子树的高度没有变小，调整结束。",
    (21, 7): "第三次删除 3，先和它的后继 4 进行交换。",
    (21, 8): "4 这棵树不平衡了，判断为中间失衡，进行两步调整。",
    (21, 9): "调整完之后，向上看 5，这棵子树的高度没有变小，调整结束。",
    (22, 0): "插入和删除都要一直向上判断到根；插入路上遇到失衡，就可以停下来，删除要路上遇到树高不再减小，才可以停下来。",
    (22, 1): "再来一个，这是一个会连续出现两次失衡的例子。",
    (22, 2): "删除 64 后，先在 70 处调整，调整完不能停下来。",
    (22, 3): "继续检查 59、36，直到检查到根 80 时才发现第二次失衡。",
    (23, 0): "AVL 整个体系能够成立还需要论证：对于任意一棵 AVL 树做出增加或者删除节点的操作之后，一定能够通过旋转操作重新得到 AVL。这样由于只有一个节点的树就符合 AVL 树，所以这棵树可以从 0 增长到任意状态，从任意状态重新删除到 0。",
    (24, 0): "这其实根本不需要证明，旋转操作能够平衡左中右三棵子树的高度，",
    (24, 1): "而增加和删除操作又只会破坏左中右三棵子树的高度。",
    (24, 2): "我们旋转操作确实是有应用条件的，那就是高度差等于 2，",
    (24, 3): "但是增和删每次只会操作一个数据，这顶多引起 1 的高度变化，",
    (24, 4): "所以要么变完之后仍符合 AVL，不用调整，要么一定能调整。",
    (25, 0): "补充说明，人眼判断时只需要观察哪一侧更高，但实际编写代码时，代码没有眼，所以需要引入平衡因子来判断树高。",
    (25, 1): "平衡因子就是左子树减去右子树的高度。",
    (25, 2): "AVL 树要求每个节点的平衡因子只取 -1、0 和 1。",
    (26, 0): "对于一棵不平衡的树的根，根节点的平衡因子大于 1，左边沉。再读左孩子的平衡因子：左孩子的平衡因子大于等于 0，左边失衡；左孩子的平衡因子小于 0，说明中间失衡，先对左孩子左旋，再对根节点右旋。",
    (26, 1): "根节点的平衡因子小于 -1，右边沉。再读右孩子的平衡因子：右孩子的平衡因子小于等于 0，右边失衡；右孩子的平衡因子大于 0，说明中间失衡，先对右孩子右旋，再对根节点左旋。",
    (27, 0): "传统教材把这两个问题排列组合成左左、右右、左右、右左四个名字，我们其实不过是先分成两边沉还是中间沉两种情况，每种情况内部再各分左右。",
    (28, 0): "接下来就是对应的 C 语言代码，这个看不看都行，意义不大。",
    (28, 1): "要看代码的话，我推荐你看传统的分四个模式的讲解视频和对应代码。",
    (28, 2): "而我给的代码是按照我们这个逻辑来写的。",
    (28, 3): "在这里放出来，证明我们的逻辑可以直接编写成代码。",
    (28, 4): "不看代码我也推荐你再看一下传统的讲解方式。",
    (29, 0): "传统方法做题快，我们的方法只是可能稍微更容易理解一些。",
    (29, 1): "下边是我们的代码与传统代码的对比，之后就是详细的代码。",
}

# Remove the former scene-5/6 cue map before adding the current manuscript.
# The updated narration has different cue boundaries, so retaining old keys
# would silently attach prior subtitles to unrelated new audio.
for _cue_key in [key for key in OVERRIDES if 19 <= key[0] <= 22]:
    del OVERRIDES[_cue_key]

# Current manuscript text for the re-recorded AVL chapter. ASR timestamps are
# retained, while these strings are the authoritative subtitle wording.
OVERRIDES.update({
    (0, 0): "AVL 树是自平衡二叉搜索树。AVL 这个名字来自它的两位发明者：Adelson-Velsky（阿德尔森-维尔斯基）和 Landis（兰迪斯）。二叉搜索树的插入可能导致极度的不平衡，导致退化问题。AVL 树当不满足平衡条件的时候，它就修一修，调一调，让它重新满足平衡，从而避免退化。这个平衡条件就是任意节点左右子树高度差最大只能为一。",
    (19, 0): "第一次旋转后是改变了重心，重心变了，左撇子变右撇子了，树高可没变，记住这点，后面要考。",
    (19, 3): "插入。",
    (19, 4): "插入前，假设最大的两颗左右子树是 n 与 n+1，那么树高是 n+2。",
    (19, 5): "插入时临时变成 n 与 n+2。",
    (19, 6): "第一次旋转后，或者说第一种旋转后，还是 n 与 n+2。",
    (19, 7): "第二次旋转后，或者说第二种旋转后，一边增加 1，一边减少 1。",
    (19, 8): "插入完成后最终，n 变成 n+1，n+2 变成 n+1。",
    (19, 9): "树高还是 n+2。",
    (19, 10): "中间失衡的调整不会引起树高变化。",
    (19, 11): "两边失衡只牵涉第二种旋转。",
    (19, 12): "同理也不会引起树高变化。",
    (19, 13): "那么，无论是两边失衡，还是中间失衡，插入前树高是多少，插入后树高就是多少。",
    (19, 14): "那么，能使 AVL 树树高增长的插入一定是无调整的。",
    (19, 15): "也就是凡牵涉调整的插入都不会引起树高变化。",
    (19, 16): "能使 AVL 树树高增长的插入一定是无调整的。",
    (19, 17): "但是无调整的插入可不一定使树高增长。",
    (19, 18): "比如单单一个 2，左子树是 1，插入 3。",
    (19, 19): "接下来让我们讲从零开始的完整插入。",
    (19, 20): "每插入一个数，首先肯定是按二叉搜索树的规则。",
    (19, 21): "给它找到落点。",
    (19, 22): "然后呢？",
    (19, 23): "然后，首先就是插入后需要从落点沿着来路一直向上判断到根，因为插入这个节点属于很多层子树，我们需要判断它对各级子树的影响。如下图，插入 80 后，一层一层向上判断，判断到 45 这一层的时候才发现失衡。",
    (19, 24): "但是在一直向上判断到根的过程中，我们发现失衡就修复，修复完还需要继续向上检查吗？",
    (19, 25): "我们再来读一读这句话。",
    (19, 26): "修复完还需要继续向上检查吗？",
    (19, 27): "是修复完！",
    (19, 28): "那说明调整操作已经发生了。",
    (19, 29): "可是刚刚我们得到结论。",
    (19, 30): "凡牵涉调整的插入都不会引起树高变化。",
    (19, 31): "那调整的这棵树树高没变化。",
    (19, 32): "它是在内部进行了修复。",
    (19, 33): "对外界来说是不可感的。",
    (19, 34): "那外界就不需要进行调整。",
    (19, 35): "因为对外界来说，它就相当于没变。",
    (19, 36): "所以其实需要且只需要调整一次！",
    (19, 37): "也就是说，插入后需要从落点沿着来路一直向上判断到根。",
    (19, 38): "但是路上一旦遇到失衡，就知道这次调整完就结束了，不需要再向上检查了。",
    (19, 39): "修完后不需要再判断是否还失衡。",
    (19, 40): "好，那么完整的插入规则是：按二叉搜索树的规则给它找到落点，插入后一直向上判断到根，一旦遇到失衡，调整一次就提前结束。",
    (19, 41): "好吧，那么现在来看从零开始的完整插入。",
    (19, 42): "插入 1：平衡。插入 3：平衡。插入 7。",
    (19, 43): "向上检查：3 自己是平衡的；再往上是 1。",
    (19, 44): "它的右子树挂着 3 和 7，高两层。",
    (19, 45): "左子树是空，高度差 2，这里失衡了。",
    (19, 46): "哪边重哪边就是天平，所以天平是 1—3。",
    (19, 47): "看三个货物：左边货物是空，中间是空，右边是 7。",
    (19, 48): "两边失衡直接旋转天平 1—3：左旋，货物原路返回。",
    (19, 49): "7 还挂在 3 的右边。整棵树恢复平衡。",
    (19, 50): "插入 6：落在 7 的左边。向上检查：7 和 3 都是平衡的。",
    (19, 51): "插入 4：落在 6 的左边。向上检查：6 平衡；再往上。",
    (19, 52): "7 的左边挂着 6 和 4，右边是空，高度差 2。",
    (19, 53): "失衡了，天平是 7—6。三个货物：左边是 4，中间空，右边空。",
    (19, 54): "两边失衡直接旋转天平 7—6：右旋，货物原路返回。",
    (19, 55): "4 还挂在 6 的左边。整棵树恢复平衡。",
    (19, 56): "插入 5：落在 4 的右边。向上检查：4 和 6 都是平衡的；再往上，3 的右子树更重，高度差 2。",
    (19, 57): "天平是 3—6。三个货物：左边是 1，中间是 4 和 5，右边是 7。中间货物更重，这是中间失衡。",
    (19, 58): "先右旋小天平 6—4，把 5 挂到 6 的左边；再左旋天平 3—4，货物原路返回。整棵树恢复平衡。",
    (19, 59): "插入 2：落在 1 的右边。向上检查：1 平衡；再往上。",
    (19, 60): "3 的左边挂着 1 和 2，右边是空，高度差 2，这里失衡了。",
    (19, 61): "天平是 3—1。左边是空，中间是 2，右边是空。",
    (19, 62): "中间货物更重，这是中间失衡。先左旋小天平 1—2。",
    (19, 63): "再右旋天平 3—2。",
    (19, 64): "货物原路返回。整棵树恢复平衡。",
    (19, 65): "插入 0：0 比 4 小，比 2 小，比 1 小，落在 1 的左边。向上检查：1、2 和 4 都是平衡的。",
    (19, 66): "插入 -2：落在 0 的左边。向上检查：0 平衡。",
    (19, 67): "再往上，1 的左边挂着 0 和 -2，右边是空，高度差 2，这里失衡了。",
    (19, 68): "哪边重哪边就是天平，所以天平是 1—0。",
    (19, 69): "左边是 -2，中间是空，右边是空。两边失衡，右旋 1—0。",
    (19, 70): "货物原路返回。",
    (19, 71): "整棵树恢复平衡。",
    (19, 72): "插入 -1：-1 比 4 小向左，比 2 小向左，比 0 小向左，比 -2 大向右。",
    (19, 73): "落在 -2 的右边。向上检查。",
    (19, 74): "-2 和 0 都是平衡的；再往上，2 的左子树更重。",
    (19, 75): "高度差 2，这里失衡了。哪边重哪边就是天平。",
    (19, 76): "所以天平是 2—0。看三个货物：左边是 -2 和 -1，中间是 1，右边是 3。",
    (19, 77): "左边货物更重，这是两边失衡。",
    (19, 78): "直接右旋天平 2—0，货物原路返回。整棵树恢复平衡。",
    (20, 0): "删除。",
    (20, 1): "首先按照二叉搜索树规则找到要删的节点，和二叉搜索树一样，判断是零个孩子、一个孩子还是两个孩子。",
    (20, 2): "两个孩子的时候，使用它的直接前驱或后继替换它，然后删掉它。",
    (20, 3): "之后看一下这棵树有没有失衡。",
    (20, 4): "没有失衡就看一下删除导致子树变小没有。",
    (20, 5): "失衡了就旋转调整。",
    (20, 6): "这时候和插入就不一样了，调整完不能直接结束，还得再看一眼这棵子树的高度变小没有。",
    (20, 7): "没变小，删除的影响到这就结束了。",
    (20, 8): "变小了，对上层就是可感的。",
    (20, 9): "还得继续向上判断。",
    (20, 10): "所以是从删除的位置沿着来路向上检查。",
    (20, 11): "一直到检查的这棵子树的高度不再变小为止。",
    (20, 12): "也就是说，不管是插入还是删除。",
    (20, 13): "需要一直向上判断到根。",
    (20, 14): "插入时路上遇到失衡了。",
    (20, 15): "就知道调整完可以停下来了。",
    (20, 16): "删除时，路上遇到树高不再减小。",
    (20, 17): "就知道可以停下来了。",
    (20, 18): "删除后一直向上判断到根。",
    (20, 19): "哪一层树高不再减小才能结束。",
    (21, 0): "我们来看几个例子。",
    (21, 1): "第一次删除 9。",
    (21, 2): "向上看，最近的 10 这棵树不平衡，进行调整。",
    (21, 3): "原来 10 的位置变成 11 了。",
    (21, 4): "沿 11 继续向上看。",
    (21, 5): "8 不平衡，进行调整。",
    (21, 6): "这已经到根了，调整结束。",
    (21, 7): "第二次删除 7，7 只有一个孩子。",
    (21, 8): "直接用它的孩子取代它。",
    (21, 9): "向上看 8，这棵子树的高度没有变小。",
    (21, 10): "调整结束。",
    (21, 11): "第三次删除 3。",
    (21, 12): "先和它的后继 4 进行交换。",
    (21, 13): "4 这棵子树不平衡了。",
    (21, 14): "判断为中间失衡，进行两步调整。",
    (21, 15): "调整完之后，向上看 5。",
    (21, 16): "这棵子树的高度没有变小，调整结束。",
    (22, 0): "再来一个，这是一个会连续出现两次失衡的例子。",
    (22, 1): "删除 64 后，先在 70 处调整，调整完不能停下来。",
    (22, 2): "继续检查 59、36，直到检查根 80 时才发现第二次失衡。",
})
