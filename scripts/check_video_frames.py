#!/usr/bin/env python3
"""Create compressed contact sheets for frame-by-frame video inspection.

The default inspection protocol is the project rule for 24 fps videos:
sample source frames 0, 8, 16, ..., put nine sampled frames in one 3x3
contact sheet, then resize and encode the completed sheet as JPEG quality 50.
The original video is never modified.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from PIL import Image, ImageDraw, ImageFont


DEFAULT_FPS = 24.0
DEFAULT_STEP = 8
DEFAULT_GROUP_SIZE = 9
DEFAULT_COLUMNS = 3
DEFAULT_JPEG_QUALITY = 50
DEFAULT_MAX_WIDTH = 2400
DEFAULT_BACKGROUND = "#000000"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate compressed contact sheets from regularly sampled video frames."
    )
    parser.add_argument("video", type=Path, help="Input WebM, MP4, or other FFmpeg-readable video")
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Directory for JPEG contact sheets and manifest.json",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=DEFAULT_FPS,
        help=f"Expected/source FPS for validation and timestamps (default: {DEFAULT_FPS:g})",
    )
    parser.add_argument(
        "--allow-fps-mismatch",
        action="store_true",
        help="Continue when the probed video FPS differs from --fps",
    )
    parser.add_argument(
        "--sample-step",
        type=int,
        default=DEFAULT_STEP,
        metavar="FRAMES",
        help=f"Take one source frame every N frames (default: {DEFAULT_STEP})",
    )
    parser.add_argument(
        "--group-size",
        type=int,
        default=DEFAULT_GROUP_SIZE,
        metavar="N",
        help=f"Number of sampled frames per contact sheet (default: {DEFAULT_GROUP_SIZE})",
    )
    parser.add_argument(
        "--columns",
        type=int,
        default=DEFAULT_COLUMNS,
        metavar="N",
        help=f"Contact-sheet columns (default: {DEFAULT_COLUMNS}; 3 gives a 3x3 sheet)",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=DEFAULT_JPEG_QUALITY,
        metavar="1-95",
        help=f"JPEG quality after stitching (default: {DEFAULT_JPEG_QUALITY})",
    )
    parser.add_argument(
        "--max-width",
        type=int,
        default=DEFAULT_MAX_WIDTH,
        metavar="PIXELS",
        help=(
            "Maximum width after stitching; use 0 to keep full-size sheets "
            f"(default: {DEFAULT_MAX_WIDTH})"
        ),
    )
    parser.add_argument(
        "--background",
        default=DEFAULT_BACKGROUND,
        metavar="#RRGGBB",
        help=f"Background used when flattening alpha (default: {DEFAULT_BACKGROUND})",
    )
    parser.add_argument(
        "--start-frame",
        type=int,
        default=0,
        metavar="N",
        help="First source frame to consider, inclusive (default: 0)",
    )
    parser.add_argument(
        "--end-frame",
        type=int,
        default=None,
        metavar="N",
        help="Stop before this source frame, exclusive (default: until video ends)",
    )
    return parser.parse_args()


def parse_rate(value: str | None) -> float | None:
    if not value or value in {"N/A", "0/0"}:
        return None
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None


def probe_video(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,avg_frame_rate,nb_frames,duration,pix_fmt",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise SystemExit("ffprobe is required but was not found on PATH") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or "ffprobe could not read the video"
        raise SystemExit(detail) from error
    try:
        streams = json.loads(result.stdout)["streams"]
        stream = streams[0]
    except (KeyError, IndexError, json.JSONDecodeError) as error:
        raise SystemExit("The input does not contain a readable video stream") from error
    actual_fps = parse_rate(stream.get("avg_frame_rate")) or parse_rate(stream.get("r_frame_rate"))
    if actual_fps is None:
        raise SystemExit("Could not determine the input video frame rate")
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "source_fps": actual_fps,
        "r_frame_rate": stream.get("r_frame_rate"),
        "avg_frame_rate": stream.get("avg_frame_rate"),
        "nb_frames": stream.get("nb_frames"),
        "duration": parse_float(stream.get("duration")),
        "pix_fmt": stream.get("pix_fmt"),
    }


def parse_float(value: str | None) -> float | None:
    if value in (None, "N/A"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_color(value: str) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    if len(text) != 6:
        raise argparse.ArgumentTypeError("background must be #RRGGBB")
    try:
        number = int(text, 16)
    except ValueError as error:
        raise argparse.ArgumentTypeError("background must be #RRGGBB") from error
    return number >> 16, (number >> 8) & 0xFF, number & 0xFF


def select_filter(start: int, end: int | None, step: int) -> str:
    terms = [f"gte(n\\,{start})", f"eq(mod(n-{start}\\,{step})\\,0)"]
    if end is not None:
        terms.append(f"lt(n\\,{end})")
    return "select=" + "*".join(terms)


def extract_sampled_frames(
    video: Path,
    target: Path,
    *,
    start: int,
    end: int | None,
    step: int,
) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-vf",
        select_filter(start, end, step),
        "-fps_mode",
        "vfr",
        str(target / "sample-%08d.png"),
    ]
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError as error:
        raise SystemExit("ffmpeg is required but was not found on PATH") from error
    except subprocess.CalledProcessError as error:
        raise SystemExit("ffmpeg could not extract sampled frames") from error
    frames = sorted(target.glob("sample-*.png"))
    if not frames:
        raise SystemExit("No frames matched the requested range")
    return frames


def font_for(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    )
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def flatten_frame(path: Path, background: tuple[int, int, int]) -> Image.Image:
    with Image.open(path) as source:
        rgba = source.convert("RGBA")
    canvas = Image.new("RGBA", rgba.size, (*background, 255))
    return Image.alpha_composite(canvas, rgba).convert("RGB")


def draw_label(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    frame_index: int,
    fps: float,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    left, top, right, bottom = box
    label = f"frame {frame_index}  {frame_index / fps:.3f}s"
    draw.rectangle((left, top, right, bottom), fill=(24, 24, 24))
    draw.text((left + 12, top + (bottom - top) // 2), label, fill=(245, 245, 245), font=font, anchor="lm")


def make_contact_sheet(
    frame_paths: list[Path],
    frame_indices: list[int],
    output_path: Path,
    *,
    columns: int,
    group_size: int,
    fps: float,
    background: tuple[int, int, int],
    max_width: int,
    quality: int,
) -> dict[str, Any]:
    with Image.open(frame_paths[0]) as first:
        frame_width, frame_height = first.size
    label_height = max(52, min(96, frame_height // 12))
    rows = (group_size + columns - 1) // columns
    sheet = Image.new(
        "RGB",
        (frame_width * columns, (frame_height + label_height) * rows),
        (10, 10, 10),
    )
    label_font = font_for(max(18, min(42, frame_width // 64)))
    draw = ImageDraw.Draw(sheet)
    for position, (frame_path, frame_index) in enumerate(zip(frame_paths, frame_indices, strict=True)):
        column = position % columns
        row = position // columns
        x = column * frame_width
        y = row * (frame_height + label_height)
        frame = flatten_frame(frame_path, background)
        sheet.paste(frame, (x, y))
        draw_label(
            draw,
            (x, y + frame_height, x + frame_width, y + frame_height + label_height),
            frame_index=frame_index,
            fps=fps,
            font=label_font,
        )
        draw.rectangle((x, y, x + frame_width - 1, y + frame_height - 1), outline=(100, 100, 100), width=2)

    original_size = sheet.size
    if max_width > 0 and sheet.width > max_width:
        resized_height = max(1, round(sheet.height * max_width / sheet.width))
        sheet = sheet.resize((max_width, resized_height), Image.Resampling.LANCZOS)
    sheet.save(output_path, format="JPEG", quality=quality, optimize=True, progressive=True)
    return {
        "file": output_path.name,
        "source_frame_first": frame_indices[0],
        "source_frame_last": frame_indices[-1],
        "sample_count": len(frame_indices),
        "sample_frames": [
            {"index": index, "time_seconds": round(index / fps, 6)}
            for index in frame_indices
        ],
        "original_sheet_size": {"width": original_size[0], "height": original_size[1]},
        "output_size": {"width": sheet.width, "height": sheet.height},
    }


def remove_previous_outputs(output_dir: Path) -> None:
    for path in output_dir.glob("sheet-*.jpg"):
        path.unlink()
    output_dir.joinpath("manifest.json").unlink(missing_ok=True)


def build(args: argparse.Namespace) -> int:
    video = args.video.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if not video.is_file():
        raise SystemExit(f"input video not found: {video}")
    if args.fps <= 0:
        raise SystemExit("--fps must be greater than zero")
    if args.sample_step <= 0:
        raise SystemExit("--sample-step must be greater than zero")
    if args.group_size <= 0:
        raise SystemExit("--group-size must be greater than zero")
    if args.columns <= 0 or args.columns > args.group_size:
        raise SystemExit("--columns must be between 1 and --group-size")
    if not 1 <= args.quality <= 95:
        raise SystemExit("--quality must be between 1 and 95")
    if args.max_width < 0:
        raise SystemExit("--max-width must be zero or greater")
    if args.start_frame < 0:
        raise SystemExit("--start-frame must be zero or greater")
    if args.end_frame is not None and args.end_frame <= args.start_frame:
        raise SystemExit("--end-frame must be greater than --start-frame")
    background = parse_color(args.background)

    probe = probe_video(video)
    fps_delta = abs(probe["source_fps"] - args.fps)
    if fps_delta > 0.02:
        message = (
            f"input is {probe['source_fps']:.6g} fps but --fps is {args.fps:.6g}; "
            "pass the source FPS explicitly or use --allow-fps-mismatch"
        )
        if not args.allow_fps_mismatch:
            raise SystemExit(message)
        print(f"warning: {message}", file=sys.stderr)

    output_dir.mkdir(parents=True, exist_ok=True)
    remove_previous_outputs(output_dir)
    with TemporaryDirectory(prefix="video-frame-check-") as temp_name:
        sampled_dir = Path(temp_name)
        frame_paths = extract_sampled_frames(
            video,
            sampled_dir,
            start=args.start_frame,
            end=args.end_frame,
            step=args.sample_step,
        )
        frame_indices = [args.start_frame + offset * args.sample_step for offset in range(len(frame_paths))]
        groups: list[dict[str, Any]] = []
        for group_index, offset in enumerate(range(0, len(frame_paths), args.group_size), start=1):
            paths = frame_paths[offset:offset + args.group_size]
            indices = frame_indices[offset:offset + args.group_size]
            output_path = output_dir / f"sheet-{group_index:05d}-f{indices[0]:08d}-f{indices[-1]:08d}.jpg"
            groups.append(
                make_contact_sheet(
                    paths,
                    indices,
                    output_path,
                    columns=args.columns,
                    group_size=args.group_size,
                    fps=args.fps,
                    background=background,
                    max_width=args.max_width,
                    quality=args.quality,
                )
            )

    manifest = {
        "input": str(video),
        "video": probe,
        "protocol": {
            "sampling_fps": args.fps,
            "sample_step_source_frames": args.sample_step,
            "group_size": args.group_size,
            "columns": args.columns,
            "jpeg_quality": args.quality,
            "max_width_after_stitching": args.max_width,
            "background": args.background,
            "start_frame": args.start_frame,
            "end_frame_exclusive": args.end_frame,
        },
        "sampled_frame_count": len(frame_paths),
        "sheet_count": len(groups),
        "groups": groups,
    }
    output_dir.joinpath("manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"input: {video}")
    print(f"sampled frames: {len(frame_paths)}")
    print(f"contact sheets: {len(groups)}")
    print(f"output: {output_dir}")
    print(f"manifest: {output_dir / 'manifest.json'}")
    return 0


def main() -> int:
    return build(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
