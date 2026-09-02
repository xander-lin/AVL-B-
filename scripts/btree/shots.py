#!/usr/bin/env python3
"""Render the B-tree course shots before the deletion chapter.

The supplied B-tree SVG/WebM assets are the visual source of truth.  This
builder only places those assets on the course canvas and adds timing-aligned
diagram annotations; it does not redraw the B-tree nodes.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "avl"))
import engine as avl  # noqa: E402
import general_order  # noqa: E402

ASR_JSON = ROOT / "outputs" / "btree-prep" / "b-asr.json"
OUT = ROOT / "outputs" / "btree-video"
WIDTH, HEIGHT, FPS = avl.WIDTH, avl.HEIGHT, avl.FPS


SHOT_AUDIO = {
    2: 27,
    3: 35,
    4: 39,
    5: 41,
    6: 47,
    7: 49,
    8: 55,
    9: 103,
    10: 107,
    11: 123,
    12: 127,
    13: 129,
    14: 133,
    15: 143,
    16: 145,
}


def audio_info(index: int) -> tuple[Path, float, list[dict]]:
    payload = json.loads(ASR_JSON.read_text(encoding="utf-8"))
    item = next(entry for entry in payload["files"] if entry["recording_index"] == index)
    path = Path(item["audio"])
    with wave.open(str(path), "rb") as handle:
        duration = handle.getnframes() / handle.getframerate()
    return path, duration, item["segments"]


def fade(value: float, start: float, end: float) -> float:
    return avl.ease(avl.clamp((value - start) / max(end - start, 1e-6)))


def source(image: Image.Image, name: str, t: float, *, play_duration: float | None = None) -> None:
    avl.draw_source_media(
        image,
        name,
        t,
        0.0,
        play_duration=play_duration,
        max_width=1500,
        max_height=800,
        y_center=560,
    )


def lower_source(image: Image.Image, name: str, t: float) -> None:
    """Place a supplied B-tree illustration wholly in the lower half."""
    avl.draw_source_media(
        image,
        name,
        t,
        0.0,
        max_width=1740,
        max_height=600,
        y_center=765,
    )


def text(draw: ImageDraw.ImageDraw, value: str, xy: tuple[float, float], *, size: int = 42, color=avl.INK, anchor: str = "mm") -> None:
    avl.draw_text(draw, xy, value, size=size, fill=color, anchor=anchor)


def top(draw: ImageDraw.ImageDraw, value: str, *, color=avl.INK) -> None:
    avl.draw_top_key(draw, value, y=118, size=42, color=color)


def corner(draw: ImageDraw.ImageDraw, value: str) -> None:
    avl.draw_text(draw, (86, 72), value, size=40, fill=avl.INK, anchor="lm")


def native_frame(image: Image.Image, name: str, frame_index: int) -> None:
    frames = avl._source_frames(name)
    frame = avl._source_frame(str(frames[min(max(0, frame_index), len(frames) - 1)]))
    image.paste(frame, ((WIDTH - frame.width) // 2, (HEIGHT - frame.height) // 2), frame)


DEFINITIONS = (
    "所有叶子都在同一深度",
    "每个节点最多有 m − 1 个关键字，m 个孩子",
    "每个节点至少有 ⌈m/2⌉ − 1 个关键字 ⌈m/2⌉ 个孩子( ⌈  ⌉ 是上取整,⌊  ⌋ 是下取整)",
    "特例:非空 B 树的根节点可以是一个关键字；叶节点没有孩子。",
)


def draw_definition_panel(draw: ImageDraw.ImageDraw) -> None:
    """The fixed upper-half definition shared by the order examples."""
    avl.draw_text(draw, (86, 72), "m 阶 B 树的定义", size=40, fill=avl.INK, anchor="lm")
    first_y = 175.0
    line_height = 41.0
    bullet_color = (245, 185, 65)
    math_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuMathTeXGyre.ttf", 28)
    cjk_font = avl.sans(28)

    def mixed_line(y: float, runs: tuple[tuple[str, ImageFont.FreeTypeFont], ...]) -> None:
        x = 150.0
        for value, font in runs:
            draw.text((round(x), round(y)), value, font=font, fill=avl.INK, anchor="lm")
            x += draw.textlength(value, font=font)

    avl.line(draw, (92, first_y), (124, first_y), bullet_color, 5)
    avl.draw_text(draw, (150, first_y), DEFINITIONS[0], size=28, fill=avl.INK, anchor="lm")

    avl.line(draw, (92, first_y + line_height), (124, first_y + line_height), bullet_color, 5)
    avl.draw_text(draw, (150, first_y + line_height), DEFINITIONS[1], size=28, fill=avl.INK, anchor="lm")

    def math_key(x: float, y: float, *, floor: bool = False, value: str = "m/2") -> float:
        """Draw a math key with hand-built ceiling/floor glyphs."""
        cap_width = 14.0
        top_y = y - 13.0
        bottom_y = y + 13.0
        horizontal_y = bottom_y if floor else top_y
        left_x = x + 2.0
        right_x = x + cap_width
        draw.line((left_x, top_y, left_x, bottom_y), fill=avl.INK, width=2)
        draw.line((left_x, horizontal_y, right_x, horizontal_y), fill=avl.INK, width=2)
        draw.text((x + cap_width + 3, y), value, font=math_font, fill=avl.INK, anchor="lm")
        middle_width = draw.textlength(value, font=math_font)
        draw.line((x + cap_width + middle_width + 7, top_y, x + cap_width + middle_width + 7, bottom_y), fill=avl.INK, width=2)
        draw.line((x + cap_width + middle_width - 5, horizontal_y, x + cap_width + middle_width + 7, horizontal_y), fill=avl.INK, width=2)
        return cap_width + middle_width + 10.0

    def math_empty_caps(x: float, y: float, *, floor: bool = False) -> float:
        """Draw the literal empty ceiling/floor pair in the parenthetical."""
        cap_width = 14.0
        top_y = y - 11.0
        bottom_y = y + 11.0
        horizontal_y = bottom_y if floor else top_y
        draw.line((x + 2, top_y, x + 2, bottom_y), fill=avl.INK, width=2)
        draw.line((x + 2, horizontal_y, x + cap_width, horizontal_y), fill=avl.INK, width=2)
        right_x = x + 38
        draw.line((right_x, top_y, right_x, bottom_y), fill=avl.INK, width=2)
        draw.line((right_x - cap_width + 2, horizontal_y, right_x, horizontal_y), fill=avl.INK, width=2)
        return 43.0

    def cjk(value: str, x: float, y: float) -> float:
        draw.text((round(x), round(y)), value, font=cjk_font, fill=avl.INK, anchor="lm")
        return draw.textlength(value, font=cjk_font)

    third_y = first_y + line_height * 2
    avl.line(draw, (92, third_y), (124, third_y), bullet_color, 5)
    x = 150.0
    x += cjk("每个节点至少有 ", x, third_y)
    x += math_key(x, third_y)
    x += cjk(" − 1 个关键字 ", x, third_y)
    x += math_key(x, third_y)
    cjk(" 个孩子", x, third_y)

    note_y = third_y + 31.0
    x = 150.0
    x += cjk("( ", x, note_y)
    x += math_empty_caps(x, note_y)
    x += cjk(" 是上取整,", x, note_y)
    x += math_empty_caps(x, note_y, floor=True)
    cjk(" 是下取整)", x, note_y)

    fourth_y = third_y + line_height * 2
    avl.line(draw, (92, fourth_y), (124, fourth_y), bullet_color, 5)
    avl.draw_text(draw, (150, fourth_y), DEFINITIONS[3], size=28, fill=avl.INK, anchor="lm")


def draw_definition(image: Image.Image, t: float) -> None:
    lower_source(image, "btree-order-4.svg", t)
    draw_definition_panel(ImageDraw.Draw(image))


def draw_order4(image: Image.Image, t: float) -> None:
    lower_source(image, "btree-order-4.svg", t)
    draw = ImageDraw.Draw(image)
    draw_definition_panel(draw)


def draw_order5(image: Image.Image, t: float) -> None:
    lower_source(image, "btree-order-5.svg", t)
    draw = ImageDraw.Draw(image)
    draw_definition_panel(draw)


def draw_transition(image: Image.Image, t: float) -> None:
    lower_source(image, "btree-order-5.svg", t)
    draw_definition_panel(ImageDraw.Draw(image))


def draw_search(image: Image.Image, t: float) -> None:
    source(image, "btree-search.svg", t)


def draw_insert(image: Image.Image, t: float, duration: float) -> None:
    native_frame(image, "btree-insert-paced.mp4", round(t * 30.0))
    draw = ImageDraw.Draw(image)
    avl.draw_text(draw, (86, 72), "插入", size=40, fill=avl.INK, anchor="lm")


def draw_summary(image: Image.Image, t: float, duration: float) -> None:
    native_frame(image, "btree-insert-paced.mp4", round(t * 30.0))


def draw_general_order(image: Image.Image, t: float) -> None:
    image.paste(general_order.render(t))


def draw_order_scaling(image: Image.Image, t: float) -> None:
    source(image, "btree-order-scaling.svg", t)


def draw_external_io(image: Image.Image, t: float) -> None:
    image.paste(general_order.render_external_io(t))


def draw_page_tree(image: Image.Image, t: float) -> None:
    image.paste(general_order.render_page_tree(t))


def draw_concurrent_writes(image: Image.Image, t: float) -> None:
    image.paste(general_order.render_concurrent_writes(t))


def draw_cost_transition(image: Image.Image, t: float) -> None:
    image.paste(general_order.render_cost_transition(t))


def draw_costs(image: Image.Image, t: float) -> None:
    image.paste(general_order.render_costs(t))


def draw_memory_transition(image: Image.Image, t: float) -> None:
    image.paste(general_order.render_memory_transition(t))


def render_native_insert(shot: int) -> None:
    audio, duration, segments = audio_info(SHOT_AUDIO[shot])
    stem = f"shot{shot:02d}"
    video_only = OUT / "segments" / f"{stem}.mp4"
    final = OUT / f"{stem}.mp4"
    temporary = video_only.with_suffix(".tmp.mp4")
    source_path = ROOT / "assets" / "btree-insert-paced.mp4"
    source_duration = duration
    hold = max(0.0, duration - source_duration)
    filters = f"tpad=stop_mode=clone:stop_duration={hold:.6f},trim=duration={duration:.6f},setpts=PTS-STARTPTS"
    if shot == 7:
        filters += ",drawtext=fontfile=/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc:text=插入:fontcolor=white:fontsize=40:x=86:y=52"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(source_path),
            "-vf", filters,
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "0", "-pix_fmt", "yuv420p",
            "-color_range", "tv", "-r", "30", "-movflags", "+faststart", str(temporary),
        ],
        check=True,
    )
    temporary.replace(video_only)
    mux_audio(video_only, final, audio, duration)
    write_srt(OUT / f"{stem}.srt", segments, duration)
    print(final)


DRAWERS = {
    2: draw_definition,
    3: draw_order4,
    4: draw_order5,
    5: draw_transition,
    6: draw_search,
    9: draw_general_order,
    10: draw_order_scaling,
    11: draw_external_io,
    12: draw_page_tree,
    13: draw_concurrent_writes,
    14: draw_cost_transition,
    15: draw_costs,
    16: draw_memory_transition,
}


def draw_frame(shot: int, t: float, duration: float) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), avl.BLACK)
    if shot in DRAWERS:
        DRAWERS[shot](image, t)
    elif shot == 7:
        draw_insert(image, t, duration)
    elif shot == 8:
        draw_summary(image, t, duration)
    else:
        raise ValueError(shot)
    return image


def corrected_text(value: str) -> str:
    exact = {
        "高度三层的M阶B数,最多能存等比数列求和为M3次方减一个关键字。": "高度三层的 m 阶 B 树，最多能存等比数列求和 m³ − 1 个关键字。",
        "同样三层,4阶B数,最多就63个关键字,100阶就100万个,512阶就1.34亿个。": "同样三层，4 阶 B 树最多 63 个关键字，100 阶约 100 万个，512 阶约 1.34 亿个。",
        "这正是B数被发明出来的场景": "这正是 B 树被发明出来的场景。",
        "磁盘一次循指读写一整页": "磁盘一次寻址读写一整页。",
        "把一整页做成一个大节点": "把一整页做成一个大节点。",
        "数的层次就约等于循指次数": "树的层数就约等于寻址次数。",
        "几百阶的B数只要三四层就能覆盖上一条的数据": "几百阶的 B 树只要三四层就能覆盖上亿条数据。",
        "读取一样多的数据读取次数越少越好。": "读取一样多的数据，读取次数越少越好。",
        "还有一点就是B数的并发写入改造比较简单。": "还有一点，B 树的并发写入改造比较简单。",
        "那么狗儿蛋代价是什么呢": "那么，B 树的代价是什么呢？",
        "B数的代价首先是空间利用率": "B 树的代价首先是空间利用率。",
        "B数每个节点内部都是一个数组": "B 树每个节点内部都是一个数组。",
        "这B数确实不错,可对于内存几乎没有业代价": "这 B 树确实不错。可对于内存几乎没有页代价，",
        "每个节点最少有m上一曲整-1个关键字m个孩子。": "每个节点至少有 ⌈m/2⌉ − 1 个关键字，⌈m/2⌉ 个孩子。",
        "考虑到既有问题最终可以是m2上曲整-1。": "考虑到奇偶问题，最终可以是 ⌈m/2⌉ − 1。",
        "最低加引号的容量。": "“最低”容量。",
    }
    value = exact.get(value, value)
    replacements = {
        "二查搜索数": "二叉搜索树",
        "二刹搜索数": "二叉搜索树",
        "b 数": "B 树",
        "B数": "B 树",
        "B数": "B 树",
        "上一出": "上溢",
        "下一出": "下溢",
        "负节点": "父节点",
        "一阶点": "内部节点",
        "A节点": "叶节点",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return value.replace(",", "，").replace("?", "？")


def write_srt(path: Path, segments: list[dict], duration: float) -> None:
    manuscript = {
        9: [
            (0.18, 8.02, "从 4 阶推广到任意阶，阶数决定容量，不改变机制。"),
            (8.38, 13.14, "每个节点最多有 m − 1 个关键字 m 个孩子"),
            (13.60, 19.96, "每个节点至少有 ⌈m/2⌉ − 1 个关键字 ⌈m/2⌉ 个孩子"),
            (21.00, 30.96, "最多 m-1 关键字。再插入一个变成 m 个但是上溢出还要推举出一个,又变成m-1个"),
            (31.20, 41.06, "分裂时是对 m -1 关键字平分为两半。考虑到奇偶问题。最终可以是 ⌈m/2⌉ − 1"),
            (43.00, duration, '上溢出之后，分裂完，两个孩子刚好就是"最低"的容量。'),
        ],
        12: [
            (0.02, 3.08, "这正是 B 树被发明出来的场景"),
            (3.08, duration, "磁盘一次寻址读写一整页，把一整页做成一个大节点，树的层数就约等于寻址次数。几百阶的 B 树只要三四层就能覆盖上亿条数据."),
        ],
        13: [(0.88, duration, "还有一点就是 B 树的并发写入改造比较简单")],
        16: [
            (0.78, 5.74, "这B树确实不错。"),
            (5.74, 10.98, "可对于内存几乎没有页代价,有没有性能更强空间还不浪费的数据结构呢？"),
            (11.50, duration, "有的"),
        ],
    }.get(int(path.stem.removeprefix("shot")))
    if manuscript is not None:
        entries = [
            f"{index}\n{stamp(start)} --> {stamp(min(end, duration))}\n{text}\n"
            for index, (start, end, text) in enumerate(manuscript, start=1)
        ]
        path.write_text("\n".join(entries), encoding="utf-8")
        return

    entries = []
    for index, segment in enumerate(segments, start=1):
        end = min(duration, segment["end"] + (0.6 if index == len(segments) else 0.0))
        entries.append(f"{index}\n{stamp(segment['start'])} --> {stamp(end)}\n{corrected_text(segment['text'].strip())}\n")
    path.write_text("\n".join(entries), encoding="utf-8")


def stamp(seconds: float) -> str:
    millis = round(seconds * 1000.0)
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{milliseconds:03d}"


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
            process.stdin.write(draw_frame(shot, min(index / FPS, duration - 1e-5), duration).tobytes())
            if index % 300 == 0:
                print(f"shot {shot} frame {index}/{frame_count}", flush=True)
    finally:
        process.stdin.close()
    if process.wait() != 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"shot {shot} encode failed")
    temporary.replace(path)


def mux_audio(video: Path, output: Path, audio: Path, duration: float) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0", "-t", f"{duration:.6f}", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart", str(output),
        ],
        check=True,
    )


def render(shot: int) -> None:
    if shot == 7:
        render_native_insert(shot)
        return
    audio, duration, segments = audio_info(SHOT_AUDIO[shot])
    stem = f"shot{shot:02d}"
    video_only = OUT / "segments" / f"{stem}.mp4"
    final = OUT / f"{stem}.mp4"
    encode_video(shot, video_only, duration)
    mux_audio(video_only, final, audio, duration)
    write_srt(OUT / f"{stem}.srt", segments, duration)
    print(final)


def preview(shot: int, values: str) -> None:
    audio, duration, _ = audio_info(SHOT_AUDIO[shot])
    target = OUT / "preview" / f"shot{shot:02d}"
    target.mkdir(parents=True, exist_ok=True)
    for value in values.split(","):
        when = float(value)
        draw_frame(shot, min(when, duration - 1e-5), duration).save(target / f"t{when:07.2f}.png")
    print(target)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shot", type=int, choices=sorted(SHOT_AUDIO))
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--at", default="1.0,6.0,12.0,20.0,30.0")
    args = parser.parse_args()
    shots = sorted(SHOT_AUDIO) if args.all else [args.shot] if args.shot else []
    if not shots:
        parser.error("choose --shot N or --all")
    for shot in shots:
        if args.preview:
            preview(shot, args.at)
        else:
            render(shot)


if __name__ == "__main__":
    main()
