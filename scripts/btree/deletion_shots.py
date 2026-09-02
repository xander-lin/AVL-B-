#!/usr/bin/env python3
"""Render the newly narrated B-tree deletion chapter one shot at a time."""
from __future__ import annotations

import argparse
import math
import subprocess
import tempfile
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "btree-delete-video"
WIDTH, HEIGHT, FPS = 1920, 1080, 60
BLACK = (0, 0, 0)
WHITE = (248, 250, 252)
BLUE = (163, 188, 247)
RIM = (143, 169, 232)
FILL = (59, 91, 165)
SHADOW = (23, 31, 51)
FONT = "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"

NEW_AUDIO = {
    3: ROOT / "audio" / "B" / "recording-1788335172651946084-3-edited.wav",
    9: ROOT / "audio" / "B" / "recording-1788335274827411256-9-edited.wav",
    11: ROOT / "audio" / "B" / "recording-1788335331997254332-11-edited.wav",
    13: ROOT / "audio" / "B" / "recording-1788335424310472654-13-edited.wav",
    21: ROOT / "audio" / "B" / "recording-1788336004392441880-21-edited.wav",
    23: ROOT / "audio" / "B" / "recording-1788336802902854848-23-edited.wav",
    27: ROOT / "audio" / "B" / "recording-1788336869306084109-27-edited.wav",
    29: ROOT / "audio" / "B" / "recording-1788336991829665601-29-edited.wav",
    31: ROOT / "audio" / "B" / "recording-1788337091494732199-31-edited.wav",
    33: ROOT / "audio" / "B" / "recording-1788337131548000387-33-edited.wav",
    37: ROOT / "audio" / "B" / "recording-1788337274266833294-37-edited.wav",
    41: ROOT / "audio" / "B" / "recording-1788337344232592979-41-edited.wav",
    49: ROOT / "audio" / "B" / "recording-1788337508612162808-49-edited.wav",
}


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def audio(index: int) -> Path:
    return NEW_AUDIO[index]


def duration(index: int) -> float:
    return wav_duration(audio(index))


