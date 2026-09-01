"""Build the AVL recap video.

The renderer is split per segment under scripts/avl/: engine.py holds the
shared style/primitives/timeline/tree machinery, seg01..seg10 each draw one
scene, and this file wires them together and produces the deliverables.

Usage:
    python scripts/build_avl_video.py                    # render missing segments and assemble
    python scripts/build_avl_video.py --segment s7-proof # render one segment and assemble
    python scripts/build_avl_video.py --assemble         # assemble cached segments only
    python scripts/build_avl_video.py --preview           # write checkpoint frames
"""
import math
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "avl"))

import engine  # noqa: E402
import seg01  # noqa: E402
import seg02  # noqa: E402
import seg03  # noqa: E402
import seg04  # noqa: E402
import seg05  # noqa: E402
import seg06  # noqa: E402
import seg07  # noqa: E402
import seg08  # noqa: E402
import seg09  # noqa: E402
import seg10  # noqa: E402
import seg11  # noqa: E402


def register_all() -> None:
    engine.register("s1-def", seg01.draw)
    engine.register("s2-contrast", seg02.draw)
    engine.register("s2-lever", seg03.draw)
    engine.register("s3-imagery", seg04.draw)
    engine.register("s4-middle", seg05.draw)
    engine.register("s5-insert", seg06.draw)
    engine.register("s6-delete", seg07.draw)
    engine.register("s7-proof", seg08.draw)
    engine.register("s8-factor", seg09.draw)
    engine.register("s9-outro", seg10.draw)
    engine.register("s10-code", seg11.draw)


PREVIEW_TIMES = (
    6.0, 24.0, 46.0, 62.0, 80.0, 97.0, 112.0, 126.0, 138.0, 150.0,
    163.0, 180.0, 196.0, 214.0, 232.0, 252.0, 262.5, 274.0, 288.0,
    305.0, 330.0, 352.0, 365.0, 374.0, 383.0, 392.0, 400.0, 412.0,
    425.0, 438.0, 447.0, 456.0, 470.0, 486.0, 500.0, 512.0, 525.0,
    540.0, 560.0, 578.0, 600.0, 625.0, 650.0, 665.0, 680.0, 700.0, 709.0,
)


def segment_paths() -> dict[str, Path]:
    directory = engine.OUTPUT_DIR / "segments"
    paths = {scene_id: directory / f"{scene_id}.mp4" for scene_id, *_ in engine.SCENES}
    paths["s10-code"] = directory / "s10-code.mp4"
    return paths


def render_segments(tl, selected: set[str] | None, *, only_missing: bool) -> list[Path]:
    paths = segment_paths()
    paths[next(iter(paths))].parent.mkdir(parents=True, exist_ok=True)
    for index, (scene_id, *_rest) in enumerate(engine.SCENES):
        if selected is not None and scene_id not in selected:
            continue
        output = paths[scene_id]
        if only_missing and output.exists():
            continue
        scene_start, scene_end = engine.scene_span(scene_id)
        start = round(scene_start * engine.FPS)
        end = round(scene_end * engine.FPS)
        print(f"render {scene_id}: frames {start}-{end - 1}", flush=True)
        engine.render_video_segment(output, start, end)
    if selected is None or "s10-code" in selected:
        output = paths["s10-code"]
        if not (only_missing and output.exists()):
            start = math.ceil(tl.total * engine.FPS)
            end = math.ceil((tl.total + seg11.CODE_DURATION) * engine.FPS)
            print(f"render s10-code: frames {start}-{end - 1}", flush=True)
            engine.render_video_segment(output, start, end)
    return [paths[scene_id] for scene_id in list(paths)]


def main() -> None:
    register_all()
    tl = engine.prepare()
    output_timeline = engine.OUTPUT_DIR / "avl-recap-timeline.json"
    if "--subtitles" in sys.argv:
        engine.write_srt(engine.OUTPUT_DIR / "avl-recap.srt", tl.cues)
    engine.write_timeline(output_timeline, tl)
    if "--preview" in sys.argv:
        preview_dir = engine.OUTPUT_DIR / "preview"
        preview_dir.mkdir(exist_ok=True)
        times = PREVIEW_TIMES
        for arg_index, value in enumerate(sys.argv):
            if value == "--at" and arg_index + 1 < len(sys.argv):
                times = tuple(float(x) for x in sys.argv[arg_index + 1].split(","))
        for when in times:
            engine.render_frame(min(when, tl.total - 0.05)).save(
                preview_dir / f"t{when:07.2f}.png"
            )
        print(f"previews written to {preview_dir}")
        return

    selected = None
    if "--segment" in sys.argv:
        value = sys.argv[sys.argv.index("--segment") + 1]
        selected = set(value.split(","))
        known = {scene_id for scene_id, *_ in engine.SCENES} | {"s10-code"}
        unknown = selected - known
        if unknown:
            raise SystemExit(f"unknown segment(s): {', '.join(sorted(unknown))}")
    if "--assemble" in sys.argv:
        paths = list(segment_paths().values())
    else:
        paths = render_segments(tl, selected, only_missing=selected is None)
    if selected is not None:
        print("selected segment(s) rendered")
        return
    if not all(path.exists() for path in paths):
        missing = [path.name for path in paths if not path.exists()]
        raise SystemExit(f"missing cached segment(s): {', '.join(sorted(missing))}")
    narration = engine.OUTPUT_DIR / "narration-concat.wav"
    concat_duration = engine.concat_audio(narration, tl.audio)
    assert abs(concat_duration - tl.total) < 0.05, (concat_duration, tl.total)
    # the code section is silent: pad the narration track with silence so the
    # mux covers the full video length
    code_duration = seg11.CODE_DURATION
    padded = engine.OUTPUT_DIR / "narration-final.wav"
    import wave

    with wave.open(str(narration), "rb") as handle:
        params = handle.getparams()
        frames = handle.readframes(handle.getnframes())
    silence = b"\x00" * (round(code_duration * params.framerate) * params.sampwidth * params.nchannels)
    with wave.open(str(padded), "wb") as handle:
        handle.setparams(params)
        handle.writeframes(frames + silence)
    final_duration = concat_duration + code_duration
    video_only = engine.OUTPUT_DIR / "avl-video-only.mp4"
    engine.concat_video_segments(video_only, paths)
    output_video = engine.OUTPUT_DIR / "avl-recap.mp4"
    engine.mux_video_audio(output_video, video_only, padded, final_duration)
    video_only.unlink(missing_ok=True)
    # record the silent code section in the timeline metadata
    timeline_payload = output_timeline.read_text(encoding="utf-8")
    import json as json_module

    timeline_data = json_module.loads(timeline_payload)
    timeline_data["visual_states"].append({
        "start": timeline_data["total_duration"],
        "end": final_duration,
        "id": "s10-code",
        "description": "我们的 C 语言代码（静默图文）",
    })
    timeline_data["notes"].append(
        f"Silent code section appended: {code_duration:.1f}s of manuscript text + C code, no narration."
    )
    output_timeline.write_text(
        json_module.dumps(timeline_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(output_video)
    print(output_timeline)
    print(f"duration={final_duration:.6f}s frames={math.ceil(final_duration * engine.FPS)}")


if __name__ == "__main__":
    main()
