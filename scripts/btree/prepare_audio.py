"""Prepare the B-tree narration recordings for shot timing.

Mirrors scripts/avl/prepare_new_audio.py: the source WAVs stay untouched and an
ASR manifest with file/segment/word timestamps is written so shot builders can
align motion to the narration deterministically.
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
DEFAULT_AUDIO_DIR = ROOT / "audio" / "B"
DEFAULT_OUTPUT = ROOT / "outputs" / "btree-prep" / "b-asr.json"
MODEL_CACHE = Path.home() / ".cache" / "huggingface" / "hub"
FILENAME_INDEX = re.compile(r"-(\d+)-edited\.wav$")


def recording_index(path: Path) -> int:
    match = FILENAME_INDEX.search(path.name)
    if match is None:
        raise ValueError(f"cannot find recording index in {path.name}")
    return int(match.group(1))


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def prepare(audio_dir: Path, output: Path, model_name: str, device: str, only: int | None) -> None:
    files = sorted(audio_dir.glob("*.wav"), key=recording_index)
    if only is not None:
        files = [path for path in files if recording_index(path) == only]
    if not files:
        raise SystemExit(f"no WAV files found in {audio_dir}")

    model = WhisperModel(
        model_name,
        device=device,
        compute_type="float16" if device != "cpu" else "int8",
        download_root=str(MODEL_CACHE),
        local_files_only=True,
    )
    previous = json.loads(output.read_text(encoding="utf-8")) if output.exists() else None
    result_files = list(previous["files"]) if previous else []
    # Different narration passes can reuse a recording index. The absolute
    # audio path, rather than the chapter label, identifies a prepared file.
    done_audio = {item["audio"] for item in result_files}
    started = time.monotonic()
    offset = sum(item["duration"] for item in result_files)
    for file_index, path in enumerate(files):
        if str(path.resolve()) in done_audio:
            continue
        print(f"transcribe {path.name}", flush=True)
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
            "duration": actual_duration,
            "duration_after_vad": info.duration_after_vad,
            "segments": segment_data,
        })
        done_audio.add(str(path.resolve()))
        result_files.sort(key=lambda item: item["recording_index"])
        offset = sum(item["duration"] for item in result_files)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "model": model_name,
                    "language": "zh",
                    "audio_directory": str(audio_dir.resolve()),
                    "file_count": len(list(audio_dir.glob("*.wav"))),
                    "total_duration": offset,
                    "files": result_files,
                    "status": "in_progress" if len(result_files) < len(list(audio_dir.glob("*.wav"))) else "complete",
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
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--only", type=int, default=None, help="transcribe one recording index only")
    args = parser.parse_args()
    prepare(args.audio_dir, args.output, args.model, args.device, args.only)


if __name__ == "__main__":
    main()