SHOTS = {
    1: {
        "audio": audio(3),
        "duration": duration(3),
        "stem": "shot01-method-overview",
        "kind": "draw",
        "subtitles": (
            (0.00, 2.64, "第一种就是传统的方法"),
            (2.64, 7.20, "传统方法先看删除叶节点元素后是否下溢"),
            (7.20, 9.62, "没有下溢，无需调整"),
            (9.62, 14.48, "发生下溢时，再分为兄弟够借和兄弟不够借两种情况"),
            (15.14, 18.14, "还有一种就是统一的语义"),
            (18.14, 20.83433106575964, "首领回家的版本"),
        ),
    },
    2: {
        "audio": audio(9),
        "duration": duration(9),
        "stem": "shot02-solution-set",
        "kind": "draw",
        "subtitles": (
            (0.00, 4.14, "在正式讲解之前，我要先告诉你一句话。"),
            (4.14, 11.44, "首领回家得到的是一个解的集合，而传统方法则是集合中的最优解。"),
            (11.44, 18.68, "我必须讲这个解集，因为它对将来的红黑树至关重要。"),
            (18.68, 21.86875283446712, "所以也请你耐心听完我们的首领回家的办法。"),
        ),
    },
    3: {
        "audio": audio(11),
        "duration": duration(11),
        "stem": "shot03-case1-no-underflow",
        "kind": "assets",
        "assets": (
            (ROOT / "assets" / "btree-case1-traditional.webm", 0.62, 0.0),
            (ROOT / "assets" / "btree-case1-ours.webm", 21.08, 0.0),
        ),
        "subtitles": (
            (0.62, 19.54, "接下来这些例子都基于四阶 B 树。情况一，传统方法中删除后不下溢。这里我们删除 10。对于传统方法，这个节点删除 10 并不会下溢，直接删除就行。"),
            (21.08, 33.74873015873016, "对于我们的方法，把 40 拉下来，把 10 删掉，再把一个首领重新推举上去，有这些个情况。"),
        ),
    },
    4: {
        "audio": audio(13),
        "duration": duration(13),
        "stem": "shot04-case2-borrow",
        "kind": "assets",
        "assets": (
            (ROOT / "assets" / "btree-case2-traditional.webm", 0.53, 0.0),
            (ROOT / "assets" / "btree-case2-ours.webm", 19.83, 0.0),
        ),
        "subtitles": (
            (0.53, 9.61, "情况二，传统方法中发生下溢，兄弟够借，向兄弟借关键字并发生旋转。"),
            (10.15, 19.83, "还是删除 10。传统方法属于下溢出，需要问兄弟借，兄弟够借，发生了旋转。"),
            (19.83, 30.95, "对于我们的方法，操作不变。把首领拉回家，把 10 删掉；在合法解集合中，可以重新推举，也可以不重新推举。"),
            (31.95, duration(13), "传统方法保持了层数不变，即便是一棵更大的树，也不会对上层造成影响，并且调整元素数量最少。"),
        ),
    },
    5: {
        "audio": audio(21),
        "duration": duration(21),
        "stem": "shot05-case2-cost",
        "kind": "assets",
        "assets": ((ROOT / "assets" / "btree-case2-ours.webm", 0.0, 0.0),),
        "subtitles": (
            (0.66, duration(21), "而我们的方法中，如果采用不重新推举，如果这是一棵更大的树，不重新推举，那父节点少了一个元素，可能会导致父节点下溢，调整范围更大。"),
        ),
    },
    6: {
        "audio": audio(23),
        "duration": duration(23),
        "stem": "shot06-case3-traditional-intro",
        "kind": "assets",
        "assets": ((ROOT / "assets" / "btree-case3-traditional.webm", 0.72, 0.0),),
        "subtitles": (
            (0.72, 8.10, "情况三，传统方法中发生下溢，兄弟不够借，只能合并。"),
            (8.34, duration(23), "这种情况合并之后父节点那一层就少了一个元素，所以父节点可能会继续下溢。"),
        ),
    },
    7: {
        "audio": audio(27),
        "duration": duration(27),
        "stem": "shot07-case3-traditional-merge",
        "kind": "assets",
        "assets": ((ROOT / "assets" / "btree-case3-traditional.webm", 0.0, 0.0),),
        "subtitles": (
            (1.23, 9.31, "传统方法：删除 70 之后发生下溢，兄弟不够借，就和父节点的关键字合并。"),
            (9.81, 18.47, "父节点因此少了一个元素，下溢还是不够借，所以父节点继续合并。"),
            (18.81, 27.65, "可以选择 50 或者 80 进行合并，这里我们选择 50。合并后，这次父节点 80 没有下溢。"),
            (28.99, 36.47, "四阶 B 树中，节点有 0 个关键字时，也仍然称为下溢，不说节点没了。"),
            (39.12, duration(27), "然后删除 10，合并 20 与 30。"),
        ),
    },
    8: {
        "audio": audio(29),
        "duration": duration(29),
        "stem": "shot08-case3-leader-home",
        "kind": "assets",
        "assets": ((ROOT / "assets" / "btree-case3-ours.webm", 0.72, 0.0),),
        "subtitles": (
            (0.72, 10.26, "对于我们的方法，这里要删除 70。首领 60 回家之后，把 70 删掉，就剩两个节点了。"),
            (11.00, 23.08, "这个结果无法重新推举，父节点下溢。在合法解集中，对于下溢的父节点，它有两个首领，选择 80 回家还是 50 回家都行。"),
            (24.16, 38.40, "50 回家之后，可以选择推举或者不推举。当然，前提是有的推举才能推举。关键字数量不够，就不能推举。这里就不能推举。"),
            (39.08, 45.82, "接下来我们删除 10，首领 20 回家，10 被删除。还是没有什么可推举的。"),
            (46.48, duration(29), "但这次父节点并不下溢，然后这就结束了。"),
        ),
    },
    9: {
        "audio": audio(31),
        "duration": duration(31),
        "stem": "shot09-promotion-parity",
        "kind": "image",
        "image": ROOT / "assets" / "btree-promotion-parity.svg",
        "subtitles": (
            (0.50, 9.00, "我们很容易发现，对于阶数为奇数的 B 树，只有大于最大容量时能够推举。"),
            (9.22, duration(31), "对于阶数为偶数的 B 树，大于等于最大容量时能够推举。"),
        ),
    },
    10: {
        "audio": audio(33),
        "duration": duration(33),
        "stem": "shot10-order5-intro",
        "kind": "assets",
        "assets": ((ROOT / "assets" / "btree-delete-5-slow.webm", 0.0, 0.0),),
        "subtitles": ((0.0, duration(33), "接下来看一个完整的例子，这次我们用的是 5 阶 B 树。"),),
    },
    11: {
        "audio": audio(37),
        "duration": duration(37),
        "stem": "shot11-order5-delete450",
        "kind": "assets",
        "assets": ((ROOT / "assets" / "btree-delete-5-slow.webm", 0.0, 0.0),),
        "subtitles": (
            (0.0, 10.16, "删除 450，它不是叶节点，先用后继 460 替换它，然后删除叶节点中的 450。"),
            (11.72, 19.18, "节点下溢，右兄弟只有两个关键字不够借，所以和分隔关键字 500 以及右兄弟合并。"),
            (19.96, duration(37), "父节点没有下溢。"),
        ),
    },
    12: {
        "audio": audio(41),
        "duration": duration(41),
        "stem": "shot12-order5-delete410",
        "kind": "assets",
        "assets": ((ROOT / "assets" / "btree-delete-5-slow.webm", 0.0, 20.0),),
        "subtitles": (
            (0.08, 5.52, "删除 410，删除 410 后节点下溢。"),
            (5.52, 16.56, "右兄弟够借，分隔关键字 460 下移到左节点，右兄弟最小关键字 480 上移到父节点。"),
            (16.56, duration(41), "完成一次旋转。"),
        ),
    },
    13: {
        "audio": audio(49),
        "duration": duration(49),
        "stem": "shot13-order5-delete360",
        "kind": "assets",
        "assets": ((ROOT / "assets" / "btree-delete-5-slow.webm", 0.0, 38.0),),
        "subtitles": (
            (0.40, 10.64, "删除 360，删除 360 后节点下溢，右兄弟不够借，和分隔关键字 380 合并。"),
            (10.90, 20.34, "父节点因此下溢，继续检查同层兄弟，兄弟仍不够借，就再和分隔关键字 300 合并。"),
            (20.56, 26.98, "上层节点也发生下溢，最后和根关键字 400 以及右兄弟合并。"),
            (26.98, duration(49), "树从 4 层缩成 3 层。"),
        ),
    },
}


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size)


