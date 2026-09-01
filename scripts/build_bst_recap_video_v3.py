#!/usr/bin/env python3
"""Build the final BST recap video from the current narration takes."""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ENGINE_SCRIPT = Path(__file__).with_name("_bst_recap_engine.py")
spec = importlib.util.spec_from_file_location("bst_recap_engine", ENGINE_SCRIPT)
if spec is None or spec.loader is None:
    raise ImportError(ENGINE_SCRIPT)
v1 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v1
spec.loader.exec_module(v1)


OUTPUT_DIR = ROOT / "outputs" / "bst-recap-v3"

# V2 keeps the V1 palette, but uses a slightly clearer hierarchy and less
# expansive glow so the existing nodes and relationships read more cleanly.
BLACK = v1.BLACK
WHITE = v1.WHITE
SOFT_WHITE = v1.SOFT_WHITE
SKY_BLUE = v1.SKY_BLUE
GLOW_BLUE = v1.GLOW_BLUE
GLOW_WHITE = v1.GLOW_WHITE
GLOW_RED = v1.GLOW_RED
GREEN = v1.GREEN
GOLD = v1.GOLD
RED = v1.RED
INK = v1.INK
MUTED_INK = v1.MUTED_INK


def draw_header(draw: ImageDraw.ImageDraw, title: str = "二叉搜索树") -> None:
    v1.line(draw, (120, 54), (120, 98), SKY_BLUE, 4)
    v1.draw_text(draw, (142, 76), title, size=30, family="sans", anchor="lm")


def draw_section_label(
    draw: ImageDraw.ImageDraw,
    xy: v1.Point,
    text: str,
    *,
    color: tuple[int, int, int] = WHITE,
    size: int = 30,
) -> None:
    v1.draw_text(draw, xy, text, size=size, fill=color, family="sans")


def draw_node(
    draw: ImageDraw.ImageDraw,
    point: v1.Point,
    key: str,
    *,
    color: tuple[int, int, int] = GLOW_BLUE,
    opacity: float = 1.0,
    radius: float = 43.0,
    halo: tuple[int, int, int] | None = None,
    fill: tuple[int, int, int] = v1.NODE_FILL,
    key_size: int = 30,
) -> None:
    """Use the same square node, with a tighter existing glow treatment."""
    x, y = point
    size = radius * 2.0
    glow = halo or color
    for grow, share in ((18.0, 0.10), (11.0, 0.16), (6.0, 0.28), (3.0, 0.50)):
        draw.rounded_rectangle(
            (
                round(x - radius - grow),
                round(y - radius - grow),
                round(x + radius + grow),
                round(y + radius + grow),
            ),
            radius=round(28 + grow / 2),
            fill=v1.blend(glow, opacity * share),
        )
    draw.rounded_rectangle(
        (round(x - radius), round(y - radius), round(x + radius), round(y + radius)),
        radius=round(size * 0.20),
        fill=v1.blend(fill, opacity),
        outline=v1.blend(v1.NODE_RIM, opacity),
        width=max(2, round(size * 0.035)),
    )
    if halo == GLOW_RED:
        draw.rounded_rectangle(
            (round(x - radius - 10), round(y - radius - 10), round(x + radius + 10), round(y + radius + 10)),
            radius=round(size * 0.25),
            outline=v1.blend(GLOW_RED, opacity),
            width=4,
        )
    v1.draw_text(draw, (x, y + 1), key, size=key_size, fill=v1.blend(INK, opacity), family="mono")


def draw_tree(
    draw: ImageDraw.ImageDraw,
    positions: dict[str, v1.Point],
    edges: tuple[v1.Edge, ...],
    *,
    edge_color: tuple[int, int, int] = INK,
    node_color: tuple[int, int, int] = GLOW_BLUE,
    opacity: float = 1.0,
    active_nodes: tuple[str, ...] = (),
    active_edges: tuple[v1.Edge, ...] = (),
    active_color: tuple[int, int, int] = GLOW_WHITE,
    radius: float = 43.0,
    key_size: int = 30,
) -> None:
    active_nodes_set = set(active_nodes)
    active_edges_set = {frozenset(edge) for edge in active_edges}
    for parent, child in edges:
        start, end = v1.trimmed_segment(positions[parent], positions[child], radius)
        active = frozenset((parent, child)) in active_edges_set
        color = active_color if active else edge_color
        v1.line(draw, start, end, v1.blend(color, opacity), 8 if not active else 10)
    for key, point in positions.items():
        active = key in active_nodes_set
        draw_node(
            draw,
            point,
            key,
            color=active_color if active else node_color,
            opacity=opacity,
            radius=radius,
            halo=active_color if active else None,
            key_size=key_size,
        )


BALANCED = {
    "20": (960.0, 305.0),
    "10": (670.0, 500.0),
    "30": (1250.0, 500.0),
    "25": (1110.0, 705.0),
    "40": (1390.0, 705.0),
}
BALANCED_EDGES = v1.BALANCED_EDGES

