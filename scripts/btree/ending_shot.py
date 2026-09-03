#!/usr/bin/env python3
"""Render the static course-ending shot: repository intro, images, MIT license."""
from __future__ import annotations

import subprocess
import tempfile
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "btree-video"
WIDTH, HEIGHT, FPS = 1920, 1080, 60
DURATION = 12.0
FONT_DIR = "/usr/share/fonts/noto-cjk"

IMAGES = (
    (ROOT / "assets/repo-intro-1.png", ROOT / "assets/repo-intro-2.png"),
)
WHITE = (255, 255, 255)
SOFT = (200, 206, 216)
BORDER = (70, 76, 88)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "NotoSansCJK-Bold.ttc" if bold else "NotoSansCJK-Regular.ttc"
    return ImageFont.truetype(f"{FONT_DIR}/{name}", size)


def compose() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    center = WIDTH / 2

    draw.text(
        (center, 78),
        "这套数据结构课程的文稿、动画，以及每一帧动画的制作脚本，都放在一个开源仓库里",
        font=font(36),
        fill=WHITE,
        anchor="mm",
    )
    draw.text(
        (center, 150),
        "github.com/xander-lin/AVL-B-",
        font=font(46, bold=True),
        fill=WHITE,
        anchor="mm",
    )

    frame_w, frame_h, gap, top = 840, 472, 60, 210
    total_w = frame_w * 2 + gap
    left = round((WIDTH - total_w) / 2)
    for index, path in enumerate(IMAGES[0]):
        shot = Image.open(path).convert("RGB").resize((frame_w, frame_h), Image.Resampling.LANCZOS)
        x = left + index * (frame_w + gap)
        image.paste(shot, (x, top))
        draw.rectangle([x - 1, top - 1, x + frame_w, top + frame_h], outline=BORDER, width=1)

    y = top + frame_h + 58
    draw.text(
        (center, y),
        "这两张图就是仓库里课程文档的样子：文稿和动画放在一起，",
        font=font(31),
        fill=SOFT,
        anchor="mm",
    )
    draw.text(
        (center, y + 46),
        "每一段讲解都配有对应的演示，每一个动画都可以用仓库里的脚本重新生成。",
        font=font(31),
        fill=SOFT,
        anchor="mm",
    )

    y += 46 + 62
    draw.text(
        (center, y),
        "如果你有更好的录音条件、动画制作技巧，或者对节奏有自己的把控，",
        font=font(31),
        fill=SOFT,
        anchor="mm",
    )
    draw.text(
        (center, y + 46),
        "欢迎基于这个仓库重新制作，把知识更快、更好、更优雅地传递给更多的人。",
        font=font(31),
        fill=SOFT,
        anchor="mm",
    )

    draw.text(
        (center, y + 46 + 66),
        "本项目采用 MIT 开源许可协议，可以自由地使用、修改和分享。",
        font=font(34, bold=True),
        fill=WHITE,
        anchor="mm",
    )
    return image


def silent_track(path: Path) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        frames = int(44100 * DURATION)
        handle.writeframes(b"\x00\x00\x00\x00" * frames)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "ending.mp4"
    with tempfile.TemporaryDirectory(prefix="btree-ending-") as temporary:
        root = Path(temporary)
        frame = compose()
        png = root / "ending.png"
        frame.save(png)
        silent = root / "silence.wav"
        silent_track(silent)
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-loop", "1", "-i", str(png),
                "-i", str(silent),
                "-map", "0:v:0", "-map", "1:a:0",
                "-t", f"{DURATION:.6f}",
                "-vf", "format=yuv420p",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", str(FPS),
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", str(target),
            ],
            check=True,
        )
    (OUT / "ending.srt").write_text("", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