def text(draw: ImageDraw.ImageDraw, value: str, xy: tuple[float, float], size: int, *, anchor: str = "mm") -> None:
    draw.text(xy, value, font=font(size), fill=WHITE, anchor=anchor)


def line(draw: ImageDraw.ImageDraw, start: tuple[float, float], end: tuple[float, float], *, width: int = 6) -> None:
    draw.line((*start, *end), fill=RIM, width=width)
    draw.line((*start, *end), fill=WHITE, width=max(2, width // 3))


def arrow(draw: ImageDraw.ImageDraw, start: tuple[float, float], end: tuple[float, float]) -> None:
    line(draw, start, end)
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    tip = end
    left = (end[0] - ux * 21 + px * 13, end[1] - uy * 21 + py * 13)
    right = (end[0] - ux * 21 - px * 13, end[1] - uy * 21 - py * 13)
    draw.polygon((tip, left, right), fill=WHITE)


def box(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], value: str, *, active: bool = False) -> None:
    left, top, right, bottom = xy
    border = WHITE if active else RIM
    draw.rounded_rectangle((left - 10, top - 10, right + 10, bottom + 10), radius=18, fill=SHADOW)
    draw.rounded_rectangle(xy, radius=10, fill=FILL, outline=border, width=4)
    text(draw, value, ((left + right) / 2, (top + bottom) / 2), 34)


def draw_traditional(draw: ImageDraw.ImageDraw, t: float) -> None:
    text(draw, "传统方法", (960, 140), 52)
    box(draw, (690, 250, 1230, 350), "删除叶节点元素", active=t < 15.14)
    arrow(draw, (960, 360), (960, 430))
    box(draw, (720, 450, 1200, 550), "是否下溢？", active=True)

    arrow(draw, (830, 560), (520, 650))
    arrow(draw, (1090, 560), (1400, 650))
    box(draw, (270, 670, 770, 770), "没有下溢：无需调整", active=7.20 <= t < 9.62)
    box(draw, (1150, 670, 1650, 770), "发生下溢", active=t >= 9.62)

    if t >= 9.62:
        arrow(draw, (1275, 780), (1120, 865))
        arrow(draw, (1525, 780), (1680, 865))
        box(draw, (865, 885, 1375, 985), "兄弟够借：借并旋转", active=True)
        box(draw, (1430, 885, 1870, 985), "兄弟不够借：合并", active=True)


def draw_home(draw: ImageDraw.ImageDraw) -> None:
    text(draw, "首领回家的统一语义", (960, 230), 52)
    labels = ("首领回家", "部落内删除", "重新推举首领")
    centers = (430, 960, 1490)
    for index, (label, center) in enumerate(zip(labels, centers)):
        box(draw, (center - 190, 440, center + 190, 560), label, active=True)
        if index:
            arrow(draw, (centers[index - 1] + 205, 500), (center - 205, 500))


def draw_solution_set(draw: ImageDraw.ImageDraw, t: float) -> None:
    if t < 4.14:
        text(draw, "传统方法与首领回家", (960, 500), 58)
        return

    text(draw, "首领回家：合法解的集合", (960, 185), 52)
    draw.rounded_rectangle((230, 270, 1690, 875), radius=38, outline=RIM, width=5)
    text(draw, "所有满足 B 树定义的调整结果", (960, 325), 34)

    box(draw, (335, 455, 805, 585), "重新推举首领", active=True)
    box(draw, (1115, 455, 1585, 585), "不重新推举", active=True)
    box(draw, (725, 665, 1195, 795), "传统方法", active=True)
    line(draw, (570, 595), (855, 665))
    line(draw, (1350, 595), (1065, 665))

    if t >= 11.44:
        text(draw, "传统方法：调整元素更少，并尽量保持树高", (960, 960), 36)


def frame(shot: int, t: float) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BLACK)
    draw = ImageDraw.Draw(image)
    if shot != 1:
        if shot != 2:
            raise ValueError(shot)
        draw_solution_set(draw, t)
    elif t < 15.14:
        draw_traditional(draw, t)
    else:
        draw_home(draw)
    return image


def stamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{millis:03d}"


def write_srt(shot: int) -> Path:
    data = SHOTS[shot]
    path = OUT / f"{data['stem']}.srt"
    entries = [
        f"{index}\n{stamp(start)} --> {stamp(end)}\n{text_value}\n"
        for index, (start, end, text_value) in enumerate(data["subtitles"], start=1)
    ]
    path.write_text("\n".join(entries), encoding="utf-8")
    return path


def encode(shot: int) -> Path:
    data = SHOTS[shot]
    OUT.mkdir(parents=True, exist_ok=True)
    duration = data["duration"]
    video_only = OUT / "segments" / f"{data['stem']}.mp4"
    video_only.parent.mkdir(parents=True, exist_ok=True)
    if shot == 3:
        encode_case1_video(video_only, duration)
        return mux_and_write(shot, video_only)
    if data["kind"] == "assets":
        encode_asset_video(video_only, duration, data["assets"])
        return mux_and_write(shot, video_only)
    if data["kind"] == "image":
        encode_image_video(video_only, duration, data["image"])
        return mux_and_write(shot, video_only)
    temporary = video_only.with_suffix(".tmp.mp4")
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
        for index in range(math.ceil(duration * FPS)):
            process.stdin.write(frame(shot, min(index / FPS, duration - 1e-5)).tobytes())
            if index % 300 == 0:
                print(f"deletion shot {shot} frame {index}", flush=True)
    finally:
        process.stdin.close()
    if process.wait() != 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"deletion shot {shot} video encoding failed")
    temporary.replace(video_only)

    return mux_and_write(shot, video_only)


