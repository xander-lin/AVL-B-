#!/usr/bin/env python3
"""Build B-tree course shot 01: the opening (BST degeneration → AVL contrast →
B-tree grows bottom-up).

Everything on screen is sampled from one pure state function of narration time.
The narration timing comes from outputs/btree-prep/b-asr.json (recording 15);
phrase windows below are measured word spans of that immutable recording.

Usage:
    python scripts/btree/shot01.py                 # render segment + mux audio
    python scripts/btree/shot01.py --preview       # checkpoint frames only
    python scripts/btree/shot01.py --preview --at 4.8,11.3
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import wave
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "avl"))
import engine as avl  # noqa: E402  shared palette, fonts, primitives
from reference_style import render as render_reference_btree  # noqa: E402

ASR_JSON = ROOT / "outputs" / "btree-prep" / "b-asr.json"
RECORDING_INDEX = 15
OUTPUT_DIR = ROOT / "outputs" / "btree-video"
WIDTH, HEIGHT, FPS = avl.WIDTH, avl.HEIGHT, avl.FPS
NODE_RADIUS = 36.0

# ---- narration phrase windows (word timestamps of recording 15) ----------
W_DEGENERATE = (6.04, 7.24)        # 导致退化
W_WHY = (7.24, 8.36)               # 为什么会这样呢?
W_ROOT_CLAIM = (9.82, 12.00)       # 谁先插入谁就是根
W_LEVEL_1 = (13.18, 13.86)         # 第一层
W_LEVEL_2 = (14.50, 14.94)         # 第二层
W_LEVEL_3 = (15.12, 16.58)         # 以此类推
W_INDEX_UP = (16.92, 20.10)        # 层数越靠上…索引的作用
W_INDEX_QUALITY = (20.30, 23.76)   # 索引质量…时间复杂度的关键
W_WHO_FIRST = (26.46, 28.20)       # 谁先来谁就是索引
W_TILT = (29.24, 32.08)            # 脖子歪了，一步错步步错
W_AVL = (33.32, 38.06)             # AVL 修补树的形状
SHOT_CUT = 38.70                   # narration pause between the two shots
FADE_TAIL = 1.5                    # end-of-shot fade-out gap before the next shot
W_BTREE = (39.28, 41.72)           # 我们今天要学习的 B 树
W_ELECT = (47.66, 49.82)           # 由各级动态推举产生

# ---- scene geometry -------------------------------------------------------
QUEUE_TOP = -80.0
CHAIN = {"10": (700.0, 285.0), "20": (855.0, 400.0), "30": (1010.0, 515.0), "40": (1165.0, 630.0)}
CHAIN_EDGES = (("10", "20"), ("20", "30"), ("30", "40"))
LANDED = (0.55, 1.67, 2.79, 3.91)   # key i starts falling; 0.8 s ease each
BALANCED = {"20": (960.0, 265.0), "10": (770.0, 470.0), "30": (1150.0, 470.0), "40": (1345.0, 655.0)}
BALANCED_EDGES = (("20", "10"), ("20", "30"), ("30", "40"))
AVL_MOVE = (33.70, 35.70)


def manifest_audio() -> tuple[Path, float]:
    payload = json.loads(ASR_JSON.read_text(encoding="utf-8"))
    item = next(file for file in payload["files"] if file["recording_index"] == RECORDING_INDEX)
    path = Path(item["audio"])
    with wave.open(str(path), "rb") as handle:
        duration = handle.getnframes() / handle.getframerate()
    assert abs(duration - item["duration"]) < 0.05, (duration, item["duration"])
    return path, duration


AUDIO_PATH, AUDIO_DURATION = manifest_audio()
TOTAL = AUDIO_DURATION


# ---- drawing helpers ------------------------------------------------------
def node(
    draw: ImageDraw.ImageDraw,
    point: avl.Point,
    key: str,
    *,
    opacity: float = 1.0,
    glow: tuple[int, int, int] = avl.GLOW_BLUE,
    halo: tuple[int, int, int] | None = None,
    radius: float = NODE_RADIUS,
    key_size: int = 30,
) -> None:
    x, y = point
    size = radius * 2.0
    if opacity <= 0.0:
        return
    for grow, share in ((18.0, 0.10), (11.0, 0.16), (6.0, 0.28), (3.0, 0.50)):
        draw.rounded_rectangle(
            (round(x - radius - grow), round(y - radius - grow),
             round(x + radius + grow), round(y + radius + grow)),
            radius=round(28 + grow / 2),
            fill=avl.blend(glow, opacity * share),
        )
    draw.rounded_rectangle(
        (round(x - radius), round(y - radius), round(x + radius), round(y + radius)),
        radius=round(size * 0.20),
        fill=avl.blend(avl.NODE_FILL, opacity),
        outline=avl.blend(avl.NODE_RIM, opacity),
        width=max(2, round(size * 0.035)),
    )
    if halo is not None:
        draw.rounded_rectangle(
            (round(x - radius - 10), round(y - radius - 10),
             round(x + radius + 10), round(y + radius + 10)),
            radius=round(size * 0.25),
            outline=avl.blend(halo, opacity),
            width=4,
        )
    avl.draw_text(draw, (x, y + 1), key, size=key_size, fill=avl.blend(avl.INK, opacity), family="mono")


def tree_edge(draw: ImageDraw.ImageDraw, a: avl.Point, b: avl.Point, *, color=None, width: int = 8, opacity: float = 1.0) -> None:
    if opacity <= 0.0:
        return
    start, end = avl.trimmed(a, b, NODE_RADIUS)
    avl.line(draw, start, end, avl.blend(color or avl.INK, opacity), width)


def window(local: tuple[float, float], t: float) -> float:
    start, end = local
    if t <= start:
        return 0.0
    if t >= end:
        return 1.0
    return avl.ease((t - start) / (end - start))


# ---- state ----------------------------------------------------------------
def chain_positions(t: float) -> dict[str, avl.Point]:
    positions: dict[str, avl.Point] = {}
    for index, key in enumerate(("10", "20", "30", "40")):
        target = CHAIN[key]
        start = (target[0], QUEUE_TOP)
        progress = window((LANDED[index], LANDED[index] + 0.8), t)
        positions[key] = avl.lerp_pt(start, target, progress)
    return positions


def current_positions(t: float) -> dict[str, avl.Point]:
    """Key positions for the first shot: chain until the AVL repair moves them."""
    if t < AVL_MOVE[0]:
        return chain_positions(t)
    progress = window(AVL_MOVE, t)
    from_chain = chain_positions(AVL_MOVE[0] + 0.8)
    return {key: avl.lerp_pt(from_chain[key], BALANCED[key], progress) for key in CHAIN}


def active_edges(t: float) -> list[tuple[str, str]]:
    landed = 0
    for index, key in enumerate(("20", "30", "40")):
        if window((LANDED[index + 1], LANDED[index + 1] + 0.8), t) >= 1.0:
            landed = index + 1
    if t >= AVL_MOVE[0]:
        return list(BALANCED_EDGES)
    return list(CHAIN_EDGES[:landed])


def draw_frame(t: float) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), avl.BLACK)
    draw = ImageDraw.Draw(image)
    if t < SHOT_CUT:
        draw_shot_intro(draw, t)
    else:
        draw_shot_growth(image, t)
    return image


def draw_shot_intro(draw: ImageDraw.ImageDraw, t: float) -> None:
    positions = current_positions(t)
    avl.draw_text(draw, (86, 72), "二叉搜索树" if t < 35.9 else "AVL 树", size=40, fill=avl.INK, anchor="lm")

    # edges (red route highlight during the tilted-chain cost beat)
    route_edges: dict[tuple[str, str], float] = {}
    for index, edge in enumerate(CHAIN_EDGES):
        start = 29.6 + index * 0.9
        route_edges[edge] = window((start, start + 0.5), t) * (1.0 - window((33.30, 33.90), t))
    for edge in active_edges(t):
        highlight = route_edges.get(edge, 0.0)
        if highlight > 0.0:
            tree_edge(draw, positions[edge[0]], positions[edge[1]], color=avl.GLOW_RED, width=9)
        else:
            tree_edge(draw, positions[edge[0]], positions[edge[1]])

    # query dot crawling down the chain
    if W_TILT[0] <= t < 33.32:
        hops = [(CHAIN["10"], CHAIN["20"]), (CHAIN["20"], CHAIN["30"]), (CHAIN["30"], CHAIN["40"])]
        for index, (a, b) in enumerate(hops):
            start = 29.6 + index * 0.9
            progress = window((start, start + 0.9), t)
            if 0.0 < progress < 1.0:
                point = avl.lerp_pt(a, b, progress)
                draw.ellipse(
                    (round(point[0] - 12), round(point[1] - 12), round(point[0] + 12), round(point[1] + 12)),
                    fill=avl.blend(avl.GLOW_RED, 1.0),
                )
                break

    # level badges (left) and insertion-order badges (right)
    levels = (("第 1 层", "20", W_LEVEL_1), ("第 2 层", "30", W_LEVEL_2), ("第 3 层", "40", W_LEVEL_3))
    fade_labels = 1.0 - window((33.70, 34.40), t) if t >= AVL_MOVE[0] else 1.0
    if t >= 13.0:
        avl.draw_text(draw, (745, 230), "根", size=34, fill=avl.blend(avl.INK, fade_labels), anchor="lm")
    for text, key, span in levels:
        opacity = window(span, t) * fade_labels
        point = positions[key]
        avl.draw_text(draw, (point[0] - 140, point[1]), text, size=30, fill=avl.blend(avl.SOFT, opacity), anchor="rm")
    for index, key in enumerate(("10", "20", "30", "40")):
        opacity = window((24.3 + index * 0.6, 25.1 + index * 0.6), t) * fade_labels
        point = positions[key]
        avl.draw_text(draw, (point[0] + 120, point[1]), "①②③④"[index], size=32, fill=avl.blend(avl.GLOW_WHITE, opacity), anchor="lm")

    # index bracket over the top two levels
    bracket = window(W_INDEX_UP, t) * fade_labels
    if bracket > 0.0:
        avl.line(draw, (545, 245), (545, 445), avl.blend(avl.SKY_BLUE, bracket), 5)
        avl.line(draw, (545, 245), (565, 245), avl.blend(avl.SKY_BLUE, bracket), 5)
        avl.line(draw, (545, 445), (565, 445), avl.blend(avl.SKY_BLUE, bracket), 5)
        avl.draw_text(draw, (505, 345), "索引", size=34, fill=avl.blend(avl.SKY_BLUE, bracket), anchor="rm")

    # root claim highlight
    if W_ROOT_CLAIM[0] <= t < 13.0:
        node(draw, positions["10"], "10", glow=avl.GLOW_WHITE, halo=avl.GLOW_WHITE)
        avl.draw_text(draw, (positions["10"][0] + 40, positions["10"][1] - 60), "先插入 → 根", size=32, fill=avl.INK, anchor="lm")

    # top captions
    if W_INDEX_QUALITY[0] <= t < W_WHO_FIRST[0]:
        avl.draw_text(draw, (960, 150), "索引质量 = 时间复杂度的关键", size=40, fill=avl.INK)
    elif W_WHO_FIRST[0] <= t < W_TILT[0]:
        avl.draw_text(draw, (960, 150), "索引位置：谁先来谁就是", size=40, fill=avl.INK)
    elif t >= 35.8:
        avl.draw_text(draw, (960, 150), "AVL：修补树的形状", size=40, fill=avl.INK)

    # degeneration callout
    if W_DEGENERATE[0] <= t < W_ROOT_CLAIM[0]:
        avl.draw_text(draw, (1350, 430), "退化", size=46, fill=avl.GLOW_RED, anchor="lm")
        if t >= W_WHY[0]:
            avl.draw_text(draw, (1350, 520), "为什么会这样？", size=32, fill=avl.INK, anchor="lm")

    for key in ("40", "30", "20", "10"):
        highlight_root = key == "10" and W_ROOT_CLAIM[0] <= t < 13.0
        node(
            draw,
            positions[key],
            key,
            glow=avl.GLOW_WHITE if highlight_root else avl.GLOW_BLUE,
            halo=avl.GLOW_WHITE if highlight_root else None,
        )


def draw_shot_growth(image: Image.Image, t: float) -> None:
    """Place the opaque source-code B-tree MP4 frame on the course canvas."""
    source = avl._source_frames("btree-insert-black.mp4")
    index = min(max(0, round((t - SHOT_CUT) * 30.0)), len(source) - 1)
    frame = avl._source_frame(str(source[index]))
    image.paste(frame, ((WIDTH - frame.width) // 2, 0))

def write_srt(path: Path) -> None:
    payload = json.loads(ASR_JSON.read_text(encoding="utf-8"))
    item = next(file for file in payload["files"] if file["recording_index"] == RECORDING_INDEX)
    corrections = {
        "二差搜索数": "二叉搜索树",
        "歪脖子数": "歪脖子树",
        "件复杂度": "时间复杂度",
        "AVL数": "AVL 树",
        "B数": "B 树",
        "一不错步不错": "一步错，步步错",
        "数的形状": "树的形状",
        "的AVL": "的 AVL",
        "的B ": "的 B ",
    }
    lines: list[str] = []
    segments = item["segments"]
    for index, segment in enumerate(segments):
        text = segment["text"].strip()
        for broken, fixed in corrections.items():
            text = text.replace(broken, fixed)
        text = text.replace(",", "，").replace("?", "？")
        start = segment["start"]
        end = segment["end"] if index + 1 < len(segments) else min(segment["end"] + 0.6, TOTAL)
        lines.append(f"{index + 1}\n{stamp(start)} --> {stamp(end)}\n{text}\n")
    path.write_text("\n".join(lines), encoding="utf-8")


def stamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000.0)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{millis:03d}"


def encode_segment(output: Path) -> None:
    encode_rendered(output, TOTAL, lambda when: draw_frame(when))


def encode_rendered(output: Path, duration: float, render) -> None:
    frame_count = math.ceil(duration * FPS)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_suffix(".tmp.mp4")
    encoder = subprocess.Popen(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo",
            "-pix_fmt", "rgb24", "-s:v", f"{WIDTH}x{HEIGHT}", "-r", str(FPS),
            "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "medium",
            "-crf", "0", "-pix_fmt", "yuv420p", "-color_range", "tv", "-movflags", "+faststart",
            str(temp_output),
        ],
        stdin=subprocess.PIPE,
    )
    assert encoder.stdin is not None
    try:
        for index in range(frame_count):
            encoder.stdin.write(render(min(index / FPS, duration - 1e-4)).tobytes())
            if index % 300 == 0:
                print(f"frame {index}/{frame_count}", flush=True)
    finally:
        encoder.stdin.close()
    if encoder.wait() != 0:
        temp_output.unlink(missing_ok=True)
        raise RuntimeError("segment encoding failed")
    temp_output.replace(output)


def encode_native_source(output: Path, duration: float) -> None:
    """Pad the opaque source-code MP4 at 60 fps for the opening shot."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_suffix(".tmp.mp4")
    play = duration - FADE_TAIL
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(ROOT / "assets" / "btree-insert-black.mp4"),
            "-vf",
            (
                f"fps=60,pad=1920:1080:166:0:color=black,trim=duration={play:.6f},"
                f"tpad=stop_mode=clone:stop_duration={FADE_TAIL:.6f},"
                f"fade=t=out:st={play:.6f}:d={FADE_TAIL:.6f},setpts=PTS-STARTPTS"
            ),
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "0", "-pix_fmt", "yuv420p",
            "-color_range", "tv", "-r", "60", "-movflags", "+faststart", str(temp_output),
        ],
        check=True,
    )
    temp_output.replace(output)