ORIGINAL_QUEUE = {key: (400.0 + index * 373.0, 330.0) for index, key in enumerate(v1.ORIGINAL_KEYS)}
ORIGINAL_FINAL = {
    "10": (520.0, 250.0),
    "20": (810.0, 455.0),
    "30": (1100.0, 660.0),
    "40": (1390.0, 865.0),
}
ORIGINAL_EDGE_BY_KEY = v1.ORIGINAL_EDGE_BY_KEY


def draw_title_scene(image: Image.Image, t: float) -> None:
    draw = ImageDraw.Draw(image)
    if t < v1.INTRO_END:
        title = "AVL 树  ·  B 树  ·  红黑树"
        subtitle = "接下来几个视频的介绍"
    else:
        title = "二叉搜索树"
        subtitle = "有序    查询    退化"
    v1.draw_text(draw, (960, 405), title, size=86 if t >= v1.INTRO_END else 68, family="sans")
    v1.line(draw, (820, 500), (1100, 500), SKY_BLUE, 5)
    v1.draw_text(draw, (960, 580), subtitle, size=36, fill=MUTED_INK, family="sans")


def draw_ordered_scene(image: Image.Image, t: float) -> None:
    draw = ImageDraw.Draw(image)
    draw_header(draw)
    draw_section_label(draw, (960, 155), "有序的二叉树", color=WHITE, size=42)
    draw_tree(draw, BALANCED, BALANCED_EDGES)
    v1.draw_text(draw, (960, 895), "有序", size=34, fill=WHITE, family="sans")


def draw_query_scene(image: Image.Image, t: float) -> None:
    draw = ImageDraw.Draw(image)
    draw_header(draw)
    draw_section_label(draw, (960, 155), "有序  →  查询", color=WHITE, size=42)
    progress = v1.clamp((t - v1.QUERY_ROUTE_START) / (v1.EFFICIENT_SHAPE_START - v1.QUERY_ROUTE_START))
    route = (("20", "30"), ("30", "25"))
    active_count = min(2, int(progress * 2.2) + 1)
    active_edges = route[:active_count]
    active_nodes = ["20"]
    if progress > 0.25:
        active_nodes.append("30")
    if progress > 0.72:
        active_nodes.append("25")
    draw_tree(draw, BALANCED, BALANCED_EDGES, active_nodes=tuple(active_nodes), active_edges=active_edges)
    if progress > 0.72:
        v1.draw_text(draw, (1110, 705), "25", size=30, fill=INK, family="mono")
    v1.draw_text(draw, (960, 895), "查询路径逐步缩短", size=30, fill=MUTED_INK, family="sans")


def draw_efficiency_scene(image: Image.Image, t: float) -> None:
    draw = ImageDraw.Draw(image)
    draw_header(draw)
    draw_section_label(draw, (960, 155), "树形使它在数据合适的情况下可以高效查询", color=INK, size=34)
    draw_tree(draw, BALANCED, BALANCED_EDGES, active_nodes=("20", "30", "25"), active_edges=(("20", "30"), ("30", "25")))
    v1.draw_height_marker(draw, 410, 305, 705, "树形", WHITE)
    v1.draw_text(draw, (960, 895), "高效查询", size=38, fill=WHITE, family="sans")


def draw_chain_static_scene(image: Image.Image) -> None:
    draw = ImageDraw.Draw(image)
    draw_header(draw)
    draw_section_label(draw, (960, 145), "普通二叉搜索树就会退化成链", color=GLOW_RED, size=42)
    for key in v1.ORIGINAL_KEYS:
        draw_node(draw, ORIGINAL_QUEUE[key], key, color=GLOW_BLUE, halo=GLOW_BLUE, radius=45, key_size=31)


def draw_chain_animation(image: Image.Image, local: float) -> None:
    draw = ImageDraw.Draw(image)
    draw_header(draw)
    draw_section_label(draw, (960, 145), "普通二叉搜索树就会退化成链", color=GLOW_RED, size=42)
    progress = v1.clamp((local - v1.CHAIN_ANIMATION_START) / v1.CHAIN_ANIMATION_DURATION)
    phase = progress * v1.ORIGINAL_ANIMATION_DURATION
    inserted = 0
    current_index = 0
    current_key: str | None = None
    for index, key in enumerate(v1.ORIGINAL_KEYS):
        move_start = 0.4 + index * 1.4
        move_end = move_start + 1.0
        if phase < move_start:
            current_index = index
            break
        if phase < move_end:
            current_index = index
            current_key = key
            break
        inserted = index + 1
        current_index = min(index + 1, len(v1.ORIGINAL_KEYS) - 1)
    else:
        inserted = len(v1.ORIGINAL_KEYS)
        current_index = len(v1.ORIGINAL_KEYS) - 1
    positions: dict[str, v1.Point] = {}
    for index, key in enumerate(v1.ORIGINAL_KEYS):
        if index < inserted:
            positions[key] = ORIGINAL_FINAL[key]
        elif index == current_index and phase < v1.ORIGINAL_ANIMATION_DURATION:
            move_start = 0.4 + index * 1.4
            move_progress = v1.clamp((phase - move_start) / 1.0)
            positions[key] = v1.lerp_point(ORIGINAL_QUEUE[key], ORIGINAL_FINAL[key], v1.ease(move_progress))
        else:
            positions[key] = ORIGINAL_QUEUE[key]
    for edge in ORIGINAL_EDGE_BY_KEY.values():
        if edge[0] in positions and edge[1] in positions and (edge[1] in v1.ORIGINAL_KEYS[:inserted] or edge[1] == current_key):
            start, end = v1.trimmed_segment(positions[edge[0]], positions[edge[1]], 54)
            v1.line(draw, start, end, INK, 8)
    for key in v1.ORIGINAL_KEYS:
        active = key == current_key
        draw_node(draw, positions[key], key, color=GLOW_WHITE if active else GLOW_BLUE, halo=GLOW_WHITE if active else GLOW_BLUE, radius=45, key_size=31)
    if inserted >= 4:
        v1.draw_text(draw, (960, 980), "退化成链", size=44, fill=GLOW_RED, family="sans")


