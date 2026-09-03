#!/usr/bin/env python3
"""Render B-tree deletion shots from the manuscript's original media only."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
import wave
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "btree-delete-video"
WIDTH, HEIGHT, FPS = 1920, 1080, 60
BOX_W, BOX_H = 1536, 756
VP9_ALPHA_DECODER = "libvpx-vp9"

AUDIO = {
    3: ROOT / "audio/B/recording-1788335172651946084-3-edited.wav",
    9: ROOT / "audio/B/recording-1788335274827411256-9-edited.wav",
    11: ROOT / "audio/B/recording-1788335331997254332-11-edited.wav",
    13: ROOT / "audio/B/recording-1788335424310472654-13-edited.wav",
    21: ROOT / "audio/B/recording-1788336004392441880-21-edited.wav",
    23: ROOT / "audio/B/recording-1788336802902854848-23-edited.wav",
    27: ROOT / "audio/B/recording-1788336869306084109-27-edited.wav",
    29: ROOT / "audio/B/recording-1788336991829665601-29-edited.wav",
    31: ROOT / "audio/B/recording-1788337091494732199-31-edited.wav",
    33: ROOT / "audio/B/recording-1788337131548000387-33-edited.wav",
    37: ROOT / "audio/B/recording-1788337274266833294-37-edited.wav",
    41: ROOT / "audio/B/recording-1788337344232592979-41-edited.wav",
    49: ROOT / "audio/B/recording-1788337508612162808-49-edited.wav",
    # chapter intro from the earlier retained batch: 转化为删除前驱或后继
    59: ROOT / "audio/B/recording-1788256295038615000-59-edited.wav",
}


def audio_duration(index: int) -> float:
    with wave.open(str(AUDIO[index]), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def source_video(
    path: str,
    *,
    at: float = 0.0,
    action_at: float | None = None,
    start: float = 0.0,
    end: float | None = None,
    panels: tuple[int, int, int, int] | None = None,
    fill: bool = False,
    pace: tuple[tuple[float, float, float, float], ...] | None = None,
    shade: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    return {
        "path": ROOT / path,
        "at": at,
        "action_at": at if action_at is None else action_at,
        "start": start,
        "end": end,
        "panels": panels,
        "fill": fill,
        "pace": pace,
        "shade": shade,
    }


def shot(stem: str, audio_indexes: tuple[int, ...], kind: str, *, title: str | None = None, **media: Any) -> dict[str, Any]:
    return {
        "stem": stem,
        "audio_indexes": audio_indexes,
        "duration": sum(audio_duration(index) for index in audio_indexes),
        "kind": kind,
        "title": title,
        **media,
    }


# Narration-driven pacing maps: (source_start, source_end, target_start, target_end)
# in seconds of the 30fps source animation. Stable states are held by giving a
# segment zero source length; action phases stretch across the window in which
# the narration describes them.
P23 = audio_duration(23)

SHOT4_PACE = (
    (0.00, 0.00, 0.00, P23 + 2.99),      # intro: hold the initial tree
    (1.50, 2.53, P23 + 2.99, P23 + 4.42),   # "删除70"
    (2.57, 3.53, P23 + 4.42, P23 + 5.77),   # check siblings
    (3.57, 5.53, P23 + 5.77, P23 + 9.32),   # "兄弟不够借…合并": 60 sinks
    (5.57, 6.13, P23 + 9.32, P23 + 10.92),  # middle internal underflow
    (6.13, 6.13, P23 + 10.92, P23 + 21.72), # hold: "还是不够借…选择50或者80"
    (6.17, 8.13, P23 + 21.72, P23 + 23.92), # "选择50": 50 sinks, merge 20
    (8.17, 8.93, P23 + 23.92, P23 + 25.52), # "80没有下溢": root forms
    (8.93, 8.93, P23 + 25.52, P23 + 39.52), # hold: 0-key talk + silence
    (8.97, 10.00, P23 + 39.52, P23 + 40.82),# "删除10"
    (10.03, 11.00, P23 + 40.82, P23 + 42.02), # check siblings
    (11.03, 13.00, P23 + 42.02, P23 + audio_duration(27)), # "合并20与30"
)

SHOT5_PACE = (
    (0.00, 0.00, 0.00, 2.80),        # intro: hold the initial tree
    (1.50, 1.97, 2.80, 4.00),        # "要删除70": target 70
    (2.00, 3.03, 4.00, 5.26),        # strike 70
    (3.07, 5.03, 5.26, 7.12),        # "首领60回家": 60 home, 55/70 follow
    (5.07, 5.63, 7.12, 8.30),        # merge with 55/70
    (5.67, 6.70, 8.30, 9.10),        # "把70删掉"
    (6.73, 7.30, 9.10, 10.40),       # "剩两个节点": [60] slot underflow
    (7.30, 7.30, 10.40, 23.50),      # hold: "无法推举…80还是50都行"
    (7.33, 9.30, 23.50, 26.10),      # "50回家了": pull leader home
    (9.33, 9.90, 26.10, 27.30),      # arrive [20,50]
    (9.90, 9.90, 27.30, 39.00),      # hold: 推举或不推举 talk
    (9.93, 10.40, 39.00, 40.00),     # "删除10": target 10
    (10.43, 11.47, 40.00, 41.30),    # strike 10
    (11.50, 13.47, 41.30, 42.70),    # "首领20回家"
    (13.50, 14.07, 42.70, 43.60),    # merge with 10/30
    (14.10, 15.13, 43.60, 44.90),    # "10被删除"
    (15.17, 18.17, 44.90, 47.00),    # right take contraction finishes by 47.0s
    (18.17, 21.166, 47.00, audio_duration(29)),  # both panels in final legal stable state from 47.0s to end
)


def title_shot(text: str) -> dict[str, Any]:
    """Chapter opening: the title word plays over its own narration (rec 59)."""
    return {
        "stem": "shot00-delete-title",
        "audio_indexes": (59,),
        "duration": audio_duration(59),
        "kind": "title",
        "text": text,
    }


# Recordings without a media tag inherit the previous media state. They do
# not create a text page, diagram, title, or other generated visual.
SHOTS: dict[int, dict[str, Any]] = {
    0: title_shot("删除"),
    1: shot("shot01-method-overview", (3, 9), "image", path=ROOT / "assets/btree-delete-cases.svg"),
    2: shot(
        "shot02-case1-no-underflow", (11,), "video",
        title="情况一，传统方法中删除后不下溢。",
        videos=(
            source_video("outputs/btree-prep/case-nocaption/btree-case1-traditional-nocaption.webm", action_at=12.10),
            source_video(
                "outputs/btree-prep/case-nocaption/btree-case1-ours-grid.webm",
                at=21.08, action_at=25.40, panels=(3, 2200, 1320, 80),
            ),
        ),
    ),
    3: shot(
        "shot03-case2-borrow", (13, 21), "video",
        title="情况二，传统方法中发生下溢，兄弟够借，向兄弟借关键字并发生旋转。",
        videos=(
            source_video("outputs/btree-prep/case-nocaption/btree-case2-traditional-nocaption.webm", action_at=10.47),
            source_video(
                "outputs/btree-prep/case-nocaption/btree-case2-ours-grid.webm",
                at=19.83, action_at=24.81, panels=(2, 2200, 1320, 80),
            ),
        ),
    ),
    4: shot(
        "shot04-case3-traditional-merge", (23, 27), "video",
        title="情况三，传统方法中发生下溢，兄弟不够借，只能合并。(可能导致副节点下溢出)",
        videos=(source_video("assets/btree-case3-traditional.webm", pace=SHOT4_PACE),),
    ),
    5: shot(
        "shot05-case3-leader-home", (29,), "video",
        title="情况三，传统方法中发生下溢，兄弟不够借，只能合并。(可能导致副节点下溢出)",
        videos=(source_video(
            "assets/btree-case3-ours.webm", pace=SHOT5_PACE,
            # thin shadow over the right (80) example once "50回家了" is said
            shade=(0.50, 0.9852, 25.10),
        ),),
    ),
    6: shot("shot06-promotion-parity", (31,), "image", path=ROOT / "assets/btree-promotion-parity.svg"),
    7: shot(
        "shot07-order5-delete450", (33, 37), "video",
        videos=(source_video(
            "assets/btree-delete-5-slow.webm", fill=True,
            pace=(
                (0.00, 0.00, 0.00, audio_duration(33)),
                (0.00, 20.00, audio_duration(33), audio_duration(33) + audio_duration(37)),
            ),
        ),),
    ),
    8: shot(
        "shot08-order5-delete410", (41,), "video",
        videos=(source_video(
            "assets/btree-delete-5-slow.webm", fill=True,
            pace=(
                (20.00, 20.00, 0.00, 0.08),    # hold the merged state before the cue
                (20.56, 24.00, 0.08, 5.52),    # "删除410…下溢": strike + underflow
                (24.00, 29.33, 5.52, 16.20),   # "右兄弟够借…460下移…480上移"
                (29.33, 32.06, 16.20, audio_duration(41)),  # "完成一次旋转"
            ),
        ),),
    ),
    9: shot(
        "shot09-order5-delete360", (49,), "video",
        videos=(source_video(
            "assets/btree-delete-5-slow.webm", fill=True,
            pace=(
                (32.06, 32.06, 0.00, 0.40),    # hold the post-rotation state
                (32.06, 35.50, 0.40, 5.64),    # "删除360…下溢"
                (35.50, 37.50, 5.64, 7.68),    # "右兄弟不够借"
                (37.50, 42.56, 7.68, 12.88),   # "和分隔关键字380合并；父节点下溢"
                (42.56, 45.22, 12.88, 15.22),  # "继续检查同层兄弟"
                (45.22, 51.78, 15.22, 20.56),  # "和分隔关键字300合并；再下溢"
                (51.78, 54.44, 20.56, 22.90),  # "上层节点也发生下溢出"
                (54.44, 61.00, 22.90, 27.20),  # "和根关键字400以及右兄弟合并"
                (61.00, 66.00, 27.20, audio_duration(49)),  # "四层缩成三层"
            ),
        ),),
    ),
}


# Sidecar subtitles remain available for the narration, but none of this text
# is rendered into the video image.
SUBTITLES: dict[int, tuple[tuple[float, float, str], ...]] = {
    0: (
        (0.00, 12.44, "删除。二叉搜索树、红黑树、AVL 树、B 树，他们对于有两个孩子的节点的删除，都是转化为删除直接前驱和后继。"),
        (13.52, 20.86, "对于 B 树，我们这里删除有两种方法，两种方法也都需要先转化为删除叶节点。"),
    ),
    1: (
        (0.00, 2.64, "第一种就是传统的方法。"),
        (2.64, 14.48, "传统方法先看删除叶节点元素后是否下溢：没有下溢,无需调整；发生下溢时,再分为兄弟够借和兄弟不够借两种情况。"),
        (15.14, audio_duration(3), "还有一种就是统一的语义,首领回家的版本。"),
        (audio_duration(3), audio_duration(3) + 4.14, "在正式讲解之前。"),
        (audio_duration(3) + 4.14, audio_duration(3) + 21.868752, "我先要告诉你一句话，首领回家得到的是一个解的集合,而传统方法则是集合中的最优解。我必须讲这个解集，因为它对将来的红黑树至关重要,所以也请你耐心听完我们的首领回家的办法。"),
    ),
    2: (
        (0.00, 19.54, "接下来这些例子都是基于四阶 B 树。情况一，传统方法中删除后不下溢。这里我们删除10。对于传统方法，这个节点删除10并不会下溢出，直接删除就行。"),
        (21.08, audio_duration(11), "对于我们的方法,把40拉下来,把10删掉,再把一个首领重新推举上去。"),
    ),
    3: (
        (0.00, 9.61, "情况二，传统方法中发生下溢，兄弟够借，向兄弟借关键字并发生旋转。"),
        (10.15, 19.83, "还是删除10。传统方法属于下溢出，需要问兄弟借，兄弟够借。发生了旋转。"),
        (19.83, audio_duration(13), "对于我们的方法,操作不变。把首领拉回家,把10删掉；在合法解集合中,可以重新推举,也可以不重新推举。传统方法保持了层数不变,即便这是一棵更大的树,也不会对上层造成影响。并且调整元素数量最少。"),
        (audio_duration(13), audio_duration(13) + audio_duration(21), "而我们的方法中如果采用不重新推举,如果这是一颗更大的树,不重新推举那父节点少了一个元素,可能会导致父节点下溢出,调整的范围更大。"),
    ),
    4: (
        (0.00, audio_duration(23), "情况三，传统方法中发生下溢，兄弟不够借，只能合并。这种情况合并之后父节点那一层就少了一个元素，所以父节点可能会继续下溢出。"),
        (audio_duration(23), audio_duration(23) + audio_duration(27), "传统方法,删除70之后发生下溢,兄弟不够借,就和父节点的关键字合并。父节点因此少了一个元素下溢出,还是不够借,所以父节点继续合并,可以选择50或者80进行合并,这里我们选择50,合并后这次父节点80没有下溢出；四阶 B 树中,节点有零个关键字时也仍然称为下溢出,不说节点没了。然后删除10,合并20与30。"),
    ),
    5: ((0.72, audio_duration(29), "对于我们的方法,这里要删除70。首领60回家之后,把70删掉,就剩两个节点了。这个结果无法重新推举；父节点下溢出,在合法解集合中,对于下溢出的父节点,它有两个首领,选择80回家还是50回家都行。50回家了,之后还是可以选择推举或者不推举,当然前提是有的推举才能推举,关键字数量不够就不能推举。这里就不能推举。接下来我们删除10,首领20回家,10被删除,还是没什么可推举的。但这次父节点并不下溢出,然后这就结束了。"),),
    6: (
        (0.00, audio_duration(31), "我们很容易发现,对于阶数为奇数的B树,只有大于最大容量时能够推举,对于阶数为偶数的B树,大于等于最大容量时能够推举。"),
    ),
    7: (
        (0.00, audio_duration(33), "接下来看一个完整的例子,这次我们用的是5阶B树。"),
        (audio_duration(33), audio_duration(33) + audio_duration(37), "删除450,它不是叶节点,先用后继460替换它。然后直接删除叶节点中的450。节点下溢,右兄弟只有两个关键字不够借,所以和分隔关键字500以及右兄弟合并。父节点没有下溢。"),
    ),
    8: ((0.00, audio_duration(41), "删除410,删除410后节点下溢,右兄弟够借。分隔关键字460下移到左节点,右兄弟最小关键字480上移到父节点,完成一次旋转。"),),
    9: ((0.00, audio_duration(49), "删除360,删除360后节点下溢出,右兄弟不够借,和分隔关键字380合并。父节点因此下溢出,继续检查同层兄弟；兄弟仍不够借,就再和分隔关键字300合并。上层节点也发生下溢出,最后和根关键字400以及右兄弟合并,树从四层缩成三层。"),),
}


def stamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{millis:03d}"


def write_srt(number: int) -> None:
    entries = [
        f"{index}\n{stamp(start)} --> {stamp(end)}\n{text}\n"
        for index, (start, end, text) in enumerate(SUBTITLES[number], 1)
    ]
    (OUT / f"{SHOTS[number]['stem']}.srt").write_text("\n".join(entries), encoding="utf-8")


def source_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def svg_geometry(path: Path) -> tuple[int, int, int, int]:
    root = ElementTree.parse(path).getroot()
    source_width = float(root.attrib["width"].removesuffix("px"))
    source_height = float(root.attrib["height"].removesuffix("px"))
    scale = min(BOX_W / source_width, BOX_H / source_height)
    width = round(source_width * scale)
    height = round(source_height * scale)
    return width, height, (WIDTH - width) // 2, (HEIGHT - height) // 2


def render_svg_png(path: Path, directory: Path) -> tuple[Path, int, int, int, int]:
    width, height, left, top = svg_geometry(path)
    png = directory / "frame-00000001.png"
    subprocess.run(
        ["rsvg-convert", "-w", str(width), "-h", str(height), str(path), "-o", str(png)],
        check=True,
    )
    return png, width, height, left, top


def encode_image(target: Path, data: dict[str, Any]) -> None:
    """Render SVG to RGBA PNG, then explicitly flatten it onto black."""
    with tempfile.TemporaryDirectory(prefix="btree-delete-svg-") as temporary:
        png, _width, _height, left, top = render_svg_png(data["path"], Path(temporary))
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"color=c=black:s={WIDTH}x{HEIGHT}:r={FPS}:d={data['duration']:.6f}",
                "-loop", "1", "-i", str(png),
                "-filter_complex", f"[1:v]format=rgba[rgba];[0:v][rgba]overlay={left}:{top}:format=auto,format=yuv420p[v]",
                "-map", "[v]", "-t", f"{data['duration']:.6f}", "-an",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS), str(target),
            ],
            check=True,
        )


def source_fps(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    numerator, denominator = result.stdout.strip().split("/")
    return float(numerator) / float(denominator)


def scale_chain(item: dict[str, Any]) -> str:
    if item.get("panels") or item.get("fill"):
        return "format=rgba"
    return (
        f"scale={BOX_W}:{BOX_H}:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2+40:color=black,format=rgba"
    )


def paced_source_time(segments: tuple[tuple[float, float, float, float], ...], t: float) -> float:
    value = segments[0][0]
    for src_start, src_end, tgt_start, tgt_end in segments:
        if t >= tgt_end:
            value = src_end
        elif t >= tgt_start:
            span = tgt_end - tgt_start
            progress = (t - tgt_start) / span if span > 0 else 0.0
            value = src_start + (src_end - src_start) * progress
            break
        else:
            break
    return value


def render_paced_pngs(item: dict[str, Any], directory: Path, total: float) -> tuple[Path, float]:
    """Rebuild the source animation on the narration timeline: hold stable
    states and stretch each action phase across the window where the
    narration describes it."""
    path = Path(item["path"])
    src = directory / "src"
    src.mkdir(parents=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-c:v", VP9_ALPHA_DECODER,
            "-i", str(path),
            "-vf", scale_chain(item),
            "-fps_mode", "vfr", str(src / "frame-%08d.png"),
        ],
        check=True,
    )
    sources = sorted(src.glob("frame-*.png"))
    # Position by fractional progress instead of a metadata frame rate: assets
    # like btree-delete-5-slow.webm stretch timestamps without changing the
    # stored frame count, so r_frame_rate does not describe the real pacing.
    span = source_duration(path)
    out = directory / "frames"
    out.mkdir(parents=True)
    for index in range(round(total * FPS)):
        src_t = paced_source_time(item["pace"], index / FPS)
        frame_index = min(len(sources) - 1, max(0, int(src_t / span * len(sources))))
        (out / f"frame-{index + 1:08d}.png").symlink_to(sources[frame_index].resolve())
    return out, total


def render_video_pngs(item: dict[str, Any], directory: Path, total: float) -> tuple[Path, float]:
    path = Path(item["path"])
    if item.get("pace"):
        return render_paced_pngs(item, directory, total)
    source_start = float(item["start"])
    source_end = item["end"]
    source_total = source_duration(path)
    end = min(float(source_end) if source_end is not None else source_total, source_total)
    playable = max(0.0, end - source_start)
    frames = directory / "frames"
    frames.mkdir(parents=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-c:v", VP9_ALPHA_DECODER,
            "-i", str(path),
            "-vf", f"trim=start={source_start:.6f}:end={end:.6f},setpts=PTS-STARTPTS,fps={FPS},{scale_chain(item)}",
            "-fps_mode", "vfr", str(frames / "frame-%08d.png"),
        ],
        check=True,
    )
    return frames, playable


def source_dimensions(path: Path) -> tuple[float, float]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    width, height = result.stdout.strip().split(",")
    return float(width), float(height)


def encode_title(target: Path, data: dict[str, Any]) -> None:
    """A silent intertitle: centered white text on black."""
    image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", 150)
    draw.text((WIDTH / 2, HEIGHT / 2), data["text"], font=font, fill=(255, 255, 255), anchor="mm")
    with tempfile.TemporaryDirectory(prefix="btree-delete-title-") as temporary:
        png = Path(temporary) / "title.png"
        image.save(png)
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png),
                "-t", f"{data['duration']:.6f}", "-vf", "format=yuv420p", "-an",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", str(FPS),
                "-movflags", "+faststart", str(target),
            ],
            check=True,
        )


def panel_boxes(item: dict[str, Any], frames_dir: Path) -> list[tuple[int, int, int, int]]:
    """Union alpha bounding box of each grid panel across sampled frames."""
    columns = item["panels"][0]
    files = sorted(frames_dir.glob("frame-*.png"))
    sample = files[:: max(1, len(files) // 12)] + [files[-1]]
    src_w, src_h = source_dimensions(Path(item["path"]))
    src_w, src_h = int(src_w), int(src_h)
    boxes: list[tuple[int, int, int, int]] = []
    for k in range(columns):
        slot_l = round(src_w * k / columns)
        slot_r = round(src_w * (k + 1) / columns)
        min_x, min_y, max_x, max_y = slot_r, src_h, slot_l, 0
        for f in sample:
            region = Image.open(f).convert("RGBA").crop((slot_l, 0, slot_r, src_h))
            lut = [255 if i >= 16 else 0 for i in range(256)]
            alpha = region.getchannel("A").point(lut)
            bbox = alpha.getbbox()
            if bbox:
                min_x = min(min_x, slot_l + bbox[0])
                min_y = min(min_y, bbox[1])
                max_x = max(max_x, slot_l + bbox[2])
                max_y = max(max_y, bbox[3])
        pad = 12
        left = max(slot_l, min_x - pad)
        top = max(0, min_y - pad)
        right = min(slot_r, max_x + pad)
        bottom = min(src_h, max_y + pad)
        boxes.append((left, top, right - left, bottom - top))
    return boxes


def layout_panels(boxes: list[tuple[int, int, int, int]], gap: int = 40) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Calculate scaling and (x, y) placement for grid panels."""
    columns = len(boxes)
    if columns == 3:
        # 2+1 layout: top row has panel 0 and panel 1; bottom row has panel 2 centered
        w_top = boxes[0][2] + boxes[1][2]
        w_bot = boxes[2][2]
        max_h = max(boxes[0][3], boxes[1][3]) + boxes[2][3] + gap
        scale = min(1760 / (w_top + gap), 910 / max_h, 1760 / w_bot)
        p_sizes = [(round(b[2] * scale), round(b[3] * scale)) for b in boxes]
        r1_w = p_sizes[0][0] + p_sizes[1][0] + gap
        r1_h = max(p_sizes[0][1], p_sizes[1][1])
        r2_w = p_sizes[2][0]
        r2_h = p_sizes[2][1]
        total_h = r1_h + r2_h + gap
        top_y = 110 + (940 - total_h) // 2
        bot_y = top_y + r1_h + gap
        r1_x = (WIDTH - r1_w) // 2
        r2_x = (WIDTH - r2_w) // 2
        positions = [
            (r1_x, top_y),
            (r1_x + p_sizes[0][0] + gap, top_y),
            (r2_x, bot_y),
        ]
        return p_sizes, positions
    elif columns == 2:
        # 1-row layout: 2 panels side by side
        w_tot = boxes[0][2] + boxes[1][2] + gap
        max_h = max(boxes[0][3], boxes[1][3])
        scale = min(1760 / w_tot, 910 / max_h)
        p_sizes = [(round(b[2] * scale), round(b[3] * scale)) for b in boxes]
        tot_w = p_sizes[0][0] + p_sizes[1][0] + gap
        tot_h = max(p_sizes[0][1], p_sizes[1][1])
        x0 = (WIDTH - tot_w) // 2
        y0 = 110 + (940 - tot_h) // 2
        positions = [
            (x0, y0),
            (x0 + p_sizes[0][0] + gap, y0),
        ]
        return p_sizes, positions
    else:
        tot_w = sum(b[2] for b in boxes) + (columns - 1) * gap
        max_h = max(b[3] for b in boxes)
        scale = min(1760 / tot_w, 910 / max_h)
        p_sizes = [(round(b[2] * scale), round(b[3] * scale)) for b in boxes]
        total_w = sum(w for w, _ in p_sizes) + (columns - 1) * gap
        top = 110 + (940 - max(h for _, h in p_sizes)) // 2
        cursor = (WIDTH - total_w) // 2
        positions = []
        for w, _ in p_sizes:
            positions.append((cursor, top))
            cursor += w + gap
        return p_sizes, positions


