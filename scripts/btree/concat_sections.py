#!/usr/bin/env python3
"""Concatenate the narrated B-tree shots into pre/post-deletion sections."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VIDEO_DIR = ROOT / "outputs" / "btree-video"
CONCAT_DIR = VIDEO_DIR / "concat"

SECTIONS = {
    "before-deletion": ["shot01-intro", *[f"shot{index:02d}" for index in range(2, 9)]],
    "after-deletion": [f"shot{index:02d}" for index in range(9, 17)],
}

TIMING = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2},\d{3}) --> (?P<end>\d{2}:\d{2}:\d{2},\d{3})"
)


def duration(path: Path) -> float:
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


def parse_stamp(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    whole, millis = seconds.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(whole) + int(millis) / 1000


def stamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{millis:03d}"


SENTENCE_ENDERS = "。！？；…!?;"
CLAUSE_BREAKS = "，、,:： "


def split_long_text(text: str, limit: int = 24) -> list[str]:
    """Re-segment a subtitle line into short cues without changing any wording."""
    text = text.replace("\n", "")
    sentences: list[str] = []
    buffer = ""
    for char in text:
        buffer += char
        if char in SENTENCE_ENDERS:
            sentences.append(buffer)
            buffer = ""
    if buffer.strip():
        sentences.append(buffer)

    pieces: list[str] = []
    for sentence in sentences:
        if len(sentence) <= limit:
            pieces.append(sentence)
            continue
        clauses: list[str] = []
        buffer = ""
        for char in sentence:
            buffer += char
            if char in CLAUSE_BREAKS and len(buffer) >= limit // 2:
                clauses.append(buffer)
                buffer = ""
        if buffer.strip():
            clauses.append(buffer)
        merged: list[str] = []
        buffer = ""
        for clause in clauses:
            if buffer and len(buffer) + len(clause) > limit:
                merged.append(buffer)
                buffer = clause
            else:
                buffer += clause
        if buffer.strip():
            merged.append(buffer)
        for chunk in merged:
            while len(chunk) > limit:
                cut = chunk.rfind("，", 0, limit + 1)
                if cut <= 0:
                    cut = limit
                pieces.append(chunk[: cut + 1])
                chunk = chunk[cut + 1 :]
            pieces.append(chunk)
    return [piece for piece in pieces if piece.strip()]


def shifted_srt(path: Path, offset: float, number_start: int) -> tuple[list[str], int]:
    blocks = [block.strip() for block in path.read_text(encoding="utf-8").split("\n\n") if block.strip()]
    entries: list[str] = []
    number = number_start
    for block in blocks:
        lines = block.splitlines()
        timing = next((line for line in lines if TIMING.fullmatch(line)), None)
        if timing is None:
            raise ValueError(f"invalid subtitle block in {path}: {block!r}")
        match = TIMING.fullmatch(timing)
        assert match is not None
        start = parse_stamp(match.group("start")) + offset
        end = parse_stamp(match.group("end")) + offset
        text_index = lines.index(timing) + 1
        text = "\n".join(lines[text_index:])
        pieces = split_long_text(text)
        if len(pieces) <= 1:
            entries.append(f"{number}\n{stamp(start)} --> {stamp(end)}\n{text}\n")
            number += 1
            continue
        weights = [len(piece) for piece in pieces]
        total = sum(weights)
        cursor = start
        for index, piece in enumerate(pieces):
            piece_end = end if index == len(pieces) - 1 else cursor + (end - start) * weights[index] / total
            entries.append(f"{number}\n{stamp(cursor)} --> {stamp(piece_end)}\n{piece}\n")
            number += 1
            cursor = piece_end
    return entries, number


def concat_section(name: str, stems: list[str]) -> None:
    CONCAT_DIR.mkdir(parents=True, exist_ok=True)
    files = [VIDEO_DIR / f"{stem}.mp4" for stem in stems]
    subtitles = [VIDEO_DIR / f"{stem}.srt" for stem in stems]
    missing = [path for path in [*files, *subtitles] if not path.exists()]
    if missing:
        raise FileNotFoundError("missing section input: " + ", ".join(map(str, missing)))

    list_path = CONCAT_DIR / f"{name}.txt"
    list_path.write_text("".join(f"file '{path}'\n" for path in files), encoding="utf-8")
    output = VIDEO_DIR / f"{name}.mp4"
    temporary = output.with_suffix(".tmp.mp4")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(temporary),
        ],
        check=True,
    )
    temporary.replace(output)

    entries: list[str] = []
    offset = 0.0
    number = 1
    for video, subtitle in zip(files, subtitles):
        current, number = shifted_srt(subtitle, offset, number)
        entries.extend(current)
        offset += duration(video)
    (VIDEO_DIR / f"{name}.srt").write_text("\n".join(entries), encoding="utf-8")
    print(f"{output} duration={duration(output):.6f}s")


def main() -> None:
    for name, stems in SECTIONS.items():
        concat_section(name, stems)


if __name__ == "__main__":
    main()
