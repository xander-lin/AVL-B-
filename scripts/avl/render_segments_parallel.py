"""Render all AVL segments in parallel, then assemble with build_avl_video.py.

Each scene span is independent: render_video_segment writes only its own mp4
and render_frame(t) is a pure function of the deterministic timeline, so one
worker process per segment is safe.  Renders all segments concurrently, then
hand off to the normal serial build for audio concat + assembly:

    python3 scripts/avl/render_segments_parallel.py
    python3 scripts/build_avl_video.py
"""
import math
import multiprocessing
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

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


def worker(payload: tuple[str, int, int]) -> tuple[str, int, float]:
    scene_id, start, end = payload
    started = time.time()
    register_all()
    engine.prepare()
    output = engine.OUTPUT_DIR / "segments" / f"{scene_id}.mp4"
    engine.render_video_segment(output, start, end)
    return scene_id, end - start, time.time() - started


def main() -> None:
    register_all()
    tl = engine.prepare()
    engine.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (engine.OUTPUT_DIR / "segments").mkdir(parents=True, exist_ok=True)
    jobs: list[tuple[str, int, int]] = []
    for scene_id, *_ in engine.SCENES:
        scene_start, scene_end = engine.scene_span(scene_id)
        jobs.append((scene_id, round(scene_start * engine.FPS), round(scene_end * engine.FPS)))
    code_start = math.ceil(tl.total * engine.FPS)
    code_end = math.ceil((tl.total + seg11.CODE_DURATION) * engine.FPS)
    jobs.append(("s10-code", code_start, code_end))
    workers = min(len(jobs), max(1, (os.cpu_count() or 1) // 2))
    print(f"{len(jobs)} segments, {workers} workers, {engine.FPS}fps", flush=True)
    started = time.time()
    if hasattr(multiprocessing, "get_context"):
        pool_context = multiprocessing.get_context("fork")
    else:
        pool_context = multiprocessing
    with pool_context.Pool(workers) as pool:
        for scene_id, frames, elapsed in pool.imap_unordered(worker, jobs):
            print(f"render {scene_id}: {frames} frames in {elapsed:.1f}s", flush=True)
    print(f"all segments rendered in {time.time() - started:.1f}s", flush=True)


if __name__ == "__main__":
    main()