def draw_height_compare_scene(image: Image.Image, local: float) -> None:
    draw = ImageDraw.Draw(image)
    draw_header(draw)
    draw_section_label(draw, (960, 150), "树高从原本希望的对数级，变成线性级", color=WHITE, size=43)
    left = v1.small_balanced_positions(550.0, 355.0, 0.84)
    draw_tree(draw, left, (("20", "10"), ("20", "30"), ("30", "40")), edge_color=GREEN, node_color=GREEN, radius=36, key_size=25)
    v1.draw_height_marker(draw, 350, 355, 557, "对数级", WHITE)
    v1.draw_text(draw, (550, 745), "合适的树形", size=32, fill=SOFT_WHITE, family="serif")
    right = {"10": (1260.0, 300.0), "20": (1420.0, 485.0), "30": (1580.0, 670.0), "40": (1740.0, 855.0)}
    draw_tree(draw, right, v1.CHAIN_EDGES, edge_color=RED, node_color=RED, radius=36, key_size=25)
    v1.draw_height_marker(draw, 1840, 300, 855, "线性级", RED)
    v1.draw_text(draw, (1475, 950), "退化后的树形", size=32, fill=SOFT_WHITE, family="serif")


def draw_route_text_scene(image: Image.Image) -> None:
    draw = ImageDraw.Draw(image)
    draw_header(draw)
    lines = v1.ROUTE_TEXT.expandtabs(4).splitlines()
    size = 31
    line_height = 52
    max_width = max(v1.draw_text_width(line, size, "mono-cjk") for line in lines)
    start_x = max(92.0, (v1.WIDTH - max_width) / 2.0)
    start_y = 180.0
    for index, text in enumerate(lines):
        v1.draw_text(draw, (start_x, start_y + index * line_height), text, size=size, fill=INK, family="mono-cjk", anchor="lm")


def render_frame(t: float, first_duration: float, total_duration: float) -> Image.Image:
    image = Image.new("RGB", (v1.WIDTH, v1.HEIGHT), BLACK)
    # Open on the ordered-tree frame and hold it through the course-intro
    # narration and the BST definition; the first motion begins with lookup.
    if t < v1.QUERY_ROUTE_START:
        draw_ordered_scene(image, t)
    elif t < v1.EFFICIENT_SHAPE_START:
        draw_query_scene(image, t)
    elif t < v1.CHAIN_STATIC_START:
        draw_efficiency_scene(image, t)
    elif t < v1.CHAIN_ANIMATION_START:
        draw_chain_static_scene(image)
    else:
        local = t
        if local < v1.CHAIN_ANIMATION_END:
            draw_chain_animation(image, local)
        elif local < v1.ROUTE_TEXT_START:
            draw_height_compare_scene(image, local)
        else:
            draw_route_text_scene(image)
    return image


def main() -> None:
    # Reuse the validated media pipeline while supplying the final renderer.
    v1.assert_inputs()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    durations = [v1.probe_duration(path) for path in v1.AUDIO_FILES]
    total_duration = sum(durations)
    subtitles = v1.make_subtitles(durations[0])
    output_video = OUTPUT_DIR / "bst-recap-v3.mp4"
    output_audio = OUTPUT_DIR / "narration-concat.wav"
    output_srt = OUTPUT_DIR / "bst-recap-v3.srt"
    output_timeline = OUTPUT_DIR / "bst-recap-v3-timeline.json"
    v1.write_srt(output_srt, subtitles)
    v1.write_timeline(output_timeline, subtitles, durations)
    concat_duration = v1.concat_audio(output_audio)
    if abs(concat_duration - total_duration) > 0.05:
        raise RuntimeError(f"Concatenated audio duration drift: {concat_duration} vs {total_duration}")
    original_render = v1.render_frame
    v1.render_frame = render_frame
    try:
        v1.encode_video(output_video, output_audio, concat_duration, durations[0])
    finally:
        v1.render_frame = original_render
    print(output_video)
    print(output_srt)
    print(output_timeline)
    print(f"duration={concat_duration:.6f}s frames={math.ceil(concat_duration * v1.FPS)}")


if __name__ == "__main__":
    main()