def encode_videos(target: Path, data: dict[str, Any]) -> None:
    """Render WebM frames to RGBA PNG, then overlay those PNGs onto black."""
    with tempfile.TemporaryDirectory(prefix="btree-delete-video-") as temporary:
        root = Path(temporary)
        rendered: list[tuple[dict[str, Any], Path, float, float, float]] = []
        for number, item in enumerate(data["videos"], 1):
            frames, playable = render_video_pngs(item, root / f"source-{number}", float(data["duration"]))
            rendered.append((item, frames, float(item["at"]), float(item["action_at"]), playable))

        inputs = ["-f", "lavfi", "-i", f"color=c=black:s={WIDTH}x{HEIGHT}:r={FPS}:d={data['duration']:.6f}"]
        for _item, frames, _at, _action_at, _playable in rendered:
            inputs.extend(["-framerate", str(FPS), "-i", str(frames / "frame-%08d.png")])

        filters: list[str] = []
        current = "0:v"
        for number, (item, _frames, at, action_at, playable) in enumerate(rendered, 1):
            if action_at < at:
                raise ValueError(f"action time {action_at} precedes overlay time {at}")
            window_end = rendered[number][2] if number < len(rendered) else float(data["duration"])
            start_hold = action_at - at
            end_hold = max(0.0, window_end - action_at - playable)
            timing = (
                f"tpad=start_mode=clone:start_duration={start_hold:.6f}"
                f":stop_mode=clone:stop_duration={end_hold:.6f},setpts=PTS-STARTPTS+{at:.6f}/TB"
            )
            enable = "" if number == len(rendered) else f":enable='between(t,{at:.6f},{window_end - 0.001:.6f})'"

            pieces: list[tuple[str, str]] = []
            panels = item.get("panels")
            if panels:
                boxes = panel_boxes(item, _frames)
                sizes, positions = layout_panels(boxes)
                for k, (panel_w, panel_h) in enumerate(sizes):
                    crop_x, crop_y, crop_w, crop_h = boxes[k]
                    px, py = positions[k]
                    label = f"source{number}p{k}"
                    filters.append(
                        f"[{number}:v]format=rgba,crop={crop_w}:{crop_h}:{crop_x}:{crop_y},"
                        f"scale={panel_w}:{panel_h},{timing}[{label}]"
                    )
                    pieces.append((label, f"{px}:{py}"))
            else:
                label = f"source{number}"
                filters.append(f"[{number}:v]format=rgba,{timing}[{label}]")
                pieces.append((label, "0:0"))

            for index, (label, position) in enumerate(pieces):
                output = f"base{number}i{index}"
                filters.append(
                    f"[{current}][{label}]overlay={position}:eof_action=pass:shortest=0:format=auto{enable}[{output}]"
                )
                current = output

        input_index = 1 + len(rendered)
        for number, (item, _frames, _at, _action_at, _playable) in enumerate(rendered, 1):
            shade = item.get("shade")
            if not shade:
                continue
            frac_l, frac_r, shade_at = shade
            source_w, source_h = source_dimensions(Path(item["path"]))
            fit = min(BOX_W / source_w, BOX_H / source_h)
            disp_w, disp_h = source_w * fit, source_h * fit
            left = round((WIDTH - disp_w) / 2 + frac_l * disp_w)
            top = round((HEIGHT - disp_h) / 2)
            rect_w, rect_h = round((frac_r - frac_l) * disp_w), round(disp_h)
            inputs.extend(["-f", "lavfi", "-i", f"color=c=black:s={rect_w}x{rect_h}:r={FPS}:d={data['duration']:.6f}"])
            label = f"shade{number}"
            filters.append(f"[{input_index}:v]format=rgba,colorchannelmixer=aa=0.32[{label}]")
            filters.append(
                f"[{current}][{label}]overlay={left}:{top}:eof_action=pass:shortest=0:format=auto"
                f":enable='gte(t,{shade_at:.6f})'[shaded{number}]"
            )
            current = f"shaded{number}"
            input_index += 1

        title_text = data.get("title")
        if title_text:
            title_img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
            draw = ImageDraw.Draw(title_img)
            font = ImageFont.truetype("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", 32)
            draw.text((80, 50), title_text, font=font, fill=(255, 255, 255, 255), anchor="lt")
            title_png = root / "corner_title.png"
            title_img.save(title_png)
            inputs.extend(["-loop", "1", "-i", str(title_png)])
            title_input_idx = input_index
            filters.append(f"[{current}][{title_input_idx}:v]overlay=0:0:format=auto[titled]")
            current = "titled"
            input_index += 1

        filters.append(f"[{current}]trim=duration={data['duration']:.6f},setpts=PTS-STARTPTS,format=yuv420p[v]")
        temporary_output = target.with_suffix(".tmp.mp4")
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", *inputs,
                "-filter_complex", ";".join(filters), "-map", "[v]", "-an",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS), str(temporary_output),
            ],
            check=True,
        )
        temporary_output.replace(target)