def encode_case1_video(video_only: Path, duration: float) -> None:
    """Keep the approved traditional and leader-home animations in sequence."""
    temporary = video_only.with_suffix(".tmp.mp4")
    traditional = ROOT / "assets" / "btree-case1-traditional.webm"
    leader_home = ROOT / "assets" / "btree-case1-ours.webm"
    source_filter = (
        "fps=60,scale=1600:1000:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black"
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=black:s={WIDTH}x{HEIGHT}:r={FPS}:d={duration:.6f}",
            "-i", str(traditional), "-i", str(leader_home),
            "-filter_complex",
            (
                f"[1:v]{source_filter},tpad=stop_mode=clone:stop_duration=13.0,"
                "setpts=PTS-STARTPTS+1.50/TB[traditional];"
                f"[2:v]{source_filter},tpad=stop_mode=clone:stop_duration=3.3,"
                "setpts=PTS-STARTPTS+21.08/TB[home];"
                "[0:v][traditional]overlay=shortest=0:eof_action=pass[base];"
                "[base][home]overlay=shortest=0:eof_action=pass,trim=duration="
                f"{duration:.6f},setpts=PTS-STARTPTS[v]"
            ),
            "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart", str(temporary),
        ],
        check=True,
    )
    temporary.replace(video_only)


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def visual_filter() -> str:
    return "fps=60,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black"


def encode_asset_video(
    video_only: Path,
    duration: float,
    assets: tuple[tuple[Path, float, float], ...],
) -> None:
    """Flatten source animations onto black and place them on the narration timeline."""
    temporary = video_only.with_suffix(".tmp.mp4")
    input_args = ["-f", "lavfi", "-i", f"color=c=black:s={WIDTH}x{HEIGHT}:r={FPS}:d={duration:.6f}"]
    for source, _, _ in assets:
        input_args.extend(["-i", str(source)])

    filters: list[str] = []
    labels: list[str] = []
    for index, (source, output_start, source_start) in enumerate(assets, start=1):
        source_duration = probe_duration(source)
        playable = max(0.0, source_duration - source_start)
        hold = max(0.0, duration - output_start - playable)
        label = f"asset{index}"
        filters.append(
            f"[{index}:v]trim=start={source_start:.6f},setpts=PTS-STARTPTS,{visual_filter()},"
            f"tpad=stop_mode=clone:stop_duration={hold:.6f},setpts=PTS-STARTPTS+{output_start:.6f}/TB[{label}]"
        )
        labels.append(label)

    base = "0:v"
    for index, label in enumerate(labels):
        output = f"base{index}"
        filters.append(f"[{base}][{label}]overlay=eof_action=pass:shortest=0[{output}]")
        base = output
    filters.append(f"[{base}]trim=duration={duration:.6f},setpts=PTS-STARTPTS[v]")
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", *input_args,
            "-filter_complex", ";".join(filters), "-map", "[v]", "-an",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-r", str(FPS), "-movflags", "+faststart", str(temporary),
        ],
        check=True,
    )
    temporary.replace(video_only)


def encode_image_video(video_only: Path, duration: float, source: Path) -> None:
    """Render an SVG still to RGB frames before encoding the final MP4."""
    temporary = video_only.with_suffix(".tmp.mp4")
    with tempfile.TemporaryDirectory(prefix="btree-delete-svg-") as directory:
        png = Path(directory) / "source.png"
        subprocess.run(["rsvg-convert", "-w", str(WIDTH), "-h", str(HEIGHT), str(source), "-o", str(png)], check=True)
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png),
                "-t", f"{duration:.6f}", "-vf", f"{visual_filter()},format=rgb24",
                "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                "-r", str(FPS), "-movflags", "+faststart", str(temporary),
            ],
            check=True,
        )
    temporary.replace(video_only)


def mux_and_write(shot: int, video_only: Path) -> Path:
    data = SHOTS[shot]
    duration = data["duration"]
    final = OUT / f"{data['stem']}.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(video_only), "-i", str(data["audio"]),
            "-map", "0:v:0", "-map", "1:a:0", "-t", f"{duration:.6f}", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart", str(final),
        ],
        check=True,
    )
    write_srt(shot)
    return final


def preview(shot: int, values: str) -> Path:
    target = OUT / "preview" / SHOTS[shot]["stem"]
    target.mkdir(parents=True, exist_ok=True)
    for value in values.split(","):
        t = float(value)
        frame(shot, t).save(target / f"t{t:06.2f}.png")
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shot", type=int, choices=sorted(SHOTS), default=1)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--at", default="1,4,8,12,16,19")
    args = parser.parse_args()
    if args.preview:
        print(preview(args.shot, args.at))
    else:
        print(encode(args.shot))


if __name__ == "__main__":
    main()
