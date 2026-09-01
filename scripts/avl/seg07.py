"""AVL recap segment seg07 (scene s6-delete)."""
from PIL import Image

from engine import *  # noqa: F401,F403


SCENE_ID = "s6-delete"

# avl-delete-to-root.webm frame anchors (30fps, 919 frames total):
#   0-89 initial still, 90-134 delete fade, 135-224 still "first imbalance 70",
# 225-372 rotation at 70, 373-462 check 59, 463-552 check 36,
# 553-642 root-80 second imbalance, 643-798 root rotation, 799-918 final.
ROOT_FRAMES = {
    "init": 20,
    "fade": (90, 134),
    "still70": 135,
    "rot70": (225, 372),
    "still59": 418,
    "still36": 508,
    "still80": 598,
}


def _extra_frame_index(t: float, tl: Timeline) -> int | None:
    """Map the extra recording's spoken windows onto the webm's phases."""
    s2 = tl.gs(22, 1)  # “删除 64 后，先在 70 处调整…”
    s3 = tl.gs(22, 2)  # “继续检查 59、36，直到根 80…”
    fade_start, fade_end = ROOT_FRAMES["fade"]
    rot_start, rot_end = ROOT_FRAMES["rot70"]
    if t < s2 + 0.20:
        return ROOT_FRAMES["init"]
    if t < s2 + 1.80:
        progress = (t - (s2 + 0.20)) / 1.60
        return fade_start + int(progress * (fade_end - fade_start))
    if t < s2 + 2.00:
        return ROOT_FRAMES["still70"]
    if t < s2 + 4.60:
        progress = (t - (s2 + 2.00)) / 2.60
        return rot_start + int(progress * (rot_end - rot_start))
    if t < s3 + 0.84:
        return rot_end
    if t < s3 + 1.66:
        return ROOT_FRAMES["still59"]
    if t < s3 + 3.40:
        return ROOT_FRAMES["still36"]
    return ROOT_FRAMES["still80"]


def draw(image: Image.Image, t: float, tl: Timeline) -> None:
    example_start = tl.gs(21, 0)
    extra_start = tl.gs(22, 0)
    if t < example_start:
        # The rule narration stays on one continuous flow diagram; the spoken
        # sentence shows as the working caption, no page switching.
        draw_source_media(
            image,
            "avl-delete-height-flow.svg",
            t,
            tl.gs(20, 0),
            loop=False,
            source_caption=True,
            max_width=1450,
            max_height=780,
            x_center=960,
            y_center=560,
        )
        return
    if t < extra_start:
        # 三个例子的叙述共 54.7s；把 77s 的源动画拉伸到整个叙述窗，
        # 让每个例子大致落在它的口播段里，而不是提前放完。
        draw_source_media(
            image,
            "avl-delete.webm",
            t,
            example_start,
            loop=False,
            source_caption=True,
            play_duration=extra_start - example_start,
            x_center=960,
        )
        return
    draw_source_media(
        image,
        "avl-delete-to-root.webm",
        t,
        extra_start,
        loop=False,
        source_caption=True,
        frame_index=_extra_frame_index(t, tl),
        x_center=960,
    )


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