def mux_audio(segment: Path, data: dict[str, Any]) -> Path:
    output = OUT / f"{data['stem']}.mp4"
    audio_paths = [AUDIO[index] for index in data["audio_indexes"]]
    inputs = ["-i", str(segment)]
    for path in audio_paths:
        inputs.extend(["-i", str(path)])
    if not audio_paths:
        inputs.extend(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"])
        command = [
            "ffmpeg", "-y", "-loglevel", "error", *inputs,
            "-map", "0:v:0", "-map", "1:a:0", "-t", f"{data['duration']:.6f}",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ac", "2",
            "-shortest", "-movflags", "+faststart", str(output),
        ]
    elif len(audio_paths) == 1:
        command = [
            "ffmpeg", "-y", "-loglevel", "error", *inputs,
            "-map", "0:v:0", "-map", "1:a:0", "-t", f"{data['duration']:.6f}",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart", str(output),
        ]
    else:
        labels = "".join(f"[{index}:a]" for index in range(1, len(audio_paths) + 1))
        command = [
            "ffmpeg", "-y", "-loglevel", "error", *inputs,
            "-filter_complex", f"{labels}concat=n={len(audio_paths)}:v=0:a=1[a]",
            "-map", "0:v:0", "-map", "[a]", "-t", f"{data['duration']:.6f}",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart", str(output),
        ]
    subprocess.run(command, check=True)
    return output


def encode(number: int) -> Path:
    data = SHOTS[number]
    OUT.mkdir(parents=True, exist_ok=True)
    segment = OUT / "segments" / f"{data['stem']}.mp4"
    segment.parent.mkdir(parents=True, exist_ok=True)
    if data["kind"] == "title":
        encode_title(segment, data)
    elif data["kind"] == "image":
        encode_image(segment, data)
    else:
        encode_videos(segment, data)
    final = mux_audio(segment, data)
    write_srt(number)
    return final


def clean_outputs() -> None:
    if not OUT.exists():
        return
    for path in OUT.glob("shot*.mp4"):
        path.unlink()
    for path in OUT.glob("shot*.srt"):
        path.unlink()
    for path in (OUT / "segments", OUT / "preview"):
        if path.exists():
            shutil.rmtree(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shot", type=int, choices=sorted(SHOTS))
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    if args.clean:
        clean_outputs()
    if args.shot is not None:
        print(encode(args.shot))


if __name__ == "__main__":
    main()
