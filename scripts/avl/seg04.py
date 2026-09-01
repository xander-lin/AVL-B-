"""AVL recap segment seg04 (scene s3-imagery)."""
from PIL import Image, ImageDraw

from engine import *  # noqa: F401,F403
import engine as avl_engine


SCENE_ID = "s3-imagery"


def _cargo_ring(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], label: str) -> None:
    draw.ellipse(box, outline=SKY_BLUE, width=7)
    draw.ellipse(tuple(value + offset for value, offset in zip(box, (9, 9, -9, -9))), outline=INK, width=2)
    draw_text(draw, ((box[0] + box[2]) / 2, box[1] - 24), label, size=28, fill=INK)


def _mark_left_middle_right(image: Image.Image, local_t: float) -> None:
    """The source frame is held here; ASR word times identify its three cargos."""
    draw = ImageDraw.Draw(image)
    if local_t >= 3.96:
        _cargo_ring(draw, (442, 626, 606, 796), "左")
    if local_t >= 4.22:
        _cargo_ring(draw, (742, 626, 906, 796), "中")
    if local_t >= 4.52:
        _cargo_ring(draw, (1135, 410, 1515, 800), "右")


def draw(image: Image.Image, t: float, tl: Timeline) -> None:
    if t < tl.gs(11, 0):
        name = "avl-single-left.webm"
        last = len(avl_engine._source_frames(name)) - 1
        gravity_start, gravity_end = tl.segment_window("new", "imagery", 11)
        if t < tl.gs(10, 0):
            # 问句与“重端下沉、抬起”叙述期：同一段动作拉伸播完，不定格。
            draw_source_media(image, name, t, tl.gs(8, 0), loop=False,
                              play_duration=tl.gs(10, 0) - tl.gs(8, 0))
        elif t < gravity_start:
            draw_source_media(image, name, t, tl.gs(8, 0), loop=False, frame_index=last)
            if tl.gs(10, 0) <= t:
                _mark_left_middle_right(image, t - tl.gs(10, 0))
        elif t < gravity_end:
            # “中间货物滑向倾斜一边”：重放滑落段，不再定格。
            frac = (t - gravity_start) / (gravity_end - gravity_start)
            index = int(last * (0.40 + 0.35 * frac))
            draw_source_media(image, name, t, tl.gs(8, 0), loop=False,
                              frame_index=min(index, last))
        else:
            draw_source_media(image, name, t, tl.gs(8, 0), loop=False, frame_index=last)
    elif t < tl.gs(12, 0):
        draw_source_media(
            image,
            "avl-example-left-rotation.webm",
            t,
            tl.gs(11, 0),
            loop=False,
            source_caption=True,
        )
    else:
        # After the first demonstration, reset to the initial tree for the
        # spoken analysis. Replay only when B is moved toward C.
        first_dur = 7.666666666666667
        first_end = tl.gs(12, 0) + first_dur
        analysis_start = tl.gs(12, 7)
        replay_start = tl.gs(13, 2)
        if t < first_end:
            draw_source_media(
                image,
                "avl-right-rotation.webm",
                t,
                tl.gs(12, 0),
                loop=False,
                source_caption=True,
            )
        elif t < analysis_start:
            draw_source_media(
                image,
                "avl-right-rotation.webm",
                first_end,
                tl.gs(12, 0),
                loop=False,
                source_caption=True,
            )
        elif t < replay_start:
            draw_source_media(
                image,
                "avl-right-rotation.webm",
                analysis_start,
                analysis_start,
                loop=False,
                source_caption=True,
            )
        else:
            draw_source_media(
                image,
                "avl-right-rotation.webm",
                t,
                replay_start,
                loop=False,
                source_caption=True,
            )

    if t >= tl.gs(8, 0):
        draw_corner_label(image, "例子一")


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import engine

    tl = engine.prepare()
    engine.register(SCENE_ID, draw)
    t0, t1 = engine.scene_span(SCENE_ID)
    out_dir = engine.OUTPUT_DIR / "preview" / SCENE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    for i in range(8):
        when = t0 + (t1 - t0) * (i + 0.5) / 8
        engine.render_frame(when).save(out_dir / f"{i}.png")
    print(f"{SCENE_ID}: {len(list(out_dir.glob('*.png')))} previews -> {out_dir}")
