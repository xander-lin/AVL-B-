"""Prepare the newly recorded AVL narration files for timeline alignment.

The source files are kept untouched. This writes an independent ASR manifest
with file, segment, and word timestamps so the final timeline can be rebuilt
after the recording boundary is confirmed.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import wave
from pathlib import Path

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUDIO_DIR = ROOT / "audio" / "avl" / "new"
DEFAULT_OUTPUT = ROOT / "outputs" / "avl-prep" / "avl-new-asr.json"
MODEL_CACHE = Path.home() / ".cache" / "huggingface" / "hub"
FILENAME_INDEX = re.compile(r"-(\d+)-edited\.wav$")
RECORDED_BOUNDARY = "删除示例第三次删除 3 的收尾（对应文稿第 213 行视频前）"


def recording_index(path: Path) -> int:
    match = FILENAME_INDEX.search(path.name)
    if match is None:
        raise ValueError(f"cannot find recording index in {path.name}")
    return int(match.group(1))


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def prepare(audio_dir: Path, output: Path, model_name: str, device: str) -> None:
    files = sorted(audio_dir.glob("*.wav"), key=recording_index)
    if not files:
        raise SystemExit(f"no WAV files found in {audio_dir}")

    model = WhisperModel(
        model_name,
        device=device,
        compute_type="float16" if device != "cpu" else "int8",
        download_root=str(MODEL_CACHE),
        local_files_only=True,
    )
    result_files = []
    started = time.monotonic()
    offset = 0.0
    for file_index, path in enumerate(files):
        print(f"transcribe {file_index + 1}/{len(files)}: {path.name}", flush=True)
        segments, info = model.transcribe(
            str(path),
            language="zh",
            beam_size=5,
            vad_filter=True,
            word_timestamps=True,
        )
        segment_data = []
        for segment in segments:
            words = [
                {
                    "start": word.start,
                    "end": word.end,
                    "global_start": offset + word.start,
                    "global_end": offset + word.end,
                    "word": word.word,
                }
                for word in (segment.words or [])
            ]
            segment_data.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
                "words": words,
            })
        actual_duration = wav_duration(path)
        result_files.append({
            "audio": str(path.resolve()),
            "recording_index": recording_index(path),
            "offset": offset,
            "duration": actual_duration,
            "duration_after_vad": info.duration_after_vad,
            "segments": segment_data,
        })
        for segment in result_files[-1]["segments"]:
            segment["global_start"] = offset + segment["start"]
            segment["global_end"] = offset + segment["end"]
        offset += actual_duration
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "model": model_name,
                    "language": "zh",
                    "audio_directory": str(audio_dir.resolve()),
                    "file_count": len(result_files),
                    "total_duration": offset,
                    "recorded_boundary": RECORDED_BOUNDARY,
                    "files": result_files,
                    "status": "in_progress" if len(result_files) < len(files) else "complete",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    print(f"wrote {output} ({len(result_files)} files, {time.monotonic() - started:.1f}s)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default="medium")
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    prepare(args.audio_dir, args.output, args.model, args.device)


if __name__ == "__main__":
    main()
