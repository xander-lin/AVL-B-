"""Render the supplied insertion recordings as an ASR-timed review MP4.

This is intentionally a review artifact, not the final AVL film. It uses only
the relevant recordings from audio/avl/new, preserves them whole, and makes
the manuscript text states visible at their spoken ASR boundaries.
"""
from __future__ import annotations

import math
import subprocess
import tempfile
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
AUDIO_DIR = ROOT / "audio" / "avl" / "new"
OUTPUT = ROOT / "outputs" / "avl-video" / "avl-insert-prelude-review.mp4"
SANS_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
MONO_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
WIDTH, HEIGHT, FPS = 1920, 1080, 24
INK = (248, 250, 252)
BLACK = (0, 0, 0)

FILES = (
    "recording-1787801537741822794-75-edited.wav",
    "recording-1787801641300247333-77-edited.wav",
    "recording-1787801757426225360-81-edited.wav",
    "recording-1787802108333678195-83-edited.wav",
    "recording-1787802502728832188-89-edited.wav",
    "recording-1787803224392662820-105-edited.wav",
    "recording-1787821421347699422-111-edited.wav",
)

# These are ASR onset times measured from the selected source recordings.
# They remain source-local so the final-film timeline can be rebuilt later.
REVEALS = (
    (0, 0.11, "height-1"),
    (0, 9.19, "height-2"),
    (0, 16.71, "height-3"),
    (0, 20.19, "height-4"),
    (0, 25.67, "height-5"),
    (0, 32.19, "height-6"),
    (0, 41.47, "height-7"),
    (0, 46.47, "height-8"),
    (1, 0.05, "height-9"),
    (1, 9.11, "height-10"),
    (2, 0.30, "height-11"),
    (3, 0.46, "question"),
    (4, 0.40, "reason-single"),
    (5, 0.21, "rule"),
    (6, 0.87, "examples"),
)

HEIGHT_BLOCKS = (
    "第一次旋转后是改变了重心,重心变了,左撇子变右撇子了,树高可没变",
    "插入前是假设最大的两颗左右子树是 n 与 n+1 ,那么树高是 n +2",
    "插入时临时变成n 与 n + 2",
    "第一次旋转后,或者说第一种旋转后,还是n 与 n + 2",
    "第二次旋转后,或者说第二种旋转后, 一边增加1 一边减少 1,插入完成后最终,n变成 n+1 ,n+2变成 n + 1,树高还是 n + 2",
    "中间失衡的调整不会引起树高变化",
    "两边失衡只牵涉第二种旋转,同理也不会引起树高变化",
    "那么\n无论是两边失衡,还是中间失衡\n插入前树高是多少 插入后树高是就是多少",
    "那么\n能使avl树树高增长的插入一定是无调整的,\n也就是 凡牵涉调整的插入都不会引起树高变化",
    "但是无调整的插入可不一定使树高增长,比如 单单2左子树是 1 ,插入3",
)
QUESTION = (
    "接下来让我们看一次从零开始的完整插入。每插入一个数，那么首先肯定是按二叉搜索树的规则给它找到落点，"
    "然后从落点沿着来路向上检查，发现失衡就修复，修复完继续向上，一直到第一次不失衡,\n"
    "啊,等等,为什么是修复到第一次不失衡就行，而不是一直判断到根呢？为什么不是一直到根呢?",
)
REASON = (
    "还是说,并不是?",
    "我们再来读一读这句话:修复完继续向上，一直到第一次不失衡,"
    "修复完继续向上，一直到第一次不失衡,修复完继续向上，一直到第一次不失衡",
    "啊,为什么是修复完啊,啊对是修复完,那说明调整操作发生了,可是刚刚我们说凡牵涉调整的插入都不会引起树高变化,"
    "那调整的这棵树树高没变化，它是在内部进行了修复,对外界来说是不可感的,那外界就不需要进行调整。"
    "因为对外界来说，它就相当于没变,所其实需要且只需要调整一次!!!",
)
RULE = "也就是说，首先按照二叉搜索树规则找到落点。之后看一下插入的这棵树有没有失衡,如果失衡了，调整一次就行。"
EXAMPLES = "好吧,那么现在来看从零开始的完整插入:"


def duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def font(size: int, family: str = "sans") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(MONO_FONT if family == "mono" else SANS_FONT, size)


def wrap(value: str, size: int, width: float) -> list[str]:
    active_font = font(size)
    result: list[str] = []
    for source in value.split("\n"):
        line = ""
        for char in source:
            candidate = line + char
            if line and active_font.getlength(candidate) > width:
                result.append(line)
                line = char
            else:
                line = candidate
        if line:
            result.append(line)
    return result


def draw_blocks(draw: ImageDraw.ImageDraw, blocks: tuple[str, ...], shown: int) -> None:
    layouts = [wrap(block, 39, 1450.0) for block in blocks]
    line_height, block_gap = 58.0, 32.0
    total_height = sum(len(lines) * line_height for lines in layouts) + block_gap * (len(layouts) - 1)
    y = (HEIGHT - total_height) / 2.0 + line_height / 2.0
    active_font = font(39)
    for index, lines in enumerate(layouts):
        if index < shown:
            for line in lines:
                draw.text((WIDTH / 2.0, y), line, font=active_font, fill=INK, anchor="mm")
                y += line_height
        else:
            y += len(lines) * line_height
        if index + 1 < len(layouts):
            y += block_gap


def active_state(t: float, offsets: list[float]) -> str | None:
    state = None
    for file_index, local_start, candidate in REVEALS:
        if t >= offsets[file_index] + local_start:
            state = candidate
        else:
            break
    return state


def frame(t: float, offsets: list[float]) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BLACK)
    draw = ImageDraw.Draw(image)
    state = active_state(t, offsets)
    if state is None:
        return image
    if state.startswith("height-"):
        draw_blocks(draw, HEIGHT_BLOCKS, int(state.rsplit("-", 1)[1]))
    elif state == "question":
        draw_blocks(draw, QUESTION, 1)
    elif state == "reason-single":
        draw_blocks(draw, REASON, 1)
    elif state == "reason-read":
        draw_blocks(draw, REASON, 2)
    elif state == "reason-2":
        draw_blocks(draw, REASON, 2)
    elif state == "rule":
        draw_blocks(draw, (RULE,), 1)
    elif state == "examples":
        draw_blocks(draw, (EXAMPLES,), 1)
    return image


def build() -> None:
    sources = [AUDIO_DIR / name for name in FILES]
    assert all(path.exists() for path in sources), sources
    durations = [duration(path) for path in sources]
    offsets = [0.0]
    for item_duration in durations[:-1]:
        offsets.append(offsets[-1] + item_duration)
    total = sum(durations)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="avl-insertion-prelude-", dir="/tmp/opencode") as temporary:
        root = Path(temporary)
        concat_list = root / "audio.txt"
        narration = root / "narration.wav"
        video = root / "video.mp4"
        concat_list.write_text("".join(f"file '{path}'\n" for path in sources), encoding="utf-8")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(narration)],
            check=True,
        )
        encoder = subprocess.Popen(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s:v", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "pipe:0", "-an",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(video),
            ],
            stdin=subprocess.PIPE,
        )
        assert encoder.stdin is not None
        try:
            for index in range(math.ceil(total * FPS)):
                encoder.stdin.write(frame(min(index / FPS, total), offsets).tobytes())
        finally:
            encoder.stdin.close()
        assert encoder.wait() == 0
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(narration),
                "-map", "0:v:0", "-map", "1:a:0", "-t", f"{total:.6f}", "-c:v", "copy", "-c:a", "aac",
                "-b:a", "192k", "-ac", "2", "-movflags", "+faststart", str(OUTPUT),
            ],
            check=True,
        )
    print(f"{OUTPUT} ({total:.3f}s)")


if __name__ == "__main__":
    build()