def concat_video_parts(parts: list[Path], output: Path) -> None:
    listing = output.with_suffix(".concat.txt")
    temporary = output.with_suffix(".tmp.mp4")
    listing.write_text("\n".join(f"file '{part.resolve()}'" for part in parts) + "\n", encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(temporary)],
        check=True,
    )
    listing.unlink(missing_ok=True)
    temporary.replace(output)


def mux_audio(video_only: Path, output: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(video_only), "-i", str(AUDIO_PATH),
            "-map", "0:v:0", "-map", "1:a:0", "-t", f"{TOTAL + FADE_TAIL:.6f}", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart",
            str(output),
        ],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--at", default="1.4,4.8,8.0,11.3,14.2,17.5,21.0,25.2,27.5,30.8,33.0,34.8,37.5,40.0,41.5,42.8,43.6,45.0,46.5,48.6,50.0")
    args = parser.parse_args()
    if args.preview:
        preview_dir = OUTPUT_DIR / "preview" / "shot01"
        preview_dir.mkdir(parents=True, exist_ok=True)
        for value in args.at.split(","):
            when = float(value)
            draw_frame(min(when, TOTAL - 1e-3)).save(preview_dir / f"t{when:07.2f}.png")
        print(f"previews written to {preview_dir}")
        return
    segment = OUTPUT_DIR / "segments" / "shot01-intro.mp4"
    custom = OUTPUT_DIR / "segments" / "shot01-intro-custom.mp4"
    native = OUTPUT_DIR / "segments" / "shot01-intro-native.mp4"
    encode_rendered(custom, SHOT_CUT, lambda when: draw_frame(when))
    encode_native_source(native, TOTAL - SHOT_CUT + FADE_TAIL)
    concat_video_parts([custom, native], segment)
    custom.unlink(missing_ok=True)
    native.unlink(missing_ok=True)
    write_srt(OUTPUT_DIR / "shot01-intro.srt")
    final = OUTPUT_DIR / "shot01-intro.mp4"
    mux_audio(segment, final)
    print(final)


if __name__ == "__main__":
    main()
