#!/usr/bin/env python3
"""Generate transparent tree diagrams and WebM motion media for the notes."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, hypot, pi, sin
from pathlib import Path
from shutil import copyfile, which
from subprocess import run
from tempfile import TemporaryDirectory
from typing import Collection, Iterable, Mapping, Sequence, TypeAlias

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
WIDTH = 900
HEIGHT = 620
RADIUS = 28.0
SKY_BLUE = "#38BDF8"
INK = "#F8FAFC"
NODE_FILL = "#3B5BA5"
NODE_RIM = "#8FA9E8"
GLOW_BLUE = "#A3BCF7"
GLOW_WHITE = "#FFFFFF"
GLOW_RED = "#FF7070"
GLOW_ORANGE = "#FFA94D"
AVL_NODE_SIZE = 44.0
AVL_INSERT_W = 1380
AVL_INSERT_H = 700
AVL_INSERT_TOP = 118.0
AVL_QUEUE_Y = 62.0
AVL_INSERT_MIN_STEP_FRAMES = 75
AVL_CAPTION_X = 260.0
AVL_CAPTION_TOP = 122.0
Snapshot: TypeAlias = tuple[int, dict[int, tuple[int | None, int | None]]]

AVL_INSERT_CAPTIONS = (
    "变成根。",
    "挂在 1 的右边。",
    "1 的右子树沉，天平是 1—3，旋转完成修复。",
    "沿搜索路径落在 7 的左边，没有破坏平衡。",
    "7 的左边沉，旋转完成修复。注意找哪棵树不平衡的时候是向上找最近的一棵树。",
    "3 的右边沉，先判断天平是 3—6；再判断是中间失衡，小天平是 4—6，先右旋转化成两边失衡，再正常调整。",
    "以 3 为根的这棵树。右边是空，所以它失衡；在判断时中间失衡，两步调整。",
    "沿搜索路径挂在 1 的左边，不动。",
    "1 的左边沉，天平是 1—0；左边失衡。",
    "2 的左边沉，天平是 2—0；左边失衡。",
)


def avl_queue_slot(index: int, total: int) -> Point:
    """Slot for the i-th pending key in the top waiting row."""
    span = AVL_INSERT_W - 200.0
    if total <= 1:
        return (AVL_INSERT_W / 2, AVL_QUEUE_Y)
    return (100.0 + span * index / (total - 1), AVL_QUEUE_Y)


def bloom_square(cx: float, cy: float, size: float, color: str, opacity: float) -> str:
    """Layered rounded squares faking a neon halo; no SVG filters needed."""
    parts = []
    for grow, share in ((13.0, 0.10), (8.0, 0.16), (4.5, 0.28), (2.0, 0.50)):
        parts.append(
            f'<rect x="{cx - size / 2 - grow:.1f}" y="{cy - size / 2 - grow:.1f}" '
            f'width="{size + 2 * grow:.1f}" height="{size + 2 * grow:.1f}" rx="15" '
            f'fill="{color}" opacity="{opacity * share:.3f}"/>'
        )
    return "".join(parts)


def glow_square(
    key: str,
    point: Point,
    *,
    opacity: float = 1.0,
    glow: str = GLOW_BLUE,
    fill: str = NODE_FILL,
    rim: str = NODE_RIM,
    ink: str = INK,
    size: float = AVL_NODE_SIZE,
    show_text: bool = True,
) -> str:
    cx, cy = point
    half = size / 2.0
    body = bloom_square(cx, cy, size, glow, opacity)
    body += (
        f'<rect x="{cx - half:.1f}" y="{cy - half:.1f}" width="{size:.1f}" height="{size:.1f}" '
        f'rx="9" fill="{fill}" stroke="{rim}" stroke-width="1.6" opacity="{opacity:.3f}"/>'
    )
    if show_text:
        body += (
            f'<text x="{cx:.1f}" y="{cy + 1.0:.1f}" style="fill:{ink}" fill="{ink}" font-weight="600" '
            f'font-family="Noto Sans CJK SC,system-ui,sans-serif" font-size="18" '
            f'text-anchor="middle" dominant-baseline="middle" opacity="{opacity:.3f}">{esc(key)}</text>'
        )
    return body


def triangle_points(point: Point, size: float) -> tuple[Point, Point, Point]:
    """Return an upright triangle whose apex is the folded subtree root."""
    cx, cy = point
    half_width = size * 0.25
    return (
        (cx, cy),
        (cx - half_width, cy + size),
        (cx + half_width, cy + size),
    )


def glow_triangle(
    point: Point,
    size: float,
    *,
    opacity: float = 1.0,
    glow: str = GLOW_BLUE,
    rim: str = NODE_RIM,
) -> str:
    """Draw a hollow triangle for a folded subtree; its interior stays transparent."""
    points = triangle_points(point, size)
    point_text = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    body = ""
    for extra, share, width in ((9.0, 0.15, 8.0), (4.0, 0.28, 5.0)):
        expanded = triangle_points(point, size + extra)
        expanded_text = " ".join(f"{x:.1f},{y:.1f}" for x, y in expanded)
        body += (
            f'<polygon points="{expanded_text}" fill="none" stroke="{glow}" '
            f'stroke-width="{width:.1f}" stroke-linejoin="round" opacity="{opacity * share:.3f}"/>'
        )
    body += (
        f'<polygon points="{point_text}" fill="none" stroke="{rim}" stroke-width="2.2" '
        f'stroke-linejoin="round" opacity="{opacity:.3f}"/>'
    )
    return body


def ray_segment_intersection(origin: Point, direction: Point, start: Point, end: Point) -> Point | None:
    edge = (end[0] - start[0], end[1] - start[1])
    denominator = direction[0] * edge[1] - direction[1] * edge[0]
    if abs(denominator) < 1e-9:
        return None
    offset = (start[0] - origin[0], start[1] - origin[1])
    distance = (offset[0] * edge[1] - offset[1] * edge[0]) / denominator
    along_edge = (offset[0] * direction[1] - offset[1] * direction[0]) / denominator
    if distance < 0.0 or not 0.0 <= along_edge <= 1.0:
        return None
    return origin[0] + direction[0] * distance, origin[1] + direction[1] * distance


def triangle_boundary(center: Point, toward: Point, size: float) -> Point:
    direction = (toward[0] - center[0], toward[1] - center[1])
    if direction == (0.0, 0.0):
        return center
    points = triangle_points(center, size)
    intersections = [
        intersection
        for start, end in zip(points, points[1:] + points[:1])
        if (intersection := ray_segment_intersection(center, direction, start, end)) is not None
    ]
    return min(
        intersections,
        key=lambda point: (point[0] - center[0]) ** 2 + (point[1] - center[1]) ** 2,
    ) if intersections else center


def avl_edge_endpoints(
    left: Point,
    right: Point,
    left_key: str,
    right_key: str,
    collapsed_triangles: Mapping[str, float] | None,
) -> tuple[float, float, float, float]:
    """Connect ordinary nodes and hollow triangles at their visible boundaries."""
    left_size = (collapsed_triangles or {}).get(left_key)
    right_size = (collapsed_triangles or {}).get(right_key)
    left_end = triangle_boundary(left, right, left_size) if left_size else endpoints(left, right, radius=21.0)[:2]
    right_end = triangle_boundary(right, left, right_size) if right_size else endpoints(right, left, radius=21.0)[:2]
    return left_end[0], left_end[1], right_end[0], right_end[1]


def glow_line(
    a: Point,
    b: Point,
    *,
    opacity: float = 1.0,
    color: str = INK,
    width: float = 3.4,
    bloom: str | None = None,
    radius: float = 21.0,
) -> str:
    x1, y1, x2, y2 = endpoints(a, b, radius=radius)
    out = ""
    if bloom is not None:
        out += (
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{bloom}" '
            f'stroke-width="{width + 8:.1f}" stroke-linecap="round" opacity="{opacity * 0.22:.3f}"/>'
        )
        out += (
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{bloom}" '
            f'stroke-width="{width + 3.5:.1f}" stroke-linecap="round" opacity="{opacity * 0.40:.3f}"/>'
        )
    out += (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" '
        f'stroke-width="{width:.1f}" stroke-linecap="round" opacity="{opacity:.3f}"/>'
    )
    return out


def glow_ring(point: Point, *, color: str = GLOW_RED, opacity: float = 1.0, extra: float = 7.0) -> str:
    """Neon halo drawn just outside a square node."""
    cx, cy = point
    half = AVL_NODE_SIZE / 2.0 + extra
    out = ""
    for grow, share in ((11.0, 0.13), (6.0, 0.22), (2.5, 0.42)):
        out += (
            f'<rect x="{cx - half - grow:.1f}" y="{cy - half - grow:.1f}" '
            f'width="{2 * (half + grow):.1f}" height="{2 * (half + grow):.1f}" rx="17" '
            f'fill="none" stroke="{color}" stroke-width="3.0" opacity="{opacity * share:.3f}"/>'
        )
    out += (
        f'<rect x="{cx - half:.1f}" y="{cy - half:.1f}" width="{2 * half:.1f}" height="{2 * half:.1f}" '
        f'rx="14" fill="none" stroke="{color}" stroke-width="3.0" opacity="{opacity:.3f}"/>'
    )
    return out
Point = tuple[float, float]
Edge = tuple[str, str]
Children = Mapping[str, tuple[str | None, str | None]]


def esc(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pair(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left <= right else (right, left)


def endpoints(start: Point, end: Point, radius: float = RADIUS) -> tuple[float, float, float, float]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    distance = hypot(dx, dy)
    if distance == 0:
        return start[0], start[1], end[0], end[1]
    return (
        start[0] + dx * radius / distance,
        start[1] + dy * radius / distance,
        end[0] - dx * radius / distance,
        end[1] - dy * radius / distance,
    )


def svg(body: str, *, width: int = WIDTH, height: int = HEIGHT, color: str = "#000", view_box: str | None = None) -> str:
    vb = view_box or f"0 0 {width} {height}"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="{vb}">
  <style>
    text{{font-family:"Noto Sans CJK SC",system-ui,sans-serif;fill:{color};text-anchor:middle;dominant-baseline:middle}}
    .edge{{stroke:{color};stroke-width:3;stroke-linecap:round}}.focus-edge{{stroke:{color};stroke-width:7;stroke-linecap:round}}
    .node{{fill:none;stroke:{color};stroke-width:3}}.focus-node{{stroke-width:7}}.detached{{stroke-dasharray:8 5}}
    .red-edge{{stroke:{color};stroke-width:4;stroke-linecap:round;stroke-dasharray:8 5}}.red-node{{fill:none;stroke:{color};stroke-width:4;stroke-dasharray:8 5}}
    .key{{font-size:21px}}.bkey{{font-size:19px}}.empty{{font-size:17px}}
  </style>
  {body}
</svg>'''


def node(key: str, point: Point, *, focus: bool = False, detached: bool = False, red: bool = False) -> str:
    classes = ["red-node" if red else "node"]
    if focus and not red:
        classes.append("focus-node")
    if detached:
        classes.append("detached")
    x, y = point
    return f'<circle class="{" ".join(classes)}" cx="{x:.1f}" cy="{y:.1f}" r="{RADIUS:.1f}"/><text class="key" x="{x:.1f}" y="{y:.1f}">{esc(key)}</text>'


def binary_edges(
    positions: Mapping[str, Point],
    edges: Iterable[Edge],
    *,
    focus: Iterable[Edge] = (),
    red: Iterable[Edge] = (),
) -> str:
    focus_pairs = {pair(a, b) for a, b in focus}
    red_pairs = {pair(a, b) for a, b in red}
    result: list[str] = []
    for left, right in edges:
        x1, y1, x2, y2 = endpoints(positions[left], positions[right])
        style = "red-edge" if pair(left, right) in red_pairs else "focus-edge" if pair(left, right) in focus_pairs else "edge"
        result.append(f'<line class="{style}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')
    return "".join(result)


def binary_frame(
    positions: Mapping[str, Point],
    edges: Iterable[Edge],
    *,
    focus_nodes: Iterable[str] = (),
    focus_edges: Iterable[Edge] = (),
    detached: Iterable[str] = (),
    red_nodes: Iterable[str] = (),
    red_edges: Iterable[Edge] = (),
    nil_double_black: Point | None = None,
    color: str = "#000",
    width: int = WIDTH,
    height: int = HEIGHT,
) -> str:
    focus = set(focus_nodes)
    detached_set = set(detached)
    red_set = set(red_nodes)
    body = binary_edges(positions, edges, focus=focus_edges, red=red_edges)
    body += "".join(
        node(key, point, focus=key in focus, detached=key in detached_set, red=key in red_set)
        for key, point in positions.items()
    )
    if nil_double_black is not None:
        x, y = nil_double_black
        body += f'<circle class="node" cx="{x:.1f}" cy="{y:.1f}" r="{RADIUS:.1f}"/><circle class="node" cx="{x:.1f}" cy="{y:.1f}" r="{RADIUS - 7:.1f}"/><text class="empty" x="{x:.1f}" y="{y:.1f}">NIL</text>'
    return svg(body, width=width, height=height, color=color)


def crop_transparent_frames(frame_dir: Path, pad: int = 0) -> None:
    bbox: tuple[int, int, int, int] | None = None
    frame_paths = sorted(frame_dir.glob("frame-*.png"))
    for path in frame_paths:
        with Image.open(path) as image:
            current = image.convert("RGBA").getchannel("A").getbbox()
        if current is None:
            continue
        if bbox is None:
            bbox = current
        else:
            bbox = (
                min(bbox[0], current[0]),
                min(bbox[1], current[1]),
                max(bbox[2], current[2]),
                max(bbox[3], current[3]),
            )
    if bbox is None:
        return
    left, top, right, bottom = bbox
    if pad:
        with Image.open(frame_paths[0]) as image:
            width, height = image.size
        left = max(0, left - pad)
        top = max(0, top - pad)
        right = min(width, right + pad)
        bottom = min(height, bottom + pad)
    if (right - left) % 2:
        right += 1
    if (bottom - top) % 2:
        bottom += 1
    bbox = (left, top, right, bottom)
    for path in frame_paths:
        with Image.open(path) as image:
            image.convert("RGBA").crop(bbox).save(path)


def inorder_layout(root: str, children: Children, *, x_start: float = 120.0, x_end: float = 780.0, y_start: float = 105.0, y_step: float = 115.0) -> dict[str, Point]:
    order: list[str] = []

    def visit(key: str | None) -> None:
        if key is None:
            return
        left, right = children.get(key, (None, None))
        visit(left)
        order.append(key)
        visit(right)

    visit(root)
    x_by_key = {
        key: x_start + (x_end - x_start) * index / max(1, len(order) - 1)
        for index, key in enumerate(order)
    }
    result: dict[str, Point] = {}

    def place(key: str | None, depth: int) -> None:
        if key is None:
            return
        result[key] = (float(x_by_key[key]), y_start + y_step * depth)
        left, right = children.get(key, (None, None))
        place(left, depth + 1)
        place(right, depth + 1)

    place(root, 0)
    return result


def tree_frame(
    root: str,
    children: Children,
    *,
    focus_nodes: Iterable[str] = (),
    focus_edges: Iterable[Edge] = (),
    detached: Iterable[str] = (),
    red_nodes: Iterable[str] = (),
    red_edges: Iterable[Edge] = (),
    nil_double_black: Point | None = None,
) -> str:
    edges = [(parent, child) for parent, (left, right) in children.items() for child in (left, right) if child is not None]
    return binary_frame(
        inorder_layout(root, children),
        edges,
        focus_nodes=focus_nodes,
        focus_edges=focus_edges,
        detached=detached,
        red_nodes=red_nodes,
        red_edges=red_edges,
        nil_double_black=nil_double_black,
    )


def bnode(key: str, center: Point, keys: Sequence[str], *, dashed: bool = False) -> tuple[str, Point, Point]:
    width = max(72.0, 24.0 + 64.0 * len(keys))
    height = 46.0
    x, y = center
    left = x - width / 2
    top = y - height / 2
    dash = ' stroke-dasharray="8 5"' if dashed else ""
    content = [f'<rect class="node" x="{left:.1f}" y="{top:.1f}" width="{width:.1f}" height="{height:.1f}" rx="4"{dash}/>']
    for index, value in enumerate(keys):
        if index:
            divider = left + index * width / len(keys)
            content.append(f'<line class="edge" x1="{divider:.1f}" y1="{top:.1f}" x2="{divider:.1f}" y2="{top + height:.1f}"/>')
        key_x = left + (index + 0.5) * width / len(keys)
        content.append(f'<text class="bkey" x="{key_x:.1f}" y="{y:.1f}">{esc(value)}</text>')
    if not keys:
        content.append(f'<text class="empty" x="{x:.1f}" y="{y:.1f}">empty</text>')
    return "".join(content), (x, top), (x, top + height)


def btree_frame(nodes: Mapping[str, tuple[Point, Sequence[str], bool]], edges: Iterable[Edge]) -> str:
    rendered: dict[str, tuple[str, Point, Point]] = {
        key: bnode(key, center, keys, dashed=dashed)
        for key, (center, keys, dashed) in nodes.items()
    }
    lines: list[str] = []
    children_by_parent: dict[str, list[str]] = {}
    for parent, child in edges:
        children_by_parent.setdefault(parent, []).append(child)
    for parent, children in children_by_parent.items():
        center, keys, _ = nodes[parent]
        width = max(72.0, 24.0 + 64.0 * len(keys))
        left = center[0] - width / 2.0
        bottom = center[1] + 23.0
        for index, child in enumerate(children):
            ratio = index / max(1, len(children) - 1)
            start_x = left + width * ratio
            end = rendered[child][1]
            lines.append(f'<line class="edge" x1="{start_x:.1f}" y1="{bottom:.1f}" x2="{end[0]:.1f}" y2="{end[1]:.1f}"/>')
    return svg("".join(lines) + "".join(part[0] for part in rendered.values()), color=SKY_BLUE)


BTREE_NEON_CELL = AVL_NODE_SIZE
BTREE_NEON_CELL_W = 56.0
BTREE_NEON_CELL_H = 44.0
BTREE_NEON_SLOT = BTREE_NEON_CELL_W


def bloom_rect(
    center: Point,
    width: float,
    height: float,
    color: str,
    opacity: float = 1.0,
    *,
    radius: float = 9.0,
) -> str:
    cx, cy = center
    parts: list[str] = []
    for grow, share in ((13.0, 0.10), (8.0, 0.16), (4.5, 0.28), (2.0, 0.50)):
        parts.append(
            f'<rect x="{cx - width / 2 - grow:.1f}" y="{cy - height / 2 - grow:.1f}" '
            f'width="{width + 2 * grow:.1f}" height="{height + 2 * grow:.1f}" '
            f'rx="{radius + grow:.1f}" fill="{color}" opacity="{opacity * share:.3f}"/>'
        )
    return "".join(parts)


def btree_neon_slots(center: Point, count: int) -> list[Point]:
    return [
        (center[0] + (index - (count - 1) / 2.0) * BTREE_NEON_SLOT, center[1])
        for index in range(count)
    ]


def btree_neon_row(
    keys: Sequence[str],
    center: Point,
    *,
    overflow: bool = False,
    focus: Iterable[str] = (),
) -> tuple[str, list[Point]]:
    focus_keys = set(focus)
    slots = btree_neon_slots(center, len(keys))
    width = len(keys) * BTREE_NEON_CELL_W
    glow = GLOW_RED if overflow else GLOW_WHITE if focus_keys else GLOW_BLUE
    body = bloom_rect(center, width, BTREE_NEON_CELL_H, glow)
    left = center[0] - width / 2.0
    top = center[1] - BTREE_NEON_CELL_H / 2.0
    body += (
        f'<rect x="{left:.1f}" y="{top:.1f}" width="{width:.1f}" height="{BTREE_NEON_CELL_H:.1f}" '
        f'rx="9" fill="{NODE_FILL}" stroke="{NODE_RIM}" stroke-width="1.8"/>'
    )
    for index, key in enumerate(keys):
        if index:
            divider_x = left + index * BTREE_NEON_CELL_W
            body += (
                f'<line x1="{divider_x:.1f}" y1="{top:.1f}" x2="{divider_x:.1f}" '
                f'y2="{top + BTREE_NEON_CELL_H:.1f}" stroke="{INK}" stroke-width="2.2"/>'
            )
        if key in focus_keys:
            body += bloom_rect(
                slots[index],
                BTREE_NEON_CELL_W - 4.0,
                BTREE_NEON_CELL_H - 4.0,
                GLOW_WHITE,
                0.8,
                radius=6.0,
            )
        body += (
            f'<text x="{slots[index][0]:.1f}" y="{slots[index][1]:.1f}" fill="{INK}" '
            f'font-family="Noto Sans CJK SC,system-ui,sans-serif" font-size="18" '
            f'font-weight="600" text-anchor="middle" dominant-baseline="middle">{esc(key)}</text>'
        )
    return body, slots


def btree_neon_row_at_positions(
    keys: Sequence[str | int | None],
    positions: Sequence[Point],
    *,
    opacity: float = 1.0,
    overflow: bool = False,
    text_layers: Mapping[int, Sequence[tuple[str, float, str]]] | None = None,
    rim: str | None = None,
    font_size: float = 18.0,
) -> str:
    """Render a moving B-tree array as one tight body with shared dividers."""
    if not keys or len(keys) != len(positions):
        return ""
    left = min(point[0] for point in positions) - BTREE_NEON_CELL_W / 2.0
    right = max(point[0] for point in positions) + BTREE_NEON_CELL_W / 2.0
    width = right - left
    center = ((left + right) / 2.0, positions[0][1])
    glow = GLOW_RED if overflow else GLOW_BLUE
    if rim is not None:
        glow = rim
    body = bloom_rect(center, width, BTREE_NEON_CELL_H, glow, opacity)
    top = center[1] - BTREE_NEON_CELL_H / 2.0
    body += (
        f'<rect x="{left:.1f}" y="{top:.1f}" width="{width:.1f}" height="{BTREE_NEON_CELL_H:.1f}" '
        f'rx="9" fill="{NODE_FILL}" stroke="{rim or NODE_RIM}" stroke-width="1.8" opacity="{opacity:.3f}"/>'
    )
    for index, (key, point) in enumerate(zip(keys, positions)):
        if index:
            divider_x = (positions[index - 1][0] + positions[index][0]) / 2.0
            body += (
                f'<line x1="{divider_x:.1f}" y1="{top:.1f}" x2="{divider_x:.1f}" '
                f'y2="{top + BTREE_NEON_CELL_H:.1f}" stroke="{INK}" stroke-width="2.2" opacity="{opacity:.3f}"/>'
            )
        layers = text_layers.get(index) if text_layers else None
        if layers is None:
            layers = () if key is None else ((str(key), 1.0, INK),)
        for text, layer_opacity, color in layers:
            body += (
                f'<text x="{point[0]:.1f}" y="{point[1]:.1f}" fill="{color}" '
                f'font-family="Noto Sans CJK SC,system-ui,sans-serif" font-size="{font_size:.0f}" '
                f'font-weight="600" text-anchor="middle" dominant-baseline="middle" '
                f'opacity="{opacity * layer_opacity:.3f}">{esc(text)}</text>'
            )
    return body


def btree_neon_gap(center: Point, count: int, slot: int) -> Point:
    slots = btree_neon_slots(center, count)
    if slot == 0:
        x = slots[0][0] - BTREE_NEON_CELL_W / 2.0
    elif slot == count:
        x = slots[-1][0] + BTREE_NEON_CELL_W / 2.0
    else:
        x = (slots[slot - 1][0] + slots[slot][0]) / 2.0
    return (x, center[1] + BTREE_NEON_CELL / 2.0)


def btree_row_gap(points: Sequence[Point], slot: int) -> Point:
    """Return the lower edge point for one child slot of a moving row."""
    if slot == 0:
        x = points[0][0] - CELL_W / 2.0
    elif slot == len(points):
        x = points[-1][0] + CELL_W / 2.0
    else:
        x = (points[slot - 1][0] + points[slot][0]) / 2.0
    return (x, points[0][1])


def btree_neon_edge(start: Point, end: Point, *, focus: bool = False, opacity: float = 1.0) -> str:
    return glow_line(
        start,
        end,
        color=GLOW_WHITE if focus else INK,
        width=4.2 if focus else 3.4,
        bloom=GLOW_WHITE if focus else GLOW_BLUE,
        radius=0.0,
        opacity=opacity,
    )


def btree_node_states_svg() -> str:
    """Phase 1: one valid tree containing one-, two-, three-, and four-key states."""
    # Keep the node bloom clear of the player edge on compact viewports.
    root = (450.0, 130.0)
    leaves = ((90.0, 455.0), (265.0, 455.0), (440.0, 455.0), (702.5, 455.0))
    root_keys = ["30", "60", "90"]
    leaf_keys = (["10", "20"], ["40", "50"], ["70", "80"], ["100", "110", "120", "130"])
    body: list[str] = []
    root_body, _ = btree_neon_row(root_keys, root)
    leaf_bodies: list[str] = []
    for center, keys in zip(leaves, leaf_keys):
        leaf_body, _ = btree_neon_row(keys, center, overflow=len(keys) == 4)
        leaf_bodies.append(leaf_body)
    for slot, leaf_center in enumerate(leaves):
        body.append(btree_neon_edge(btree_neon_gap(root, len(root_keys), slot), (leaf_center[0], leaf_center[1] - BTREE_NEON_CELL / 2.0)))
    body.extend(leaf_bodies)
    body.append(root_body)
    return svg("".join(body), width=900, height=600, color=INK)


def btree_order_5_svg() -> str:
    """Show the maximum branching and minimum non-root capacity of order 5."""
    root = (550.0, 155.0)
    leaves = ((120.0, 445.0), (335.0, 445.0), (550.0, 445.0), (765.0, 445.0), (980.0, 445.0))
    root_keys = ["50", "100", "150", "200"]
    leaf_keys = (["10", "20"], ["60", "70"], ["110", "120"], ["160", "170"], ["210", "220"])
    body: list[str] = []
    for slot, leaf_center in enumerate(leaves):
        body.append(
            btree_neon_edge(
                btree_neon_gap(root, len(root_keys), slot),
                (leaf_center[0], leaf_center[1] - BTREE_NEON_CELL / 2.0),
            )
        )
    for center, keys in zip(leaves, leaf_keys):
        row, _ = btree_neon_row(keys, center)
        body.append(row)
    root_row, _ = btree_neon_row(root_keys, root)
    body.append(root_row)
    body.extend(
        [
            f'<text x="550" y="55" fill="{INK}" font-family="Noto Sans CJK SC,system-ui,sans-serif" '
            f'font-size="22" font-weight="600" text-anchor="middle">最多 4 个关键字，5 个孩子</text>',
            f'<text x="550" y="555" fill="{GLOW_WHITE}" font-family="Noto Sans CJK SC,system-ui,sans-serif" '
            f'font-size="20" text-anchor="middle">非根节点至少 2 个关键字；内部节点至少 3 个孩子</text>',
        ]
    )
    return svg("".join(body), width=1100, height=600, color=INK)


def btree_delete_cases_svg() -> str:
    """Show both deletion presentations with the same brace structure."""
    blue = GLOW_BLUE
    red = "#FCA5A5"
    white = INK
    bright = GLOW_WHITE

    def neon_brace(x: float, top: float, bottom: float, width: float = 28.0) -> str:
        span = bottom - top
        k = min(16.0, span * 0.30)
        d = min(9.0, span * 0.16)
        t = 7.0
        mid = (top + bottom) / 2.0
        path = (
            f"M {x + width:.1f} {top:.1f} "
            f"C {x + width * 0.45:.1f} {top:.1f} {x:.1f} {top + 5:.1f} {x:.1f} {top + k:.1f} "
            f"L {x:.1f} {mid - d:.1f} "
            f"C {x:.1f} {mid - d * 0.35:.1f} {x - t * 0.55:.1f} {mid - d * 0.15:.1f} {x - t:.1f} {mid:.1f} "
            f"C {x - t * 0.55:.1f} {mid + d * 0.15:.1f} {x:.1f} {mid + d * 0.35:.1f} {x:.1f} {mid + d:.1f} "
            f"L {x:.1f} {bottom - k:.1f} "
            f"C {x:.1f} {bottom - 5:.1f} {x + width * 0.45:.1f} {bottom:.1f} {x + width:.1f} {bottom:.1f}"
        )
        layers = ((10.5, 0.18), (5.5, 0.36), (2.8, 1.0))
        return "".join(
            f'<path d="{path}" fill="none" stroke="{blue}" stroke-width="{w}" '
            f'stroke-linecap="round" stroke-linejoin="round" opacity="{o}"/>'
            for w, o in layers
        )

    def label(x: float, y: float, content: str, size: int, color: str, *, halo: bool = False) -> str:
        style = f"fill:{color};text-anchor:start"
        weight = ' font-weight="600"' if halo else ""
        halo_opacity = 0.10 if color == bright else 0.18
        out = ""
        if halo:
            out += (
                f'<text x="{x}" y="{y}" font-size="{size}"{weight} stroke-linejoin="round" '
                f'stroke="{color}" stroke-width="{max(5.0, size * 0.36):.1f}" opacity="{halo_opacity}" '
                f'style="{style}">{content}</text>'
            )
        out += f'<text x="{x}" y="{y}" font-size="{size}"{weight} style="{style}">{content}</text>'
        return out

    body = [
        label(36, 40, "删除非叶结点元素最终都转换成删除", 21, bright, halo=True),
        label(382, 40, "叶结点元素", 21, red, halo=True),
        label(20, 147, "叶结点元素", 18, white),
        neon_brace(126, 96, 198),
        label(182, 106, "没有下溢", 18, white),
        label(286, 106, "无需调整", 18, red, halo=True),
        label(182, 188, "下溢", 18, white),
        neon_brace(232, 154, 222, 24),
        label(278, 164, "兄弟够借：", 17, white),
        label(396, 164, "借", 17, red, halo=True),
        label(278, 212, "兄弟不够借：", 17, white),
        label(396, 212, "合并", 17, red, halo=True),
        label(396, 241, "(可能导致父结点下溢)", 14, red),
        label(36, 288, "另一种版本：", 18, bright, halo=True),
        label(20, 386, "叶结点元素", 18, white),
        neon_brace(126, 332, 440),
        label(182, 342, "首领回家", 18, white),
        label(182, 386, "部落内删除", 18, white),
        label(182, 430, "重新推举首领", 18, red, halo=True),
    ]
    return svg("".join(body), width=580, height=456, color=INK)


def btree_search_svg() -> str:
    """Phase 2: the first diagram's nodes after the root split, with two lookup routes."""
    root = (550.0, 92.0)
    il = (310.0, 270.0)
    ir = (790.0, 270.0)

    def leaf(x: float) -> Point:
        return (x, 500.0)

    groups = {
        "root": (["90"], root, False, 1.0),
        "il": (["30", "60"], il, False, 1.0),
        "ir": (["120"], ir, False, 1.0),
        "g10": (["10", "20"], leaf(120), False, 1.0),
        "g4050": (["40", "50"], leaf(330), False, 1.0),
        "g7080": (["70", "80"], leaf(540), False, 1.0),
        "g100110": (["100", "110"], leaf(750), False, 1.0),
        "g130": (["130"], leaf(930), False, 1.0),
    }
    positions = {
        key: slot
        for name, (keys, center, _, _) in groups.items()
        for key, slot in zip(keys, btree_neon_slots(center, len(keys)))
    }
    edges = (
        ("root", "il", 0, 2, 1.0), ("root", "ir", 1, 2, 1.0),
        ("il", "g10", 0, 3, 1.0), ("il", "g4050", 1, 3, 1.0), ("il", "g7080", 2, 3, 1.0),
        ("ir", "g100110", 0, 2, 1.0), ("ir", "g130", 1, 2, 1.0),
    )
    rects = {name: group_rect([positions[m] for m in members], home) for name, (members, home, _, _) in groups.items()}
    body: list[str] = []
    body.extend(
        [
            btree_neon_edge(btree_neon_gap(root, 1, 0), ((rects["il"][0] + rects["il"][2]) / 2.0, rects["il"][1]), focus=True),
            btree_neon_edge(btree_neon_gap(groups["il"][1], 2, 1), ((rects["g4050"][0] + rects["g4050"][2]) / 2.0, rects["g4050"][1]), focus=True),
            btree_neon_edge(btree_neon_gap(root, 1, 1), ((rects["ir"][0] + rects["ir"][2]) / 2.0, rects["ir"][1]), focus=True),
            btree_neon_edge(btree_neon_gap(groups["ir"][1], 1, 1), ((rects["g130"][0] + rects["g130"][2]) / 2.0, rects["g130"][1]), focus=True),
        ]
    )
    for parent, child, slot, total, _ in edges:
        start_rect = rects[parent]
        end_rect = rects[child]
        body.append(btree_neon_edge(
            btree_neon_gap(groups[parent][1], len(groups[parent][0]), slot),
            ((end_rect[0] + end_rect[2]) / 2.0, end_rect[1]),
        ))
    for name, (keys, center, _, _) in groups.items():
        row, _ = btree_neon_row(keys, center, focus=["50"] if name == "g4050" else [])
        body.append(row)
    body.extend([
        f'<text x="80" y="95" fill="{GLOW_WHITE}" font-family="Noto Sans CJK SC,system-ui,sans-serif" font-size="17" font-weight="600" style="text-anchor:start">查找 50：90 &gt; 50，左</text>',
        f'<text x="70" y="350" fill="{INK}" font-family="Noto Sans CJK SC,system-ui,sans-serif" font-size="16" style="text-anchor:start">[30,60]：中间</text>',
        f'<text x="330" y="555" fill="{GLOW_WHITE}" font-family="Noto Sans CJK SC,system-ui,sans-serif" font-size="16" text-anchor="middle">命中 50</text>',
        f'<text x="760" y="95" fill="{GLOW_WHITE}" font-family="Noto Sans CJK SC,system-ui,sans-serif" font-size="17" font-weight="600" style="text-anchor:start">查找 125：90 &lt; 125，右</text>',
        f'<text x="1040" y="350" fill="{INK}" font-family="Noto Sans CJK SC,system-ui,sans-serif" font-size="16" style="text-anchor:end">[120]：125 &gt; 120，右</text>',
        f'<text x="930" y="555" fill="{GLOW_RED}" font-family="Noto Sans CJK SC,system-ui,sans-serif" font-size="16" text-anchor="middle">没有 125</text>',
    ])
    return svg("".join(body), width=1100, height=600, color=INK)


def btree_order_scaling_svg() -> str:
    """Keep the original three-row capacity comparison, rendered in neon style."""
    rows = (
        ("4 阶", 120.0, "最多 63 个"),
        ("100 阶", 460.0, "约 100 万个"),
        ("512 阶", 750.0, "约 1.34 亿个"),
    )
    parts = [
        f'<text x="450" y="34" fill="{INK}" font-family="Noto Sans CJK SC,system-ui,sans-serif" '
        'font-size="24" font-weight="600" text-anchor="middle">同样三层，能装多少关键字？</text>'
    ]
    for index, (label, bar_width, note) in enumerate(rows):
        top = 78.0 + index * 104.0
        center = (140.0 + bar_width / 2.0, top + 28.0)
        parts.append(
            f'<text x="70" y="{top + 28:.1f}" fill="{INK}" font-family="Noto Sans CJK SC,system-ui,sans-serif" '
            f'font-size="15" font-weight="600" text-anchor="middle" dominant-baseline="middle">{esc(label)}</text>'
        )
        parts.append(bloom_rect(center, bar_width, 56.0, GLOW_BLUE, 1.0))
        parts.append(
            f'<rect x="140" y="{top:.1f}" width="{bar_width:.1f}" height="56" rx="9" '
            f'fill="{NODE_FILL}" stroke="{NODE_RIM}" stroke-width="1.8"/>'
        )
        parts.append(
            f'<text x="{center[0]:.1f}" y="{center[1]:.1f}" fill="{INK}" font-family="Noto Sans CJK SC,system-ui,sans-serif" '
            f'font-size="20" font-weight="600" text-anchor="middle" dominant-baseline="middle">{esc(note)}</text>'
        )
    parts.append(
        f'<text x="450" y="398" fill="{INK}" font-family="Noto Sans CJK SC,system-ui,sans-serif" '
        'font-size="18" text-anchor="middle">高度三层的 m 阶 B 树最多存 m³ − 1 个关键字；阶数由存储页大小决定</text>'
    )
    return svg("".join(parts), width=900, height=420, color=INK)


def render_webm(
    filename_base: str,
    frames: Sequence[str],
    *,
    repeats: Sequence[int] | None = None,
    fps: int = 24,
    transparent: bool = True,
    crop: bool = True,
    crop_pad: int = 0,
    zoom: float = 2.0,
    output_path: Path | str | None = None,
    background: str = "white",
) -> None:
    """Render SVG states into a WebM stream; never assemble a GIF."""
    image_magick = which("magick") or which("convert")
    if which("rsvg-convert") is None or which("ffmpeg") is None or image_magick is None:
        raise RuntimeError("rsvg-convert, ffmpeg, and ImageMagick are required")
    counts = list(repeats) if repeats is not None else [1] * len(frames)
    if len(counts) != len(frames):
        raise ValueError("each frame needs a repeat count")
    with TemporaryDirectory(prefix="tree-motion-", dir=ROOT) as temp_name:
        temp = Path(temp_name)
        frame_dir = temp / "frames"
        frame_dir.mkdir()
        rendered_cache: dict[str, Path] = {}
        output_index = 0
        for index, (frame, count) in enumerate(zip(frames, counts, strict=True)):
            target = temp / f"rendered-{index:04d}.png"
            cached = rendered_cache.get(frame)
            if cached is not None:
                copyfile(cached, target)
            else:
                source = temp / f"frame-{index:04d}.svg"
                raw_png = temp / f"raw-{index:04d}.png"
                source.write_text(frame, encoding="utf-8")
                run(["rsvg-convert", "--zoom", str(zoom), str(source), "--output", str(raw_png)], check=True)
                if transparent:
                    raw_png.rename(target)
                else:
                    run([
                        image_magick,
                        str(raw_png),
                        "-background",
                        background,
                        "-alpha",
                        "remove",
                        "-alpha",
                        "off",
                        str(target),
                    ], check=True)
                rendered_cache[frame] = target
            for _ in range(count):
                copyfile(target, frame_dir / f"frame-{output_index:05d}.png")
                output_index += 1
        if transparent and crop:
            crop_transparent_frames(frame_dir, pad=crop_pad)
        video = Path(output_path) if output_path else ASSETS / f"{filename_base}.webm"
        video.unlink(missing_ok=True)
        if not output_path:
            (ASSETS / f"{filename_base}.gif").unlink(missing_ok=True)
            (ASSETS / f"{filename_base}.mp4").unlink(missing_ok=True)
        video_command = [
            "ffmpeg",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(frame_dir / "frame-%05d.png"),
        ]
        if transparent:
            video_command += ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", "-crf", "18", "-b:v", "0"]
        else:
            video_command += ["-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-crf", "28", "-b:v", "0"]
        video_command.append(str(video))
        run(video_command, check=True)


def render_gif(filename: str, frames: Sequence[str], *, repeats: Sequence[int] | None = None, delay: int = 8) -> None:
    """Keep the legacy renderer for process figures that are still being redesigned."""
    image_magick = which("magick") or which("convert")
    if which("rsvg-convert") is None or image_magick is None:
        raise RuntimeError("rsvg-convert and ImageMagick are required")
    counts = list(repeats) if repeats is not None else [1] * len(frames)
    if len(counts) != len(frames):
        raise ValueError("each frame needs a repeat count")
    with TemporaryDirectory(prefix="tree-media-", dir=ROOT) as temp_name:
        temp = Path(temp_name)
        pngs: list[str] = []
        for index, (frame, count) in enumerate(zip(frames, counts, strict=True)):
            source = temp / f"frame-{index:03d}.svg"
            target = temp / f"frame-{index:03d}.png"
            opaque = temp / f"opaque-{index:03d}.png"
            source.write_text(frame, encoding="utf-8")
            run(["rsvg-convert", str(source), "--output", str(target)], check=True)
            run([
                image_magick,
                str(target),
                "-background",
                "white",
                "-alpha",
                "remove",
                "-alpha",
                "off",
                str(opaque),
            ], check=True)
            pngs.extend([str(opaque)] * count)
        run([
            image_magick,
            "-delay",
            str(delay),
            "-loop",
            "0",
            *pngs,
            str(ASSETS / filename),
        ], check=True)


def ease(value: float) -> float:
    return 0.5 - 0.5 * cos(pi * value)


def lerp(start: float, end: float, value: float) -> float:
    return start + (end - start) * value


def lerp_point(start: Point, end: Point, value: float) -> Point:
    return lerp(start[0], end[0], value), lerp(start[1], end[1], value)


def interpolate_positions(start: Mapping[str, Point], end: Mapping[str, Point], t: float) -> dict[str, Point]:
    eased = ease(t)
    return {
        key: (lerp(start[key][0], end[key][0], eased), lerp(start[key][1], end[key][1], eased))
        for key in start.keys() & end.keys()
    }


def avl_balance_state(angle: float, middle_position: float) -> tuple[dict[str, Point], Point]:
    """Return the local tree positions and the middle mount point on the 5--9 balance."""
    center = (390.0, 190.0)
    half_length = hypot(180.0, 120.0) / 2.0
    direction = (cos(angle), sin(angle))
    left = (center[0] - half_length * direction[0], center[1] - half_length * direction[1])
    right = (center[0] + half_length * direction[0], center[1] + half_length * direction[1])
    mount = (
        left[0] + (2.0 * half_length * middle_position) * direction[0],
        left[1] + (2.0 * half_length * middle_position) * direction[1],
    )
    positions = {
        "5": left,
        "9": right,
        "3": (left[0] - 90.0, left[1] + 120.0),
        "6": (mount[0], mount[1] + 150.0),
        "14": (right[0] + 120.0, right[1] + 120.0),
    }
    positions["17"] = (positions["14"][0] + 90.0, positions["14"][1] + 120.0)
    return positions, mount


def avl_balance_line(
    start: Point,
    end: Point,
    *,
    width: float = 3.0,
    opacity: float = 1.0,
    stroke: str = INK,
) -> str:
    return f'<line x1="{start[0]:.1f}" y1="{start[1]:.1f}" x2="{end[0]:.1f}" y2="{end[1]:.1f}" stroke="{stroke}" stroke-width="{width:.2f}" stroke-linecap="round" opacity="{opacity:.3f}"/>'


def avl_mount_clamp(mount: Point, angle: float, *, opacity: float) -> str:
    """Draw a clamp across the balance so the rope has a visible attachment point."""
    normal = (-sin(angle), cos(angle))
    outer_start = (mount[0] - normal[0] * 11.0, mount[1] - normal[1] * 11.0)
    outer_end = (mount[0] + normal[0] * 11.0, mount[1] + normal[1] * 11.0)
    inner_start = (mount[0] - normal[0] * 8.0, mount[1] - normal[1] * 8.0)
    inner_end = (mount[0] + normal[0] * 8.0, mount[1] + normal[1] * 8.0)
    return (
        avl_balance_line(outer_start, outer_end, width=8.0, opacity=opacity, stroke="#274C99")
        + avl_balance_line(inner_start, inner_end, width=3.0, opacity=opacity, stroke=INK)
    )


def avl_balance_frame(
    angle: float,
    middle_position: float,
    *,
    focus: float = 0.0,
    attached: float = 0.0,
    final_mix: float = 0.0,
) -> str:
    balance_positions, mount = avl_balance_state(angle, middle_position)
    final_positions: dict[str, Point] = {
        "9": (480.0, 130.0),
        "5": (300.0, 250.0),
        "14": (600.0, 250.0),
        "3": (210.0, 370.0),
        "6": (375.0, 370.0),
        "17": (690.0, 370.0),
    }
    positions = {
        key: (
            lerp(balance_positions[key][0], final_positions[key][0], ease(final_mix)),
            lerp(balance_positions[key][1], final_positions[key][1], ease(final_mix)),
        )
        for key in balance_positions
    }
    final_mix_eased = ease(final_mix)
    normal_edges = (("5", "3"), ("5", "9"), ("9", "14"), ("14", "17"))
    body: list[str] = [
        '<defs>'
         '<linearGradient id="avl-rope-gradient" gradientUnits="userSpaceOnUse" x1="390" y1="190" x2="390" y2="370">'
        '<stop offset="0" stop-color="#274C99"/><stop offset="0.45" stop-color="#8FA9E8"/><stop offset="1" stop-color="#EAF1FF"/>'
        '</linearGradient>'
        '</defs>'
    ]
    focus_eased = focus * (1.0 - final_mix_eased)
    for parent, child in normal_edges:
        x1, y1, x2, y2 = endpoints(positions[parent], positions[child])
        if {parent, child} == {"5", "9"} and focus_eased > 0.0:
            body.append(glow_line((x1, y1), (x2, y2), width=3.6, bloom=GLOW_WHITE))
        else:
            body.append(avl_balance_line((x1, y1), (x2, y2)))

    # Remove the original child edge before the rope becomes visible. This keeps
    # the physical connection unambiguous during the handoff.
    original_edge_opacity = (1.0 - final_mix_eased) * max(0.0, 1.0 - 2.0 * attached)
    if original_edge_opacity > 0.0:
        x1, y1, x2, y2 = endpoints(positions["9"], positions["6"])
        body.append(avl_balance_line((x1, y1), (x2, y2), width=3.0, opacity=original_edge_opacity))

    # During reassembly the middle subtree becomes the right child of 5.
    if final_mix_eased > 0.0:
        x1, y1, x2, y2 = endpoints(positions["5"], positions["6"])
        body.append(avl_balance_line((x1, y1), (x2, y2), width=3.0, opacity=final_mix_eased))

    if attached > 0.0 and final_mix_eased < 1.0:
        mount_opacity = min(1.0, attached * 2.0) * (1.0 - final_mix_eased)
        rope_end = (positions["6"][0], positions["6"][1] - RADIUS)
        body.append(avl_balance_line(mount, rope_end, width=9.0, opacity=mount_opacity, stroke="#075985"))
        body.append(avl_balance_line(mount, rope_end, width=4.0, opacity=mount_opacity, stroke="url(#avl-rope-gradient)"))
        body.append(avl_mount_clamp(mount, angle, opacity=mount_opacity))

    for key, point in positions.items():
        lever_glow = key in {"5", "9"} and focus_eased > 0.0
        body.append(glow_square(key, point, glow=GLOW_WHITE if lever_glow else GLOW_BLUE))
    return svg("".join(body), color=INK)


def avl_single_left() -> None:
    initial_angle = atan2(120.0, 180.0)
    final_angle = -initial_angle
    original_middle = 0.78
    center_middle = 0.50
    opposite_middle = 0.22
    frames: list[str] = []

    # The ordinary tree starts with the middle subtree at the center mount.
    frames.extend([avl_balance_frame(initial_angle, center_middle)] * 36)
    for step in range(1, 25):
        t = ease(step / 24.0)
        frames.append(avl_balance_frame(initial_angle, center_middle, focus=t))
    frames.extend([avl_balance_frame(initial_angle, center_middle, focus=1.0)] * 24)

    for step in range(1, 31):
        t = ease(step / 30.0)
        frames.append(avl_balance_frame(initial_angle, center_middle, focus=1.0, attached=t))
    frames.extend([avl_balance_frame(initial_angle, center_middle, focus=1.0, attached=1.0)] * 24)

    # First level the original balance while the cargo stays at the center.
    for step in range(1, 46):
        t = ease(step / 45.0)
        frames.append(
            avl_balance_frame(
                lerp(initial_angle, 0.0, t),
                center_middle,
                focus=1.0,
                attached=1.0,
            )
        )
    frames.extend([avl_balance_frame(0.0, center_middle, focus=1.0, attached=1.0)] * 24)

    # Restore the original tilt; gravity moves the cargo back to its original side.
    for step in range(1, 66):
        t = ease(step / 65.0)
        frames.append(
            avl_balance_frame(
                lerp(0.0, initial_angle, t),
                lerp(center_middle, original_middle, t),
                focus=1.0,
                attached=1.0,
            )
        )
    frames.extend([avl_balance_frame(initial_angle, original_middle, focus=1.0, attached=1.0)] * 30)

    # Continue through level to the opposite tilt; the cargo slides to the other side.
    for step in range(1, 66):
        t = ease(step / 65.0)
        frames.append(
            avl_balance_frame(
                lerp(initial_angle, final_angle, t),
                lerp(original_middle, opposite_middle, t),
                focus=1.0,
                attached=1.0,
            )
        )
    frames.extend([avl_balance_frame(final_angle, opposite_middle, focus=1.0, attached=1.0)] * 30)

    for step in range(1, 46):
        t = ease(step / 45.0)
        frames.append(avl_balance_frame(final_angle, opposite_middle, focus=1.0, attached=1.0, final_mix=t))
    frames.extend([avl_balance_frame(final_angle, opposite_middle, final_mix=1.0)] * 42)
    render_webm("avl-single-left", frames, fps=30, transparent=True)


def avl_rotation_frame(
    positions: Mapping[str, Point],
    edges: Sequence[tuple[str, str, float]],
    *,
    lever: Iterable[str] = ("y", "x"),
) -> str:
    """Draw one rotation frame; every edge carries its own opacity.
    The two lever nodes carry a white neon glow."""
    lever_keys = set(lever)
    parts: list[str] = []
    for a, b, opacity in edges:
        if opacity <= 0.0:
            continue
        on_lever = a in lever_keys and b in lever_keys
        parts.append(
            glow_line(
                positions[a],
                positions[b],
                opacity=opacity,
                bloom=GLOW_WHITE if on_lever else None,
            )
        )
    for key, point in positions.items():
        parts.append(glow_square(key, point, glow=GLOW_WHITE if key in lever_keys else GLOW_BLUE))
    return svg("".join(parts), color=INK)


def avl_right_rotation() -> None:
    diag = cos(pi / 4)
    center = (380.0, 205.0)
    radius = 140.0

    def lever(offset_angle: float) -> tuple[Point, Point]:
        ca, sa = cos(offset_angle), sin(offset_angle)

        def spin(offset: Point) -> Point:
            return (
                center[0] + offset[0] * ca - offset[1] * sa,
                center[1] + offset[0] * sa + offset[1] * ca,
            )

        return spin((radius * diag, -radius * diag)), spin((-radius * diag, radius * diag))

    y0, x0 = lever(0.0)
    start_subtrees = {
        "A": (x0[0] - 90.0, x0[1] + 136.0),
        "B": (x0[0] + 90.0, x0[1] + 136.0),
        "C": (y0[0] + 90.0, y0[1] + 136.0),
    }
    waiting = {"A": (140.0, 480.0), "B": (380.0, 512.0), "C": (650.0, 460.0)}
    y1, x1 = lever(pi / 2)
    final_subtrees = {
        "A": (x1[0] - 90.0, x1[1] + 136.0),
        "B": (y1[0] - 90.0, y1[1] + 136.0),
        "C": (y1[0] + 90.0, y1[1] + 136.0),
    }

    def frame(yp: Point, xp: Point, subtrees: Mapping[str, Point], edges: Sequence[tuple[str, str, float]]) -> str:
        return avl_rotation_frame({"y": yp, "x": xp, **subtrees}, edges)

    full_edges = (("y", "x", 1.0), ("x", "A", 1.0), ("x", "B", 1.0), ("y", "C", 1.0))
    lever_only = (("y", "x", 1.0),)
    final_edges = (("y", "x", 1.0), ("x", "A", 1.0), ("y", "B", 1.0), ("y", "C", 1.0))
    frames: list[str] = []

    frames.extend([frame(y0, x0, start_subtrees, full_edges)] * 30)

    for step in range(1, 37):
        t = ease(step / 36.0)
        fade = max(0.0, 1.0 - 2.0 * t)
        edges = (("y", "x", 1.0), ("x", "A", fade), ("x", "B", fade), ("y", "C", fade))
        frames.append(frame(y0, x0, interpolate_positions(start_subtrees, waiting, step / 36.0), edges))
    frames.extend([frame(y0, x0, waiting, lever_only)] * 20)

    for step in range(1, 49):
        yp, xp = lever(pi / 2 * ease(step / 48.0))
        frames.append(frame(yp, xp, waiting, lever_only))
    frames.extend([frame(y1, x1, waiting, lever_only)] * 20)

    for step in range(1, 37):
        t = ease(step / 36.0)
        appear = max(0.0, 2.0 * t - 1.0)
        edges = (("y", "x", 1.0), ("x", "A", appear), ("y", "B", appear), ("y", "C", appear))
        frames.append(frame(y1, x1, interpolate_positions(waiting, final_subtrees, step / 36.0), edges))
    frames.extend([frame(y1, x1, final_subtrees, final_edges)] * 40)

    render_webm("avl-right-rotation", frames, fps=30, transparent=True)


def spin_lever(a: Point, b: Point, angle: float) -> tuple[Point, Point]:
    """Rotate the two-node lever about its midpoint; positive turns clockwise on screen."""
    mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    ca, sa = cos(angle), sin(angle)

    def spin(point: Point) -> Point:
        ox, oy = point[0] - mid[0], point[1] - mid[1]
        return (mid[0] + ox * ca - oy * sa, mid[1] + ox * sa + oy * ca)

    return spin(a), spin(b)


def avl_right_left() -> None:
    """Right-left double rotation narrated step by step: find the lever shape z—y, weigh the middle cargo X,
    rotate X's own subtree first, then rotate the reshaped lever z—X."""
    RED = RB_RED

    def page(body: str) -> str:
        return svg(body, width=1000, height=660, color=INK)

    def circle(key: str, point: Point, *, cls: str = "node", opacity: float = 1.0) -> str:
        glow = GLOW_WHITE if "focus-node" in cls else GLOW_BLUE
        return glow_square(key, point, opacity=opacity, glow=glow)

    def ln(a: Point, b: Point, *, cls: str | None = "edge", opacity: float = 1.0, stroke: str | None = None, width: float = 3.0) -> str:
        if cls == "focus-edge":
            return glow_line(a, b, opacity=opacity, bloom=GLOW_WHITE, width=3.6)
        x1, y1, x2, y2 = endpoints(a, b)
        if cls and stroke is None:
            return f'<line stroke="{INK}" stroke-width="3.4" stroke-linecap="round" opacity="{opacity:.3f}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>'
        stroke = stroke or INK
        return f'<line stroke="{stroke}" stroke-width="{width:.1f}" stroke-linecap="round" opacity="{opacity:.3f}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>'

    def caption(*lines: str) -> str:
        # The narration is supplied by the course video; keep this source
        # animation free of burned-in subtitles.
        return ""

    def red_box(rect: tuple[float, float, float, float], opacity: float) -> str:
        x, y, w, h = rect
        out = ""
        for grow, share in ((10.0, 0.12), (5.5, 0.20), (2.5, 0.38)):
            out += (
                f'<rect x="{x - grow:.1f}" y="{y - grow:.1f}" width="{w + 2 * grow:.1f}" height="{h + 2 * grow:.1f}" '
                f'rx="16" fill="none" stroke="{GLOW_RED}" stroke-width="3.0" opacity="{opacity * share:.3f}"/>'
            )
        out += (
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="12" '
            f'fill="none" stroke="{GLOW_RED}" stroke-width="3.0" opacity="{opacity:.3f}"/>'
        )
        return out

    def red_ring(point: Point, opacity: float) -> str:
        return glow_ring(point, color=GLOW_RED, opacity=opacity)

    base = {
        "z": (500.0, 150.0),
        "A": (350.0, 290.0),
        "y": (720.0, 290.0),
        "x": (600.0, 430.0),
        "B": (520.0, 570.0),
        "C": (680.0, 570.0),
        "D": (840.0, 430.0),
    }
    base_edges = (("z", "A"), ("z", "y"), ("y", "x"), ("y", "D"), ("x", "B"), ("x", "C"))

    def draw_tree(pos: dict[str, Point], *, lever: tuple[str, str] | None = None, extra_edges: Sequence[tuple[str, str, str, float]] = ()) -> str:
        parts = []
        for a, b in base_edges:
            active_lever = lever is not None and {a, b} == set(lever)
            parts.append(ln(pos[a], pos[b], cls="focus-edge" if active_lever else "edge"))
        for a, b, stroke, op in extra_edges:
            parts.append(ln(pos[a], pos[b], cls=None, stroke=stroke, opacity=op))
        order = ("D", "C", "B", "x", "A", "y", "z")
        body = "".join(parts)
        for key in order:
            cls = "node focus-node" if lever is not None and key in lever else "node"
            body += circle(key, pos[key], cls=cls)
        return body

    frames: list[str] = []

    right_box_full = (462.0, 230.0, 460.0, 380.0)
    x_box_target = (600.0 - RADIUS - 16.0, 430.0 - RADIUS - 12.0, 2 * (RADIUS + 16.0), 2 * (RADIUS + 12.0))

    # Step 1: look at the shape — the right side stands taller.
    for step in range(1, 61):
        t = ease(step / 61.0)
        frames.append(page(draw_tree(base) + caption("先看形状：右子树更高，是右边更重")))
    for step in range(0, 60):
        frames.append(page(draw_tree(base, lever=("z", "y")) + caption("哪边更重，杠杆在哪边——杠杆是 z—y")))

    # Step 2: the lever is z—y; its three cargos are A, X and D.
    for step in range(1, 61):
        t = ease(step / 61.0)
        rect = (
            lerp(right_box_full[0], x_box_target[0], t),
            lerp(right_box_full[1], x_box_target[1], t),
            lerp(right_box_full[2], x_box_target[2], t),
            lerp(right_box_full[3], x_box_target[3], t),
        )
        frames.append(page(draw_tree(base, lever=("z", "y")) + caption("杠杆上的三个货物：A、X、D")))

    # Step 3: the middle cargo X is the heavier one.
    for step in range(1, 61):
        t = ease(step / 61.0)
        body = draw_tree(base, lever=("z", "y"))
        body += red_box(x_box_target, 0.45 * (1.0 - t))
        body += red_ring(base["x"], t)
        frames.append(page(body + caption("中间货物 X 更重——这就是中间失衡")))

    # Step 4 — the first rotation: rotate the subtree containing X.
    for step in range(0, 60):
        body = draw_tree(base, lever=("z", "y"))
        body += red_ring(base["x"], 1.0)
        frames.append(page(body + caption("第一次旋转：旋转 X 所在子树")))

    # Detach the middle cargo from z.
    for step in range(1, 31):
        t = ease(step / 31.0)
        parts = []
        for a, b in base_edges:
            if (a, b) == ("z", "y"):
                parts.append(ln(base[a], base[b], cls="edge", opacity=1.0 - t))
            elif (a, b) == ("y", "x"):
                parts.append(ln(base[a], base[b], cls="focus-edge"))
            else:
                parts.append(ln(base[a], base[b]))
        order = ("D", "C", "B", "x", "A", "y", "z")
        for key in order:
            cls = "node focus-node" if key in ("x", "y") else "node"
            parts.append(circle(key, base[key], cls=cls))
        parts.append(red_ring(base["x"], 1.0))
        frames.append(page("".join(parts) + caption("第一次旋转：先把 X 所在子树摘下")))
    frames.extend([page(
        "".join(ln(base[a], base[b]) if (a, b) != ("z", "y") else "" for a, b in base_edges if (a, b) != ("y", "x"))
        + ln(base["y"], base["x"], cls="focus-edge")
        + "".join(circle(key, base[key], cls="node focus-node" if key in ("x", "y") else "node") for key in ("D", "C", "B", "x", "A", "y", "z"))
        + red_ring(base["x"], 1.0)
        + caption("X 所在子树已摘下")
    )] * 29)

    # Inside it, detach its three mounted cargos B, C, D.
    inner_wait = {"B": (400.0, 598.0), "C": (800.0, 598.0), "D": (930.0, 348.0)}
    for step in range(1, 61):
        t = ease(step / 61.0)
        pos = dict(base)
        for k in ("B", "C", "D"):
            pos[k] = lerp_point(base[k], inner_wait[k], t)
        body = ln(pos["y"], pos["x"], cls="focus-edge")
        body += ln(pos["z"], pos["A"])
        body += ln(pos["x"], pos["B"], opacity=1.0 - t)
        body += ln(pos["x"], pos["C"], opacity=1.0 - t)
        body += ln(pos["y"], pos["D"], opacity=1.0 - t)
        for key in ("D", "C", "B", "x", "A", "y", "z"):
            cls = "node focus-node" if key in ("x", "y") else "node"
            body += circle(key, pos[key], cls=cls)
        body += red_ring(pos["x"], 1.0)
        body += caption("摘下子树的三个挂载：B、C、D")
        frames.append(page(body))
    detached_inner = dict(base)
    detached_inner.update(inner_wait)
    frames.extend([page(
        ln(detached_inner["y"], detached_inner["x"], cls="focus-edge")
        + ln(detached_inner["z"], detached_inner["A"])
        + "".join(circle(key, detached_inner[key], cls="node focus-node" if key in ("x", "y") else "node") for key in ("D", "C", "B", "x", "A", "y", "z"))
        + red_ring(detached_inner["x"], 1.0)
        + caption("空杠杆 y—X")
    )] * 60)

    # Spin the bare y—X lever; the center of gravity crosses to the right.
    m1, m2 = (660.0, 360.0), (730.0, 330.0)
    vx, vy = base["y"][0] - m1[0], base["y"][1] - m1[1]
    import math

    for step in range(1, 61):
        t = ease(step / 61.0)
        angle = math.radians(90.0 * t)
        c, sn = math.cos(angle), math.sin(angle)
        cx = m1[0] + (m2[0] - m1[0]) * t
        cy = m1[1] + (m2[1] - m1[1]) * t
        rvx = vx * c - vy * sn
        rvy = vx * sn + vy * c
        pos = dict(detached_inner)
        pos["y"] = (cx + rvx, cy + rvy)
        pos["x"] = (cx - rvx, cy - rvy)
        body = ln(pos["y"], pos["x"], cls="focus-edge")
        body += ln(pos["z"], pos["A"])
        for key in ("D", "C", "B", "x", "A", "y", "z"):
            cls = "node focus-node" if key in ("x", "y") else "node"
            body += circle(key, pos[key], cls=cls)
        body += red_ring(pos["x"], 1.0)
        body += caption("第一次旋转：重心从左边转移到右边")
        frames.append(page(body))

    after_one = {"z": base["z"], "A": base["A"]}
    after_one["x"] = (m2[0] - (vx * math.cos(math.radians(90.0)) - vy * math.sin(math.radians(90.0))), m2[1] - (vx * math.sin(math.radians(90.0)) + vy * math.cos(math.radians(90.0))))
    after_one["y"] = (m2[0] + (vx * math.cos(math.radians(90.0)) - vy * math.sin(math.radians(90.0))), m2[1] + (vx * math.sin(math.radians(90.0)) + vy * math.cos(math.radians(90.0))))
    inner_final = {"B": (610.0, 430.0), "C": (750.0, 550.0), "D": (880.0, 430.0)}

    # Reattach B, C, D left-middle-right inside the rotated subtree.
    for step in range(1, 46):
        t = ease(step / 46.0)
        pos = dict(after_one)
        pos.update({k: lerp_point(inner_wait[k], inner_final[k], t) for k in ("B", "C", "D")})
        body = ln(pos["y"], pos["x"], cls="focus-edge")
        body += ln(pos["z"], pos["A"])
        body += ln(pos["x"], pos["B"])
        body += ln(pos["y"], pos["C"])
        body += ln(pos["y"], pos["D"])
        for key in ("D", "C", "B", "x", "A", "y", "z"):
            cls = "node focus-node" if key in ("x", "y") else "node"
            body += circle(key, pos[key], cls=cls)
        body += red_box((inner_final["C"][0] - 55.0, after_one["y"][1] - 62.0, inner_final["D"][0] - inner_final["C"][0] + 130.0, 300.0), 0.9)
        body += caption("现在对于杠杆 z—X，右边货物更重")
        frames.append(page(body))
    frames.extend([frames[-1]] * 14)

    # Step 5 — the lever is a shape: it is now z—X.
    lever_note_frames = []
    for _ in range(0, 60):
        body = ln(after_one["z"], after_one["x"], cls="focus-edge")
        body += ln(after_one["x"], inner_final["B"])
        body += ln(after_one["x"], after_one["y"])
        body += ln(after_one["y"], inner_final["C"])
        body += ln(after_one["y"], inner_final["D"])
        body += ln(after_one["z"], after_one["A"])
        for key in ("D", "C", "B", "x", "A", "y", "z"):
            cls = "node focus-node" if key in ("z", "x") else "node"
            body += circle(key, after_one.get(key, inner_final.get(key, base[key])), cls=cls)
        lever_note_frames.append(page(body + caption("注意：杠杆是一个形状，原来是 z—y，现在是 z—X")))
    frames += lever_note_frames

    root_wait = {"A": (160.0, 330.0), "B": (430.0, 592.0)}
    group_dx, group_dy = 52.0, 44.0
    for _ in range(0, 60):
        pos = dict(after_one)
        pos.update(inner_final)
        body = ln(pos["z"], pos["x"], cls="focus-edge")
        body += ln(pos["x"], pos["B"])
        body += ln(pos["x"], pos["y"])
        body += ln(pos["y"], pos["C"])
        body += ln(pos["y"], pos["D"])
        body += ln(pos["z"], pos["A"])
        for key in ("D", "C", "B", "x", "A", "y", "z"):
            cls = "node focus-node" if key in ("z", "x") else "node"
            body += circle(key, pos[key], cls=cls)
        body += red_box((pos["y"][0] - 50.0, pos["y"][1] - 58.0, 240.0, 290.0), 0.9)
        body += caption("右边货物更重，第二次旋转即可")
        frames.append(page(body))

    # Detach the three cargos of lever z—X.
    for step in range(1, 61):
        t = ease(step / 61.0)
        pos = {"z": after_one["z"], "x": after_one["x"], "y": (after_one["y"][0] + group_dx, after_one["y"][1] + group_dy)}
        pos["A"] = lerp_point(after_one["A"], root_wait["A"], t)
        pos["B"] = lerp_point(inner_final["B"], root_wait["B"], t)
        pos["C"] = (inner_final["C"][0] + group_dx, inner_final["C"][1] + group_dy)
        pos["D"] = (inner_final["D"][0] + group_dx, inner_final["D"][1] + group_dy)
        body = ln(pos["z"], pos["x"], cls="focus-edge")
        body += ln(pos["y"], pos["C"], opacity=1.0)
        body += ln(pos["y"], pos["D"], opacity=1.0)
        body += ln(pos["z"], pos["A"], opacity=1.0 - t)
        body += ln(pos["x"], pos["B"], opacity=1.0 - t)
        body += ln(pos["x"], pos["y"], opacity=1.0 - t)
        for key in ("D", "C", "B", "x", "A", "y", "z"):
            cls = "node focus-node" if key in ("z", "x") else "node"
            body += circle(key, pos[key], cls=cls)
        body += caption("摘下三个货物：A、B、y 组")
        frames.append(page(body))
    root_detached_pos = {"z": after_one["z"], "x": after_one["x"], "y": (after_one["y"][0] + group_dx, after_one["y"][1] + group_dy), "A": root_wait["A"], "B": root_wait["B"], "C": (inner_final["C"][0] + group_dx, inner_final["C"][1] + group_dy), "D": (inner_final["D"][0] + group_dx, inner_final["D"][1] + group_dy)}
    frames.extend([page(
        ln(root_detached_pos["z"], root_detached_pos["x"], cls="focus-edge")
        + ln(root_detached_pos["y"], root_detached_pos["C"]) + ln(root_detached_pos["y"], root_detached_pos["D"])
        + "".join(circle(key, root_detached_pos[key], cls="node focus-node" if key in ("z", "x") else "node") for key in ("D", "C", "B", "x", "A", "y", "z"))
        + caption("空杠杆 z—X")
    )] * 60)

    # Spin the bare z—X lever.
    rm1, rm2 = (580.0, 215.0), (575.0, 205.0)
    rvx0, rvy0 = after_one["z"][0] - rm1[0], after_one["z"][1] - rm1[1]
    for step in range(1, 61):
        t = ease(step / 61.0)
        angle = math.radians(-90.0 * t)
        c, sn = math.cos(angle), math.sin(angle)
        cx = rm1[0] + (rm2[0] - rm1[0]) * t
        cy = rm1[1] + (rm2[1] - rm1[1]) * t
        nrvx = rvx0 * c - rvy0 * sn
        nrvy = rvx0 * sn + rvy0 * c
        pos = dict(root_detached_pos)
        pos["z"] = (cx + nrvx, cy + nrvy)
        pos["x"] = (cx - nrvx, cy - nrvy)
        body = ln(pos["z"], pos["x"], cls="focus-edge")
        body += ln(pos["y"], pos["C"]) + ln(pos["y"], pos["D"])
        for key in ("D", "C", "B", "x", "A", "y", "z"):
            cls = "node focus-node" if key in ("z", "x") else "node"
            body += circle(key, pos[key], cls=cls)
        body += caption("第二次旋转：抬起更重的一端")
        frames.append(page(body))
    z_final = (rm2[0] + rvx0 * math.cos(math.radians(-90.0)) - rvy0 * math.sin(math.radians(-90.0)), rm2[1] + rvx0 * math.sin(math.radians(-90.0)) + rvy0 * math.cos(math.radians(-90.0)))
    x_final = (rm2[0] - (rvx0 * math.cos(math.radians(-90.0)) - rvy0 * math.sin(math.radians(-90.0))), rm2[1] - (rvx0 * math.sin(math.radians(-90.0)) + rvy0 * math.cos(math.radians(-90.0))))

    # Reattach everything left-middle-right.
    final_tree = {
        "x": x_final,
        "z": z_final,
        "A": (z_final[0] - 70.0, z_final[1] + 140.0),
        "B": (z_final[0] + 70.0, z_final[1] + 140.0),
        "y": (x_final[0] + 145.0, x_final[1] + 140.0),
        "C": (x_final[0] + 85.0, x_final[1] + 280.0),
        "D": (x_final[0] + 205.0, x_final[1] + 280.0),
    }
    group_from = {"y": root_detached_pos["y"], "C": root_detached_pos["C"], "D": root_detached_pos["D"]}
    for step in range(1, 46):
        t = ease(step / 46.0)
        pos = {"z": z_final, "x": x_final}
        pos["A"] = lerp_point(root_wait["A"], final_tree["A"], t)
        pos["B"] = lerp_point(root_wait["B"], final_tree["B"], t)
        for k in ("y", "C", "D"):
            pos[k] = lerp_point(group_from[k], final_tree[k], t)
        body = ln(pos["x"], pos["z"])
        body += ln(pos["z"], pos["A"])
        body += ln(pos["z"], pos["B"])
        body += ln(pos["x"], pos["y"])
        body += ln(pos["y"], pos["C"])
        body += ln(pos["y"], pos["D"])
        for key in ("D", "C", "B", "x", "A", "y", "z"):
            body += circle(key, pos[key])
        frames.append(page(body))
    frames.extend([frames[-1]] * 14)
    frames.extend([page(
        "".join(ln(final_tree[a], final_tree[b]) for a, b in (("x", "z"), ("z", "A"), ("z", "B"), ("x", "y"), ("y", "C"), ("y", "D")))
        + "".join(circle(key, final_tree[key]) for key in ("D", "C", "B", "x", "A", "y", "z"))
        + caption("平衡恢复")
    )] * 60)
    render_webm("avl-right-left", frames, fps=30, transparent=True)


def avl_delete_legacy() -> None:
    before = (
        50,
        {
            50: (30, 80), 30: (20, 40), 20: (10, 25), 10: (None, None), 25: (None, None),
            40: (35, 45), 35: (None, None), 45: (None, None),
            80: (70, 90), 70: (60, 75), 60: (None, None), 75: (None, None),
            90: (85, 100), 85: (None, None), 100: (95, 105), 95: (None, None), 105: (None, None),
        },
    )
    after_10 = (50, {**before[1], 20: (None, 25), 10: None})
    after_10 = (50, {key: value for key, value in after_10[1].items() if key != 10})
    after_20 = (50, {50: (30, 80), 30: (25, 40), 25: (None, None), 40: (35, 45), 35: (None, None), 45: (None, None), 80: (70, 90), 70: (60, 75), 60: (None, None), 75: (None, None), 90: (85, 100), 85: (None, None), 100: (95, 105), 95: (None, None), 105: (None, None)})
    after_30 = (50, {50: (35, 80), 35: (25, 40), 25: (None, None), 40: (None, 45), 45: (None, None), 80: (70, 90), 70: (60, 75), 60: (None, None), 75: (None, None), 90: (85, 100), 85: (None, None), 100: (95, 105), 95: (None, None), 105: (None, None)})
    before_rotation = (50, {50: (35, 85), 35: (25, 40), 25: (None, None), 40: (None, 45), 45: (None, None), 85: (70, 90), 70: (60, 75), 60: (None, None), 75: (None, None), 90: (None, 100), 100: (95, 105), 95: (None, None), 105: (None, None)})
    after_80 = (50, {50: (35, 85), 35: (25, 40), 25: (None, None), 40: (None, 45), 45: (None, None), 85: (70, 100), 70: (60, 75), 60: (None, None), 75: (None, None), 100: (90, 105), 90: (None, 95), 95: (None, None), 105: (None, None)})

    snapshots = (before, after_10, after_20, after_30, before_rotation, after_80)
    layouts = {id(snapshot): avl_insert_layout(snapshot) for snapshot in snapshots}
    frames: list[str] = []
    narration_frames = 90

    def hold(
        snapshot: tuple[int, dict[int, tuple[int | None, int | None]]],
        count: int = narration_frames,
        caption: str | None = None,
    ) -> None:
        positions, edges = layouts[id(snapshot)]
        frame = avl_insert_frame(positions, ((a, b, 1.0) for a, b in sorted(edges)))
        frames.extend([frame] * count)

    def fade_delete(
        old: tuple[int, dict[int, tuple[int | None, int | None]]],
        new: tuple[int, dict[int, tuple[int | None, int | None]]],
        key: int,
        label: str,
    ) -> None:
        old_positions, old_edges = layouts[id(old)]
        new_positions, new_edges = layouts[id(new)]
        for step in range(1, 46):
            t = ease(step / 45.0)
            positions = dict(old_positions)
            positions.update({name: lerp_point(old_positions[name], point, t) for name, point in new_positions.items() if name in old_positions})
            opacity = max(0.0, 1.0 - t)
            edges = [(a, b, 1.0) for a, b in sorted(old_edges) if key not in (int(a), int(b))]
            edges.extend((a, b, opacity) for a, b in sorted(old_edges) if key in (int(a), int(b)))
            frames.append(avl_insert_frame(positions, edges, node_opacities={str(key): opacity}))
        hold(new, narration_frames)

    def swap_then_delete(
        old: tuple[int, dict[int, tuple[int | None, int | None]]],
        new: tuple[int, dict[int, tuple[int | None, int | None]]],
        target: int,
        replacement: int,
        swap_caption: str,
        delete_caption: str,
    ) -> None:
        old_positions, old_edges = layouts[id(old)]
        new_positions, new_edges = layouts[id(new)]
        target_key, replacement_key = str(target), str(replacement)
        # Keep both node positions fixed while the old labels fade out and the new labels fade in.
        # Four seconds at 30 FPS makes the overlap easy to observe.
        for step in range(1, 121):
            t = ease(step / 120.0)
            frames.append(
                avl_insert_frame(
                    old_positions,
                    ((a, b, 1.0) for a, b in sorted(old_edges)),
                    node_text_layers={
                        target_key: ((target_key, 1.0 - t, INK), (replacement_key, t, GLOW_ORANGE)),
                        replacement_key: ((replacement_key, 1.0 - t, INK), (target_key, t, GLOW_ORANGE)),
                    },
                )
            )
        swapped_labels = {target_key: replacement_key, replacement_key: target_key}
        frames.extend([
            avl_insert_frame(
                old_positions,
                ((a, b, 1.0) for a, b in sorted(old_edges)),
                node_text_layers={
                    target_key: ((replacement_key, 1.0, GLOW_ORANGE),),
                    replacement_key: ((target_key, 1.0, GLOW_ORANGE),),
                },
            )
        ] * narration_frames)

        # Delete the target value from the replacement's original node, then settle the tree.
        for step in range(1, 46):
            t = ease(step / 45.0)
            positions = {
                name: lerp_point(old_positions[name], point, t)
                for name, point in new_positions.items()
                if name in old_positions and name not in (target_key, replacement_key)
            }
            positions[replacement_key] = lerp_point(old_positions[target_key], new_positions[replacement_key], t)
            positions[target_key] = old_positions[replacement_key]
            opacity = max(0.0, 1.0 - t)
            edges = [(a, b, 1.0) for a, b in sorted(new_edges)]
            frames.append(
                avl_insert_frame(
                    positions,
                    edges,
                    node_opacities={target_key: opacity},
                    node_text_layers={
                        replacement_key: ((replacement_key, 1.0, GLOW_ORANGE),),
                        target_key: ((target_key, opacity, GLOW_ORANGE),),
                    },
                )
            )
        hold(new, narration_frames)

    hold(before, narration_frames, caption="先看完整的 AVL 树，再沿同一棵树连续完成四次删除。")
    fade_delete(before, after_10, 10, "第一步删除叶节点 10；它没有孩子，可以直接从原位置摘下。")
    fade_delete(after_10, after_20, 20, "第二步删除单孩子节点 20；让唯一的孩子 25 接管 20 原来的位置。")
    swap_then_delete(after_20, after_30, 30, 35, "第三步先交换节点里的数值：把 30 和它的前驱 35 互换，节点位置和连线都不动。", "数值交换完成后，再删除前驱位置上的 30，橙色的 35 留在目标节点位置。")
    swap_then_delete(after_30, before_rotation, 80, 85, "第四步先交换节点里的数值：把 80 和它的后继 85 互换，节点位置和连线都不动。", "数值交换完成后，再删除后继位置上的 80，橙色的 85 留在目标节点位置。")
    hold(before_rotation, narration_frames, caption="删除完成后，高度下降继续向上传播，接下来检查 90 的平衡。")
    rotation_highlights = [(list(map(str, avl_insert_descendants(before_rotation[1], 90))), GLOW_RED)]
    rotation_positions, _ = layouts[id(before_rotation)]
    avl_insert_rotation_scene(frames, before_rotation, after_80, rotation_positions, layouts[id(after_80)][0], 90, "left", rotation_highlights)
    hold(after_80, narration_frames, caption="旋转完成，AVL 树恢复平衡。")
    render_webm("avl-delete", frames, fps=30, transparent=True)


def avl_delete() -> None:
    """Show four deletions, including a deletion whose height drop repairs twice."""
    insertion_order = [3, 10, 8, 7, 5, 1, 11, 6, 9, 4, 12, 2]
    deletion_order = (9, 7, 3)
    narration_frames = 90
    swap_frames = 120

    def snapshot(node: AvlInsertNode) -> Snapshot:
        children: dict[int, tuple[int | None, int | None]] = {}

        def visit(current: AvlInsertNode | None) -> None:
            if current is None:
                return
            children[current.key] = (
                current.left.key if current.left else None,
                current.right.key if current.right else None,
            )
            visit(current.left)
            visit(current.right)

        visit(node)
        return node.key, children

    def clone(snapshot_value: Snapshot) -> AvlInsertNode:
        root, children = snapshot_value
        nodes = {key: AvlInsertNode(key) for key in children}
        for key, (left, right) in children.items():
            nodes[key].left = nodes[left] if left is not None else None
            nodes[key].right = nodes[right] if right is not None else None
        return nodes[root]

    def locate(node: AvlInsertNode | None, key: int) -> AvlInsertNode | None:
        while node is not None and node.key != key:
            node = node.left if key < node.key else node.right
        return node

    def successor(node: AvlInsertNode) -> int:
        current = node.right
        assert current is not None
        while current.left is not None:
            current = current.left
        return current.key

    def bst_delete(node: AvlInsertNode | None, key: int) -> AvlInsertNode | None:
        if node is None:
            return None
        if key < node.key:
            node.left = bst_delete(node.left, key)
        elif key > node.key:
            node.right = bst_delete(node.right, key)
        elif node.left is None:
            return node.right
        elif node.right is None:
            return node.left
        else:
            replacement = successor(node)
            node.key = replacement
            node.right = bst_delete(node.right, replacement)
        return node

    def heights(snapshot_value: Snapshot) -> dict[int, int]:
        _, children = snapshot_value
        result: dict[int, int] = {}

        def height(key: int | None) -> int:
            if key is None:
                return 0
            if key not in result:
                left, right = children[key]
                result[key] = 1 + max(height(left), height(right))
            return result[key]

        height(snapshot_value[0])
        return result

    def balance(snapshot_value: Snapshot, key: int) -> int:
        children = snapshot_value[1]
        measured = heights(snapshot_value)
        left, right = children[key]
        return (measured[left] if left is not None else 0) - (measured[right] if right is not None else 0)

    def repair(
        old: Snapshot,
        snapshot_value: Snapshot,
        path: Sequence[int],
        replaced_key: int | None,
    ) -> tuple[Snapshot, list[tuple[str, Snapshot, int, int | str, Snapshot | None]]]:
        current = snapshot_value
        events: list[tuple[str, Snapshot, int, int | str, Snapshot | None]] = []
        old_heights = heights(old)
        for index, upper in enumerate(path):
            if upper not in current[1]:
                continue
            old_key = replaced_key if index == 0 and replaced_key is not None else upper
            old_height = old_heights[old_key]
            current_balance = balance(current, upper)
            events.append(("check", current, upper, current_balance, None))
            local_root = upper
            if abs(current_balance) > 1:
                left, right = current[1][upper]
                if current_balance > 1:
                    assert left is not None
                    if balance(current, left) < 0:
                        next_snapshot = avl_insert_rotate_snapshot(current, left, "left")
                        events.append(("rotation", current, left, "left", next_snapshot))
                        current = next_snapshot
                    local_root = current[1][upper][0]
                    assert local_root is not None
                    next_snapshot = avl_insert_rotate_snapshot(current, upper, "right")
                    events.append(("rotation", current, upper, "right", next_snapshot))
                    current = next_snapshot
                else:
                    assert right is not None
                    if balance(current, right) > 0:
                        next_snapshot = avl_insert_rotate_snapshot(current, right, "right")
                        events.append(("rotation", current, right, "right", next_snapshot))
                        current = next_snapshot
                    local_root = current[1][upper][1]
                    assert local_root is not None
                    next_snapshot = avl_insert_rotate_snapshot(current, upper, "left")
                    events.append(("rotation", current, upper, "left", next_snapshot))
                    current = next_snapshot

            new_height = heights(current)[local_root]
            event_type = "height_stop" if new_height == old_height else "height_continue"
            events.append((event_type, current, local_root, f"{old_height}->{new_height}", None))
            if new_height == old_height:
                break
        return current, events

    def deletion_path(
        old: Snapshot,
        raw: Snapshot,
        key: int,
        replacement: int | None,
    ) -> list[int]:
        old_root, old_children = old
        old_path: list[int] = []
        current = old_root
        while current != key:
            old_path.append(current)
            left, right = old_children[current]
            current = left if key < current else right
            assert current is not None
        raw_parents = {
            child: parent
            for parent, children in raw[1].items()
            for child in children
            if child is not None
        }
        current = replacement if replacement is not None else (old_path[-1] if old_path else raw[0])
        path = [current]
        while current in raw_parents:
            current = raw_parents[current]
            path.append(current)
        return path

    tree: AvlInsertNode | None = None
    for key in insertion_order:
        if tree is None:
            tree = AvlInsertNode(key)
        else:
            tree, _ = avl_insert_balanced(tree, key)
    assert tree is not None

    initial_snapshot = snapshot(tree)
    current = initial_snapshot
    deletion_data: list[tuple[Snapshot, Snapshot, Snapshot, int, int | None, list[tuple[str, Snapshot, int, int | str, Snapshot | None]]]] = []
    all_snapshots: list[Snapshot] = [current]
    for key in deletion_order:
        old_tree = clone(current)
        target = locate(old_tree, key)
        assert target is not None
        replacement = successor(target) if target.left is not None and target.right is not None else None
        raw_tree = bst_delete(old_tree, key)
        assert raw_tree is not None
        raw = snapshot(raw_tree)
        path = deletion_path(current, raw, key, replacement)
        repaired, events = repair(current, raw, path, key if replacement is not None else None)
        deletion_data.append((current, raw, repaired, key, replacement, events))
        all_snapshots.extend((raw, repaired, *(entry[1] for entry in events), *(entry[4] for entry in events if entry[4] is not None)))
        current = repaired

    layouts = {
        # Leave visual air between separate subtrees without making the tree
        # wider than the final video's main canvas.
        id(value): avl_insert_layout(value, gap=160.0, step_side=175.0)
        for value in all_snapshots
    }
    frames: list[str] = []

    def hold(snapshot_value: Snapshot, caption: str, count: int = narration_frames) -> None:
        positions, edges = layouts[id(snapshot_value)]
        frame = avl_insert_frame(positions, ((a, b, 1.0) for a, b in sorted(edges)))
        frames.extend([frame] * count)

    def fade_delete(old: Snapshot, new: Snapshot, key: int, caption: str) -> None:
        old_positions, old_edges = layouts[id(old)]
        new_positions, _ = layouts[id(new)]
        for step in range(1, swap_frames + 1):
            t = ease(step / swap_frames)
            positions = dict(old_positions)
            positions.update({name: lerp_point(old_positions[name], point, t) for name, point in new_positions.items() if name in old_positions})
            opacity = max(0.0, 1.0 - t)
            edges = [(a, b, 1.0) for a, b in sorted(old_edges) if key not in (int(a), int(b))]
            edges.extend((a, b, opacity) for a, b in sorted(old_edges) if key in (int(a), int(b)))
            frames.append(avl_insert_frame(positions, edges, node_opacities={str(key): opacity}))

    def swap_then_delete(old: Snapshot, raw: Snapshot, key: int, replacement: int, swap_caption: str, delete_caption: str) -> None:
        old_positions, old_edges = layouts[id(old)]
        raw_positions, raw_edges = layouts[id(raw)]
        target_key, replacement_key = str(key), str(replacement)
        # Swap the two key digits by carrying them one after the other, no
        # cross-fade: first the target key flies into the replacement's node,
        # then — as a separate move — the replacement key flies back into the
        # target's node. Each node's box stays where it is throughout.
        move_frames = 36
        for step in range(1, move_frames + 1):
            t = ease(step / move_frames)
            frames.append(avl_insert_frame(
                old_positions,
                ((a, b, 1.0) for a, b in sorted(old_edges)),
                node_text_layers={target_key: ()},
                moving_texts=((
                    target_key,
                    lerp_point(old_positions[target_key], old_positions[replacement_key], t),
                    1.0,
                    GLOW_ORANGE,
                ),),
            ))
        frames.extend([avl_insert_frame(
            old_positions,
            ((a, b, 1.0) for a, b in sorted(old_edges)),
            node_text_layers={
                target_key: (),
                replacement_key: ((target_key, 1.0, GLOW_ORANGE),),
            },
        )] * 8)
        for step in range(1, move_frames + 1):
            t = ease(step / move_frames)
            frames.append(avl_insert_frame(
                old_positions,
                ((a, b, 1.0) for a, b in sorted(old_edges)),
                node_text_layers={
                    target_key: (),
                    replacement_key: ((target_key, 1.0, GLOW_ORANGE),),
                },
                moving_texts=((
                    replacement_key,
                    lerp_point(old_positions[replacement_key], old_positions[target_key], t),
                    1.0,
                    GLOW_ORANGE,
                ),),
            ))
        frames.extend([avl_insert_frame(
            old_positions,
            ((a, b, 1.0) for a, b in sorted(old_edges)),
            node_text_layers={
                target_key: ((replacement_key, 1.0, GLOW_ORANGE),),
                replacement_key: ((target_key, 1.0, GLOW_ORANGE),),
            },
        )] * narration_frames)
        for step in range(1, 61):
            t = ease(step / 60.0)
            positions = {name: lerp_point(old_positions[name], point, t) for name, point in raw_positions.items() if name in old_positions and name not in (target_key, replacement_key)}
            positions[replacement_key] = lerp_point(old_positions[target_key], raw_positions[replacement_key], t)
            positions[target_key] = old_positions[replacement_key]
            opacity = max(0.0, 1.0 - t)
            frames.append(avl_insert_frame(
                positions,
                ((a, b, 1.0) for a, b in sorted(raw_edges)),
                node_opacities={target_key: opacity},
                node_text_layers={
                    replacement_key: ((replacement_key, 1.0, GLOW_ORANGE),),
                    target_key: ((target_key, opacity, GLOW_ORANGE),),
                },
            ))

    hold(initial_snapshot, "先看一棵 12 个节点的 AVL 树；接下来连续删除三个节点。")
    captions = (
        "第一步删除叶节点 9；高度下降沿回溯路径连续经过 10 和 8，并触发两次旋转。",
        "第二步删除只有一个孩子的节点 7；让唯一的孩子 6 接管原来的位置。",
        "第三步删除双孩子节点 3；先交换它和后继 4 的数值，再删除旧目标值。",
    )
    for index, (old, raw, repaired, key, replacement, events) in enumerate(deletion_data):
        if replacement is None:
            fade_delete(old, raw, key, captions[index])
        else:
            swap_then_delete(old, raw, key, replacement, captions[index] + " 数值交换持续四秒，两个数值会交叉淡化。", captions[index] + " 交换完成后，继续删除旧目标值。")
        rotation_index = 0
        for event_type, event_snapshot, upper, value, after_snapshot in events:
            if event_type == "check":
                current_balance = int(value)
                if abs(current_balance) <= 1:
                    hold(event_snapshot, f"检查节点 {upper}：仍然平衡，不需要旋转；接着比较这棵子树的高度。")
                else:
                    shape = "左高" if current_balance > 1 else "右高"
                    hold(event_snapshot, f"检查节点 {upper}：{shape}，平衡因子为 {current_balance}，需要调整。")
                continue
            if event_type in ("height_stop", "height_continue"):
                old_height, new_height = str(value).split("->")
                if event_type == "height_stop":
                    hold(event_snapshot, f"局部子树高度仍是 {new_height} 层，没有继续下降；删除的影响到这里为止。")
                else:
                    hold(event_snapshot, f"局部子树从 {old_height} 层降到 {new_height} 层；继续检查更高的祖先。")
                continue
            assert after_snapshot is not None
            direction = str(value)
            lower = event_snapshot[1][upper][1 if direction == "left" else 0]
            assert lower is not None
            rotation_index += 1
            pair_name = f"{lower}-{upper}"
            rotation_caption = f"第 {rotation_index} 次旋转：{pair_name}{'左' if direction == 'left' else '右'}旋，沿回溯路径继续向上。"
            avl_insert_rotation_scene(
                frames,
                event_snapshot,
                after_snapshot,
                layouts[id(event_snapshot)][0],
                layouts[id(after_snapshot)][0],
                upper,
                direction,
            )
        hold(repaired, f"删除 {key} 后修复完成。")
    render_webm("avl-delete", frames, fps=30, transparent=True, crop=True, crop_pad=60)


@dataclass
class AvlInsertNode:
    key: int
    left: AvlInsertNode | None = None
    right: AvlInsertNode | None = None
    height: int = 1


def avl_insert_height(node: AvlInsertNode | None) -> int:
    return node.height if node else 0


def avl_insert_update(node: AvlInsertNode) -> AvlInsertNode:
    node.height = 1 + max(avl_insert_height(node.left), avl_insert_height(node.right))
    return node


def avl_insert_clone(node: AvlInsertNode | None) -> AvlInsertNode | None:
    if node is None:
        return None
    return AvlInsertNode(node.key, avl_insert_clone(node.left), avl_insert_clone(node.right), node.height)


def avl_insert_plain(node: AvlInsertNode | None, key: int) -> AvlInsertNode:
    if node is None:
        return AvlInsertNode(key)
    if key < node.key:
        node.left = avl_insert_plain(node.left, key)
    else:
        node.right = avl_insert_plain(node.right, key)
    return node


def avl_insert_left(node: AvlInsertNode) -> AvlInsertNode:
    child = node.right
    assert child is not None
    node.right = child.left
    child.left = node
    avl_insert_update(node)
    return avl_insert_update(child)


def avl_insert_right(node: AvlInsertNode) -> AvlInsertNode:
    child = node.left
    assert child is not None
    node.left = child.right
    child.right = node
    avl_insert_update(node)
    return avl_insert_update(child)


def avl_insert_balanced(node: AvlInsertNode | None, key: int) -> tuple[AvlInsertNode, str | None]:
    if node is None:
        return AvlInsertNode(key), None
    if key < node.key:
        node.left, event = avl_insert_balanced(node.left, key)
    else:
        node.right, event = avl_insert_balanced(node.right, key)
    avl_insert_update(node)
    balance = avl_insert_height(node.left) - avl_insert_height(node.right)
    if balance > 1:
        assert node.left is not None
        if key < node.left.key:
            return avl_insert_right(node), "LL"
        node.left = avl_insert_left(node.left)
        return avl_insert_right(node), "LR"
    if balance < -1:
        assert node.right is not None
        if key > node.right.key:
            return avl_insert_left(node), "RR"
        node.right = avl_insert_right(node.right)
        return avl_insert_left(node), "RL"
    return node, event


def avl_insert_snapshot(node: AvlInsertNode) -> tuple[int, dict[int, tuple[int | None, int | None]]]:
    children: dict[int, tuple[int | None, int | None]] = {}

    def visit(current: AvlInsertNode | None) -> None:
        if current is None:
            return
        children[current.key] = (
            current.left.key if current.left else None,
            current.right.key if current.right else None,
        )
        visit(current.left)
        visit(current.right)

    visit(node)
    return node.key, children


def avl_insert_validate(node: AvlInsertNode | None, lower: int | None = None, upper: int | None = None) -> int:
    if node is None:
        return 0
    assert (lower is None or lower < node.key) and (upper is None or node.key < upper)
    left_height = avl_insert_validate(node.left, lower, node.key)
    right_height = avl_insert_validate(node.right, node.key, upper)
    assert abs(left_height - right_height) <= 1
    assert node.height == 1 + max(left_height, right_height)
    return node.height


def avl_insert_layout(
    snapshot: tuple[int, Mapping[int, tuple[int | None, int | None]]],
    ranks: Mapping[int, int] | None = None,
    *,
    gap: float = 110.0,
    step_side: float = 108.0,
    top: float = AVL_INSERT_TOP,
    level_step: float = 92.0,
    collapsed_triangles: Mapping[str, float] | None = None,
    hidden_nodes: Collection[str] | None = None,
) -> tuple[dict[str, Point], set[Edge]]:
    """Tidy layered layout: parents centered over their children, sibling
    subtrees kept `gap` apart. `ranks` is accepted for compatibility and
    no longer drives geometry."""
    root, children = snapshot
    rel: dict[int, float] = {}
    depth_of: dict[int, int] = {}

    def build(key: int, depth: int) -> tuple[list[int], float, float, float]:
        """Place the subtree with `key` at relative x 0; return (members, lo, hi, center)."""
        rel[key] = 0.0
        depth_of[key] = depth
        if collapsed_triangles and str(key) in collapsed_triangles:
            return [key], 0.0, 0.0, 0.0
        left, right = children[key]
        if left is None and right is None:
            return [key], 0.0, 0.0, 0.0
        if right is None:
            assert left is not None
            members, lo, hi, center = build(left, depth + 1)
            delta = -step_side - center
            for k in members:
                rel[k] += delta
            return members + [key], min(lo + delta, 0.0), max(hi + delta, 0.0), 0.0
        if left is None:
            members, lo, hi, center = build(right, depth + 1)
            delta = step_side - center
            for k in members:
                rel[k] += delta
            return members + [key], min(lo + delta, 0.0), max(hi + delta, 0.0), 0.0
        l_members, l_lo, l_hi, l_center = build(left, depth + 1)
        r_members, r_lo, r_hi, r_center = build(right, depth + 1)
        shift = max(0.0, (l_hi + gap) - r_lo)
        if shift:
            for k in r_members:
                rel[k] += shift
            r_lo += shift
            r_hi += shift
            r_center += shift
        center = (l_center + r_center) / 2.0
        for k in l_members + r_members:
            rel[k] -= center
        return (
            l_members + r_members + [key],
            min(l_lo - center, r_lo - center, 0.0),
            max(l_hi - center, r_hi - center, 0.0),
            0.0,
        )

    _, lo, hi, _ = build(root, 0)
    mid = (lo + hi) / 2.0
    positions = {
        str(k): (AVL_INSERT_W / 2 + rel[k] - mid, top + depth_of[k] * level_step)
        for k in rel
    }
    if collapsed_triangles:
        for triangle_root in collapsed_triangles:
            root_key = int(triangle_root)
            if root_key not in children:
                continue
            stack = [children[root_key][0], children[root_key][1]]
            while stack:
                child = stack.pop()
                if child is None:
                    continue
                positions[str(child)] = positions[triangle_root]
                stack.extend(children[child])
    edges = avl_insert_tree_edges(children)
    return positions, edges


def avl_insert_tree_edges(children: Mapping[int, tuple[int | None, int | None]]) -> set[Edge]:
    return {
        pair(str(parent), str(child))
        for parent, (left, right) in children.items()
        for child in (left, right)
        if child is not None
    }


def avl_insert_descendants(
    children: Mapping[int, tuple[int | None, int | None]],
    root: int,
) -> set[int]:
    result: set[int] = set()

    def visit(key: int) -> None:
        if key in result:
            return
        result.add(key)
        left, right = children[key]
        if left is not None:
            visit(left)
        if right is not None:
            visit(right)

    visit(root)
    return result


def avl_insert_parent(
    children: Mapping[int, tuple[int | None, int | None]],
    child: int,
) -> int | None:
    for parent, (left, right) in children.items():
        if child in (left, right):
            return parent
    return None


def avl_insert_unbalanced_key(
    snapshot: tuple[int, dict[int, tuple[int | None, int | None]]],
    inserted_key: int,
) -> int:
    root, children = snapshot
    path: list[int] = []
    current = root
    while True:
        path.append(current)
        if current == inserted_key:
            break
        left, right = children[current]
        current = left if inserted_key < current else right
        assert current is not None

    def height(key: int | None) -> int:
        if key is None:
            return 0
        left, right = children[key]
        return 1 + max(height(left), height(right))

    unbalanced = [
        key
        for key in path
        if abs(height(children[key][0]) - height(children[key][1])) > 1
    ]
    assert unbalanced
    return unbalanced[-1]


def avl_insert_rotate_snapshot(
    snapshot: tuple[int, dict[int, tuple[int | None, int | None]]],
    upper: int,
    direction: str,
) -> tuple[int, dict[int, tuple[int | None, int | None]]]:
    root, original = snapshot
    children = dict(original)
    left, right = children[upper]
    if direction == "left":
        assert right is not None
        lower = right
        lower_left, lower_right = children[lower]
        children[upper] = (left, lower_left)
        children[lower] = (upper, lower_right)
    else:
        assert left is not None
        lower = left
        lower_left, lower_right = children[lower]
        children[upper] = (lower_right, right)
        children[lower] = (lower_left, upper)

    parent = avl_insert_parent(original, upper)
    if parent is None:
        root = lower
    else:
        parent_left, parent_right = children[parent]
        children[parent] = (
            lower if parent_left == upper else parent_left,
            lower if parent_right == upper else parent_right,
        )
    return root, children


def avl_insert_rotation_mounts(
    children: Mapping[int, tuple[int | None, int | None]],
    upper: int,
    direction: str,
) -> tuple[int, tuple[int | None, int | None, int | None]]:
    left, right = children[upper]
    if direction == "left":
        assert right is not None
        lower = right
        lower_left, lower_right = children[lower]
        return lower, (left, lower_left, lower_right)
    assert left is not None
    lower = left
    lower_left, lower_right = children[lower]
    return lower, (lower_left, lower_right, right)


def avl_insert_rotation_scene(
    frames: list[str],
    before: tuple[int, dict[int, tuple[int | None, int | None]]],
    after: tuple[int, dict[int, tuple[int | None, int | None]]],
    before_positions: Mapping[str, Point],
    after_positions: Mapping[str, Point],
    upper: int,
    direction: str,
    highlights: Sequence[tuple[Sequence[str], str]] | None = None,
    queue_slots: Mapping[str, Point] | None = None,
    collapsed_triangles: Mapping[str, float] | None = None,
    hidden_nodes: Collection[str] | None = None,
    cargo_down: bool = False,
    compact_lever: bool = False,
) -> None:
    """Animate one ordinary AVL rotation as detach, bare-lever turn, reattach."""
    _, before_children = before
    _, after_children = after
    lower, mount_roots = avl_insert_rotation_mounts(before_children, upper, direction)
    upper_key, lower_key = str(upper), str(lower)
    parent = avl_insert_parent(before_children, upper)

    parent_edge = pair(str(parent), upper_key) if parent is not None else None
    if direction == "left":
        mount_edges = ((upper, mount_roots[0]), (lower, mount_roots[1]), (lower, mount_roots[2]))
    else:
        mount_edges = ((lower, mount_roots[0]), (lower, mount_roots[1]), (upper, mount_roots[2]))
    mount_edges_set = {pair(str(a), str(b)) for a, b in mount_edges if b is not None}

    before_edges = avl_insert_tree_edges(before_children)
    after_edges = avl_insert_tree_edges(after_children)
    subtree_edges = before_edges - ({parent_edge} if parent_edge is not None else set())
    cargo_edges = subtree_edges - mount_edges_set
    after_parent = pair(str(parent), str(lower)) if parent is not None else None
    attachment_edges = after_edges - cargo_edges - ({after_parent} if after_parent is not None else set())

    center = (
        (before_positions[upper_key][0] + before_positions[lower_key][0]) / 2.0,
        (before_positions[upper_key][1] + before_positions[lower_key][1]) / 2.0,
    )
    mount_groups: list[tuple[int, set[int], Point]] = []
    # Detach = drop every cargo group straight down where it stands: the left
    # cargo stays on the left, the middle stays in the middle, the right stays
    # on the right. No repositioning, no gaps — the bare lever spins in the
    # cleared band above them.
    cargo_drop = 180.0
    for mount_root in mount_roots:
        if mount_root is None:
            continue
        group = avl_insert_descendants(before_children, mount_root)
        root_point = before_positions[str(mount_root)]
        mount_groups.append((mount_root, group, (root_point[0], root_point[1] + cargo_drop)))

    def shifted_positions(
        base: Mapping[str, Point],
        progress: float,
        targets: Mapping[int, Point],
        *,
        move_cargo_down: bool = False,
    ) -> dict[str, Point]:
        result = dict(base)
        for root_key, group, target in mount_groups:
            root_point = base[str(root_key)]
            target_point = (
                (root_point[0], root_point[1] + 180.0)
                if move_cargo_down
                else targets[root_key]
            )
            dx = (target_point[0] - root_point[0]) * progress
            dy = (target_point[1] - root_point[1]) * progress
            for key in group:
                point = base[str(key)]
                result[str(key)] = (point[0] + dx, point[1] + dy)
        return result

    def render(positions: Mapping[str, Point], edges: Iterable[tuple[str, str, float]], marks: Sequence[tuple[Sequence[str], str]] | None = None) -> None:
        frames.append(
            avl_insert_frame(
                positions,
                edges,
                highlights=marks,
                queue_slots=queue_slots,
                collapsed_triangles=collapsed_triangles,
                hidden_nodes=hidden_nodes,
            )
        )

    # First detach the local subtree from its parent. The cargo remains attached.
    if parent_edge is not None:
        for step in range(1, 15):
            opacity = max(0.0, 1.0 - ease(step / 14.0))
            edges = [(a, b, 1.0) for a, b in sorted(subtree_edges)]
            edges.append((parent_edge[0], parent_edge[1], opacity))
            render(before_positions, edges, highlights)
        frames.extend([
            avl_insert_frame(
                before_positions,
                ((a, b, 1.0) for a, b in sorted(subtree_edges)),
                highlights=highlights,
                queue_slots=queue_slots,
                collapsed_triangles=collapsed_triangles,
                hidden_nodes=hidden_nodes,
            )
        ] * 10)

    # Then detach the three mounted cargo groups from the lever.
    waiting_targets = {root_key: waiting_root for root_key, _, waiting_root in mount_groups}
    for step in range(1, 19):
        t = ease(step / 18.0)
        positions = shifted_positions(
            before_positions, t, waiting_targets, move_cargo_down=cargo_down
        )
        opacity = max(0.0, 1.0 - 2.0 * t)
        edges = [(a, b, 1.0) for a, b in sorted(cargo_edges)]
        edges.extend((a, b, opacity) for a, b in sorted(mount_edges_set))
        render(positions, edges)

    detached = shifted_positions(
        before_positions, 1.0, waiting_targets, move_cargo_down=cargo_down
    )
    frames.extend([
        avl_insert_frame(
            detached,
            ((a, b, 1.0) for a, b in sorted(cargo_edges)),
            queue_slots=queue_slots,
            collapsed_triangles=collapsed_triangles,
            hidden_nodes=hidden_nodes,
        )
        ] * 10)

    if compact_lever:
        lever_center = (
            (before_positions[upper_key][0] + before_positions[lower_key][0]) / 2.0,
            (before_positions[upper_key][1] + before_positions[lower_key][1]) / 2.0,
        )
        compact_scale = 0.42
        compacted = dict(detached)
        for step in range(1, 25):
            t = ease(step / 24.0)
            positions = dict(detached)
            for key in (upper_key, lower_key):
                point = before_positions[key]
                compact_point = (
                    lever_center[0] + (point[0] - lever_center[0]) * compact_scale,
                    lever_center[1] + (point[1] - lever_center[1]) * compact_scale,
                )
                positions[key] = lerp_point(point, compact_point, t)
            render(positions, ((a, b, 1.0) for a, b in sorted(cargo_edges)))
        for key in (upper_key, lower_key):
            point = before_positions[key]
            compacted[key] = (
                lever_center[0] + (point[0] - lever_center[0]) * compact_scale,
                lever_center[1] + (point[1] - lever_center[1]) * compact_scale,
            )
        frames.extend([
            avl_insert_frame(
                compacted,
                ((a, b, 1.0) for a, b in sorted(cargo_edges)),
                queue_slots=queue_slots,
                collapsed_triangles=collapsed_triangles,
                hidden_nodes=hidden_nodes,
            )
        ] * 8)
    else:
        compacted = detached

    # Rotate the lever by exactly the angle the final layout needs — never a
    # hardcoded 90 degrees. The signed delta is derived from the pre-spin and
    # final lever vectors, so the turn lands on the final orientation and
    # nothing has to swing back afterwards.
    start_vector = (
        compacted[lower_key][0] - compacted[upper_key][0],
        compacted[lower_key][1] - compacted[upper_key][1],
    )
    final_vector = (
        after_positions[lower_key][0] - after_positions[upper_key][0],
        after_positions[lower_key][1] - after_positions[upper_key][1],
    )
    rotation_angle = atan2(final_vector[1], final_vector[0]) - atan2(
        start_vector[1], start_vector[0]
    )
    while rotation_angle > pi:
        rotation_angle -= 2.0 * pi
    while rotation_angle <= -pi:
        rotation_angle += 2.0 * pi
    for step in range(1, 31):
        angle = rotation_angle * ease(step / 30.0)
        first, second = spin_lever(compacted[upper_key], compacted[lower_key], angle)
        positions = dict(compacted)
        positions[upper_key] = first
        positions[lower_key] = second
        render(positions, ((a, b, 1.0) for a, b in sorted(cargo_edges)))

    turned = dict(compacted)
    turned[upper_key], turned[lower_key] = spin_lever(
        compacted[upper_key], compacted[lower_key], rotation_angle
    )
    frames.extend([
        avl_insert_frame(
            turned,
            ((a, b, 1.0) for a, b in sorted(cargo_edges)),
            queue_slots=queue_slots,
            collapsed_triangles=collapsed_triangles,
            hidden_nodes=hidden_nodes,
        )
        ] * 10)

    # After turning, restore the lever's original length at the same center.
    # Only after this has finished does the rotated subtree translate to its
    # final layout position.
    if compact_lever:
        stretch_center = (
            (turned[upper_key][0] + turned[lower_key][0]) / 2.0,
            (turned[upper_key][1] + turned[lower_key][1]) / 2.0,
        )
        compact_scale = 0.42
        stretched = dict(turned)
        for step in range(1, 25):
            t = ease(step / 24.0)
            positions = dict(turned)
            for key in (upper_key, lower_key):
                point = turned[key]
                stretched_point = (
                    stretch_center[0] + (point[0] - stretch_center[0]) / compact_scale,
                    stretch_center[1] + (point[1] - stretch_center[1]) / compact_scale,
                )
                positions[key] = lerp_point(point, stretched_point, t)
            render(positions, ((a, b, 1.0) for a, b in sorted(cargo_edges)))
        for key in (upper_key, lower_key):
            point = turned[key]
            stretched[key] = (
                stretch_center[0] + (point[0] - stretch_center[0]) / compact_scale,
                stretch_center[1] + (point[1] - stretch_center[1]) / compact_scale,
            )
    else:
        stretched = turned

    # Move the cargo groups back to their new left, middle, and right mounts.
    # Nodes outside the rotated subtree glide to the new layout in the same
    # span, so the whole frame stays continuous.
    reattach_targets = {root_key: after_positions[str(root_key)] for root_key, _, _ in mount_groups}
    subtree_keys = {str(key) for key in avl_insert_descendants(before_children, upper)} | {upper_key}
    for step in range(1, 23):
        t = ease(step / 22.0)
        positions = shifted_positions(stretched, t, reattach_targets)
        positions[upper_key] = lerp_point(stretched[upper_key], after_positions[upper_key], t)
        positions[lower_key] = lerp_point(stretched[lower_key], after_positions[lower_key], t)
        for other_key in after_positions:
            if other_key not in subtree_keys:
                positions[other_key] = lerp_point(before_positions[other_key], after_positions[other_key], t)
        opacity = max(0.0, 2.0 * t - 1.0)
        edges = [(a, b, 1.0) for a, b in sorted(cargo_edges)]
        edges.extend((a, b, opacity) for a, b in sorted(attachment_edges))
        render(positions, edges)
    frames.extend([
        avl_insert_frame(
            after_positions,
            ((a, b, 1.0) for a, b in sorted(cargo_edges | attachment_edges)),
            queue_slots=queue_slots,
            collapsed_triangles=collapsed_triangles,
            hidden_nodes=hidden_nodes,
        )
    ] * 10)

    # Finally reconnect the rotated subtree to its parent.
    if after_parent is not None:
        for step in range(1, 15):
            opacity = ease(step / 14.0)
            edges = [(a, b, 1.0) for a, b in sorted(cargo_edges | attachment_edges)]
            edges.append((after_parent[0], after_parent[1], opacity))
            render(after_positions, edges)
        frames.extend([
            avl_insert_frame(
                after_positions,
                ((a, b, 1.0) for a, b in sorted(after_edges)),
                queue_slots=queue_slots,
                collapsed_triangles=collapsed_triangles,
                hidden_nodes=hidden_nodes,
            )
        ] * 10)


def avl_insert_node(
    key: str,
    point: Point,
    *,
    glow: str = GLOW_BLUE,
    ink: str = INK,
    opacity: float = 1.0,
    show_text: bool = True,
) -> str:
    return glow_square(key, point, glow=glow, ink=ink, opacity=opacity, show_text=show_text)


def avl_insert_text(key: str, point: Point, *, ink: str = INK, opacity: float = 1.0) -> str:
    return (
        f'<text x="{point[0]:.1f}" y="{point[1] + 1.0:.1f}" style="fill:{ink}" fill="{ink}" '
        f'font-weight="600" font-family="Noto Sans CJK SC,system-ui,sans-serif" font-size="18" '
        f'text-anchor="middle" dominant-baseline="middle" opacity="{opacity:.3f}">{esc(key)}</text>'
    )


def avl_insert_frame(
    positions: Mapping[str, Point],
    edges: Iterable[tuple[str, str, float]],
    *,
    moving: tuple[str, Point] | None = None,
    highlights: Sequence[tuple[Sequence[str], str]] | None = None,
    queue_slots: Mapping[str, Point] | None = None,
    node_opacities: Mapping[str, float] | None = None,
    node_labels: Mapping[str, str] | None = None,
    node_glows: Mapping[str, str] | None = None,
    node_inks: Mapping[str, str] | None = None,
    node_text_layers: Mapping[str, Sequence[tuple[str, float, str]]] | None = None,
    moving_texts: Sequence[tuple[str, Point, float, str]] | None = None,
    collapsed_triangles: Mapping[str, float] | None = None,
    hidden_nodes: Collection[str] | None = None,
) -> str:
    body: list[str] = []
    for left, right, opacity in edges:
        if opacity <= 0.0:
            continue
        if hidden_nodes and (left in hidden_nodes or right in hidden_nodes):
            continue
        x1, y1, x2, y2 = avl_edge_endpoints(
            positions[left], positions[right], left, right, collapsed_triangles
        )
        body.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{INK}" stroke-width="3.4" stroke-linecap="round" opacity="{opacity:.3f}"/>'
        )
    highlight_map: dict[str, str] = {}
    for members, color in highlights or ():
        for key in members:
            highlight_map[key] = color
    for key, point in positions.items():
        if hidden_nodes and key in hidden_nodes:
            continue
        opacity = (node_opacities or {}).get(key, 1.0)
        glow = (node_glows or {}).get(key, highlight_map.get(key, GLOW_BLUE))
        ink = (node_inks or {}).get(key, INK)
        if collapsed_triangles and key in collapsed_triangles:
            body.append(
                glow_triangle(
                    point,
                    collapsed_triangles[key],
                    opacity=opacity,
                    glow=glow,
                )
            )
        else:
            body.append(
                avl_insert_node(
                    (node_labels or {}).get(key, key),
                    point,
                    glow=glow,
                    ink=ink,
                    opacity=opacity,
                    show_text=key not in (node_text_layers or {}),
                )
            )
        for label, label_opacity, label_ink in (node_text_layers or {}).get(key, ()):
            body.append(avl_insert_text(label, point, ink=label_ink, opacity=label_opacity))
    for label, point, label_opacity, label_ink in (moving_texts or ()):
        body.append(avl_insert_text(label, point, ink=label_ink, opacity=label_opacity))
    if moving is not None:
        body.append(avl_insert_node(*moving))
    for key, point in (queue_slots or {}).items():
        body.append(glow_square(key, point, size=40.0, glow=GLOW_BLUE))
    return svg("".join(body), width=AVL_INSERT_W, height=AVL_INSERT_H, color=INK)


def avl_delete_to_root() -> None:
    """Repair once below, inspect more ancestors, then repair again at root 80."""
    def minimum_shape(height: int):
        if height == 0:
            return None
        if height == 1:
            return (None, None)
        return (minimum_shape(height - 1), minimum_shape(height - 2))

    def add_minimum_subtree(
        children: dict[int, tuple[int | None, int | None]],
        root: int,
        height: int,
    ) -> None:
        tree_shape = minimum_shape(height)

        def size(node_shape) -> int:
            if node_shape is None:
                return 0
            return 1 + size(node_shape[0]) + size(node_shape[1])

        root_index = size(tree_shape[0]) if tree_shape is not None else 0
        keys = list(range(root - root_index, root - root_index + size(tree_shape)))
        assert keys[root_index] == root
        cursor = 0

        def fill(node_shape) -> int | None:
            nonlocal cursor
            if node_shape is None:
                return None
            left_shape, right_shape = node_shape
            left = fill(left_shape)
            key = keys[cursor]
            cursor += 1
            right = fill(right_shape)
            children[key] = (left, right)
            return key

        fill(tree_shape)

    initial: Snapshot = (
        80,
        {
            80: (36, 239),
            36: (17, 59),
            59: (56, 70),
            70: (64, 74),
            64: (None, None),
            74: (None, 76),
            76: (None, None),
            239: (222, 341),
        },
    )
    add_minimum_subtree(initial[1], 17, 3)
    add_minimum_subtree(initial[1], 56, 2)
    add_minimum_subtree(initial[1], 222, 5)
    add_minimum_subtree(initial[1], 341, 5)
    triangle_level_step = 54.0
    triangle_sizes = {
        "17": AVL_NODE_SIZE / 2.0 + (3 - 1) * triangle_level_step,
        "56": AVL_NODE_SIZE / 2.0 + (2 - 1) * triangle_level_step,
        "222": AVL_NODE_SIZE / 2.0 + (5 - 1) * triangle_level_step,
        "341": AVL_NODE_SIZE / 2.0 + (5 - 1) * triangle_level_step,
    }
    hidden_nodes = {
        str(key)
        for root in triangle_sizes
        for key in avl_insert_descendants(initial[1], int(root))
        if str(key) != root
    }
    delete_key = 64
    after_delete: Snapshot = (
        80,
        {key: children for key, children in initial[1].items() if key != delete_key},
    )
    after_delete[1][70] = (None, 74)
    after_first_rotation = avl_insert_rotate_snapshot(after_delete, 70, "left")
    after_root_rotation = avl_insert_rotate_snapshot(after_first_rotation, 80, "left")

    def height(snapshot_value: Snapshot, key: int | None) -> int:
        if key is None:
            return 0
        left, right = snapshot_value[1][key]
        return 1 + max(height(snapshot_value, left), height(snapshot_value, right))

    assert height(initial, 80) == 7
    assert height(initial, 70) == 3 and height(after_first_rotation, 74) == 2
    assert height(initial, 59) == 4 and height(after_first_rotation, 59) == 3
    assert height(initial, 36) == 5 and height(after_first_rotation, 36) == 4
    assert abs(height(initial, initial[1][80][0]) - height(initial, initial[1][80][1])) <= 1
    assert abs(height(after_first_rotation, after_first_rotation[1][80][0]) - height(after_first_rotation, after_first_rotation[1][80][1])) == 2
    assert all(
        abs(height(after_root_rotation, left) - height(after_root_rotation, right)) <= 1
        for left, right in after_root_rotation[1].values()
    )

    layouts = {
        id(snapshot_value): avl_insert_layout(
            snapshot_value,
            gap=170.0,
            step_side=90.0,
            top=120.0,
            level_step=triangle_level_step,
            collapsed_triangles=triangle_sizes,
            hidden_nodes=hidden_nodes,
        )
        for snapshot_value in (initial, after_delete, after_first_rotation, after_root_rotation)
    }
    frames: list[str] = []

    def annotate(frame: str, title: str, detail: str, focus: Point | None = None, color: str = GLOW_BLUE) -> str:
        # Narration is supplied by the film; the reusable tree asset stays subtitle-free.
        return frame

    def still(
        snapshot_value: Snapshot,
        title: str,
        detail: str,
        *,
        focus_key: int | None = None,
        color: str = GLOW_BLUE,
        count: int = 90,
    ) -> None:
        positions, edges = layouts[id(snapshot_value)]
        frame = avl_insert_frame(
            positions,
            ((left, right, 1.0) for left, right in sorted(edges)),
            node_glows={str(focus_key): color} if focus_key is not None else None,
            collapsed_triangles=triangle_sizes,
            hidden_nodes=hidden_nodes,
        )
        focus = positions[str(focus_key)] if focus_key is not None else None
        frames.extend([annotate(frame, title, detail, focus, color)] * count)

    still(
        initial,
        "删除 64：沿回溯路径向上检查",
        "删掉叶节点 64，从它的父节点 70 开始向上",
        focus_key=delete_key,
        color=GLOW_RED,
    )

    old_positions, old_edges = layouts[id(initial)]
    raw_positions, _ = layouts[id(after_delete)]
    for step in range(1, 46):
        progress = ease(step / 45.0)
        positions = dict(old_positions)
        positions.update(
            {
                key: lerp_point(old_positions[key], point, progress)
                for key, point in raw_positions.items()
            }
        )
        opacity = 1.0 - progress
        edges = [
            (left, right, opacity if str(delete_key) in (left, right) else 1.0)
            for left, right in sorted(old_edges)
        ]
        frame = avl_insert_frame(
            positions,
            edges,
            node_opacities={str(delete_key): opacity},
            collapsed_triangles=triangle_sizes,
            hidden_nodes=hidden_nodes,
        )
        frames.append(annotate(frame, "删除 64", "从它原来的父节点 70 开始向上检查", old_positions[str(delete_key)], GLOW_RED))

    still(
        after_delete,
        "第一次失衡在 70",
        "右边更高，在 70 处进行左旋",
        focus_key=70,
        color=GLOW_RED,
    )
    rotation_start = len(frames)
    avl_insert_rotation_scene(
        frames,
        after_delete,
        after_first_rotation,
        layouts[id(after_delete)][0],
        layouts[id(after_first_rotation)][0],
        70,
        "left",
        collapsed_triangles=triangle_sizes,
        hidden_nodes=hidden_nodes,
        cargo_down=True,
    )
    for index in range(rotation_start, len(frames)):
        frames[index] = annotate(frames[index], "在 70 处左旋", "第一次调整完成，但回溯还不能停")

    still(
        after_first_rotation,
        "继续检查 59：平衡",
        "以 59 为根的子树变矮，继续向上",
        focus_key=59,
        color=GLOW_ORANGE,
    )
    still(
        after_first_rotation,
        "继续检查 36：平衡",
        "以 36 为根的子树继续变矮，仍然不能停",
        focus_key=36,
        color=GLOW_ORANGE,
    )
    still(
        after_first_rotation,
        "检查根 80：第二次失衡",
        "查了多层之后，到 80 才发现右边高出 2 层",
        focus_key=80,
        color=GLOW_RED,
        count=90,
    )
    root_rotation_start = len(frames)
    avl_insert_rotation_scene(
        frames,
        after_first_rotation,
        after_root_rotation,
        layouts[id(after_first_rotation)][0],
        layouts[id(after_root_rotation)][0],
        80,
        "left",
        collapsed_triangles=triangle_sizes,
        hidden_nodes=hidden_nodes,
        cargo_down=True,
        compact_lever=True,
    )
    for index in range(root_rotation_start, len(frames)):
        frames[index] = annotate(frames[index], "在根 80 处左旋", "第二次失衡调整完成，回溯结束")
    still(
        after_root_rotation,
        "两次失衡都已调整",
        "第一次在 70，第二次直到根 80 才发现",
        focus_key=after_root_rotation[0],
        color=GLOW_WHITE,
        count=120,
    )
    render_webm("avl-delete-to-root", frames, fps=30, transparent=True, crop=True, crop_pad=60)


def avl_insertion() -> None:
    sequence = [1, 3, 7, 6, 4, 5, 2, 0, -2, -1]
    ranks = {key: index for index, key in enumerate(sorted(sequence))}
    queue_slots = {
        str(key): avl_queue_slot(index, len(sequence))
        for index, key in enumerate(sequence)
    }
    root: AvlInsertNode | None = None
    frames: list[str] = []
    glide_frames = 22

    for index, key in enumerate(sequence):
        step_start = len(frames)
        before_queue = {str(item): queue_slots[str(item)] for item in sequence[index:]}
        after_queue = {str(item): queue_slots[str(item)] for item in sequence[index + 1:]}

        previous_snapshot = avl_insert_snapshot(root) if root is not None else None
        raw_root = avl_insert_plain(avl_insert_clone(root), key)
        raw_snapshot = avl_insert_snapshot(raw_root)
        root, event = avl_insert_balanced(root, key)
        avl_insert_validate(root)
        post_snapshot = avl_insert_snapshot(root)

        current_positions, current_edges = (
            avl_insert_layout(previous_snapshot, ranks)
            if previous_snapshot is not None
            else ({}, set())
        )
        raw_positions, raw_edges = avl_insert_layout(raw_snapshot, ranks)
        post_positions, post_edges = avl_insert_layout(post_snapshot, ranks)
        target = raw_positions[str(key)]

        frames.extend([
            avl_insert_frame(
                current_positions,
                ((a, b, 1.0) for a, b in sorted(current_edges)),
                queue_slots=before_queue,
            )
        ] * 12)

        # Existing nodes glide to their make-room slots while the new key flies in.
        make_room = 12
        for step in range(1, make_room + 1):
            t = ease(step / make_room)
            positions = {
                name: lerp_point(current_positions[name], raw_positions[name], t)
                for name in current_positions
            }
            frames.append(
                avl_insert_frame(
                    positions,
                    ((a, b, 1.0) for a, b in sorted(raw_edges & current_edges)),
                    queue_slots=before_queue,
                )
            )

        for step in range(0, 15):
            t = ease(step / 14.0)
            moving_point = lerp_point(queue_slots[str(key)], target, t)
            base_positions = {
                name: raw_positions[name] for name in current_positions
            }
            frames.append(
                avl_insert_frame(
                    base_positions,
                    ((a, b, 1.0) for a, b in sorted(raw_edges & current_edges)),
                    moving=(str(key), moving_point),
                    queue_slots=after_queue,
                )
            )

        frames.extend([
            avl_insert_frame(
                raw_positions,
                ((a, b, 1.0) for a, b in sorted(raw_edges)),
                queue_slots=after_queue,
            )
        ] * 6)

        upper = avl_insert_unbalanced_key(raw_snapshot, key) if event is not None else None
        highlights: list[tuple[list[str], str]] | None = None
        if event is not None:
            assert upper is not None
            highlights = []
            raw_children = raw_snapshot[1]
            for side_child, color in zip(raw_children[upper], (GLOW_ORANGE, GLOW_RED)):
                if side_child is not None:
                    members = [str(k) for k in avl_insert_descendants(raw_children, side_child)]
                    highlights.append((members, color))
            frames.extend(
                [
                    avl_insert_frame(
                        raw_positions,
                        ((a, b, 1.0) for a, b in sorted(raw_edges)),
                        highlights=highlights,
                        queue_slots=after_queue,
                    )
                ] * 16
            )

        if event is None:
            glide = 22
            for step in range(1, glide + 1):
                t = ease(step / glide)
                positions = {
                    name: lerp_point(raw_positions[name], post_positions[name], t)
                    for name in post_positions
                }
                frames.append(
                    avl_insert_frame(
                        positions,
                        ((a, b, 1.0) for a, b in sorted(post_edges)),
                        queue_slots=after_queue,
                    )
                )
        else:
            middle = None
            if event in ("RL", "LR"):
                raw_children = raw_snapshot[1]
                pivot = raw_children[upper][1] if event == "RL" else raw_children[upper][0]
                assert pivot is not None
                middle = avl_insert_rotate_snapshot(raw_snapshot, pivot, "right" if event == "RL" else "left")
                middle_positions, middle_edges = avl_insert_layout(middle, ranks)
            if event == "RR":
                avl_insert_rotation_scene(
                    frames, raw_snapshot, post_snapshot, raw_positions, post_positions, upper, "left", highlights,
                    after_queue,
                )
            elif event == "LL":
                avl_insert_rotation_scene(
                    frames, raw_snapshot, post_snapshot, raw_positions, post_positions, upper, "right", highlights,
                    after_queue,
                )
            elif event == "RL":
                raw_children = raw_snapshot[1]
                right = raw_children[upper][1]
                assert right is not None
                assert middle is not None
                avl_insert_rotation_scene(
                    frames, raw_snapshot, middle, raw_positions, middle_positions, right, "right", highlights,
                    after_queue,
                )
                avl_insert_rotation_scene(
                    frames, middle, post_snapshot, middle_positions, post_positions, upper, "left", highlights,
                    after_queue,
                )
            else:
                raw_children = raw_snapshot[1]
                left = raw_children[upper][0]
                assert left is not None
                assert middle is not None
                avl_insert_rotation_scene(
                    frames, raw_snapshot, middle, raw_positions, middle_positions, left, "left", highlights,
                    after_queue,
                )
                avl_insert_rotation_scene(
                    frames, middle, post_snapshot, middle_positions, post_positions, upper, "right", highlights,
                    after_queue,
                )

        post_frame = avl_insert_frame(
            post_positions,
            ((a, b, 1.0) for a, b in sorted(post_edges)),
            queue_slots=after_queue,
        )
        frames.extend([post_frame] * max(6, AVL_INSERT_MIN_STEP_FRAMES - (len(frames) - step_start)))

    import re as _re

    def _frame_keys(frame: str) -> dict[str, tuple[float, float]]:
        positions: dict[str, tuple[float, float]] = {}
        for match in _re.finditer(
            r'<text x="([\-0-9.]+)" y="([\-0-9.]+)"[^>]*>([^<]+)</text>', frame
        ):
            x, y, label = float(match.group(1)), float(match.group(2)), match.group(3)
            positions[label] = (x, y)
        return positions

    MAX_STEP_PX = 90.0
    AUDIT_JUMPS = False
    previous_keys: dict[str, tuple[float, float]] = {}
    for frame_index, frame in enumerate(frames):
        if not AUDIT_JUMPS:
            break
        current_keys = _frame_keys(frame)
        for node_key, point in current_keys.items():
            if node_key in previous_keys:
                old_point = previous_keys[node_key]
                distance = ((point[0] - old_point[0]) ** 2 + (point[1] - old_point[1]) ** 2) ** 0.5
                assert distance <= MAX_STEP_PX, (
                    f"jump detected at frame {frame_index}: node {node_key} moved "
                    f"{distance:.1f}px ({old_point} -> {point})"
                )
        previous_keys = current_keys

    # This legacy asset is also used outside the recap renderer.  Keep the
    # frames limited to the tree so no narration is burned into the media.
    render_webm("avl-insertion", frames, fps=30, transparent=True, crop=False)


def bst_increasing() -> None:
    queue = {"10": (225.0, 80.0), "20": (375.0, 80.0), "30": (525.0, 80.0), "40": (675.0, 80.0)}
    final = {"10": (250.0, 205.0), "20": (400.0, 315.0), "30": (550.0, 425.0), "40": (700.0, 535.0)}
    keys = ["10", "20", "30", "40"]
    edge_by_key = {"20": ("10", "20"), "30": ("20", "30"), "40": ("30", "40")}
    frames: list[str] = []

    def frame(inserted_count: int, moving_key: str | None = None, moving_point: Point | None = None) -> str:
        positions: dict[str, Point] = {}
        inserted = set(keys[:inserted_count])
        for key in keys:
            if key in inserted:
                positions[key] = final[key]
            elif key == moving_key and moving_point is not None:
                positions[key] = moving_point
            else:
                positions[key] = queue[key]
        edges = [edge_by_key[key] for key in keys[1:inserted_count]]
        if moving_key in edge_by_key:
            edges.append(edge_by_key[moving_key])
        body = "".join(
            glow_line(positions[a], positions[b]) for a, b in edges
        )
        glow_override = {moving_key: GLOW_WHITE} if moving_key else {}
        for key, point in positions.items():
            body += glow_square(key, point, glow=glow_override.get(key, GLOW_BLUE))
        return svg(body, width=900, height=620, color=INK)

    hold = 12
    move = 30
    frames.extend([frame(0)] * hold)
    for index, key in enumerate(keys):
        for step in range(1, move + 1):
            t = step / move
            current = (lerp(queue[key][0], final[key][0], ease(t)), lerp(queue[key][1], final[key][1], ease(t)))
            frames.append(frame(index, key, current))
        frames.extend([frame(index + 1)] * hold)
    frames.extend([frame(len(keys))] * 30)
    render_webm("bst-increasing", frames, fps=30, transparent=True)


def avl_example_one_svg() -> str:
    positions = {
        "5": (165.0, 55.0),
        "3": (80.0, 155.0),
        "9": (250.0, 155.0),
        "6": (185.0, 255.0),
        "14": (315.0, 255.0),
        "17": (370.0, 355.0),
    }
    edges = [("5", "3"), ("5", "9"), ("9", "6"), ("9", "14"), ("14", "17")]
    body = "".join(glow_line(positions[a], positions[b]) for a, b in edges)
    body += "".join(glow_square(k, p) for k, p in positions.items())
    return svg(body, width=450, height=410, color=INK)


def avl_deep_subtrees_svg() -> str:
    """Keep the deep mounted subtrees readable without auto-layout crowding."""
    positions = {
        "z": (360.0, 45.0),
        "A": (175.0, 140.0),
        "y": (535.0, 140.0),
        "S1": (85.0, 240.0),
        "S2": (265.0, 240.0),
        "x": (440.0, 240.0),
        "D": (630.0, 240.0),
        "B": (390.0, 340.0),
        "S4": (565.0, 340.0),
        "S5": (695.0, 340.0),
        "S3": (340.0, 440.0),
    }
    edges = [
        ("z", "A"),
        ("z", "y"),
        ("A", "S1"),
        ("A", "S2"),
        ("y", "x"),
        ("y", "D"),
        ("x", "B"),
        ("B", "S3"),
        ("D", "S4"),
        ("D", "S5"),
    ]
    return binary_frame(positions, edges, color=SKY_BLUE, width=760, height=490)


CELL_W = 56.0
CELL_H = 40.0


def cell_slots(center: Point, count: int) -> list[Point]:
    """Tightly packed cell centers for `count` keys: one node is one contiguous array."""
    return [(center[0] + (index - (count - 1) / 2.0) * CELL_W, center[1]) for index in range(count)]


def cell_fragment(point: Point, key: str, opacity: float = 1.0, *, dashed: bool = False) -> str:
    """One key sealed inside its own little box; cells travel as whole units."""
    x, y = point
    left = x - CELL_W / 2
    top = y - CELL_H / 2
    dash = ' stroke-dasharray="7 4"' if dashed else ""
    return (
        f'<g opacity="{opacity:.3f}">'
        f'<rect class="node" x="{left:.1f}" y="{top:.1f}" width="{CELL_W:.1f}" height="{CELL_H:.1f}" rx="4"{dash}/>'
        f'<text class="bkey" x="{x:.1f}" y="{y:.1f}">{esc(key)}</text>'
        '</g>'
    )


def group_rect(members: Sequence[Point], home: Point | None = None) -> tuple[float, float, float, float]:
    """Bounding box of the bare cell row — nodes have no outer frame.

    Returns (left, top, right, bottom). An emptied group collapses onto its home center.
    """
    if not members:
        hx, hy = home if home is not None else (0.0, 0.0)
        return hx - CELL_W / 2, hy - CELL_H / 2, hx + CELL_W / 2, hy + CELL_H / 2
    return (
        min(p[0] for p in members) - CELL_W / 2,
        min(p[1] for p in members) - CELL_H / 2,
        max(p[0] for p in members) + CELL_W / 2,
        max(p[1] for p in members) + CELL_H / 2,
    )


def bscene_page(
    cells: Mapping[str, tuple[Point, str, float]],
    groups: Mapping[str, tuple[Sequence[str], Point, bool, float]],
    edges: Sequence[tuple[str, str, int, int, float]],
    *,
    width: int,
    height: int,
    overlay: str = "",
) -> str:
    """Assemble one frame of the array-style B-tree world.

    Nodes are bare rows of touching cells — no outer frames. Every edge hangs from a
    gap boundary under the parent row: with `total` children the anchors sit at
    row-left + slot * CELL_W, i.e. exactly on the dividers between cells.

    cells:  name -> (center, key text, opacity)
    groups: name -> (ordered member cell names, home center when empty, unused, unused)
    edges:  (parent group, child group, child slot, total children, opacity)
    """
    positions = {name: part[0] for name, part in cells.items()}
    rects = {
        name: group_rect([positions[m] for m in members], home)
        for name, (members, home, _, _) in groups.items()
    }
    parts: list[str] = []
    for parent, child, slot, total, opacity in edges:
        pl, pt, pr, pb = rects[parent]
        cl, ct, cr, cb = rects[child]
        start_x = min(pl + slot * CELL_W, pr)
        parts.append(f'<line class="edge" opacity="{opacity:.3f}" x1="{start_x:.1f}" y1="{pb:.1f}" x2="{(cl + cr) / 2.0:.1f}" y2="{ct:.1f}"/>')
    for name, (point, key, opacity) in cells.items():
        parts.append(cell_fragment(point, key, opacity))
    parts.append(overlay)
    return svg("".join(parts), width=width, height=height, color=SKY_BLUE)


def bscene_neon_page(
    cells: Mapping[str, tuple[Point, str, float]],
    groups: Mapping[str, tuple[Sequence[str], Point, bool, float]],
    edges: Sequence[tuple[str, str, int, int, float]],
    *,
    width: int,
    height: int,
) -> str:
    """Render the B-tree motion with the filled neon square style used by AVL."""
    positions = {name: part[0] for name, part in cells.items()}
    effective_groups = groups
    rects = {
        name: group_rect([positions[m] for m in members], home)
        for name, (members, home, _, _) in effective_groups.items()
    }
    parts: list[str] = []
    for parent, child, slot, _total, opacity in edges:
        pl, _pt, _pr, pb = rects[parent]
        cl, ct, cr, _cb = rects[child]
        start = (min(pl + slot * CELL_W, _pr), pb)
        end = ((cl + cr) / 2.0, ct)
        parts.append(btree_neon_edge(start, end, opacity=opacity))
    rendered: set[str] = set()
    group_items = []
    for group_index, (members, home, overflow, group_opacity) in enumerate(effective_groups.values()):
        names = [name for name in members if name in positions]
        points = [positions[name] for name in names]
        tight = bool(points) and (
            len(points) == 1
            or (
                max(point[1] for point in points) - min(point[1] for point in points) < 0.5
                and all(abs(points[index][0] - points[index - 1][0] - BTREE_NEON_CELL_W) <= 20.0 for index in range(1, len(points)))
            )
        )
        group_items.append((names, points, overflow, group_opacity, tight, group_index))

    for names, points, overflow, group_opacity, tight, _group_index in sorted(
        group_items, key=lambda item: (not item[4], -item[5])
    ):
        names = [name for name in names if name not in rendered]
        if not names:
            continue
        points = [positions[name] for name in names]
        if tight:
            opacity = min(cells[name][2] for name in names) * group_opacity
            parts.append(btree_neon_row_at_positions(names, points, opacity=opacity, overflow=overflow))
        else:
            for name in names:
                point, key, opacity = cells[name]
                parts.append(glow_square(key, point, size=BTREE_NEON_CELL, opacity=opacity * group_opacity, glow=GLOW_BLUE))
        rendered.update(names)
    for name, (point, key, opacity) in cells.items():
        if name not in rendered:
            parts.append(glow_square(key, point, size=BTREE_NEON_CELL, opacity=opacity, glow=GLOW_BLUE))
    return svg("".join(parts), width=width, height=height, color=INK)


def btree_insert() -> None:
    """One continuous order-4 tree: sequential splits merge beside existing keys, then a middle child split pushes the upper median straight into its parent slot."""
    width, height = 900, 600
    fill_c = (450.0, 505.0)
    root_c = (450.0, 305.0)
    top_root_c = (450.0, 110.0)

    def frame(cells, groups, edges) -> str:
        return bscene_neon_page(cells, groups, edges, width=width, height=height)

    def cell_map(positions: Mapping[str, Point]) -> dict:
        return {name: (pos, name, 1.0) for name, pos in positions.items()}

    def ramp(value: float) -> float:
        return min(1.0, max(0.0, value))

    def leaf(x: float) -> Point:
        return (x, 505.0)

    frames: list[str] = []
    frames.extend([frame({}, {}, ())] * 10)

    # Phase 1 — keys drop into one lone leaf until the fourth key overflows it.
    positions: dict[str, Point] = {}
    for index, value in enumerate(("10", "20", "30", "40")):
        targets: dict[str, Point] = dict(zip(("10", "20", "30", "40"), cell_slots(fill_c, index + 1)))
        falling_target = targets[value]
        for step in range(1, 15):
            t = ease(step / 14.0)
            moving = {name: lerp_point(start, targets[name], t) for name, start in positions.items()}
            moving[value] = lerp_point((falling_target[0], -30.0), falling_target, t)
            groups = {"node": (list(positions.keys()), fill_c, False, 1.0)}
            frames.append(frame(cell_map(moving), groups, ()))
        positions = targets
        frames.extend([frame(cell_map(positions), {"node": (list(positions.keys()), fill_c, False, 1.0)}, ())] * 12)

    # Split 1 — the upper median 30 rises into a new root; [10,20] and [40] become its children.
    s1 = {"10": leaf(222), "20": leaf(278), "30": cell_slots(root_c, 1)[0], "40": leaf(650)}
    for step in range(1, 47):
        t = ease(step / 46.0)
        pos = {name: lerp_point(positions[name], s1[name], t) for name in positions}
        born = 1.0
        edge_in = 1.0
        groups = {
            "left": (["10", "20"], leaf(250), False, born),
            "root": (["30"], root_c, False, born),
            "right": (["40"], leaf(650), False, born),
        }
        edges = (("root", "left", 0, 2, edge_in), ("root", "right", 1, 2, edge_in))
        frames.append(frame(cell_map(pos), groups, edges))
    positions = dict(s1)
    stage_two_groups = {
        "left": (["10", "20"], leaf(250), False, 1.0),
        "root": (["30"], root_c, False, 1.0),
        "right": (["40"], leaf(650), False, 1.0),
    }
    stage_two_edges = (("root", "left", 0, 2, 1.0), ("root", "right", 1, 2, 1.0))
    frames.extend([frame(cell_map(positions), stage_two_groups, stage_two_edges)] * 18)

    # Phase 2 — 50 lands in the right leaf.
    for step in range(1, 15):
        t = ease(step / 14.0)
        pos = dict(positions)
        pos["40"] = lerp_point(s1["40"], leaf(622), t)
        pos["50"] = lerp_point((678.0, -30.0), leaf(678), t)
        frames.append(frame(cell_map(pos), stage_two_groups, stage_two_edges))
    positions.update({"40": leaf(622), "50": leaf(678)})
    stage_two_groups["right"] = (["40", "50"], leaf(650), False, 1.0)
    frames.extend([frame(cell_map(positions), stage_two_groups, stage_two_edges)] * 12)

    # Phase 3 — 60 joins the right leaf.
    for step in range(1, 15):
        t = ease(step / 14.0)
        pos = dict(positions)
        pos["40"] = lerp_point(positions["40"], leaf(594), t)
        pos["50"] = lerp_point(positions["50"], leaf(650), t)
        pos["60"] = lerp_point((706.0, -30.0), leaf(706), t)
        frames.append(frame(cell_map(pos), stage_two_groups, stage_two_edges))
    positions.update({"40": leaf(594), "50": leaf(650), "60": leaf(706)})
    stage_two_groups["right"] = (["40", "50", "60"], leaf(650), False, 1.0)
    frames.extend([frame(cell_map(positions), stage_two_groups, stage_two_edges)] * 12)

    # Phase 4 — 70 overflows the right leaf.
    for step in range(1, 15):
        t = ease(step / 14.0)
        pos = dict(positions)
        pos["40"] = lerp_point(positions["40"], leaf(566), t)
        pos["50"] = lerp_point(positions["50"], leaf(622), t)
        pos["60"] = lerp_point(positions["60"], leaf(678), t)
        pos["70"] = lerp_point((734.0, -30.0), leaf(734), t)
        frames.append(frame(cell_map(pos), stage_two_groups, stage_two_edges))
    positions.update({"40": leaf(566), "50": leaf(622), "60": leaf(678), "70": leaf(734)})
    stage_two_groups["right"] = (["40", "50", "60", "70"], leaf(650), True, 1.0)
    frames.extend([frame(cell_map(positions), stage_two_groups, stage_two_edges)] * 12)

    # Split 2 — the upper median 50 is promoted. The original line from 30 to the left
    # half never breaks: its parent anchor stays on 30's right boundary, which is exactly
    # where 50's left tether will land, so the two lines coincide after docking.
    s3 = {
        "10": leaf(122),
        "20": leaf(178),
        "30": (422.0, 305.0),
        "60": (478.0, 305.0),
        "40": leaf(422),
        "50": leaf(478),
        "70": leaf(750),
    }
    hover60 = (678.0, 305.0)
    for step in range(1, 47):
        t = ease(step / 46.0)
        pos = {name: lerp_point(positions[name], s3[name], t) for name in positions}
        pos["60"] = lerp_point(positions["60"], hover60, t)
        born = 1.0
        edge_in = 1.0
        groups = {
            "left": (["10", "20"], leaf(150), False, born),
            "mid": (["40", "50"], leaf(450), False, born),
            "right": (["70"], leaf(750), False, born),
            "promo": (["60"], hover60, False, 1.0),
            "root": (["30"], root_c, False, born),
        }
        edges = (
            ("root", "left", 0, 2, 1.0),        # original line, never breaks
            ("root", "mid", 1, 2, 1.0),         # original line, retargeted onto the left half
            ("promo", "mid", 0, 2, edge_in),    # tether from 50's left boundary — will coincide
            ("promo", "right", 1, 2, edge_in),  # tether from 50's right boundary
        )
        frames.append(frame(cell_map(pos), groups, edges))

    # 50 hangs between the levels as an independent node, both lines taut.
    hover_cells = cell_map(s3)
    hover_cells["60"] = (hover60, "60", 1.0)
    hover_groups = {
        "left": (["10", "20"], leaf(150), False, 1.0),
        "mid": (["40", "50"], leaf(450), False, 1.0),
        "right": (["70"], leaf(750), False, 1.0),
        "promo": (["60"], hover60, False, 1.0),
        "root": (["30"], root_c, False, 1.0),
    }
    hover_edges = (
        ("root", "left", 0, 2, 1.0),
        ("root", "mid", 1, 2, 1.0),
        ("promo", "mid", 0, 2, 1.0),
        ("promo", "right", 1, 2, 1.0),
    )
    frames.extend([frame(hover_cells, hover_groups, hover_edges)] * 10)

    # Dock — 50 lands beside 30; its left tether coincides exactly with the original line.
    for step in range(1, 13):
        t = ease(step / 12.0)
        pos = dict(s3)
        pos["60"] = lerp_point(hover60, s3["60"], t)
        # A row exists only when the key reaches the exact adjacent slot. Any
        # earlier switch would attach formal parent edges to a still-floating
        # cell and create a visible topology jump.
        joined = step == 12
        groups = {
            "left": (["10", "20"], leaf(150), False, 1.0),
            "mid": (["40", "50"], leaf(450), False, 1.0),
            "right": (["70"], leaf(750), False, 1.0),
            "root": (["30", "60"] if joined else ["30"], root_c, False, 1.0),
        }
        if not joined:
            groups["promo"] = (["60"], hover60, False, 1.0)
            edges = hover_edges
        else:
            edges = (
                ("root", "left", 0, 3, 1.0),
                ("root", "mid", 1, 3, 1.0),
                ("root", "right", 2, 3, 1.0),
            )
        frames.append(frame(cell_map(pos), groups, edges))

    positions = dict(s3)
    stage_three_groups = {
        "left": (["10", "20"], leaf(150), False, 1.0),
        "mid": (["40", "50"], leaf(450), False, 1.0),
        "right": (["70"], leaf(750), False, 1.0),
        "root": (["30", "60"], root_c, False, 1.0),
    }
    stage_three_edges = (
        ("root", "left", 0, 3, 1.0),
        ("root", "mid", 1, 3, 1.0),
        ("root", "right", 2, 3, 1.0),
    )
    frames.extend([frame(cell_map(positions), stage_three_groups, stage_three_edges)] * 16)

    # Phase 5 — 45 lands in the middle leaf sitting between its two siblings.
    for step in range(1, 15):
        t = ease(step / 14.0)
        pos = dict(positions)
        pos["40"] = lerp_point(positions["40"], leaf(394), t)
        pos["50"] = lerp_point(positions["50"], leaf(506), t)
        pos["45"] = lerp_point((450.0, -30.0), leaf(450), t)
        frames.append(frame(cell_map(pos), stage_three_groups, stage_three_edges))
    positions.update({"40": leaf(394), "45": leaf(450), "50": leaf(506)})
    stage_three_groups["mid"] = (["40", "45", "50"], leaf(450), False, 1.0)
    frames.extend([frame(cell_map(positions), stage_three_groups, stage_three_edges)] * 12)

    # Phase 6 — 55 joins the middle leaf; four keys overflow it.
    for step in range(1, 15):
        t = ease(step / 14.0)
        pos = dict(positions)
        pos["40"] = lerp_point(positions["40"], leaf(366), t)
        pos["45"] = lerp_point(positions["45"], leaf(422), t)
        pos["50"] = lerp_point(positions["50"], leaf(478), t)
        pos["55"] = lerp_point((534.0, -30.0), leaf(534), t)
        frames.append(frame(cell_map(pos), stage_three_groups, stage_three_edges))
    positions.update({"40": leaf(366), "45": leaf(422), "50": leaf(478), "55": leaf(534)})
    stage_three_groups["mid"] = (["40", "45", "50", "55"], leaf(450), True, 1.0)
    frames.extend([frame(cell_map(positions), stage_three_groups, stage_three_edges)] * 12)

    # Split 3, beat 1 — the parent tears open between 30 and 60 to make room;
    # the overflowing middle leaf keeps its overflow rim during the tear.
    for step in range(1, 13):
        t = ease(step / 12.0)
        pos = dict(positions)
        pos["30"] = lerp_point(positions["30"], (394.0, 305.0), t)
        pos["60"] = lerp_point(positions["60"], (506.0, 305.0), t)
        frames.append(frame(cell_map(pos), stage_three_groups, stage_three_edges))
    positions.update({"30": (394.0, 305.0), "60": (506.0, 305.0)})
    frames.extend([frame(cell_map(positions), stage_three_groups, stage_three_edges)] * 8)

    # Split 3, beat 2 — the upper median 50 is pushed straight up into the opened
    # slot between 30 and 60: it never hovers at the parent height and never
    # slides sideways. The two leaf halves stay where the tear left them, so the
    # only moving cell is 50 itself; its left tether coincides with 30's
    # original line and its right tether with the row edge on arrival.
    s4 = {
        "10": leaf(122),
        "20": leaf(178),
        "30": (394.0, 305.0),
        "50": (450.0, 305.0),
        "60": (506.0, 305.0),
        "40": leaf(366),
        "45": leaf(422),
        "55": leaf(534),
        "70": leaf(750),
    }
    for step in range(1, 47):
        t = ease(step / 46.0)
        pos = {name: lerp_point(positions[name], s4[name], t) for name in positions}
        joined = step >= 43
        groups = {
            "left": (["10", "20"], leaf(150), False, 1.0),
            "half_left": (["40", "45"], leaf(394), False, 1.0),
            "half_right": (["55"], leaf(534), False, 1.0),
            "right": (["70"], leaf(750), False, 1.0),
            "root": (["30", "50", "60"] if joined else ["30", "60"], root_c, False, 1.0),
        }
        if not joined:
            groups["promo"] = (["50"], pos["50"], False, 1.0)
            edges = (
                ("root", "left", 0, 3, 1.0),
                ("root", "half_left", 1, 3, 1.0),
                ("root", "right", 2, 3, 1.0),
                ("promo", "half_left", 0, 2, 1.0),
                ("promo", "half_right", 1, 2, 1.0),
            )
        else:
            edges = (
                ("root", "left", 0, 4, 1.0),
                ("root", "half_left", 1, 4, 1.0),
                ("root", "half_right", 2, 4, 1.0),
                ("root", "right", 3, 4, 1.0),
            )
        frames.append(frame(cell_map(pos), groups, edges))

    final_cells = dict(s4)
    final_groups = {
        "left": (["10", "20"], leaf(150), False, 1.0),
        "half_left": (["40", "45"], leaf(394), False, 1.0),
        "half_right": (["55"], leaf(534), False, 1.0),
        "right": (["70"], leaf(750), False, 1.0),
        "root": (["30", "50", "60"], root_c, False, 1.0),
    }
    final_edges = (
        ("root", "left", 0, 4, 1.0),
        ("root", "half_left", 1, 4, 1.0),
        ("root", "half_right", 2, 4, 1.0),
        ("root", "right", 3, 4, 1.0),
    )
    frames.extend([frame(cell_map(final_cells), final_groups, final_edges)] * 30)

    # Phase 7 — continue in the rightmost leaf. An incoming key is not part of
    # the tree until it touches down: it has no parent edge while falling.
    # Existing keys reposition around its computed slot, so each completed row
    # remains one contiguous B-tree node.
    positions = dict(final_cells)
    stage_three_groups = dict(final_groups)
    stage_three_edges = final_edges
    right_names = ["70"]
    for value in ("80", "90", "100"):
        before = {name: positions[name] for name in right_names}
        names = [*right_names, value]
        targets = dict(zip(names, cell_slots(leaf(750), len(names))))
        for step in range(1, 15):
            t = ease(step / 14.0)
            pos = dict(positions)
            for name in right_names:
                pos[name] = lerp_point(before[name], targets[name], t)
            pos[value] = lerp_point((targets[value][0], -30.0), targets[value], t)
            groups = dict(stage_three_groups)
            groups["right"] = (right_names, leaf(750), False, 1.0)
            groups["incoming"] = ([value], pos[value], False, 1.0)
            frames.append(frame(cell_map(pos), groups, stage_three_edges))
        positions.update(targets)
        right_names = names
        stage_three_groups["right"] = (right_names, leaf(750), value == "100", 1.0)
        frames.extend([frame(cell_map(positions), stage_three_groups, stage_three_edges)] * 12)

    # Split 4 follows Split 2's established two-step grammar. The existing
    # parent remains intact while the promoted leader is lifted by two chains,
    # held as its own node, then moves sideways into the parent row.
    parent_targets = dict(zip(("30", "50", "60", "90"), cell_slots(root_c, 4)))
    hover90 = (678.0, 305.0)
    split90_targets = {
        "10": leaf(122), "20": leaf(178),
        "30": parent_targets["30"],
        "40": cell_slots(leaf(394), 2)[0], "45": cell_slots(leaf(394), 2)[1],
        "50": parent_targets["50"],
        "55": leaf(534),
        "60": parent_targets["60"],
        "70": cell_slots(leaf(650), 2)[0], "80": cell_slots(leaf(650), 2)[1],
        "90": hover90, "100": leaf(800),
    }
    split90_before = dict(positions)
    for step in range(1, 47):
        t = ease(step / 46.0)
        pos = {name: lerp_point(split90_before[name], target, t) for name, target in split90_targets.items()}
        groups = {
            "left": (["10", "20"], leaf(150), False, 1.0),
            "half_left": (["40", "45"], leaf(394), False, 1.0),
            "half_right": (["55"], leaf(534), False, 1.0),
            "right": (["70", "80"], leaf(650), False, 1.0),
            "far_right": (["100"], leaf(800), False, 1.0),
            "root": (["30", "50", "60"], root_c, False, 1.0),
            "promo": (["90"], pos["90"], False, 1.0),
        }
        edges = (
            ("root", "left", 0, 4, 1.0),
            ("root", "half_left", 1, 4, 1.0),
            ("root", "half_right", 2, 4, 1.0),
            ("root", "right", 3, 4, 1.0),
            ("promo", "right", 0, 2, 1.0),
            ("promo", "far_right", 1, 2, 1.0),
        )
        frames.append(frame(cell_map(pos), groups, edges))
    positions = dict(split90_targets)
    hover90_groups = {
        "left": (["10", "20"], leaf(150), False, 1.0),
        "half_left": (["40", "45"], leaf(394), False, 1.0),
        "half_right": (["55"], leaf(534), False, 1.0),
        "right": (["70", "80"], leaf(650), False, 1.0),
        "far_right": (["100"], leaf(800), False, 1.0),
        "root": (["30", "50", "60"], root_c, False, 1.0),
        "promo": (["90"], hover90, False, 1.0),
    }
    hover90_edges = (
        ("root", "left", 0, 4, 1.0),
        ("root", "half_left", 1, 4, 1.0),
        ("root", "half_right", 2, 4, 1.0),
        ("root", "right", 3, 4, 1.0),
        ("promo", "right", 0, 2, 1.0),
        ("promo", "far_right", 1, 2, 1.0),
    )
    frames.extend([frame(cell_map(positions), hover90_groups, hover90_edges)] * 10)
    stage_four_groups = {name: value for name, value in hover90_groups.items() if name != "promo"}
    stage_four_groups["root"] = (["30", "50", "60", "90"], root_c, True, 1.0)
    stage_four_edges = (
        ("root", "left", 0, 5, 1.0),
        ("root", "half_left", 1, 5, 1.0),
        ("root", "half_right", 2, 5, 1.0),
        ("root", "right", 3, 5, 1.0),
        ("root", "far_right", 4, 5, 1.0),
    )
    for step in range(1, 13):
        t = ease(step / 12.0)
        pos = dict(positions)
        pos["90"] = lerp_point(hover90, parent_targets["90"], t)
        if step < 12:
            groups = dict(hover90_groups)
            groups["promo"] = (["90"], pos["90"], False, 1.0)
            frames.append(frame(cell_map(pos), groups, hover90_edges))
        else:
            frames.append(frame(cell_map(pos), stage_four_groups, stage_four_edges))
    positions = dict(split90_targets)
    positions["90"] = parent_targets["90"]
    frames.extend([frame(cell_map(positions), stage_four_groups, stage_four_edges)] * 12)

    # The final parent split has no receiving parent. Its two new internal
    # children directly carry 60 upward; their chains exist for the whole lift
    # and become the new-root links exactly when 60 reaches the root position.
    final_positions = {
        "60": cell_slots(top_root_c, 1)[0],
        "30": cell_slots((330.0, 305.0), 2)[0],
        "50": cell_slots((330.0, 305.0), 2)[1],
        "90": cell_slots((650.0, 305.0), 1)[0],
        "10": cell_slots(leaf(150), 2)[0],
        "20": cell_slots(leaf(150), 2)[1],
        "40": cell_slots(leaf(330), 2)[0],
        "45": cell_slots(leaf(330), 2)[1],
        "55": leaf(450),
        "70": cell_slots(leaf(650), 2)[0],
        "80": cell_slots(leaf(650), 2)[1],
        "100": leaf(800),
    }
    final_groups = {
        "root": (["60"], top_root_c, False, 1.0),
        "left_internal": (["30", "50"], (330.0, 305.0), False, 1.0),
        "right_internal": (["90"], (650.0, 305.0), False, 1.0),
        "left_a": (["10", "20"], leaf(150), False, 1.0),
        "left_b": (["40", "45"], leaf(330), False, 1.0),
        "left_c": (["55"], leaf(450), False, 1.0),
        "right_a": (["70", "80"], leaf(650), False, 1.0),
        "right_b": (["100"], leaf(800), False, 1.0),
    }
    final_tree_edges = (
        ("root", "left_internal", 0, 2, 1.0),
        ("root", "right_internal", 1, 2, 1.0),
        ("left_internal", "left_a", 0, 3, 1.0),
        ("left_internal", "left_b", 1, 3, 1.0),
        ("left_internal", "left_c", 2, 3, 1.0),
        ("right_internal", "right_a", 0, 2, 1.0),
        ("right_internal", "right_b", 1, 2, 1.0),
    )
    parent_split_before = dict(positions)
    for step in range(1, 47):
        t = ease(step / 46.0)
        pos = {
            name: lerp_point(parent_split_before[name], target, t)
            for name, target in final_positions.items()
        }
        pos["60"] = lerp_point(parent_split_before["60"], final_positions["60"], t)
        moving_groups = {
            "promo": (["60"], pos["60"], False, 1.0),
            "left_internal": (["30", "50"], (330.0, 305.0), False, 1.0),
            "right_internal": (["90"], (650.0, 305.0), False, 1.0),
            "left_a": (["10", "20"], leaf(150), False, 1.0),
            "left_b": (["40", "45"], leaf(330), False, 1.0),
            "left_c": (["55"], leaf(450), False, 1.0),
            "right_a": (["70", "80"], leaf(650), False, 1.0),
            "right_b": (["100"], leaf(800), False, 1.0),
        }
        moving_edges = (
            # The separated internal nodes carry 60 throughout its ascent.
            ("promo", "left_internal", 0, 2, 1.0),
            ("promo", "right_internal", 1, 2, 1.0),
            ("left_internal", "left_a", 0, 3, 1.0),
            ("left_internal", "left_b", 1, 3, 1.0),
            ("left_internal", "left_c", 2, 3, 1.0),
            ("right_internal", "right_a", 0, 2, 1.0),
            ("right_internal", "right_b", 1, 2, 1.0),
        )
        frames.append(frame(cell_map(pos), moving_groups, moving_edges))
    frames.extend([frame(cell_map(final_positions), final_groups, final_tree_edges)] * 10)
    frames.extend([frame(cell_map(final_positions), final_groups, final_tree_edges)] * 30)
    render_webm("btree-insert", frames, fps=30, transparent=True)


RB_NODE_W = 56.0
RB_NODE_H = 40.0
RB_RED = "#DC2626"
RB_RED_GLOW = "#F87171"
RB_BLACK_FILL = "#111827"
RB_BLACK_INK = "#64748B"
RB_BLACK_GLOW = "#94A3B8"


def _box_trim(start: Point, end: Point) -> tuple[float, float, float, float]:
    """Trim a segment to the borders of the two square nodes."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    distance = (dx * dx + dy * dy) ** 0.5 or 1.0
    ux, uy = dx / distance, dy / distance
    trim = min(
        RB_NODE_W / 2 / abs(ux) if ux else float("inf"),
        RB_NODE_H / 2 / abs(uy) if uy else float("inf"),
    )
    return start[0] + ux * trim, start[1] + uy * trim, end[0] - ux * trim, end[1] - uy * trim


def rb_node(point: Point, key: str, opacity: float = 1.0, *, red: bool) -> str:
    """One neon red-black square: glowing halo, colored body, white key."""
    x, y = point
    left = x - RB_NODE_W / 2
    top = y - RB_NODE_H / 2
    glow = RB_RED_GLOW if red else RB_BLACK_GLOW
    body = bloom_rect(point, RB_NODE_W, RB_NODE_H, glow, opacity * 0.85, radius=9.0)
    if red:
        body += (
            f'<rect fill="{RB_RED}" stroke="{RB_RED_GLOW}" stroke-width="1.6" opacity="{opacity:.3f}" '
            f'x="{left:.1f}" y="{top:.1f}" width="{RB_NODE_W:.1f}" height="{RB_NODE_H:.1f}" rx="9"/>'
        )
    else:
        body += (
            f'<rect fill="{RB_BLACK_FILL}" stroke="{RB_BLACK_INK}" stroke-width="1.8" opacity="{opacity:.3f}" '
            f'x="{left:.1f}" y="{top:.1f}" width="{RB_NODE_W:.1f}" height="{RB_NODE_H:.1f}" rx="9"/>'
        )
    return body + (
        f'<text fill="#FFFFFF" opacity="{opacity:.3f}" x="{x:.1f}" y="{y:.1f}" font-size="20px" font-weight="600" '
        f'text-anchor="middle" dominant-baseline="middle" font-family="Noto Sans CJK SC,system-ui,sans-serif">{esc(key)}</text>'
    )


def rb_edge_fragment(start: Point, end: Point, opacity: float, red: object) -> str:
    """One white structural edge; red/black remains a node property."""
    x1, y1, x2, y2 = _box_trim(start, end)
    return glow_line(
        (x1, y1),
        (x2, y2),
        opacity=opacity,
        color=INK,
        bloom=GLOW_WHITE,
        width=3.4,
        radius=0.0,
    )


def rb_crossfade_square(point: Point, key: str, from_red: bool, to_red: bool, blend: float) -> str:
    """Neon crossfade of one square between red and black membership."""
    return rb_node(point, key, 1.0 - blend, red=from_red) + rb_node(point, key, blend, red=to_red)


def rb_crossfade_edge(start: Point, end: Point, from_red: bool, to_red: bool, blend: float) -> str:
    """Neon crossfade of one link between red and black coloring."""
    return rb_edge_fragment(start, end, 1.0 - blend, from_red) + rb_edge_fragment(start, end, blend, to_red)


def rb_nil_fragment(center: Point, opacity: float) -> str:
    x, y = center
    return (
        f'<g opacity="{opacity:.3f}">'
        f'<rect fill="none" stroke="{RB_BLACK_INK}" stroke-width="3" x="{x - RB_NODE_W / 2:.1f}" y="{y - RB_NODE_H / 2:.1f}" width="{RB_NODE_W:.1f}" height="{RB_NODE_H:.1f}" rx="4"/>'
        f'<rect fill="none" stroke="{RB_BLACK_INK}" stroke-width="2" x="{x - RB_NODE_W / 2 + 8:.1f}" y="{y - RB_NODE_H / 2 + 6:.1f}" width="{RB_NODE_W - 16:.1f}" height="{RB_NODE_H - 12:.1f}" rx="4"/>'
        f'<text fill="{RB_BLACK_INK}" font-size="17px" text-anchor="middle" dominant-baseline="middle" font-family="Noto Sans CJK SC,system-ui,sans-serif" x="{x:.1f}" y="{y:.1f}">NIL</text></g>'
    )


def rb_scene(
    nodes: Sequence[tuple[str, Point, float, bool]],
    edges: Sequence[tuple[str, str, float, bool]],
    *,
    nil: tuple[Point, float] | None = None,
    width: int = WIDTH,
    height: int = HEIGHT,
) -> str:
    """One complete colored red-black frame from (key, position, opacity, red) tuples."""
    positions = {key: point for key, point, _, _ in nodes}
    if nil is not None and nil[1] > 0.0:
        positions.setdefault("NIL", nil[0])
    parts = [rb_edge_fragment(positions[a], positions[b], opacity, red) for a, b, opacity, red in edges]
    parts += [rb_node(point, key, opacity, red=red) for key, point, opacity, red in nodes]
    if nil is not None:
        point, opacity = nil
        parts.append(rb_nil_fragment(point, opacity))
    return svg("".join(parts), width=width, height=height, color=INK)


def rb_balanced_case_frame(
    nodes: Mapping[str, tuple[Point, bool]],
    edges: Sequence[tuple[str, str] | tuple[str, str, float]],
    *,
    caption: str,
    width: int = 900,
    height: int = 620,
    focus_nodes: Collection[str] = (),
    focus_edges: Collection[tuple[str, str]] = (),
    color_transitions: Mapping[str, tuple[bool, bool, float]] | None = None,
) -> str:
    """Render a local insertion repair with its current topology visible."""
    positions = {key: point for key, (point, _red) in nodes.items()}
    def edge_parts(edge: tuple[str, str] | tuple[str, str, float]) -> tuple[str, str, float]:
        parent, child, *opacity = edge
        return parent, child, opacity[0] if opacity else 1.0

    body = "".join(
        rb_edge_fragment(positions[parent], positions[child], opacity, False)
        for edge in edges
        for parent, child, opacity in (edge_parts(edge),)
        if opacity > 0.0
    )
    edge_opacities = {
        (parent, child): opacity
        for edge in edges
        for parent, child, opacity in (edge_parts(edge),)
    }
    body += "".join(
        rb_edge_fragment(
            positions[parent],
            positions[child],
            edge_opacities.get((parent, child), 1.0),
            False,
        ).replace('stroke-width="3.4"', 'stroke-width="6.0"')
        for parent, child in focus_edges
        if parent in positions and child in positions
        and edge_opacities.get((parent, child), 1.0) > 0.0
    )
    transitions = color_transitions or {}

    def draw_node(key: str, point: Point, red: bool) -> str:
        transition = transitions.get(key)
        if transition is None:
            return rb_node(point, key, red=red)
        from_red, to_red, blend = transition
        return rb_node(point, key, 1.0 - blend, red=from_red) + rb_node(point, key, blend, red=to_red)

    body += "".join(
        draw_node(key, point, red)
        for key, (point, red) in nodes.items()
        if key not in focus_nodes
    )
    body += "".join(
        glow_ring(positions[key], color=GLOW_WHITE, extra=8.0)
        + draw_node(key, positions[key], nodes[key][1])
        for key in focus_nodes
    )
    return svg(body, width=width, height=height, color=INK)


def rotate_segment_about_center(
    start_a: Point,
    start_b: Point,
    target_a: Point,
    target_b: Point,
    progress: float,
) -> tuple[Point, Point]:
    """Rotate a two-node balance around its fixed midpoint."""
    center = ((start_a[0] + start_b[0]) / 2.0, (start_a[1] + start_b[1]) / 2.0)
    start_angle = atan2(start_b[1] - start_a[1], start_b[0] - start_a[0])
    target_angle = atan2(target_b[1] - target_a[1], target_b[0] - target_a[0])
    delta = (target_angle - start_angle + pi) % (2.0 * pi) - pi
    angle = delta * progress
    c, s = cos(angle), sin(angle)

    def rotate(point: Point) -> Point:
        dx, dy = point[0] - center[0], point[1] - center[1]
        return (center[0] + dx * c - dy * s, center[1] + dx * s + dy * c)

    return rotate(start_a), rotate(start_b)


def _rb_ll_rr_legacy() -> None:
    """Show a right-right violation while rotating only the 51—52 balance."""
    fixed = {"55": ((450.0, 120.0), False), "57": ((650.0, 300.0), False)}
    start = {**fixed, "51": ((300.0, 300.0), False), "52": ((420.0, 420.0), True), "54": ((540.0, 540.0), True)}
    rotated_51, rotated_52 = (300.0, 420.0), (420.0, 300.0)
    final = {**fixed, "52": (rotated_52, False), "51": (rotated_51, True), "54": ((540.0, 420.0), True)}
    wait = (start["54"][0][0], 700.0)

    def page(nodes, edges, caption, focus=(), transitions=None):
        return rb_balanced_case_frame(
            nodes,
            edges,
            caption=caption,
            focus_nodes=focus,
            color_transitions=transitions,
        )

    old_edges = (("55", "51"), ("51", "52"), ("52", "54"), ("55", "57"))
    balance_edges = (("51", "52"),)
    new_edges = (("55", "52"), ("52", "51"), ("52", "54"), ("55", "57"))
    frames = [page(start, old_edges, "先看形状：55 左侧的 51—52—54 违反不红红")] * 24

    # Find the balance, then detach only its mounted cargo 54.
    for step in range(1, 31):
        t = ease(step / 30.0)
        nodes = dict(start)
        nodes["54"] = (lerp_point(start["54"][0], wait, t), True)
        frames.append(page(nodes, (("51", "52"), ("55", "57")),
                           "找到天平 51—52：先摘下右边货物 54", ("51", "52")))
    frames.extend([page({**start, "54": (wait, True)}, (balance_edges[0], ("55", "57")),
                         "只剩天平 51—52，55 和 57 保持不动", ("51", "52"))] * 18)

    # Rotate only the two-node balance. The lever centre and angle define the
    # actual motion; the rest of the tree is not interpolated.
    for step in range(1, 49):
        t = ease(step / 48.0)
        p51, p52 = rotate_segment_about_center(
            start["51"][0], start["52"][0], rotated_51, rotated_52, t
        )
        nodes = {**fixed, "51": (p51, False), "52": (p52, True), "54": (wait, True)}
        frames.append(page(nodes, (balance_edges[0], ("55", "57")), "只旋转天平 51—52，树的其他部分不动", ("51", "52")))

    # Put the right cargo back first. The new parent edge is still absent.
    connected = {**final, "52": (final["52"][0], True), "51": (final["51"][0], False)}
    for step in range(1, 31):
        t = ease(step / 30.0)
        nodes = {**connected, "54": (lerp_point(wait, connected["54"][0], t), True)}
        frames.append(page(nodes, (("52", "51"), ("52", "54"), ("55", "57")),
                           "天平旋转完成，54 按原来的右侧货物位置接回", ("52",)))
    frames.extend([page(connected, (("52", "51"), ("52", "54"), ("55", "57")),
                         "54 已恢复连接，接下来恢复 52—55", ("52",))] * 14)
    # Restore the parent edge only after the cargo edge is stable.
    frames.extend([page(connected, new_edges, "最后恢复 52—55 的连接")] * 16)
    frames.extend([page(connected, new_edges, "连接全部恢复，最后才进行变色")] * 14)
    for step in range(1, 31):
        t = ease(step / 30.0)
        nodes = dict(connected)
        if t >= 0.5:
            nodes["52"] = (final["52"][0], False)
            nodes["51"] = (final["51"][0], True)
        frames.append(page(
            nodes,
            new_edges,
            "最后变色：52 黑，51 和 54 红",
            ("52",),
            {"52": (True, False, t), "51": (False, True, t)},
        ))
    render_webm("rb-ll-rr", frames, fps=30, transparent=True, zoom=1.0)


def _rb_lr_rl_legacy() -> None:
    """Show a right-left violation with two successive balance-only rotations."""
    fixed = {"15": ((270.0, 300.0), False)}
    start = {**fixed, "20": ((450.0, 120.0), False), "23": ((650.0, 300.0), True),
             "21": ((550.0, 420.0), True), "22": ((650.0, 540.0), False)}
    after_first = {**fixed, "20": ((450.0, 120.0), False), "21": ((550.0, 300.0), True),
                   "23": ((650.0, 420.0), True), "22": ((650.0, 540.0), False)}
    final = {"21": ((600.0, 120.0), False), "20": ((400.0, 300.0), True),
             "23": ((700.0, 300.0), True), "22": ((700.0, 460.0), False),
             "15": ((300.0, 460.0), False)}
    wait22 = (start["22"][0][0], 700.0)
    wait15 = (start["15"][0][0], 650.0)
    wait23 = (start["23"][0][0], 700.0)
    old_edges = (("20", "15"), ("20", "23"), ("23", "21"), ("21", "22"))
    first_edges = (("20", "15"), ("20", "21"), ("21", "23"), ("23", "22"))
    final_edges = (("21", "20"), ("20", "15"), ("21", "23"), ("23", "22"))

    def page(nodes, edges, caption, focus=(), transitions=None):
        return rb_balanced_case_frame(
            nodes,
            edges,
            caption=caption,
            focus_nodes=focus,
            color_transitions=transitions,
        )

    frames = [page(start, old_edges, "先找天平：20—23，右子树更高且 23—21 形成折线", ("20", "23"))] * 26
    # First rotation: detach only the small balance's cargo 22.
    for step in range(1, 31):
        t = ease(step / 30.0)
        nodes = dict(start)
        nodes["22"] = (lerp_point(start["22"][0], wait22, t), False)
        frames.append(page(nodes, (("20", "15"), ("20", "23"), ("23", "21")),
                           "第一次：找到小天平 23—21，先摘下货物 22", ("23", "21")))
    small_start_a, small_start_b = start["23"][0], start["21"][0]
    small_target_a, small_target_b = (600.0, 360.0), (700.0, 360.0)
    for step in range(1, 49):
        t = ease(step / 48.0)
        p23, p21 = rotate_segment_about_center(
            small_start_a,
            small_start_b,
            small_target_a,
            small_target_b,
            t,
        )
        nodes = {"20": start["20"], "15": start["15"], "23": (p23, True),
                 "21": (p21, True), "22": (wait22, False)}
        frames.append(page(nodes, (("20", "15"), ("23", "21")), "只旋转小天平 23—21，20 和 15 不动", ("23", "21")))
    for step in range(1, 25):
        t = ease(step / 24.0)
        nodes = dict(after_first)
        nodes["22"] = (lerp_point(wait22, after_first["22"][0], t), False)
        frames.append(page(nodes, (("20", "15"), ("21", "23"), ("23", "22")), "小天平完成：先接回 23—22，20—21 稍后恢复", ("21",)))
    frames.extend([page(after_first, (("20", "15"), ("21", "23"), ("23", "22")),
                         "23—22 已恢复，接下来恢复 20—21", ("21",))] * 14)

    # Second rotation: re-identify the balance as 20—21 and rotate only it.
    for step in range(1, 31):
        t = ease(step / 30.0)
        nodes = dict(after_first)
        nodes["15"] = (lerp_point(after_first["15"][0], wait15, t), False)
        nodes["23"] = (lerp_point(after_first["23"][0], wait23, t), True)
        nodes["22"] = (lerp_point(after_first["22"][0], wait22, t), False)
        frames.append(page(nodes, (("20", "21"), ("23", "22")), "重新找天平：现在天平已经是 20—21，摘下左右货物", ("20", "21")))
    lever_start_a, lever_start_b = after_first["20"][0], after_first["21"][0]
    lever_target_a, lever_target_b = final["20"][0], final["21"][0]
    for step in range(1, 49):
        t = ease(step / 48.0)
        p20, p21 = rotate_segment_about_center(
            lever_start_a,
            lever_start_b,
            lever_target_a,
            lever_target_b,
            t,
        )
        nodes = {"20": (p20, False), "21": (p21, True), "15": (wait15, False),
                 "23": (wait23, True), "22": (wait22, False)}
        frames.append(page(nodes, (("20", "21"), ("23", "22")), "只旋转变形后的天平 20—21", ("20", "21")))
    for step in range(1, 31):
        t = ease(step / 30.0)
        nodes = dict(final)
        nodes["15"] = (lerp_point(wait15, final["15"][0], t), False)
        nodes["23"] = (lerp_point(wait23, final["23"][0], t), True)
        nodes["22"] = (lerp_point(wait22, final["22"][0], t), False)
        frames.append(page(nodes, (("21", "20"), ("23", "22")), "两次都只转天平，先接回货物，最后恢复 21—20", ("21",)))
    frames.extend([page(final, final_edges, "连接全部恢复，最后才进行变色", ("21",))] * 14)
    for step in range(1, 31):
        t = ease(step / 30.0)
        frames.append(page(
            final,
            final_edges,
            "最后变色：21 黑，20 和 23 红",
            ("21",),
            {"21": (True, False, t), "20": (False, True, t)},
        ))
    render_webm("rb-lr-rl", frames, fps=30, transparent=True, zoom=1.0)


def rb_ll_rr() -> None:
    """Render the LL/RR repair as one scene updated only by frame deltas."""
    compact_scale_x = 1.0
    compact_scale_y = 0.65
    source_centre = (475.0, 330.0)
    compact_centre = (380.0, 300.0)

    def compact(point: Point) -> Point:
        return (
            compact_centre[0] + (point[0] - source_centre[0]) * compact_scale_x,
            compact_centre[1] + (point[1] - source_centre[1]) * compact_scale_y,
        )

    nodes = {
        "55": (compact((450.0, 120.0)), False),
        "51": (compact((280.0, 300.0)), False),
        "52": (compact((400.0, 430.0)), True),
        "54": (compact((520.0, 560.0)), True),
        "57": (compact((640.0, 300.0)), False),
    }
    edge_opacity = {
        ("55", "51"): 1.0,
        ("51", "52"): 1.0,
        ("52", "54"): 1.0,
        ("55", "57"): 1.0,
        ("55", "52"): 0.0,
    }
    edges = tuple(edge_opacity)
    frames: list[str] = []
    color_blend = 0.0

    def page(caption: str, focus=(), focus_edges=()) -> None:
        frames.append(rb_balanced_case_frame(
            nodes,
            tuple((*edge, edge_opacity[edge]) for edge in edges),
            caption=caption,
            focus_nodes=focus,
            focus_edges=focus_edges,
            color_transitions={
                "52": (True, False, color_blend),
                "51": (False, True, color_blend),
            } if color_blend > 0.0 else None,
            width=760,
            height=600,
        ))

    page("先看形状：55 左侧的 51—52—54 违反不红红")
    frames.extend([frames[-1]] * 23)

    # The cargo leaves vertically, with its x coordinate unchanged.
    cargo_start = nodes["54"][0]
    cargo_offset = (
        nodes["54"][0][0] - nodes["52"][0][0],
        nodes["54"][0][1] - nodes["52"][0][1],
    )
    cargo_drop = (cargo_start[0], cargo_start[1] + abs(cargo_offset[1]) * 0.4)
    cargo_dy = (cargo_drop[1] - cargo_start[1]) / 36.0
    edge_step = 1.0 / 36.0
    for _ in range(36):
        nodes["54"] = ((nodes["54"][0][0], nodes["54"][0][1] + cargo_dy), True)
        edge_opacity[("52", "54")] = max(0.0, edge_opacity[("52", "54")] - edge_step)
        page("找到天平 51—52：货物 54 竖直向下移动", ("51", "52"), (("51", "52"),))
    for _ in range(18):
        page("只保留天平 51—52，55—57 保持连接", ("51", "52"), (("51", "52"),))

    # Disconnect the balance from its parent, but never disconnect its rod.
    for _ in range(18):
        edge_opacity[("55", "51")] = max(0.0, edge_opacity[("55", "51")] - 1.0 / 18.0)
        page("先断开天平与 55 的连接，其他部分不动", ("51", "52"), (("51", "52"),))

    # Rotate the rod around its fixed midpoint by a fixed delta per frame.
    centre = (
        (nodes["51"][0][0] + nodes["52"][0][0]) / 2.0,
        (nodes["51"][0][1] + nodes["52"][0][1]) / 2.0,
    )
    rotation_step = -pi / 2.0 / 48.0
    for _ in range(48):
        c, s = cos(rotation_step), sin(rotation_step)

        def spin(point: Point) -> Point:
            dx, dy = point[0] - centre[0], point[1] - centre[1]
            return (centre[0] + dx * c - dy * s, centre[1] + dx * s + dy * c)

        nodes["51"] = (spin(nodes["51"][0]), False)
        nodes["52"] = (spin(nodes["52"][0]), True)
        page("只旋转天平 51—52，旋转中心固定在杆子中点", ("51", "52"), (("51", "52"),))

    # Move the cargo back to its structural slot before restoring either link.
    cargo_target = (
        nodes["52"][0][0] + cargo_offset[0],
        nodes["52"][0][1] + cargo_offset[1],
    )
    cargo_dy = (cargo_target[1] - nodes["54"][0][1]) / 36.0
    cargo_dx = (cargo_target[0] - nodes["54"][0][0]) / 36.0
    for _ in range(36):
        nodes["54"] = ((nodes["54"][0][0] + cargo_dx, nodes["54"][0][1] + cargo_dy), True)
        page("先把右侧货物 54 接回 52", ("52",), (("51", "52"),))
    for _ in range(18):
        edge_opacity[("52", "54")] = min(1.0, edge_opacity[("52", "54")] + 1.0 / 18.0)
        page("先恢复 52—54 的连接", ("52",), (("52", "54"),))
    for _ in range(18):
        edge_opacity[("55", "52")] = min(1.0, edge_opacity[("55", "52")] + 1.0 / 18.0)
        page("再恢复 52—55 的连接", ("52",), (("55", "52"),))

    for _ in range(24):
        page("连接全部恢复后，准备最后变色", ("52",), (("55", "52"),))
    for _ in range(36):
        color_blend = min(1.0, color_blend + 1.0 / 36.0)
        page("最后变色渐变：52 黑，51 和 54 红", ("52",), (("55", "52"),))
    nodes["52"] = (nodes["52"][0], False)
    nodes["51"] = (nodes["51"][0], True)
    frames.extend([frames[-1]] * 24)
    render_webm("rb-ll-rr", frames, fps=30, transparent=True, crop=True, crop_pad=12, zoom=1.0)


def rb_lr_rl() -> None:
    """Render the LR/RL repair as one scene updated only by frame deltas."""
    # Keep every complete tree state legible: the initial zig-zag, the
    # straightened subtree, and the final 22-rooted subtree share one visual
    # centre instead of being tuned to a single rotation frame.
    nodes = {
        "20": ((380.0, 75.0), False),
        "15": ((180.0, 190.0), False),
        "23": ((620.0, 190.0), False),
        "21": ((445.0, 300.0), True),
        "22": ((545.0, 380.0), True),
    }
    final_positions = {
        "22": (520.0, 190.0),
        "21": (420.0, 290.0),
        "23": (620.0, 290.0),
    }
    final_child_offset = (
        final_positions["21"][0] - final_positions["22"][0],
        final_positions["21"][1] - final_positions["22"][1],
    )
    edge_opacity = {
        ("20", "15"): 1.0,
        ("20", "23"): 1.0,
        ("23", "21"): 1.0,
        ("21", "22"): 1.0,
        ("20", "22"): 0.0,
        ("23", "22"): 0.0,
    }
    edges = tuple(edge_opacity)
    frames: list[str] = []
    color_blend = 0.0

    def page(caption: str, focus=(), focus_edges=()) -> None:
        # Keep every frame readable, including the detached-lever stages.
        points = [point for point, _red in nodes.values()]
        minimum_gap = hypot(RB_NODE_W + 32.0, RB_NODE_H + 32.0)
        assert all(hypot(a[0] - b[0], a[1] - b[1]) >= minimum_gap for i, a in enumerate(points) for b in points[i + 1:])
        for parent, child in edges:
            if edge_opacity[(parent, child)] > 0.0:
                assert hypot(
                    nodes[parent][0][0] - nodes[child][0][0],
                    nodes[parent][0][1] - nodes[child][0][1],
                ) >= hypot(RB_NODE_W, RB_NODE_H)
        frames.append(rb_balanced_case_frame(
            nodes,
            tuple((*edge, edge_opacity[edge]) for edge in edges),
            caption=caption,
            focus_nodes=focus,
            focus_edges=focus_edges,
            color_transitions={
                "23": (False, True, color_blend),
                "22": (True, False, color_blend),
            } if color_blend > 0.0 else None,
            width=760,
            height=600,
        ))

    page("先找天平：20 右侧更高，23—21 形成折线", ("20", "23"), (("20", "23"),))
    frames.extend([frames[-1]] * 25)

    # First rotation: 21--22 is the lever. Only its upper attachment is removed.
    for _ in range(18):
        edge_opacity[("23", "21")] = max(0.0, edge_opacity[("23", "21")] - 1.0 / 18.0)
        page("第一次只断开 23—21，准备旋转 21—22", ("21", "22"), (("21", "22"),))

    first_centre = (
        (nodes["21"][0][0] + nodes["22"][0][0]) / 2.0,
        (nodes["21"][0][1] + nodes["22"][0][1]) / 2.0,
    )
    first_target_21 = (470.0, 390.0)
    first_target_22 = (520.0, 290.0)
    first_start_angle = atan2(
        nodes["22"][0][1] - nodes["21"][0][1],
        nodes["22"][0][0] - nodes["21"][0][0],
    )
    first_target_angle = atan2(
        first_target_22[1] - first_target_21[1],
        first_target_22[0] - first_target_21[0],
    )
    first_step = ((first_target_angle - first_start_angle + pi) % (2.0 * pi) - pi) / 48.0
    for _ in range(48):
        c, s = cos(first_step), sin(first_step)

        def spin_first(point: Point) -> Point:
            dx, dy = point[0] - first_centre[0], point[1] - first_centre[1]
            return (first_centre[0] + dx * c - dy * s, first_centre[1] + dx * s + dy * c)

        nodes["21"] = (spin_first(nodes["21"][0]), True)
        nodes["22"] = (spin_first(nodes["22"][0]), True)
        page("第一次只旋转天平 21—22，旋转中心固定在杆子中点", ("21", "22"), (("21", "22"),))

    for _ in range(18):
        edge_opacity[("23", "22")] = min(1.0, edge_opacity[("23", "22")] + 1.0 / 18.0)
        page("第一次完成：恢复 23—22 的连接", ("22",), (("23", "22"),))

    # Second rotation: unload 21, then rotate only the 22--23 lever right.
    unload_distance = abs(nodes["21"][0][1] - nodes["22"][0][1])
    cargo_drop = (nodes["21"][0][0], nodes["21"][0][1] + unload_distance * 0.4)
    cargo_dy = (cargo_drop[1] - nodes["21"][0][1]) / 36.0
    for _ in range(36):
        nodes["21"] = ((nodes["21"][0][0], nodes["21"][0][1] + cargo_dy), True)
        edge_opacity[("21", "22")] = max(0.0, edge_opacity[("21", "22")] - 1.0 / 36.0)
        page("第二次：把 21 竖直卸下，只留下天平 22—23", ("22", "23"), (("22", "23"),))
    for _ in range(18):
        edge_opacity[("20", "23")] = max(0.0, edge_opacity[("20", "23")] - 1.0 / 18.0)
        page("只断开天平 22—23 与 20 的连接", ("22", "23"), (("22", "23"),))

    second_centre = (
        (nodes["22"][0][0] + nodes["23"][0][0]) / 2.0,
        (nodes["22"][0][1] + nodes["23"][0][1]) / 2.0,
    )
    second_target_22 = final_positions["22"]
    second_target_23 = final_positions["23"]
    second_start_angle = atan2(
        nodes["23"][0][1] - nodes["22"][0][1],
        nodes["23"][0][0] - nodes["22"][0][0],
    )
    second_target_angle = atan2(
        second_target_23[1] - second_target_22[1],
        second_target_23[0] - second_target_22[0],
    )
    second_step = ((second_target_angle - second_start_angle + pi) % (2.0 * pi) - pi) / 48.0
    for _ in range(48):
        c, s = cos(second_step), sin(second_step)

        def spin_second(point: Point) -> Point:
            dx, dy = point[0] - second_centre[0], point[1] - second_centre[1]
            return (second_centre[0] + dx * c - dy * s, second_centre[1] + dx * s + dy * c)

        nodes["22"] = (spin_second(nodes["22"][0]), True)
        nodes["23"] = (spin_second(nodes["23"][0]), False)
        page("第二次只旋转天平 22—23，旋转中心固定在杆子中点", ("22", "23"), (("22", "23"),))

    cargo_target = final_positions["21"]
    cargo_dx = (cargo_target[0] - nodes["21"][0][0]) / 36.0
    cargo_dy = (cargo_target[1] - nodes["21"][0][1]) / 36.0
    for _ in range(36):
        nodes["21"] = ((nodes["21"][0][0] + cargo_dx, nodes["21"][0][1] + cargo_dy), True)
        page("先把 21 接回 22 的左侧", ("22",), (("22", "23"),))
    for _ in range(18):
        edge_opacity[("21", "22")] = min(1.0, edge_opacity[("21", "22")] + 1.0 / 18.0)
        page("先恢复 22—21 的连接", ("22",), (("21", "22"),))
    for _ in range(18):
        edge_opacity[("20", "22")] = min(1.0, edge_opacity[("20", "22")] + 1.0 / 18.0)
        page("再恢复 20—22 的连接", ("22",), (("20", "22"),))

    for _ in range(24):
        page("连接全部恢复后，准备最后变色", ("22",), (("20", "22"),))
    for _ in range(36):
        color_blend = min(1.0, color_blend + 1.0 / 36.0)
        page("最后变色渐变：22 黑，23 红", ("22",), (("20", "22"),))
    nodes["21"] = (nodes["21"][0], True)
    nodes["20"] = (nodes["20"][0], False)
    nodes["23"] = (nodes["23"][0], True)
    nodes["22"] = (nodes["22"][0], False)
    frames.extend([frames[-1]] * 24)
    render_webm("rb-lr-rl", frames, fps=30, transparent=True, crop=True, crop_pad=12, zoom=1.0)


def rb_overflow() -> None:
    """Show why the B-tree overflow promotes B rather than C."""
    row_y = 390.0
    base = {key: (point, red) for key, point, red in (
        ("A", (270.0, row_y), True),
        ("B", (390.0, row_y), False),
        ("C", (510.0, row_y), True),
        ("D", (630.0, row_y), True),
    )}

    def link(a: Point, b: Point, lane: float = 0.0) -> str:
        left, right = sorted((a[0], b[0]))
        return glow_line((left + RB_NODE_W / 2, a[1] + lane),
                         (right - RB_NODE_W / 2, b[1] + lane),
                         color=INK, bloom=GLOW_WHITE, width=3.4, radius=0.0)

    def page(
        nodes: Mapping[str, tuple[Point, bool]],
        caption: str,
        focus=(),
        transitions: Mapping[str, tuple[bool, bool, float]] | None = None,
    ) -> str:
        positions = {key: point for key, (point, _red) in nodes.items()}
        body = link(positions["A"], positions["B"], -12.0)
        body += link(positions["C"], positions["D"], 14.0)
        body += link(positions["B"], positions["D"], -12.0)

        def draw_node(key: str, point: Point, red: bool) -> str:
            transition = (transitions or {}).get(key)
            if transition is None:
                return rb_node(point, key, red=red)
            from_red, to_red, blend = transition
            return rb_node(point, key, 1.0 - blend, red=from_red) + rb_node(point, key, blend, red=to_red)

        body += "".join(
            glow_ring(positions[key], color=GLOW_WHITE, extra=8.0) + draw_node(key, positions[key], red)
            if key in focus else draw_node(key, positions[key], red)
            for key, (_point, red) in nodes.items()
        )
        return svg(body, width=900, height=520, color=INK)

    frames = [page(base, "四键暂时上溢：先判断谁适合被推举")] * 26
    c_high = dict(base)
    c_high["C"] = ((510.0, 280.0), True)
    for step in range(1, 31):
        t = ease(step / 30.0)
        live = dict(base)
        live["C"] = (lerp_point(base["C"][0], c_high["C"][0], t), True)
        frames.append(page(live, "尝试推举 C：只能向上拉起一点点，位置不自然", ("C",)))
    for step in range(1, 25):
        t = ease(step / 24.0)
        live = dict(base)
        live["C"] = (lerp_point(c_high["C"][0], base["C"][0], t), True)
        frames.append(page(live, "C 放回原位，改选 B 作为推举键", ("B", "C")))
    b_high = dict(base)
    b_high["B"] = ((390.0, 145.0), False)
    for step in range(1, 43):
        t = ease(step / 42.0)
        live = dict(base)
        live["B"] = (lerp_point(base["B"][0], b_high["B"][0], t), False)
        frames.append(page(live, "B 向上推举：提举完成前保持黑色", ("B",)))
    stage = dict(b_high)
    for step in range(1, 37):
        t = ease(step / 36.0)
        frames.append(page(
            stage,
            "提举完成：A、B、D 同时开始变色",
            ("A", "B", "D"),
            {
                "A": (True, False, t),
                "B": (False, True, t),
                "D": (True, False, t),
            },
        ))
    recolored = dict(stage)
    recolored["A"] = (stage["A"][0], False)
    recolored["B"] = (stage["B"][0], True)
    recolored["D"] = (stage["D"][0], False)
    frames.extend([page(recolored, "A、B、D 变色完成，稍后 B 再变黑", ("B",))] * 18)
    for step in range(1, 31):
        t = ease(step / 30.0)
        frames.append(page(
            recolored,
            "最后 B 渐变为黑色：上溢修复完成",
            ("B",),
            {"B": (True, False, t)},
        ))
    final = dict(recolored)
    final["B"] = (recolored["B"][0], False)
    frames.extend([page(final, "最后 B 变黑：上溢修复完成")] * 34)
    render_webm("rb-overflow", frames, fps=30, transparent=True, zoom=1.0)


def btree_borrow_legacy() -> None:
    """Show a four-key descent, deletion, then the sibling-key borrow."""
    width, height = 1100, 600
    root_c = (550.0, 120.0)
    left_c = (300.0, 370.0)
    right_c = (820.0, 370.0)

    def frame(cells, groups, edges) -> str:
        return bscene_neon_page(cells, groups, edges, width=width, height=height)

    def cell_map(positions: Mapping[str, Point]) -> dict:
        return {name: (pos, name, 1.0) for name, pos in positions.items()}

    def ramp(value: float) -> float:
        return min(1.0, max(0.0, value))

    left_three = cell_slots(left_c, 3)
    left_four = cell_slots(left_c, 4)
    left_two_after_delete = cell_slots(left_c, 3)
    forty = cell_slots(root_c, 1)[0]
    sixty, seventy = cell_slots(right_c, 2)

    start_positions: dict[str, Point] = {
        "10": left_three[0],
        "20": left_three[1],
        "30": left_three[2],
        "40": forty,
        "60": sixty,
        "70": seventy,
    }
    start_groups = {
        "left": (["10", "20", "30"], left_c, False, 1.0),
        "root": (["40"], root_c, False, 1.0),
        "right": (["60", "70"], right_c, False, 1.0),
    }
    start_edges = (("root", "left", 0, 2, 1.0), ("root", "right", 1, 2, 1.0))

    frames: list[str] = []
    frames.extend([frame(cell_map(start_positions), start_groups, start_edges)] * 20)

    # Pull 40 down and make the target a visible four-key node first.
    for step in range(1, 31):
        t = ease(step / 24.0)
        pos = dict(start_positions)
        pos["40"] = lerp_point(forty, left_four[3], t)
        groups = {
            "left": (["10", "20", "30"], left_c, False, 1.0),
            "root": ([], root_c, False, 1.0 - ramp(step / 10.0)),
            "right": (["60", "70"], right_c, False, 1.0),
        }
        edge_op = 1.0 - ramp(step / 15.0)
        edges = (("root", "left", 0, 2, edge_op), ("root", "right", 1, 2, edge_op))
        frames.append(frame(cell_map(pos), groups, edges))

    pulled_positions = {
        "10": left_four[0],
        "20": left_four[1],
        "30": left_four[2],
        "40": left_four[3],
        "60": sixty,
        "70": seventy,
    }
    pulled_groups = {
        "left": (["10", "20", "30", "40"], left_c, False, 1.0),
        "right": (["60", "70"], right_c, False, 1.0),
    }
    frames.extend([frame(cell_map(pulled_positions), pulled_groups, ())] * 8)

    # Delete 10 from the four-key node, leaving a visible three-key node.
    delete_groups = {
        "left": (["20", "30", "40"], left_c, False, 1.0),
        "right": (["60", "70"], right_c, False, 1.0),
    }
    for step in range(1, 15):
        cells = cell_map(pulled_positions)
        cells["10"] = (left_four[0], "10", 1.0 - ease(step / 14.0))
        frames.append(frame(cells, delete_groups, ()))

    deleted_positions = {
        "20": left_four[1],
        "30": left_four[2],
        "40": left_four[3],
        "60": sixty,
        "70": seventy,
    }
    for step in range(1, 19):
        t = ease(step / 12.0)
        pos = dict(deleted_positions)
        targets = dict(zip(("20", "30", "40"), left_two_after_delete))
        for name in ("20", "30", "40"):
            pos[name] = lerp_point(deleted_positions[name], targets[name], t)
        groups = {"left": (["20", "30", "40"], left_c, False, 1.0), "right": (["60", "70"], right_c, False, 1.0)}
        frames.append(frame(cell_map(pos), groups, ()))

    left_final = dict(zip(("20", "30", "40"), left_two_after_delete))
    deleted_positions.update(left_final.items())
    frames.extend([frame(cell_map(deleted_positions), delete_groups, ())] * 12)

    # Borrow: 60 rises to the parent and 70 recentres in its sibling.
    borrow_to = {"60": cell_slots(root_c, 1)[0], "70": cell_slots(right_c, 1)[0]}
    for step in range(1, 31):
        t = ease(step / 28.0)
        pos = {
            "20": left_final["20"],
            "30": left_final["30"],
            "40": left_final["40"],
            "60": lerp_point(sixty, borrow_to["60"], t),
            "70": lerp_point(seventy, borrow_to["70"], t),
        }
        groups = {
            "left": (["20", "30", "40"], left_c, False, 1.0),
            "root": (["60"], root_c, False, ramp((step - 16) / 12.0)),
            "right": (["70"], right_c, False, 1.0),
        }
        edges = (
            ("root", "left", 0, 2, ramp((step - 16) / 12.0)),
            ("root", "right", 1, 2, ramp((step - 16) / 12.0)),
        )
        frames.append(frame(cell_map(pos), groups, edges))

    final_positions = {"20": left_final["20"], "30": left_final["30"], "40": left_final["40"], "60": borrow_to["60"], "70": borrow_to["70"]}
    final_groups = {
        "left": (["20", "30", "40"], left_c, False, 1.0),
        "root": (["60"], root_c, False, 1.0),
        "right": (["70"], right_c, False, 1.0),
    }
    frames.extend([frame(cell_map(final_positions), final_groups, start_edges)] * 26)
    render_webm("btree-borrow", frames, fps=30, transparent=True)


def btree_borrow_bad_transition() -> None:
    """Merge both children, delete, then split and promote a new separator."""
    width, height = 1100, 600
    root_c = (550.0, 120.0)
    left_c = (300.0, 370.0)
    right_c = (820.0, 370.0)
    merged_c = (550.0, 370.0)

    def frame(cells, groups, edges) -> str:
        return bscene_neon_page(cells, groups, edges, width=width, height=height)

    def cell_map(positions: Mapping[str, Point], fading: Mapping[str, float] | None = None) -> dict:
        fading = fading or {}
        return {name: (pos, name, fading.get(name, 1.0)) for name, pos in positions.items()}

    def ramp(value: float) -> float:
        return min(1.0, max(0.0, value))

    left_three = cell_slots(left_c, 3)
    right_two = cell_slots(right_c, 2)
    merged_six = cell_slots(merged_c, 6)
    merged_five = cell_slots(merged_c, 5)
    left_final = cell_slots(left_c, 2)
    right_final = cell_slots(right_c, 2)
    root_one = cell_slots(root_c, 1)[0]

    start = {
        "10": left_three[0], "20": left_three[1], "30": left_three[2],
        "40": root_one, "60": right_two[0], "70": right_two[1],
    }
    frames: list[str] = []
    start_groups = {
        "left": (["10", "20", "30"], left_c, False, 1.0),
        "root": (["40"], root_c, False, 1.0),
        "right": (["60", "70"], right_c, False, 1.0),
    }
    start_edges = (("root", "left", 0, 2, 1.0), ("root", "right", 1, 2, 1.0))
    frames.extend([frame(cell_map(start), start_groups, start_edges)] * 24)

    # Pull the separator and both children into one six-key array.
    merge_names = ("10", "20", "30", "40", "60", "70")
    merge_sources = {name: start[name] for name in merge_names}
    merge_targets: dict[str, Point] = dict(zip(merge_names, merged_six))
    for step in range(1, 43):
        t = ease(step / 42.0)
        pos = {name: lerp_point(merge_sources[name], merge_targets[name], t) for name in merge_names}
        merge_opacity = ramp((step - 15) / 18.0)
        groups = {
            "left": (["10", "20", "30"], left_c, False, 1.0 - merge_opacity),
            "root": (["40"], root_c, False, 1.0 - merge_opacity),
            "right": (["60", "70"], right_c, False, 1.0 - merge_opacity),
            "merged": (list(merge_names), merged_c, False, merge_opacity),
        }
        edges = (
            ("root", "left", 0, 2, 1.0 - merge_opacity),
            ("root", "right", 1, 2, 1.0 - merge_opacity),
        )
        frames.append(frame(cell_map(pos), groups, edges))
    frames.extend([frame(cell_map(merge_targets), {"merged": (list(merge_names), merged_c, False, 1.0)}, ())] * 18)

    # Delete 10 while the remaining five keys stay in one merged node.
    delete_names = ("20", "30", "40", "60", "70")
    delete_targets: dict[str, Point] = dict(zip(delete_names, merged_five))
    for step in range(1, 25):
        t = ease(step / 24.0)
        pos = {name: lerp_point(merge_targets[name], delete_targets[name], t) for name in delete_names}
        pos["10"] = lerp_point(merge_targets["10"], (merge_targets["10"][0] - 100.0, merge_targets["10"][1] - 80.0), t)
        groups = {"merged": (list(delete_names), merged_c, False, 1.0)}
        frames.append(frame(cell_map(pos, {"10": 1.0 - t}), groups, ()))
    frames.extend([frame(cell_map(delete_targets), {"merged": (list(delete_names), merged_c, False, 1.0)}, ())] * 18)

    # Split the five-key array and promote 40 as the new parent separator.
    split_targets = {
        "20": left_final[0], "30": left_final[1], "40": root_one,
        "60": right_final[0], "70": right_final[1],
    }
    for step in range(1, 43):
        t = ease(step / 42.0)
        pos = {name: lerp_point(delete_targets[name], split_targets[name], t) for name in delete_names}
        split_opacity = ramp((step - 18) / 18.0)
        groups = {
            "left": (["20", "30"], left_c, False, split_opacity),
            "root": (["40"], root_c, False, split_opacity),
            "right": (["60", "70"], right_c, False, split_opacity),
            "merged": (list(delete_names), merged_c, False, 1.0 - split_opacity),
        }
        edges = (
            ("root", "left", 0, 2, split_opacity),
            ("root", "right", 1, 2, split_opacity),
        )
        frames.append(frame(cell_map(pos), groups, edges))
    final_groups = {
        "left": (["20", "30"], left_c, False, 1.0),
        "root": (["40"], root_c, False, 1.0),
        "right": (["60", "70"], right_c, False, 1.0),
    }
    frames.extend([frame(cell_map(split_targets), final_groups, start_edges)] * 30)
    render_webm("btree-borrow", frames, fps=30, transparent=True)


def btree_borrow_transition_bug() -> None:
    """Show merge, deletion, and re-splitting with one owner per key per frame."""
    width, height = 1100, 600
    root_c = (550.0, 120.0)
    left_c = (300.0, 370.0)
    right_c = (820.0, 370.0)
    merged_c = (550.0, 370.0)

    def frame(cells, groups, edges) -> str:
        return bscene_neon_page(cells, groups, edges, width=width, height=height)

    def cell_map(positions: Mapping[str, Point], opacity: Mapping[str, float] | None = None) -> dict:
        opacity = opacity or {}
        return {name: (point, name, opacity.get(name, 1.0)) for name, point in positions.items()}

    left_three = cell_slots(left_c, 3)
    right_two = cell_slots(right_c, 2)
    merged_six = cell_slots(merged_c, 6)
    merged_five = cell_slots(merged_c, 5)
    left_two = cell_slots(left_c, 2)
    right_two_final = cell_slots(right_c, 2)
    root_one = cell_slots(root_c, 1)[0]

    start_positions: dict[str, Point] = {
        "10": left_three[0], "20": left_three[1], "30": left_three[2],
        "40": root_one, "60": right_two[0], "70": right_two[1],
    }
    start_groups = {
        "left": (["10", "20", "30"], left_c, False, 1.0),
        "root": (["40"], root_c, False, 1.0),
        "right": (["60", "70"], right_c, False, 1.0),
    }
    tree_edges = (("root", "left", 0, 2, 1.0), ("root", "right", 1, 2, 1.0))
    frames: list[str] = []
    frames.extend([frame(cell_map(start_positions), start_groups, tree_edges)] * 24)

    # The separator and both children travel into one six-key node.
    names = ("10", "20", "30", "40", "60", "70")
    merged_positions: dict[str, Point] = dict(zip(names, merged_six))
    for step in range(1, 43):
        t = ease(step / 42.0)
        current = {
            name: lerp_point(start_positions[name], merged_positions[name], t)
            for name in names
        }
        groups = {"merged": (list(names), merged_c, False, 1.0)}
        frames.append(frame(cell_map(current), groups, ()))
    frames.extend([frame(cell_map(merged_positions), {"merged": (list(names), merged_c, False, 1.0)}, ())] * 18)

    # Delete 10 as a state change; the remaining five keys immediately re-pack.
    remaining = ("20", "30", "40", "60", "70")
    after_delete: dict[str, Point] = dict(zip(remaining, merged_five))
    frames.extend([frame(cell_map(after_delete), {"merged": (list(remaining), merged_c, False, 1.0)}, ())] * 24)
    frames.extend([frame(cell_map(after_delete), {"merged": (list(remaining), merged_c, False, 1.0)}, ())] * 18)

    # Split the five-key node and promote 40 back to the parent.
    final_positions: dict[str, Point] = {
        "20": left_two[0], "30": left_two[1], "40": root_one,
        "60": right_two_final[0], "70": right_two_final[1],
    }
    for step in range(1, 43):
        t = ease(step / 42.0)
        current = {
            name: lerp_point(after_delete[name], final_positions[name], t)
            for name in remaining
        }
        groups = {
            "left": (["20", "30"], left_c, False, 1.0),
            "root": (["40"], root_c, False, 1.0),
            "right": (["60", "70"], right_c, False, 1.0),
        }
        edges = tree_edges
        frames.append(frame(cell_map(current), groups, edges))
    frames.extend([frame(cell_map(final_positions), {
        "left": (["20", "30"], left_c, False, 1.0),
        "root": (["40"], root_c, False, 1.0),
        "right": (["60", "70"], right_c, False, 1.0),
    }, tree_edges)] * 30)
    render_webm("btree-borrow", frames, fps=30, transparent=True)


def neon_text(text: str, center: Point, *, size: float = 22.0, color: str = INK, opacity: float = 1.0, glow: str = GLOW_BLUE) -> str:
    cx, cy = center
    font = "Noto Sans CJK SC,system-ui,sans-serif"
    underlay = (
        f'<text x="{cx:.1f}" y="{cy:.1f}" fill="none" stroke="{glow}" stroke-width="{size / 3.0:.1f}" '
        f'stroke-linejoin="round" opacity="{opacity * 0.28:.3f}" font-family="{font}" font-size="{size:.0f}" '
        f'font-weight="600" text-anchor="middle" dominant-baseline="middle">{esc(text)}</text>'
    )
    return underlay + (
        f'<text x="{cx:.1f}" y="{cy:.1f}" fill="{color}" opacity="{opacity:.3f}" font-family="{font}" '
        f'font-size="{size:.0f}" font-weight="600" text-anchor="middle" dominant-baseline="middle">{esc(text)}</text>'
    )


def btree_title_card(text: str, width: int, height: int) -> list[str]:
    center = (width / 2.0, height / 2.0)
    frames: list[str] = []
    for step in range(1, 11):
        frames.append(svg(neon_text(text, center, size=40.0, opacity=step / 10.0), width=width, height=height, color=INK))
    frames.extend([svg(neon_text(text, center, size=40.0), width=width, height=height, color=INK)] * 44)
    for step in range(10, 0, -1):
        frames.append(svg(neon_text(text, center, size=40.0, opacity=step / 10.0), width=width, height=height, color=INK))
    return frames


def btree_borrow_frames(width: int, height: int, root_c: Point, left_c: Point, right_c: Point, merged_c: Point) -> list[str]:
    """Animate one continuous merge, deletion, and re-split without split-cell gaps."""

    def row(keys: Sequence[str], positions: Sequence[Point]) -> str:
        return btree_neon_row_at_positions(keys, positions)

    def row_center(points: Sequence[Point]) -> Point:
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )

    def render_rows(
        rows: Sequence[tuple[Sequence[str], Sequence[Point]]],
        *,
        tree: bool = False,
        overlay: str = "",
    ) -> str:
        parts: list[str] = []
        if tree and len(rows) == 3:
            parent = row_center(rows[1][1])
            for child in (rows[0][1], rows[2][1]):
                child_center = row_center(child)
                parts.append(
                    btree_neon_edge(
                        (parent[0], parent[1] + BTREE_NEON_CELL_H / 2.0),
                        (child_center[0], child_center[1] - BTREE_NEON_CELL_H / 2.0),
                    )
                )
        parts.extend(row(keys, points) for keys, points in rows)
        parts.append(overlay)
        return svg("".join(parts), width=width, height=height, color=INK)

    left_three = cell_slots(left_c, 3)
    right_two = cell_slots(right_c, 2)
    merged_six = cell_slots(merged_c, 6)
    merged_five = cell_slots(merged_c, 5)
    final_left = cell_slots(left_c, 2)
    final_right = cell_slots(right_c, 2)
    root_one = cell_slots(root_c, 1)[0]
    frames: list[str] = []

    # Initial tree. Every multi-key node is drawn as one contiguous array.
    frames.extend([
        render_rows([
            (("10", "20", "30"), left_three),
            (("40",), (root_one,)),
            (("60", "70"), right_two),
        ], tree=True)
    ] * 24)

    # Move each complete row into the six-key merge line; no row is split apart.
    merge_sources = [left_three, (root_one,), right_two]
    merge_targets = [merged_six[:3], (merged_six[3],), merged_six[4:]]
    for step in range(1, 43):
        t = ease(step / 42.0)
        rows = [
            (keys, tuple(lerp_point(source, target, t) for source, target in zip(source_points, target_points)))
            for keys, source_points, target_points in zip(
                (("10", "20", "30"), ("40",), ("60", "70")),
                merge_sources,
                merge_targets,
            )
        ]
        frames.append(render_rows(rows, tree=True))
    frames.extend([render_rows([(("10", "20", "30", "40", "60", "70"), merged_six)])] * 18)

    # Outline 10 with a red dashed frame; at deletion the frame vanishes with the node.
    ten_point = merged_six[0]

    def red_dashed_frame(point: Point, opacity: float) -> str:
        left = point[0] - BTREE_NEON_CELL_W / 2.0 - 5.0
        right = point[0] + BTREE_NEON_CELL_W / 2.0 + 5.0
        top = point[1] - BTREE_NEON_CELL_H / 2.0 - 5.0
        bottom = point[1] + BTREE_NEON_CELL_H / 2.0 + 5.0
        return (
            f'<rect x="{left:.1f}" y="{top:.1f}" width="{right - left:.1f}" height="{bottom - top:.1f}" '
            f'fill="none" stroke="#FF7070" stroke-width="2.5" stroke-dasharray="7 5" opacity="{opacity:.2f}" rx="9.0"/>'
        )

    for step in range(1, 19):
        frames.append(
            render_rows(
                [(("10", "20", "30", "40", "60", "70"), merged_six)],
                overlay=red_dashed_frame(ten_point, ease(step / 18.0)),
            )
        )
    frames.extend([
        render_rows(
            [(("10", "20", "30", "40", "60", "70"), merged_six)],
            overlay=red_dashed_frame(ten_point, 1.0),
        )
    ] * 8)

    # Remove 10 in place: the remaining keys keep their original six-key slots.
    remaining_positions = merged_six[1:]
    frames.extend([
        render_rows([(("20", "30", "40", "60", "70"), remaining_positions)])
    ] * 24)
    frames.extend([
        render_rows([(("20", "30", "40", "60", "70"), remaining_positions)])
    ] * 18)

    # Pull the five-key array apart as three complete rows and promote 40.
    split_sources = remaining_positions
    split_targets = tuple(final_left[:2]) + (root_one,) + tuple(final_right)
    for step in range(1, 43):
        t = ease(step / 42.0)
        positions = tuple(
            lerp_point(source, target, t)
            for source, target in zip(split_sources, split_targets)
        )
        rows = [
            (("20", "30"), positions[:2]),
            (("40",), (positions[2],)),
            (("60", "70"), positions[3:]),
        ]
        frames.append(render_rows(rows, tree=True))
    final_rows = [
        (("20", "30"), final_left),
        (("40",), (root_one,)),
        (("60", "70"), final_right),
    ]
    # 30 fps * 3 seconds: keep the final state visible after the action ends.
    frames.extend([render_rows(final_rows, tree=True)] * 90)
    return frames


def btree_borrow() -> None:
    """Render the unified borrow case as a standalone transparent WebM."""
    render_webm(
        "btree-borrow",
        btree_borrow_frames(1100, 600, (550.0, 120.0), (300.0, 370.0), (820.0, 370.0), (550.0, 370.0)),
        fps=30,
        transparent=True,
    )


def btree_merge_legacy() -> None:
    """Delete by pulling the separator down first, then delete and merge the children."""
    width, height = 900, 540
    root_c = (450.0, 130.0)
    left_c = (260.0, 330.0)
    right_c = (640.0, 330.0)
    merged_c = (450.0, 330.0)

    def frame(cells, groups, edges) -> str:
        return bscene_neon_page(cells, groups, edges, width=width, height=height)

    def cell_map(positions: Mapping[str, Point]) -> dict:
        return {name: (pos, name, 1.0) for name, pos in positions.items()}

    def ramp(value: float) -> float:
        return min(1.0, max(0.0, value))

    ten = cell_slots(left_c, 1)[0]
    forty = cell_slots(root_c, 1)[0]
    sixty = cell_slots(right_c, 1)[0]

    start_positions: dict[str, Point] = {"10": ten, "40": forty, "60": sixty}
    start_groups = {
        "left": (["10"], left_c, False, 1.0),
        "root": (["40"], root_c, False, 1.0),
        "right": (["60"], right_c, False, 1.0),
    }
    start_edges = (("root", "left", 0, 2, 1.0), ("root", "right", 1, 2, 1.0))

    frames: list[str] = []
    frames.extend([frame(cell_map(start_positions), start_groups, start_edges)] * 20)

    # Pull the separator 40 down into the left child before deleting anything.
    left_two = cell_slots(left_c, 2)
    for step in range(1, 25):
        t = ease(step / 24.0)
        pos = {"10": ten, "40": lerp_point(forty, left_two[1], t), "60": sixty}
        groups = {
            "left": (["10"], left_c, False, 1.0),
            "root": ([], root_c, False, 1.0 - ramp(step / 10.0)),
            "right": (["60"], right_c, False, 1.0),
        }
        edge_op = 1.0 - ramp(step / 12.0)
        edges = (("root", "left", 0, 2, edge_op), ("root", "right", 1, 2, edge_op))
        frames.append(frame(cell_map(pos), groups, edges))

    pulled_positions = {"10": ten, "40": left_two[1], "60": sixty}
    pulled_groups = {"left": (["10", "40"], left_c, False, 1.0), "right": (["60"], right_c, False, 1.0)}
    frames.extend([frame(cell_map(pulled_positions), pulled_groups, ())] * 8)

    # Delete 10 after the parent separator has become a leaf key.
    for step in range(1, 11):
        cells = cell_map(pulled_positions)
        cells["10"] = (ten, "10", 1.0 - ease(step / 10.0))
        frames.append(frame(cells, pulled_groups, ()))

    # The surviving 40 and sibling 60 move together to form the merged array.
    merged_slots = cell_slots(merged_c, 2)
    for step in range(1, 29):
        t = ease(step / 28.0)
        pos = {
            "40": lerp_point(left_two[1], merged_slots[0], t),
            "60": lerp_point(sixty, merged_slots[1], t),
        }
        groups = {"merged": (["40", "60"], merged_c, False, 1.0)}
        frames.append(frame(cell_map(pos), groups, ()))

    # The merged node rises and the tree loses a level.
    mid_cells = {name: (merged_slots[i], name, 1.0) for i, name in enumerate(("40", "60"))}
    mid_groups = {"merged": (["40", "60"], merged_c, False, 1.0)}
    frames.extend([frame(mid_cells, mid_groups, ())] * 12)

    rise_to = cell_slots(root_c, 2)
    for step in range(1, 17):
        t = ease(step / 16.0)
        cells = {
            "40": (lerp_point(merged_slots[0], rise_to[0], t), "40", 1.0),
            "60": (lerp_point(merged_slots[1], rise_to[1], t), "60", 1.0),
        }
        frames.append(frame(cells, mid_groups, ()))

    top_cells = {name: (rise_to[i], name, 1.0) for i, name in enumerate(("40", "60"))}
    top_groups = {"merged": (["40", "60"], root_c, False, 1.0)}
    frames.extend([frame(top_cells, top_groups, ())] * 28)
    render_webm("btree-merge", frames, fps=30, transparent=True)


def btree_delete_complex_frames(
    order: int,
    tree_spec: tuple,
    ops: Sequence[tuple],
    *,
    width: int = 1500,
    height: int = 700,
    leaf_gap: float = 56.0,
    top_offset: float = 0.0,
    cell_scale: float = 1.0,
    output_width: int = 0,
    output_height: int = 0,
    view_width: int = 0,
    camera_keyframes: Sequence[tuple[int, float]] = (),
) -> list[str]:
    """Render successor replacement plus pull-down merge deletions for the given order."""
    global CELL_W, CELL_H, BTREE_NEON_CELL_W, BTREE_NEON_CELL_H
    _saved_geo = (CELL_W, CELL_H, BTREE_NEON_CELL_W, BTREE_NEON_CELL_H)
    CELL_W *= cell_scale
    CELL_H *= cell_scale
    BTREE_NEON_CELL_W *= cell_scale
    BTREE_NEON_CELL_H *= cell_scale
    _fsz = 18.0 * cell_scale
    _out_w = output_width or width
    _out_h = output_height or height
    _view_w = [float(view_width or _out_w)]
    _view_y = [0.0]

    def _camera_x(frame_index: int) -> float:
        if not camera_keyframes:
            return width / 2.0
        for i in range(len(camera_keyframes) - 1):
            f0, x0 = camera_keyframes[i]
            f1, x1 = camera_keyframes[i + 1]
            if frame_index <= f1:
                if f0 == f1:
                    return x0
                t = max(0.0, min(1.0, (frame_index - f0) / (f1 - f0)))
                t = t * t * (3.0 - 2.0 * t)
                return x0 + (x1 - x0) * t
        return camera_keyframes[-1][1]
    from dataclasses import dataclass, field

    @dataclass
    class Node:
        keys: list[int] = field(default_factory=list)
        children: list["Node"] = field(default_factory=list)
        node_id: int = 0

        @property
        def leaf(self) -> bool:
            return not self.children

    @dataclass
    class Event:
        before: Node
        after: Node
        kind: str
        key: int | None = None
        replacement: int | None = None
        target_id: int | None = None
        target_index: int | None = None
        source_id: int | None = None
        source_index: int | None = None
        orange_keys: tuple[int, ...] = ()
        parent_id: int | None = None
        target_child_id: int | None = None
        sibling_id: int | None = None
        pivot: int | None = None
        pivot_index: int | None = None

    def clone(node: Node) -> Node:
        return Node(node.keys[:], [clone(child) for child in node.children], node.node_id)

    def build(spec: tuple) -> Node:
        keys, children = spec
        return Node(list(keys), [build(child) for child in children])

    root = build(tree_spec)
    next_id = 1

    def assign_ids(node: Node) -> None:
        nonlocal next_id
        node.node_id = next_id
        next_id += 1
        for child in node.children:
            assign_ids(child)

    assign_ids(root)

    def locate(node: Node, node_id: int) -> Node:
        if node.node_id == node_id:
            return node
        for child in node.children:
            try:
                return locate(child, node_id)
            except KeyError:
                pass
        raise KeyError(node_id)

    def locate_key(node: Node, key: int) -> tuple[Node, Node, int, int]:
        for index, item in enumerate(node.keys):
            if item == key:
                return node, node, index, -1
        for child_index, child in enumerate(node.children):
            try:
                found, owner, key_index, owner_child_index = locate_key(child, key)
                if owner_child_index == -1:
                    return found, node, key_index, child_index
                return found, owner, key_index, owner_child_index
            except KeyError:
                continue
        raise KeyError(key)

    max_keys = order - 1
    min_keys = (order + 1) // 2 - 1
    swap_orange: tuple[int, ...] = ()
    events: list[Event] = []

    def delete_leaf(key: int, *, sibling_side: str) -> None:
        leaf, parent, _unused, child_index = locate_key(root, key)
        assert leaf.leaf and child_index >= 0
        if sibling_side == "right":
            sibling_index = child_index + 1
            pivot_index = child_index
        else:
            sibling_index = child_index - 1
            pivot_index = child_index - 1
        sibling = parent.children[sibling_index]
        pivot = parent.keys[pivot_index]
        before_state = clone(root)
        merged = sorted([*leaf.keys, pivot, *sibling.keys])
        merged.remove(key)
        kind = "merge"
        if len(merged) <= max_keys:
            leaf.keys = merged
            parent.keys.pop(pivot_index)
            parent.children.pop(sibling_index)
        else:
            promote_index = len(merged) // 2
            if sibling_index < child_index:
                sibling.keys = merged[:promote_index]
                leaf.keys = merged[promote_index + 1 :]
            else:
                leaf.keys = merged[:promote_index]
                sibling.keys = merged[promote_index + 1 :]
            parent.keys[pivot_index] = merged[promote_index]
        events.append(Event(
            before_state,
            clone(root),
            kind,
            key=key,
            parent_id=parent.node_id,
            target_child_id=leaf.node_id,
            sibling_id=sibling.node_id,
            pivot=pivot,
            pivot_index=pivot_index,
            orange_keys=swap_orange,
        ))

    for op in ops:
        if op[0] == "replace":
            _, target_key, replacement = op
            before_state = clone(root)
            target_node, _, target_index, _ = locate_key(root, target_key)
            source_node, _, source_index, _ = locate_key(root, replacement)
            target_node.keys[target_index], source_node.keys[source_index] = (
                source_node.keys[source_index],
                target_node.keys[target_index],
            )
            swap_orange = (target_key, replacement)
            events.append(Event(
                before_state,
                clone(root),
                "replace",
                key=target_key,
                replacement=replacement,
                target_id=target_node.node_id,
                target_index=target_index,
                source_id=source_node.node_id,
                source_index=source_index,
                orange_keys=swap_orange,
            ))
        elif op[0] == "delete_leaf":
            delete_leaf(op[1], sibling_side=op[2])
        elif op[0] == "merge_internal":
            *path, target_index, sibling_index = op[1:]
            parent_node = root
            for path_index in path:
                parent_node = parent_node.children[path_index]
            before_state = clone(root)
            target_node = parent_node.children[target_index]
            sibling_node = parent_node.children[sibling_index]
            pivot_index = min(target_index, sibling_index)
            pivot = parent_node.keys[pivot_index]
            target_node.keys = sorted([*target_node.keys, pivot, *sibling_node.keys])
            if sibling_index < target_index:
                target_node.children = sibling_node.children + target_node.children
            else:
                target_node.children = target_node.children + sibling_node.children
            del parent_node.children[sibling_index]
            del parent_node.keys[pivot_index]
            if parent_node is root and not root.keys:
                after_state = clone(target_node)
            else:
                after_state = clone(root)
            events.append(Event(
                before_state,
                after_state,
                "internal_merge",
                parent_id=parent_node.node_id,
                target_child_id=target_node.node_id,
                sibling_id=sibling_node.node_id,
                pivot=pivot,
                pivot_index=pivot_index,
                orange_keys=swap_orange,
            ))

    def layout(tree: Node) -> tuple[dict[int, tuple[tuple[int, ...], Point]], list[tuple[int, int]]]:
        groups: dict[int, tuple[tuple[int, ...], Point]] = {}
        links: list[tuple[int, int]] = []
        cursor = 170.0

        def visit(node: Node, depth: int) -> Point:
            nonlocal cursor
            y = (90.0, 300.0, 510.0, 720.0)[min(depth, 3)] + top_offset
            if node.leaf:
                center = (cursor, y)
                cursor += max(140.0, CELL_W * max(1, len(node.keys)) + leaf_gap)
            else:
                children = [visit(child, depth + 1) for child in node.children]
                center = (sum(point[0] for point in children) / len(children), y)
                links.extend((node.node_id, child.node_id) for child in node.children)
            groups[node.node_id] = (tuple(node.keys), center)
            return center

        visit(tree, 0)
        return groups, links

    def link_segment(
        groups: Mapping[int, tuple[tuple[int, ...], Point]],
        links: Sequence[tuple[int, int]],
        parent_id: int,
        child_id: int,
        *,
        parent_points: Sequence[Point] | None = None,
        child_center: Point | None = None,
    ) -> tuple[Point, Point]:
        children = [child for parent, child in links if parent == parent_id]
        slot = children.index(child_id)
        parent_keys, parent_center = groups[parent_id]
        points = list(parent_points) if parent_points is not None else cell_slots(parent_center, len(parent_keys))
        return btree_row_gap(points, slot), child_center or groups[child_id][1]

    def ghost_slot(center: Point, opacity: float) -> str:
        left = center[0] - CELL_W / 2.0
        top = center[1] - CELL_H / 2.0
        return (
            f'<rect x="{left:.1f}" y="{top:.1f}" width="{CELL_W:.1f}" height="{CELL_H:.1f}" rx="9" fill="none" '
            f'stroke="#94A3B8" stroke-width="2.6" stroke-dasharray="9 7" opacity="{opacity:.3f}"/>'
        )

    def edge(start: Point, end: Point, opacity: float = 1.0) -> str:
        return btree_neon_edge(
            (start[0], start[1] + CELL_H / 2.0),
            (end[0], end[1] - CELL_H / 2.0),
            opacity=opacity,
        )

    def edge_up(start: Point, end: Point) -> str:
        return btree_neon_edge(
            (start[0], start[1] - CELL_H / 2.0),
            (end[0], end[1] + CELL_H / 2.0),
        )

    def row_center(points: Sequence[Point]) -> Point:
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )

    def rows_svg(
        rows: Sequence[tuple[Sequence[int | None], Sequence[Point]]],
        edges: Sequence[tuple[Point, Point] | tuple[Point, Point, float]],
        *,
        orange_keys: Sequence[int] = (),
        text_layers: Mapping[tuple[int, int], Sequence[tuple[str, float, str]]] | None = None,
        strike: Point | None = None,
        ghosts: Sequence[tuple[Point, float]] | None = None,
        red_rows: Collection[int] = (),
    ) -> str:
        body = []
        for item in edges:
            start, end = item[0], item[1]
            opacity = item[2] if len(item) > 2 else 1.0
            body.append(edge(start, end, opacity))
        if ghosts:
            body.extend(ghost_slot(point, opacity) for point, opacity in ghosts)
        orange = set(orange_keys)
        red = set(red_rows)
        for row_index, (keys, points) in enumerate(rows):
            layers: dict[int, Sequence[tuple[str, float, str]]] = {}
            for index, key in enumerate(keys):
                if text_layers and (row_index, index) in text_layers:
                    layers[index] = text_layers[(row_index, index)]
                elif key is not None and key in orange:
                    layers[index] = ((str(key), 1.0, GLOW_ORANGE),)
            body.append(btree_neon_row_at_positions(
                [str(key) if key is not None else None for key in keys],
                points,
                text_layers=layers,
                rim=GLOW_RED if row_index in red else None,
                font_size=_fsz,
            ))
        if strike is not None:
            body.append(glow_line(
                (strike[0] - 22.0, strike[1] - 17.0),
                (strike[0] + 22.0, strike[1] + 17.0),
                color=GLOW_RED,
                width=5.0,
                bloom=GLOW_RED,
                radius=0.0,
            ))
        return svg("".join(body), width=_out_w, height=_out_h, color=INK,
                    view_box=f"{_x_off[0]:.1f} {_view_y[0]:.1f} {_view_w[0]:.1f} {_out_h}")

    def blanked_rows(
        blank: Sequence[int | None],
        points: Sequence[Point],
        ghost_opacity: float,
    ) -> tuple[list[tuple[Sequence[int | None], Sequence[Point]]], list[tuple[Point, float]]]:
        rows: list[tuple[Sequence[int | None], Sequence[Point]]] = []
        ghosts: list[tuple[Point, float]] = []
        run_keys: list[int | None] = []
        run_points: list[Point] = []
        for key, point in zip(blank, points):
            if key is None:
                if run_keys:
                    rows.append((tuple(run_keys), tuple(run_points)))
                    run_keys, run_points = [], []
                ghosts.append((point, ghost_opacity))
            else:
                run_keys.append(key)
                run_points.append(point)
        if run_keys:
            rows.append((tuple(run_keys), tuple(run_points)))
        return rows, ghosts

    def red_row_indices(groups: Mapping[int, tuple[tuple[int, ...], Point]], root_id: int) -> set[int]:
        return {
            index
            for index, (node_id, (keys, _center)) in enumerate(groups.items())
            if node_id != root_id and len(keys) < min_keys
        }

    def render_tree(tree: Node, *, orange_keys: Sequence[int] = ()) -> str:
        groups, links = layout(tree)
        rows = [(keys, cell_slots(center, len(keys))) for keys, center in groups.values()]
        edges = [link_segment(groups, links, parent, child) for parent, child in links]
        return rows_svg(rows, edges, orange_keys=orange_keys, red_rows=red_row_indices(groups, tree.node_id))

    def transition(frames: list[str], event: Event) -> None:
        before_groups, _ = layout(event.before)
        after_groups, _ = layout(event.after)
        shared = set(before_groups) & set(after_groups)
        for step in range(1, 25):
            progress = ease(step / 24.0)
            moved = {
                node_id: lerp_point(before_groups[node_id][1], after_groups[node_id][1], progress)
                for node_id in shared
            }
            groups, links = layout(event.after)
            groups = {
                node_id: (keys, moved.get(node_id, center))
                for node_id, (keys, center) in groups.items()
            }
            rows = [(keys, cell_slots(center, len(keys))) for keys, center in groups.values()]
            edges = [link_segment(groups, links, parent, child) for parent, child in links]
            frames.append(rows_svg(rows, edges, orange_keys=event.orange_keys, red_rows=red_row_indices(groups, event.after.node_id)))

    def action_context(event: Event) -> tuple[
        dict[int, tuple[tuple[int, ...], Point]],
        list[tuple[int, int]],
        int,
        int,
        int,
        tuple[Point, ...],
        tuple[Point, ...],
        tuple[Point, ...],
        tuple[int | None, ...],
    ]:
        assert event.parent_id is not None
        assert event.target_child_id is not None and event.sibling_id is not None
        assert event.pivot_index is not None
        groups, links = layout(event.before)
        parent_id = event.parent_id
        target_id = event.target_child_id
        sibling_id = event.sibling_id
        parent_keys, parent_center = groups[parent_id]
        target_keys, target_center = groups[target_id]
        sibling_keys, sibling_center = groups[sibling_id]
        parent_points = tuple(cell_slots(parent_center, len(parent_keys)))
        target_points = tuple(cell_slots(target_center, len(target_keys)))
        sibling_points = tuple(cell_slots(sibling_center, len(sibling_keys)))
        parent_blank = tuple(None if i == event.pivot_index else key for i, key in enumerate(parent_keys))
        return groups, links, parent_id, target_id, sibling_id, parent_points, target_points, sibling_points, parent_blank

    def action_edges(
        groups: Mapping[int, tuple[tuple[int, ...], Point]],
        links: Sequence[tuple[int, int]],
        parent_id: int,
        target_id: int,
        sibling_id: int,
        parent_points: Sequence[Point],
        target_center: Point,
        sibling_center: Point,
        *,
        keep_children: Sequence[int] = (),
    ) -> list[tuple[Point, Point]]:
        active = {parent_id, target_id, sibling_id}
        edges = [
            link_segment(groups, links, parent, child)
            for parent, child in links
            if parent not in active and child not in active
        ]
        for parent, child in links:
            if child == parent_id:
                edges.append(link_segment(groups, links, parent, child))
        children = [child for parent, child in links if parent == parent_id]
        for child in children:
            if child in {target_id, sibling_id} and child not in keep_children:
                continue
            if child == target_id:
                child_center = target_center
            elif child == sibling_id:
                child_center = sibling_center
            else:
                child_center = groups[child][1]
            edges.append((btree_row_gap(parent_points, children.index(child)), child_center))
        return edges

    def animate_replace(frames: list[str], event: Event) -> None:
        assert event.target_id is not None and event.target_index is not None
        assert event.source_id is not None and event.source_index is not None
        assert event.key is not None and event.replacement is not None
        groups, links = layout(event.before)
        rows = [(keys, cell_slots(center, len(keys))) for keys, center in groups.values()]
        edges = [link_segment(groups, links, parent, child) for parent, child in links]
        target_row = list(groups).index(event.target_id)
        source_row = list(groups).index(event.source_id)
        orange_layers = {
            (target_row, event.target_index): ((str(event.key), 1.0, GLOW_ORANGE),),
            (source_row, event.source_index): ((str(event.replacement), 1.0, GLOW_ORANGE),),
        }
        frames.extend([rows_svg(rows, edges, text_layers=orange_layers)] * 12)
        target_point = rows[target_row][1][event.target_index]
        source_point = rows[source_row][1][event.source_index]
        for step in range(1, 91):
            progress = ease(step / 90.0)
            target_now = lerp_point(target_point, source_point, progress)
            source_now = lerp_point(source_point, target_point, progress)
            moving = {
                (target_row, event.target_index): (),
                (source_row, event.source_index): (),
            }
            moving_svg = rows_svg(rows, edges, text_layers=moving)
            moving_svg = moving_svg.replace(
                "</svg>",
                neon_text(str(event.replacement), target_now, size=22.0, color=GLOW_ORANGE, glow=GLOW_ORANGE)
                + neon_text(str(event.key), source_now, size=22.0, color=GLOW_ORANGE, glow=GLOW_ORANGE)
                + "</svg>",
            )
            frames.append(moving_svg)
        hold_layers = {
            (target_row, event.target_index): (
                (str(event.replacement), 1.0, GLOW_ORANGE),
            ),
            (source_row, event.source_index): (
                (str(event.key), 1.0, GLOW_ORANGE),
            ),
        }
        frames.extend([rows_svg(rows, edges, text_layers=hold_layers)] * 30)
        frames.extend([render_tree(event.after, orange_keys=(event.key, event.replacement))] * 1)

    def animate_leaf_delete(frames: list[str], event: Event) -> None:
        """Pull the separator down so it merges with BOTH neighboring children."""
        assert event.key is not None and event.pivot is not None
        assert event.pivot_index is not None
        pivot_index: int = event.pivot_index
        groups, links, parent_id, target_id, sibling_id, parent_points, target_points, sibling_points, parent_blank = action_context(event)
        target_keys = groups[target_id][0]
        sibling_keys = groups[sibling_id][0]
        target_center = groups[target_id][1]
        sibling_center = groups[sibling_id][1]
        merged_keys = tuple(sorted((*target_keys, event.pivot, *sibling_keys)))
        merged_center = ((target_center[0] + sibling_center[0]) / 2.0, target_center[1])
        merged_slots = tuple(cell_slots(merged_center, len(merged_keys)))
        gap_point = parent_points[pivot_index]
        static_edges = action_edges(groups, links, parent_id, target_id, sibling_id, parent_points, target_center, sibling_center)
        base_rows: list[tuple[Sequence[int | None], Sequence[Point]]] = [
            (keys, cell_slots(center, len(keys)))
            for node_id, (keys, center) in groups.items()
            if node_id not in {parent_id, target_id, sibling_id}
        ]

        def blanked_parent(ghost_opacity: float) -> tuple[list[tuple[Sequence[int | None], Sequence[Point]]], list[tuple[Point, float]]]:
            return blanked_rows(parent_blank, parent_points, ghost_opacity)

        target_gap = link_segment(groups, links, parent_id, target_id)[0]
        sibling_gap = link_segment(groups, links, parent_id, sibling_id)[0]
        parent_under = len(groups[parent_id][0]) - 1 < min_keys

        def parent_red(parent_row_count: int) -> set[int]:
            if not parent_under:
                return set()
            return set(range(len(base_rows), len(base_rows) + parent_row_count))

        def convergence_frame(progress: float) -> str:
            ghost_opacity = min(1.0, progress / 0.35)
            anchor_blend = min(1.0, progress / 0.3)
            target_now = tuple(lerp_point(point, merged_slots[merged_keys.index(key)], progress) for key, point in zip(target_keys, target_points))
            sibling_now = tuple(lerp_point(point, merged_slots[merged_keys.index(key)], progress) for key, point in zip(sibling_keys, sibling_points))
            pivot_now = lerp_point(gap_point, merged_slots[merged_keys.index(event.pivot)], progress)
            parent_rows, ghosts = blanked_parent(ghost_opacity)
            rows = [
                *base_rows,
                *parent_rows,
                (target_keys, target_now),
                (sibling_keys, sibling_now),
                ((event.pivot,), (pivot_now,)),
            ]
            edges = static_edges + [
                ((target_gap[0] + (pivot_now[0] - target_gap[0]) * anchor_blend, pivot_now[1]), row_center(target_now)),
                ((sibling_gap[0] + (pivot_now[0] - sibling_gap[0]) * anchor_blend, pivot_now[1]), row_center(sibling_now)),
            ]
            return rows_svg(rows, edges, ghosts=ghosts, orange_keys=event.orange_keys, red_rows=parent_red(len(parent_rows)))

        for step in range(1, 47):
            frames.append(convergence_frame(ease(step / 46.0)))
        parent_rows, ghosts = blanked_parent(1.0)
        merged_rows = [*base_rows, *parent_rows, (merged_keys, merged_slots)]
        stable_merged = rows_svg(merged_rows, static_edges, ghosts=ghosts, orange_keys=event.orange_keys, red_rows=parent_red(len(parent_rows)))
        frames.extend([stable_merged] * 18)

        strike_point = merged_slots[merged_keys.index(event.key)]
        for step in range(1, 19):
            progress = ease(step / 18.0)
            line = glow_line(
                (strike_point[0] - 22.0, strike_point[1] - 17.0),
                (strike_point[0] - 22.0 + 44.0 * progress, strike_point[1] - 17.0 + 34.0 * progress),
                color=GLOW_RED,
                width=5.0,
                bloom=GLOW_RED,
                radius=0.0,
            )
            frames.append(stable_merged.replace("</svg>", line + "</svg>"))
        full_strike = glow_line(
            (strike_point[0] - 22.0, strike_point[1] - 17.0),
            (strike_point[0] + 22.0, strike_point[1] + 17.0),
            color=GLOW_RED,
            width=5.0,
            bloom=GLOW_RED,
            radius=0.0,
        )
        frames.extend([stable_merged.replace("</svg>", full_strike + "</svg>")] * 8)

        survivors = tuple(key for key in merged_keys if key != event.key)
        survivor_points = tuple(point for key, point in zip(merged_keys, merged_slots) if key != event.key)
        survivor_rows = [*base_rows, *parent_rows, (survivors, survivor_points)]
        frames.extend([rows_svg(survivor_rows, static_edges, ghosts=ghosts, orange_keys=event.orange_keys, red_rows=parent_red(len(parent_rows)))] * 15)

        if len(survivors) <= max_keys:
            kept = tuple(key for key in parent_blank if key is not None)
            kept_start = tuple(point for key, point in zip(parent_blank, parent_points) if key is not None)
            kept_end = cell_slots(groups[parent_id][1], len(kept))

            def closing_frame(progress: float) -> str:
                kept_now = tuple(lerp_point(start, end, progress) for start, end in zip(kept_start, kept_end))
                fade_rows, fade_ghosts = blanked_parent(1.0 - progress)
                rows = [*base_rows, *fade_rows, (survivors, survivor_points)]
                hook = (btree_row_gap(kept_now, 0), row_center(survivor_points), ease(progress))
                return rows_svg(rows, static_edges + [hook], ghosts=fade_ghosts, orange_keys=event.orange_keys, red_rows=parent_red(len(fade_rows)))

            for step in range(1, 25):
                frames.append(closing_frame(ease(step / 24.0)))
            frames.extend([closing_frame(1.0)] * 12)
        else:
            promote_index = len(survivors) // 2
            promote_key = survivors[promote_index]
            left_keys = survivors[:promote_index]
            right_keys = survivors[promote_index + 1 :]
            left_center, right_center = (sibling_center, target_center) if sibling_center[0] < target_center[0] else (target_center, sibling_center)
            left_dst = cell_slots(left_center, len(left_keys))
            right_dst = cell_slots(right_center, len(right_keys))

            def split_frame(progress: float) -> str:
                ghost_opacity = 1.0 if progress < 0.7 else max(0.0, 1.0 - (progress - 0.7) / 0.3)
                fade_rows, fade_ghosts = blanked_parent(ghost_opacity)
                left_now = tuple(lerp_point(point, end, progress) for point, end in zip(survivor_points[:promote_index], left_dst))
                right_now = tuple(lerp_point(point, end, progress) for point, end in zip(survivor_points[promote_index + 1 :], right_dst))
                promote_now = lerp_point(survivor_points[promote_index], gap_point, progress)
                rows = [
                    *base_rows,
                    *fade_rows,
                    (left_keys, left_now),
                    (right_keys, right_now),
                    ((promote_key,), (promote_now,)),
                ]
                left_gap = btree_row_gap(parent_points, pivot_index)
                right_gap = btree_row_gap(parent_points, pivot_index + 1)
                anchor_blend = max(0.0, (progress - 0.75) / 0.25)
                line_opacity = min(1.0, progress / 0.2)
                edges = static_edges + [
                    (
                        (promote_now[0] + (left_gap[0] - promote_now[0]) * anchor_blend, promote_now[1]),
                        row_center(left_now),
                        line_opacity,
                    ),
                    (
                        (promote_now[0] + (right_gap[0] - promote_now[0]) * anchor_blend, promote_now[1]),
                        row_center(right_now),
                        line_opacity,
                    ),
                ]
                return rows_svg(rows, edges, ghosts=fade_ghosts, orange_keys=event.orange_keys)

            for step in range(1, 37):
                frames.append(split_frame(ease(step / 36.0)))
            filled_parent = tuple(promote_key if key is None else key for key in parent_blank)
            landed_rows = [
                *base_rows,
                (filled_parent, parent_points),
                (left_keys, left_dst),
                (right_keys, right_dst),
            ]
            landed_edges = static_edges + [
                (btree_row_gap(parent_points, pivot_index), row_center(left_dst)),
                (btree_row_gap(parent_points, pivot_index + 1), row_center(right_dst)),
            ]
            frames.extend([rows_svg(landed_rows, landed_edges, orange_keys=event.orange_keys)] * 18)
        transition(frames, event)

    def animate_internal_merge(frames: list[str], event: Event) -> None:
        """Pull the root separator down between two internal nodes; the merged node becomes the new root."""
        assert event.pivot is not None and event.pivot_index is not None
        assert event.target_child_id is not None and event.sibling_id is not None
        groups, links, parent_id, target_id, sibling_id, parent_points, target_points, sibling_points, parent_blank = action_context(event)
        target_keys = groups[target_id][0]
        sibling_keys = groups[sibling_id][0]
        target_center = groups[target_id][1]
        sibling_center = groups[sibling_id][1]
        merged_keys = tuple(sorted((*target_keys, event.pivot, *sibling_keys)))
        merged_center = ((target_center[0] + sibling_center[0]) / 2.0, target_center[1])
        merged_slots = tuple(cell_slots(merged_center, len(merged_keys)))
        gap_point = parent_points[event.pivot_index]
        after_groups, after_links = layout(event.after)
        target_gap = link_segment(groups, links, parent_id, target_id)[0]
        sibling_gap = link_segment(groups, links, parent_id, sibling_id)[0]
        target_child_ids = [child for parent, child in links if parent == target_id]
        sibling_child_ids = [child for parent, child in links if parent == sibling_id]
        if sibling_center[0] < target_center[0]:
            all_children = sibling_child_ids + target_child_ids
        else:
            all_children = target_child_ids + sibling_child_ids
        leaf_rows = [
            (keys, cell_slots(center, len(keys)))
            for node_id, (keys, center) in groups.items()
            if node_id not in {parent_id, target_id, sibling_id}
        ]
        static_edges = action_edges(groups, links, parent_id, target_id, sibling_id, parent_points, target_center, sibling_center)
        parent_under = len(groups[parent_id][0]) - 1 < min_keys

        def convergence_frame(progress: float) -> str:
            ghost_opacity = min(1.0, progress / 0.35)
            anchor_blend = min(1.0, progress / 0.3)
            target_now = tuple(lerp_point(point, merged_slots[merged_keys.index(key)], progress) for key, point in zip(target_keys, target_points))
            sibling_now = tuple(lerp_point(point, merged_slots[merged_keys.index(key)], progress) for key, point in zip(sibling_keys, sibling_points))
            pivot_now = lerp_point(gap_point, merged_slots[merged_keys.index(event.pivot)], progress)
            fade_rows, fade_ghosts = blanked_rows(parent_blank, parent_points, ghost_opacity)
            rows = [
                *leaf_rows,
                *fade_rows,
                (target_keys, target_now),
                (sibling_keys, sibling_now),
                ((event.pivot,), (pivot_now,)),
            ]
            red = {len(leaf_rows) + len(fade_rows)}
            if parent_under:
                red.update(len(leaf_rows) + offset for offset in range(len(fade_rows)))
            edges = static_edges + [
                (btree_row_gap(target_now, slot), groups[child_id][1])
                for slot, child_id in enumerate(target_child_ids)
            ] + [
                (btree_row_gap(sibling_now, slot), groups[child_id][1])
                for slot, child_id in enumerate(sibling_child_ids)
            ] + [
                ((target_gap[0] + (pivot_now[0] - target_gap[0]) * anchor_blend, pivot_now[1]), row_center(target_now)),
                ((sibling_gap[0] + (pivot_now[0] - sibling_gap[0]) * anchor_blend, pivot_now[1]), row_center(sibling_now)),
            ]
            return rows_svg(rows, edges, ghosts=fade_ghosts, orange_keys=event.orange_keys, red_rows=red)

        for step in range(1, 47):
            frames.append(convergence_frame(ease(step / 46.0)))
        stable_edges = [
            (btree_row_gap(merged_slots, slot), groups[child_id][1])
            for slot, child_id in enumerate(all_children)
        ]
        parent_rows, ghosts = blanked_rows(parent_blank, parent_points, 1.0)
        stable_red = {len(leaf_rows) + offset for offset in range(len(parent_rows))} if parent_under else set()
        stable = rows_svg(
            [*leaf_rows, *parent_rows, (merged_keys, merged_slots)],
            static_edges + stable_edges,
            ghosts=ghosts,
            orange_keys=event.orange_keys,
            red_rows=stable_red,
        )
        frames.extend([stable] * 18)

        start_positions = {node_id: center for node_id, (_keys, center) in groups.items()}
        start_positions[event.target_child_id] = merged_center
        settle_red = red_row_indices(after_groups, event.after.node_id)
        children_by_parent: dict[int, list[int]] = {}
        for link_parent, link_child in after_links:
            children_by_parent.setdefault(link_parent, []).append(link_child)
        for step in range(1, 43):
            progress = ease(step / 42.0)
            positions = {
                node_id: lerp_point(start_positions.get(node_id, after_groups[node_id][1]), after_groups[node_id][1], progress)
                for node_id in after_groups
            }
            rows = [
                (keys, tuple(cell_slots(positions[node_id], len(keys))))
                for node_id, (keys, _center) in after_groups.items()
            ]
            edges: list[tuple[Point, Point]] = []
            for link_parent, link_children in children_by_parent.items():
                parent_points_now = cell_slots(positions[link_parent], len(after_groups[link_parent][0]))
                for slot, link_child in enumerate(link_children):
                    edges.append((btree_row_gap(parent_points_now, slot), positions[link_child]))
            frames.append(rows_svg(
                rows,
                edges,
                ghosts=[(gap_point, 1.0 - progress)],
                orange_keys=event.orange_keys,
                red_rows=set(settle_red),
            ))

    def burn_caption(frame: str, lines: Sequence[str]) -> str:
        caption_body = []
        for index, line in enumerate(lines):
            caption_body.append(
                neon_text(
                    line,
                    (_out_w / 2.0, 34.0 + index * 38.0),
                    size=30.0,
                    color=INK,
                    glow=GLOW_BLUE,
                )
            )
        return frame.replace("</svg>", "".join(caption_body) + "</svg>")

    _overview_center = width / 2.0
    _overview_width = float(width)
    _work_width = 3000.0
    _x_off = [_overview_center - _overview_width / 2.0]

    _cam_by_event = []
    for ev in events:
        if ev.kind == "replace":
            _cam_by_event.append(2300.0)
        elif ev.kind == "internal_merge" and ev.key is None:
            # Keep the left-side context through the root contraction; do not pan back.
            _cam_by_event.append(1650.0)
        elif ev.kind == "internal_merge":
            _cam_by_event.append(1650.0)
        else:
            if ev.key is not None and ev.key >= 400:
                _cam_by_event.append(2300.0)
            else:
                _cam_by_event.append(1650.0)

    _center_cam = 2050.0

    def _set_view(center: float, view_width: float) -> None:
        _view_w[0] = view_width
        _view_y[0] = 0.0
        _x_off[0] = center - view_width / 2.0

    def _pan(
        from_cam: float,
        from_width: float,
        to_cam: float,
        to_width: float,
        step: int,
        total: int,
    ) -> None:
        if total <= 1:
            _set_view(to_cam, to_width)
            return
        t = ease(step / (total - 1))
        _set_view(
            from_cam + (to_cam - from_cam) * t,
            from_width + (to_width - from_width) * t,
        )

    frames: list[str] = []
    _prev_cam = _overview_center
    _prev_width = _overview_width
    _set_view(_prev_cam, _prev_width)
    for _ in range(24):
        frames.append(render_tree(events[0].before, orange_keys=events[0].orange_keys))
    for ev_idx, event in enumerate(events):
        curr_cam = _cam_by_event[ev_idx]
        for step in range(12):
            _pan(_prev_cam, _prev_width, curr_cam, _work_width, step, 12)
            frames.append(render_tree(event.before, orange_keys=event.orange_keys))
        _set_view(curr_cam, _work_width)
        if event.kind == "replace":
            animate_replace(frames, event)
        elif event.kind == "internal_merge":
            animate_internal_merge(frames, event)
        else:
            animate_leaf_delete(frames, event)
        for _ in range(12):
            _set_view(curr_cam, _work_width)
            frames.append(render_tree(event.after, orange_keys=event.orange_keys))
        _prev_cam = curr_cam
        _prev_width = _work_width
    _set_view(_prev_cam, _prev_width)
    for _ in range(90):
        frames.append(render_tree(events[-1].after, orange_keys=events[-1].orange_keys))
    CELL_W, CELL_H, BTREE_NEON_CELL_W, BTREE_NEON_CELL_H = _saved_geo
    return frames


def btree_delete_5() -> None:
    """Render every deletion action of the order-5 lesson on one four-level tree."""
    subtitle_spans: list[tuple[int, int, tuple[str, ...]]] = [
        (0, 36, ("这是一个五阶、四层的 B 树。", "每个节点最多四个关键字，非根节点至少两个。")),
        (36, 48, ("删除内部关键字 450。", "它不是叶节点，先用后继 460 替换它。")),
        (48, 138, ("替换前，450 和 460 先变成橙色。", "450 飞到 460 原来的格子，460 飞到 450 原来的格子。")),
        (138, 181, ("替换结束后，两个数字继续保持橙色。", "原来的 450 转到叶节点，接下来删除这个 450。")),
        (181, 217, ("删除叶节点中的 450。", "分隔关键字 500 被两个子民拉回去。")),
        (217, 257, ("原来的位置留下空槽，首领和两个子民之间保持两根线。", "三个部分合并成一个节点：450、480、500、520、540。")),
        (257, 298, ("划掉并删除 450。", "剩下四个关键字，没有超过容量，不需要推举，直接完成合并。")),
        (298, 370, ("合并完成，父节点没有下溢。",)),
        (370, 406, ("接着删除叶节点中的 410。", "分隔关键字 460 被两个子民拉回去。")),
        (406, 452, ("合并后得到六个关键字，超过五阶节点的容量。",)),
        (452, 511, ("中间关键字 500 带着两根线向上推举。", "它落回父节点的空槽。")),
        (511, 577, ("左右两个子节点重新接好。", "推举完成。")),
        (577, 635, ("现在删除叶节点中的 360。", "分隔关键字 380 被两个子民拉回去。")),
        (635, 679, ("合并后划掉并删除 360，剩下四个关键字，直接合并。",)),
        (679, 766, ("父节点交出 380 后，只剩下 [350]。", "关键字数量少于下限，节点下溢，亮起红边。")),
        (766, 824, ("下溢继续向上传递。", "分隔关键字 300 被两个子民拉回去。")),
        (824, 842, ("[220,250]、300 和 [350] 合并成一个节点。",)),
        (842, 896, ("父节点 [200,300] 交出 300 后，只剩 [200]。", "它也下溢了，红边继续保留。")),
        (896, 954, ("最后处理根节点。", "根的分隔关键字 400 被两个子民拉回去。")),
        (954, 972, ("[200]、400 和 [600,700] 合并成 [200,400,600,700]。", "合并结果没有超过容量，不需要推举。")),
        (972, 1026, ("根节点变空，合并节点整体上升成为新根。", "整棵树从四层减少为三层。")),
        (1026, 1116, ("删除完成：下溢一路传到根，树从四层缩成三层。",)),
    ]

    tree_frames = btree_delete_complex_frames(
        5,
        (
            (400,),
            (
                ((200, 300), (
                    ((100, 150), (((50, 80), ()), ((120, 140), ()), ((160, 180), ()))),
                    ((220, 250), (((210, 215), ()), ((230, 240), ()), ((260, 280), ()))),
                    ((350, 380), (((340, 345), ()), ((360, 370), ()), ((390, 395), ()))),
                )),
                ((600, 700), (
                    ((450, 500, 550), (((410, 430), ()), ((460, 480), ()), ((520, 540), ()), ((560, 580), ()))),
                    ((650, 680), (((610, 630), ()), ((660, 670), ()), ((685, 695), ()))),
                    ((750, 800), (((710, 730), ()), ((760, 780), ()), ((810, 860), ()))),
                )),
            ),
        ),
        (
            ("replace", 450, 460),
            ("delete_leaf", 450, "right"),
            ("delete_leaf", 410, "right"),
            ("delete_leaf", 360, "right"),
            ("merge_internal", 0, 2, 1),
            ("merge_internal", 0, 1),
        ),
        width=5100,
        height=720,
        leaf_gap=96.0,
        output_width=1920,
        output_height=920,
        view_width=1800,
    )
    total = len(tree_frames)
    video_w, video_h = 1920, 920
    sub_h = 160

    def _subtitle_frame(lines: tuple[str, ...]) -> str:
        body = []
        for i, line in enumerate(lines):
            body.append(neon_text(line, (video_w / 2.0, 52.0 + i * 52.0),
                                  size=34.0, color=INK, glow=GLOW_BLUE))
        return svg("".join(body), width=video_w, height=sub_h, color=INK)

    sub_frames: list[str] = []
    for idx in range(total):
        active = next((lines for s, e, lines in subtitle_spans if s <= idx < e), None)
        sub_frames.append(_subtitle_frame(active) if active else _subtitle_frame(("",)))

    with TemporaryDirectory(prefix="btree5-comb-", dir=ROOT) as tmp:
        tmp_path = Path(tmp)
        tree_webm = tmp_path / "tree.webm"
        sub_webm = tmp_path / "sub.webm"
        render_webm(
            "btree-delete-5",
            tree_frames,
            fps=30,
            transparent=False,
            crop=False,
            zoom=2.0,
            background="black",
            output_path=tree_webm,
        )
        render_webm(
            "btree-delete-5-sub",
            sub_frames,
            fps=30,
            transparent=False,
            crop=False,
            zoom=2.0,
            background="black",
            output_path=sub_webm,
        )
        final = ASSETS / "btree-delete-5.webm"
        final.unlink(missing_ok=True)
        run(["ffmpeg", "-y",
             "-i", str(sub_webm), "-i", str(tree_webm),
             "-filter_complex",
             f"[0:v]scale={video_w}:{sub_h},setsar=1[sub];"
             f"[1:v]scale={video_w}:{video_h},setsar=1[tree];"
             f"[sub][tree]vstack=inputs=2[out]",
             "-map", "[out]",
             "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "16",
             "-pix_fmt", "yuv420p", str(final)], check=True)


def btree_delete_complex_legacy_v1() -> None:
    """Delete repeatedly from a three-level order-4 tree with local and cascading repairs."""
    width, height = 1300, 700

    def state(groups: Mapping[str, tuple[Sequence[str], Point]], edges: Sequence[tuple[str, str]]) -> dict:
        keys = [key for members, _ in groups.values() for key in members]
        assert len(keys) == len(set(keys))
        return {"groups": groups, "edges": edges}

    def positions_for(tree: dict) -> dict[str, Point]:
        positions: dict[str, Point] = {}
        for members, center in tree["groups"].values():
            for key, point in zip(members, cell_slots(center, len(members))):
                positions[key] = point
        return positions

    def render(tree: dict, positions: Mapping[str, Point] | None = None, strike: str = "") -> str:
        positions = positions or positions_for(tree)
        parts: list[str] = []
        for parent, child in tree["edges"]:
            parent_members, parent_center = tree["groups"][parent]
            child_members, child_center = tree["groups"][child]
            parent_points = [positions[key] for key in parent_members]
            child_points = [positions[key] for key in child_members]
            parent_x = sum(point[0] for point in parent_points) / len(parent_points)
            child_x = sum(point[0] for point in child_points) / len(child_points)
            parts.append(
                btree_neon_edge(
                    (parent_x, parent_center[1] + CELL_H / 2.0),
                    (child_x, child_center[1] - CELL_H / 2.0),
                )
            )
        for members, _center in tree["groups"].values():
            parts.append(btree_neon_row_at_positions(members, [positions[key] for key in members]))
        if strike:
            point = positions[strike]
            parts.append(
                glow_line(
                    (point[0] - 22.0, point[1] - 17.0),
                    (point[0] + 22.0, point[1] + 17.0),
                    color=GLOW_RED,
                    width=5.0,
                    bloom=GLOW_RED,
                    radius=0.0,
                )
            )
        return svg("".join(parts), width=width, height=height, color=INK)

    def transition(frames: list[str], before: dict, after: dict, deleted: str) -> None:
        before_positions = positions_for(before)
        after_positions = positions_for(after)
        frames.extend([render(before)] * 12)
        for step in range(1, 19):
            progress = ease(step / 18.0)
            frames.append(render(before, strike=deleted))
        for step in range(1, 31):
            progress = ease(step / 30.0)
            current = dict(after_positions)
            for key in after_positions:
                if key in before_positions and key != deleted:
                    current[key] = lerp_point(before_positions[key], after_positions[key], progress)
            frames.append(render(after, current))
        frames.extend([render(after)] * 15)

    root = (650.0, 80.0)
    a = (230.0, 270.0)
    b = (650.0, 270.0)
    c = (1060.0, 270.0)
    a1, a2, a3 = (100.0, 480.0), (230.0, 480.0), (360.0, 480.0)
    b1, b2 = (560.0, 480.0), (740.0, 480.0)
    c1, c2 = (960.0, 480.0), (1140.0, 480.0)

    s0 = state(
        {
            "root": (("60", "120"), root),
            "a": (("20", "40"), a),
            "b": (("90",), b),
            "c": (("150",), c),
            "a1": (("5", "10"), a1),
            "a2": (("25", "30"), a2),
            "a3": (("45", "50"), a3),
            "b1": (("65", "70"), b1),
            "b2": (("100", "110"), b2),
            "c1": (("130", "140"), c1),
            "c2": (("160", "170"), c2),
        },
        (("root", "a"), ("root", "b"), ("root", "c"),
         ("a", "a1"), ("a", "a2"), ("a", "a3"),
         ("b", "b1"), ("b", "b2"), ("c", "c1"), ("c", "c2")),
    )
    s1 = state({**s0["groups"], "a1": (("5",), a1)}, s0["edges"])
    s2 = state({**s1["groups"], "a2": (("30",), a2)}, s1["edges"])
    s3 = state(
        {
            "root": s2["groups"]["root"], "a": (("20", "45"), a), "b": s2["groups"]["b"], "c": s2["groups"]["c"],
            "a1": (("5",), a1), "a2": (("40",), a2), "a3": (("50",), a3),
            "b1": s2["groups"]["b1"], "b2": s2["groups"]["b2"],
            "c1": s2["groups"]["c1"], "c2": s2["groups"]["c2"],
        },
        (("root", "a"), ("root", "b"), ("root", "c"),
         ("a", "a1"), ("a", "a2"), ("a", "a3"),
         ("b", "b1"), ("b", "b2"), ("c", "c1"), ("c", "c2")),
    )
    s4 = state(
        {
            "root": s3["groups"]["root"], "a": (("20",), a), "b": s3["groups"]["b"], "c": s3["groups"]["c"],
            "a1": s3["groups"]["a1"], "a2": (("40", "45"), (300.0, 480.0)),
            "b1": s3["groups"]["b1"], "b2": s3["groups"]["b2"],
            "c1": s3["groups"]["c1"], "c2": s3["groups"]["c2"],
        },
        (("root", "a"), ("root", "b"), ("root", "c"),
         ("a", "a1"), ("a", "a2"), ("b", "b1"), ("b", "b2"), ("c", "c1"), ("c", "c2")),
    )
    s5 = state({**s4["groups"], "b1": (("70",), b1)}, s4["edges"])
    s6 = state(
        {**s5["groups"], "b": (("100",), b), "b1": (("90",), b1), "b2": (("110",), b2)},
        s5["edges"],
    )
    # Deleting 110 merges B's two leaf children, then the empty B internal node
    # merges upward with A through the root separator 60.
    s7 = state(
        {
            "root": (("120",), root),
            "ab": (("20", "60"), (360.0, 270.0)),
            "c": s6["groups"]["c"],
            "ab1": (("5",), (170.0, 480.0)),
            "ab2": (("40", "45"), (350.0, 480.0)),
            "ab3": (("90", "100"), (530.0, 480.0)),
            "c1": s6["groups"]["c1"], "c2": s6["groups"]["c2"],
        },
        (("root", "ab"), ("root", "c"), ("ab", "ab1"), ("ab", "ab2"), ("ab", "ab3"), ("c", "c1"), ("c", "c2")),
    )
    s8 = state({**s7["groups"], "c1": (("130",), c1)}, s7["edges"])
    s9 = state(
        {**s8["groups"], "c": (("160",), c), "c1": (("150",), c1), "c2": (("170",), c2)},
        s8["edges"],
    )

    frames: list[str] = []
    for before, after, deleted in (
        (s0, s1, "10"), (s1, s2, "25"), (s2, s3, "30"),
        (s3, s4, "50"), (s4, s5, "65"), (s5, s6, "70"),
        (s6, s7, "110"), (s7, s8, "140"), (s8, s9, "130"),
    ):
        transition(frames, before, after, deleted)
    frames.extend([render(s9)] * 90)
    render_webm("btree-delete-complex", frames, fps=30, transparent=True)


def btree_merge_frames(width: int, height: int, root_c: Point, left_c: Point, right_c: Point, merged_c: Point) -> list[str]:
    """Merge both children, strike the deleted key, then shrink the root level."""

    def row(keys: Sequence[str], points: Sequence[Point]) -> str:
        return btree_neon_row_at_positions(keys, points)

    def center(points: Sequence[Point]) -> Point:
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )

    def render_rows(rows: Sequence[tuple[Sequence[str], Sequence[Point]]], *, tree: bool = False, overlay: str = "") -> str:
        parts: list[str] = []
        if tree and len(rows) == 3:
            parent = center(rows[1][1])
            for child in (rows[0][1], rows[2][1]):
                child_center = center(child)
                parts.append(btree_neon_edge(
                    (parent[0], parent[1] + BTREE_NEON_CELL_H / 2.0),
                    (child_center[0], child_center[1] - BTREE_NEON_CELL_H / 2.0),
                ))
        parts.extend(row(keys, points) for keys, points in rows)
        parts.append(overlay)
        return svg("".join(parts), width=width, height=height, color=INK)

    ten = cell_slots(left_c, 1)[0]
    forty = cell_slots(root_c, 1)[0]
    sixty = cell_slots(right_c, 1)[0]
    merged_three = cell_slots(merged_c, 3)
    merged_two = cell_slots(merged_c, 2)
    frames: list[str] = []

    initial_rows = [
        (("10",), (ten,)),
        (("40",), (forty,)),
        (("60",), (sixty,)),
    ]
    frames.extend([render_rows(initial_rows, tree=True)] * 24)

    # Pull both children and the separator into one contiguous three-key node.
    sources = (ten, forty, sixty)
    for step in range(1, 43):
        t = ease(step / 42.0)
        rows = [
            (("10",), (lerp_point(sources[0], merged_three[0], t),)),
            (("40",), (lerp_point(sources[1], merged_three[1], t),)),
            (("60",), (lerp_point(sources[2], merged_three[2], t),)),
        ]
        frames.append(render_rows(rows, tree=True))
    frames.extend([render_rows([(("10", "40", "60"), merged_three)])] * 18)

    # Strike through 10 before deleting it.
    strike_point = merged_three[0]
    for step in range(1, 19):
        t = ease(step / 18.0)
        strike = glow_line(
            (strike_point[0] - 22.0, strike_point[1] - 17.0),
            (strike_point[0] - 22.0 + 44.0 * t, strike_point[1] - 17.0 + 34.0 * t),
            color=GLOW_RED,
            width=5.0,
            bloom=GLOW_RED,
            radius=0.0,
        )
        frames.append(render_rows([(("10", "40", "60"), merged_three)], overlay=strike))
    full_strike = glow_line(
        (strike_point[0] - 22.0, strike_point[1] - 17.0),
        (strike_point[0] + 22.0, strike_point[1] + 17.0),
        color=GLOW_RED,
        width=5.0,
        bloom=GLOW_RED,
        radius=0.0,
    )
    frames.extend([render_rows([(("10", "40", "60"), merged_three)], overlay=full_strike)] * 8)

    # Remove 10; 40 and 60 keep their original three-key slots.
    remaining_positions = merged_three[1:]
    frames.extend([render_rows([(("40", "60"), remaining_positions)])] * 24)
    frames.extend([render_rows([(("40", "60"), remaining_positions)])] * 18)

    # Raise the complete merged node to become the new root.
    root_two = cell_slots(root_c, 2)
    for step in range(1, 37):
        t = ease(step / 36.0)
        raised = tuple(lerp_point(source, target, t) for source, target in zip(remaining_positions, root_two))
        frames.append(render_rows([(("40", "60"), raised)]))
    final = render_rows([(("40", "60"), root_two)])
    frames.extend([final] * 90)
    return frames


def btree_merge() -> None:
    """Render the unified merge case as a standalone transparent WebM."""
    render_webm(
        "btree-merge",
        btree_merge_frames(900, 540, (450.0, 120.0), (250.0, 350.0), (650.0, 350.0), (450.0, 350.0)),
        fps=30,
        transparent=True,
    )


def btree_lend_frames(width: int, height: int, root_c: Point, left_c: Point, right_c: Point, merged_c: Point) -> list[str]:
    """Unified deletion case two: merge, delete, then promote the sibling's key instead of the old separator."""

    def row(keys: Sequence[str], positions: Sequence[Point]) -> str:
        return btree_neon_row_at_positions(keys, positions)

    def row_center(points: Sequence[Point]) -> Point:
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )

    def render_rows(
        rows: Sequence[tuple[Sequence[str], Sequence[Point]]],
        *,
        tree: bool = False,
        overlay: str = "",
    ) -> str:
        parts: list[str] = []
        if tree and len(rows) == 3:
            parent = row_center(rows[1][1])
            for child in (rows[0][1], rows[2][1]):
                child_center = row_center(child)
                parts.append(
                    btree_neon_edge(
                        (parent[0], parent[1] + BTREE_NEON_CELL_H / 2.0),
                        (child_center[0], child_center[1] - BTREE_NEON_CELL_H / 2.0),
                    )
                )
        parts.extend(row(keys, points) for keys, points in rows)
        parts.append(overlay)
        return svg("".join(parts), width=width, height=height, color=INK)

    ten_slot = cell_slots(left_c, 1)[0]
    forty_slot = cell_slots(root_c, 1)[0]
    right_three = cell_slots(right_c, 3)
    merged_five = cell_slots(merged_c, 5)
    final_left = cell_slots(left_c, 2)
    final_right = cell_slots(right_c, 1)
    root_one = cell_slots(root_c, 1)[0]
    frames: list[str] = []

    frames.extend([
        render_rows([
            (("10",), (ten_slot,)),
            (("40",), (forty_slot,)),
            (("50", "60", "70"), right_three),
        ], tree=True)
    ] * 24)

    merge_sources = [(ten_slot,), (forty_slot,), tuple(right_three)]
    merge_targets = [tuple(merged_five[:1]), tuple(merged_five[1:2]), tuple(merged_five[2:5])]
    for step in range(1, 43):
        t = ease(step / 42.0)
        rows = [
            (keys, tuple(lerp_point(source, target, t) for source, target in zip(source_points, target_points)))
            for keys, source_points, target_points in zip(
                (("10",), ("40",), ("50", "60", "70")),
                merge_sources,
                merge_targets,
            )
        ]
        frames.append(render_rows(rows, tree=True))
    frames.extend([render_rows([(("10", "40", "50", "60", "70"), merged_five)])] * 18)

    ten_point = merged_five[0]

    def red_dashed_frame(point: Point, opacity: float) -> str:
        left = point[0] - BTREE_NEON_CELL_W / 2.0 - 5.0
        right = point[0] + BTREE_NEON_CELL_W / 2.0 + 5.0
        top = point[1] - BTREE_NEON_CELL_H / 2.0 - 5.0
        bottom = point[1] + BTREE_NEON_CELL_H / 2.0 + 5.0
        return (
            f'<rect x="{left:.1f}" y="{top:.1f}" width="{right - left:.1f}" height="{bottom - top:.1f}" '
            f'fill="none" stroke="#FF7070" stroke-width="2.5" stroke-dasharray="7 5" opacity="{opacity:.2f}" rx="9.0"/>'
        )

    for step in range(1, 19):
        frames.append(render_rows([(("10", "40", "50", "60", "70"), merged_five)], overlay=red_dashed_frame(ten_point, ease(step / 18.0))))
    frames.extend([
        render_rows(
            [(("10", "40", "50", "60", "70"), merged_five)],
            overlay=red_dashed_frame(ten_point, 1.0),
        )
    ] * 8)

    remaining_positions = merged_five[1:]
    frames.extend([render_rows([(("40", "50", "60", "70"), remaining_positions)])] * 24)
    frames.extend([render_rows([(("40", "50", "60", "70"), remaining_positions)])] * 18)

    split_sources = remaining_positions
    split_targets = tuple(final_left) + (root_one,) + tuple(final_right)
    for step in range(1, 43):
        t = ease(step / 42.0)
        positions = tuple(
            lerp_point(source, target, t)
            for source, target in zip(split_sources, split_targets)
        )
        rows = [
            (("40", "50"), positions[:2]),
            (("60",), (positions[2],)),
            (("70",), positions[3:]),
        ]
        frames.append(render_rows(rows, tree=True))
    final_rows = [
        (("40", "50"), final_left),
        (("60",), (root_one,)),
        (("70",), final_right),
    ]
    frames.extend([render_rows(final_rows, tree=True)] * 90)
    return frames


def btree_lend() -> None:
    """Render the unified lend case as a standalone transparent WebM."""
    render_webm(
        "btree-lend",
        btree_lend_frames(1100, 600, (550.0, 120.0), (300.0, 370.0), (820.0, 370.0), (550.0, 370.0)),
        fps=30,
        transparent=True,
    )


def btree_classic_plain_frames(
    width: int,
    height: int,
    root_c: Point,
    left_c: Point,
    right_c: Point,
    captions: Mapping[str, str] | None = None,
) -> list[str]:
    """Traditional deletion case one: the leaf keeps enough keys, so plain removal needs no repair."""

    def caption(phase: str) -> str:
        if not captions or phase not in captions:
            return ""
        return neon_text(captions[phase], (width / 2.0, height - 130.0))

    def row(keys: Sequence[str], positions: Sequence[Point]) -> str:
        return btree_neon_row_at_positions(keys, positions)

    def row_center(points: Sequence[Point]) -> Point:
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )

    def render_rows(
        rows: Sequence[tuple[Sequence[str], Sequence[Point]]],
        *,
        tree: bool = False,
        overlay: str = "",
    ) -> str:
        parts: list[str] = []
        if tree and len(rows) == 3:
            parent = row_center(rows[1][1])
            for child in (rows[0][1], rows[2][1]):
                child_center = row_center(child)
                parts.append(
                    btree_neon_edge(
                        (parent[0], parent[1] + BTREE_NEON_CELL_H / 2.0),
                        (child_center[0], child_center[1] - BTREE_NEON_CELL_H / 2.0),
                    )
                )
        parts.extend(row(keys, points) for keys, points in rows)
        parts.append(overlay)
        return svg("".join(parts), width=width, height=height, color=INK)

    def strike_at(point: Point, progress: float) -> str:
        return glow_line(
            (point[0] - 22.0, point[1] - 17.0),
            (point[0] - 22.0 + 44.0 * progress, point[1] - 17.0 + 34.0 * progress),
            color=GLOW_RED,
            width=5.0,
            bloom=GLOW_RED,
            radius=0.0,
        )

    left_three = cell_slots(left_c, 3)
    right_two = cell_slots(right_c, 2)
    root_one = cell_slots(root_c, 1)[0]
    frames: list[str] = []

    initial_rows = [
        (("10", "20", "30"), left_three),
        (("40",), (root_one,)),
        (("60", "70"), right_two),
    ]
    frames.extend([render_rows(initial_rows, tree=True)] * 24)

    for step in range(1, 19):
        frames.append(render_rows(initial_rows, tree=True, overlay=strike_at(left_three[0], ease(step / 18.0)) + caption("slash")))
    frames.extend([render_rows(initial_rows, tree=True, overlay=strike_at(left_three[0], 1.0) + caption("slash"))] * 8)

    settled_rows = [
        (("20", "30"), tuple(left_three[1:])),
        (("40",), (root_one,)),
        (("60", "70"), right_two),
    ]
    frames.extend([render_rows(settled_rows, tree=True, overlay=caption("settled"))] * 24)
    frames.extend([render_rows(settled_rows, tree=True, overlay=caption("final"))] * 90)
    return frames


def btree_side_by_side_frames(
    left_frames: Sequence[str],
    right_frames: Sequence[str],
    *,
    panel_width: int,
    height: int,
    left_title: str,
    right_title: str,
    pause_frames: int = 75,
) -> list[str]:
    """Play two takes in separate windows, dimming the inactive window."""
    if not left_frames or not right_frames:
        raise ValueError("both side-by-side takes need at least one frame")
    if pause_frames < 0:
        raise ValueError("pause_frames must be non-negative")

    def panel_body(frame: str, x_offset: int) -> str:
        start = frame.find(">")
        end = frame.rfind("</svg>")
        if start < 0 or end < start:
            raise ValueError("expected a complete SVG frame")
        return f'<svg x="{x_offset}" y="0" width="{panel_width}" height="{height}" viewBox="0 0 {panel_width} {height}">{frame[start + 1:end]}</svg>'

    def compose(left: str, right: str, active: str) -> str:
        if active not in {"left", "right"}:
            raise ValueError("active panel must be left or right")
        shadow_left = '<rect x="0" y="0" width="{0}" height="{1}" fill="#000000" opacity="0.20"/>'.format(panel_width, height) if active != "left" else ""
        shadow_right = '<rect x="{0}" y="0" width="{1}" height="{2}" fill="#000000" opacity="0.20"/>'.format(panel_width, panel_width, height) if active != "right" else ""
        body = (
            panel_body(left, 0)
            + panel_body(right, panel_width)
            + glow_line((panel_width, 84.0), (panel_width, height - 84.0), color=NODE_RIM, width=2.0, bloom=GLOW_BLUE)
            + neon_text(left_title, (panel_width / 2.0, 40.0), size=30.0, glow=GLOW_BLUE)
            + neon_text(right_title, (panel_width * 1.5, 40.0), size=30.0, glow=GLOW_BLUE)
            + shadow_left
            + shadow_right
        )
        return svg(body, width=panel_width * 2, height=height, color=INK)

    left_initial = left_frames[0]
    right_initial = right_frames[0]
    left_final = left_frames[-1]
    body: list[str] = [compose(left, right_initial, "left") for left in left_frames]
    body.extend([compose(left_final, right_initial, "right")] * pause_frames)
    body.extend([compose(left_final, right, "right") for right in right_frames])
    return body


def btree_cascade_merge_frames(width: int, height: int) -> list[str]:
    """Our deletion method: a leaf merge makes its internal parent underflow, then merges upward."""
    root = (550.0, 100.0)
    left_parent = (300.0, 285.0)
    right_parent = (800.0, 285.0)
    left_leaf = (200.0, 510.0)
    middle_leaf = (400.0, 510.0)
    right_left_leaf = (700.0, 510.0)
    right_right_leaf = (900.0, 510.0)
    merged_leaf = (300.0, 510.0)
    merged_parent = (550.0, 285.0)
    final_root = (550.0, 125.0)
    final_leaves = ((300.0, 380.0), (550.0, 380.0), (800.0, 380.0))

    def row(keys: Sequence[str | None], points: Sequence[Point], rim: str | None = None) -> str:
        return btree_neon_row_at_positions(keys, points, rim=rim)

    def center(points: Sequence[Point]) -> Point:
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )

    def render(
        rows: Sequence[tuple[Sequence[str | None], Sequence[Point], str | None]],
        links: Sequence[tuple[Point, Point]],
        text: str = "",
        overlay: str = "",
    ) -> str:
        parts: list[str] = []
        for start, end in links:
            parts.append(btree_neon_edge(
                (start[0], start[1] + BTREE_NEON_CELL_H / 2.0),
                (end[0], end[1] - BTREE_NEON_CELL_H / 2.0),
            ))
        for keys, points, rim in rows:
            parts.append(row(keys, points, rim))
        if text:
            parts.append(neon_text(text, (width / 2.0, height - 58.0), size=22.0, glow=GLOW_BLUE))
        parts.append(overlay)
        return svg("".join(parts), width=width, height=height, color=INK)

    def tree_rows(
        root_keys: Sequence[str | None],
        left_keys: Sequence[str | None],
        right_keys: Sequence[str | None],
        leaves: Sequence[tuple[Sequence[str | None], Point, str | None]],
        *,
        root_point: Point = root,
        left_point: Point = left_parent,
        right_point: Point = right_parent,
        links_override: Sequence[tuple[Point, Point]] | None = None,
        text: str = "",
    ) -> str:
        rows = [
            (root_keys, cell_slots(root_point, len(root_keys)), None),
            (left_keys, cell_slots(left_point, len(left_keys)) if left_keys else cell_slots(left_point, 1), GLOW_RED if not left_keys else None),
            (right_keys, cell_slots(right_point, len(right_keys)), None),
            *leaves,
        ]
        links = links_override if links_override is not None else [
            (root_point, left_point),
            (root_point, right_point),
            (left_point, leaves[0][1]),
            (left_point, leaves[1][1]),
            (right_point, leaves[2][1]),
            (right_point, leaves[3][1]),
        ]
        return render(rows, links, text)

    leaves = (
        (("10",), left_leaf, None),
        (("60",), middle_leaf, None),
        (("90",), right_left_leaf, None),
        (("110",), right_right_leaf, None),
    )
    frames: list[str] = []
    frames.extend([tree_rows(("80",), ("40",), ("100",), leaves, text="初始状态")] * 24)

    source = (cell_slots(left_leaf, 1)[0], cell_slots(left_parent, 1)[0], cell_slots(middle_leaf, 1)[0])
    target = cell_slots(merged_leaf, 3)
    for step in range(1, 43):
        t = ease(step / 42.0)
        points = tuple(lerp_point(start, end, t) for start, end in zip(source, target))
        rows = [
            (("80",), cell_slots(root, 1), None),
            (("100",), cell_slots(right_parent, 1), None),
            (("90",), cell_slots(right_left_leaf, 1), None),
            (("110",), cell_slots(right_right_leaf, 1), None),
            (("10", "40", "60"), points, None),
        ]
        links = ((root, right_parent), (right_parent, right_left_leaf), (right_parent, right_right_leaf))
        frames.append(render(rows, links, "首领 40 拉下，和两个子民合并"))
    merged_slots = cell_slots(merged_leaf, 3)
    frames.extend([
        render(
            [
                (("80",), cell_slots(root, 1), None),
                (("100",), cell_slots(right_parent, 1), None),
                (("90",), cell_slots(right_left_leaf, 1), None),
                (("110",), cell_slots(right_right_leaf, 1), None),
                (("10", "40", "60"), merged_slots, None),
            ],
            ((root, right_parent), (right_parent, right_left_leaf), (right_parent, right_right_leaf)),
            "首领回家后形成 [10,40,60]",
        )
    ] * 18)

    ten = merged_slots[0]
    for step in range(1, 19):
        t = ease(step / 18.0)
        strike = glow_line(
            (ten[0] - 22.0, ten[1] - 17.0),
            (ten[0] - 22.0 + 44.0 * t, ten[1] - 17.0 + 34.0 * t),
            color=GLOW_RED, width=5.0, bloom=GLOW_RED, radius=0.0,
        )
        rows = [
            (("80",), cell_slots(root, 1), None),
            (("100",), cell_slots(right_parent, 1), None),
            (("90",), cell_slots(right_left_leaf, 1), None),
            (("110",), cell_slots(right_right_leaf, 1), None),
            (("10", "40", "60"), merged_slots, None),
        ]
        frames.append(render(rows, ((root, right_parent), (right_parent, right_left_leaf), (right_parent, right_right_leaf)), "删除 10", strike))
    remaining = merged_slots[1:]
    underflow = cell_slots(left_parent, 1)
    frames.extend([
        render(
            [
                (("80",), cell_slots(root, 1), None),
                ((), underflow, GLOW_RED),
                (("100",), cell_slots(right_parent, 1), None),
                (("40", "60"), remaining, None),
                (("90",), cell_slots(right_left_leaf, 1), None),
                (("110",), cell_slots(right_right_leaf, 1), None),
            ],
            ((root, left_parent), (root, right_parent), (left_parent, merged_leaf), (right_parent, right_left_leaf), (right_parent, right_right_leaf)),
            "左侧父节点下溢，继续向上处理",
        )
    ] * 24)

    parent_source = (cell_slots(root, 1)[0], cell_slots(right_parent, 1)[0])
    parent_target = cell_slots(merged_parent, 2)
    for step in range(1, 43):
        t = ease(step / 42.0)
        points = tuple(lerp_point(start, end, t) for start, end in zip(parent_source, parent_target))
        rows = [
            (("80", "100"), points, None),
            (("40", "60"), remaining, None),
            (("90",), cell_slots(right_left_leaf, 1), None),
            (("110",), cell_slots(right_right_leaf, 1), None),
        ]
        links = ((merged_parent, merged_leaf), (merged_parent, right_left_leaf), (merged_parent, right_right_leaf))
        frames.append(render(rows, links, "父节点下溢：再和根分隔键 80、右兄弟合并"))
    merged_parent_slots = cell_slots(merged_parent, 2)
    frames.extend([
        render(
            [
                (("80", "100"), merged_parent_slots, None),
                (("40", "60"), remaining, None),
                (("90",), cell_slots(right_left_leaf, 1), None),
                (("110",), cell_slots(right_right_leaf, 1), None),
            ],
            ((merged_parent, merged_leaf), (merged_parent, right_left_leaf), (merged_parent, right_right_leaf)),
            "合并完成，根节点变空",
        )
    ] * 18)

    before_centers = (merged_parent, merged_leaf, right_left_leaf, right_right_leaf)
    after_centers = (final_root, final_leaves[0], final_leaves[1], final_leaves[2])
    for step in range(1, 37):
        t = ease(step / 36.0)
        centers = tuple(lerp_point(start, end, t) for start, end in zip(before_centers, after_centers))
        rows = [
            (("80", "100"), cell_slots(centers[0], 2), None),
            (("40", "60"), cell_slots(centers[1], 2), None),
            (("90",), cell_slots(centers[2], 1), None),
            (("110",), cell_slots(centers[3], 1), None),
        ]
        links = ((centers[0], centers[1]), (centers[0], centers[2]), (centers[0], centers[3]))
        frames.append(render(rows, links, "根收缩，合并节点上升成为新根"))
    final_rows = [
        (("80", "100"), cell_slots(final_root, 2), None),
        (("40", "60"), cell_slots(final_leaves[0], 2), None),
        (("90",), cell_slots(final_leaves[1], 1), None),
        (("110",), cell_slots(final_leaves[2], 1), None),
    ]
    frames.extend([render(final_rows, ((final_root, final_leaves[0]), (final_root, final_leaves[1]), (final_root, final_leaves[2])), "父节点下溢已向上修复")] * 90)
    return frames


def btree_cascade_classic_frames(width: int, height: int) -> list[str]:
    """Traditional deletion method for the same parent-underflow example."""
    root = (550.0, 100.0)
    left_parent = (300.0, 285.0)
    right_parent = (800.0, 285.0)
    left_leaf = (200.0, 510.0)
    middle_leaf = (400.0, 510.0)
    right_left_leaf = (700.0, 510.0)
    right_right_leaf = (900.0, 510.0)
    merged_parent = (550.0, 285.0)
    final_root = (550.0, 125.0)
    final_leaves = ((300.0, 380.0), (550.0, 380.0), (800.0, 380.0))

    def render(
        rows: Sequence[tuple[Sequence[str | None], Sequence[Point], str | None]],
        links: Sequence[tuple[Point, Point]],
        text: str = "",
        overlay: str = "",
    ) -> str:
        parts: list[str] = []
        for start, end in links:
            parts.append(btree_neon_edge(
                (start[0], start[1] + BTREE_NEON_CELL_H / 2.0),
                (end[0], end[1] - BTREE_NEON_CELL_H / 2.0),
            ))
        for keys, points, rim in rows:
            parts.append(btree_neon_row_at_positions(keys, points, rim=rim))
        if text:
            parts.append(neon_text(text, (width / 2.0, height - 58.0), size=22.0, glow=GLOW_BLUE))
        parts.append(overlay)
        return svg("".join(parts), width=width, height=height, color=INK)

    def ring(points: Sequence[Point], opacity: float) -> str:
        left = min(point[0] for point in points) - BTREE_NEON_CELL_W / 2.0
        right = max(point[0] for point in points) + BTREE_NEON_CELL_W / 2.0
        return bloom_rect(((left + right) / 2.0, points[0][1]), right - left, BTREE_NEON_CELL_H, GLOW_WHITE, opacity, radius=12.0)

    root_row = (("80",), cell_slots(root, 1), None)
    left_row = (("40",), cell_slots(left_parent, 1), None)
    right_row = (("100",), cell_slots(right_parent, 1), None)
    leaf_rows = (
        (("10",), cell_slots(left_leaf, 1), None),
        (("60",), cell_slots(middle_leaf, 1), None),
        (("90",), cell_slots(right_left_leaf, 1), None),
        (("110",), cell_slots(right_right_leaf, 1), None),
    )
    tree_links = ((root, left_parent), (root, right_parent), (left_parent, left_leaf), (left_parent, middle_leaf), (right_parent, right_left_leaf), (right_parent, right_right_leaf))
    frames: list[str] = []
    frames.extend([render([root_row, left_row, right_row, *leaf_rows], tree_links, "初始状态")] * 24)

    ten = leaf_rows[0][1][0]
    for step in range(1, 19):
        t = ease(step / 18.0)
        strike = glow_line((ten[0] - 22.0, ten[1] - 17.0), (ten[0] - 22.0 + 44.0 * t, ten[1] - 17.0 + 34.0 * t), color=GLOW_RED, width=5.0, bloom=GLOW_RED, radius=0.0)
        frames.append(render([root_row, left_row, right_row, *leaf_rows], tree_links, "直接删除 10，左叶下溢", strike))
    empty_leaf = ((), cell_slots(left_leaf, 1), GLOW_RED)
    frames.extend([render([root_row, left_row, right_row, empty_leaf, *leaf_rows[1:]], tree_links, "左叶下溢，检查兄弟")] * 18)
    for step in range(36):
        frames.append(render([root_row, left_row, right_row, empty_leaf, *leaf_rows[1:]], tree_links, "兄弟 60 只有一个关键字，不能借", ring(leaf_rows[1][1], (0.35, 0.55, 0.8, 0.55)[(step // 3) % 4])))

    parent_key = cell_slots(left_parent, 1)[0]
    sibling_key = cell_slots(middle_leaf, 1)[0]
    merge_target = cell_slots(left_leaf, 2)
    for step in range(1, 43):
        t = ease(step / 42.0)
        points = (lerp_point(parent_key, merge_target[0], t), lerp_point(sibling_key, merge_target[1], t))
        rows = [root_row, right_row, (("90",), cell_slots(right_left_leaf, 1), None), (("110",), cell_slots(right_right_leaf, 1), None), (("40", "60"), points, None)]
        frames.append(render(rows, ((root, right_parent), (right_parent, right_left_leaf), (right_parent, right_right_leaf)), "借不到，和分隔键 40 合并"))
    remaining = merge_target
    underflow = ((), cell_slots(left_parent, 1), GLOW_RED)
    frames.extend([render([root_row, underflow, right_row, (("40", "60"), remaining, None), *leaf_rows[2:]], ((root, left_parent), (root, right_parent), (left_parent, left_leaf), (right_parent, right_left_leaf), (right_parent, right_right_leaf)), "父节点也下溢，继续向上")] * 24)
    for step in range(36):
        frames.append(render([root_row, underflow, right_row, (("40", "60"), remaining, None), *leaf_rows[2:]], ((root, left_parent), (root, right_parent), (left_parent, left_leaf), (right_parent, right_left_leaf), (right_parent, right_right_leaf)), "检查右兄弟内部节点 100", ring(right_row[1], (0.35, 0.55, 0.8, 0.55)[(step // 3) % 4])))

    root_key = cell_slots(root, 1)[0]
    right_key = cell_slots(right_parent, 1)[0]
    target = cell_slots(merged_parent, 2)
    for step in range(1, 43):
        t = ease(step / 42.0)
        points = (lerp_point(root_key, target[0], t), lerp_point(right_key, target[1], t))
        rows = [
            (("80", "100"), points, None),
            (("40", "60"), remaining, None),
            (("90",), cell_slots(right_left_leaf, 1), None),
            (("110",), cell_slots(right_right_leaf, 1), None),
        ]
        links = ((merged_parent, left_leaf), (merged_parent, right_left_leaf), (merged_parent, right_right_leaf))
        frames.append(render(rows, links, "父节点和根分隔键、右兄弟合并"))
    merged_slots = cell_slots(merged_parent, 2)
    frames.extend([render([(("80", "100"), merged_slots, None), (("40", "60"), remaining, None), *leaf_rows[2:]], ((merged_parent, left_leaf), (merged_parent, right_left_leaf), (merged_parent, right_right_leaf)), "根节点变空")] * 18)

    before = (merged_parent, left_leaf, right_left_leaf, right_right_leaf)
    after = (final_root, final_leaves[0], final_leaves[1], final_leaves[2])
    for step in range(1, 37):
        t = ease(step / 36.0)
        centers = tuple(lerp_point(start, end, t) for start, end in zip(before, after))
        rows = [
            (("80", "100"), cell_slots(centers[0], 2), None),
            (("40", "60"), cell_slots(centers[1], 2), None),
            (("90",), cell_slots(centers[2], 1), None),
            (("110",), cell_slots(centers[3], 1), None),
        ]
        frames.append(render(rows, ((centers[0], centers[1]), (centers[0], centers[2]), (centers[0], centers[3])), "根收缩，合并节点上升成为新根"))
    final_rows = [
        (("80", "100"), cell_slots(final_root, 2), None),
        (("40", "60"), cell_slots(final_leaves[0], 2), None),
        (("90",), cell_slots(final_leaves[1], 1), None),
        (("110",), cell_slots(final_leaves[2], 1), None),
    ]
    frames.extend([render(final_rows, ((final_root, final_leaves[0]), (final_root, final_leaves[1]), (final_root, final_leaves[2])), "父节点下溢已向上修复")] * 90)
    return frames


def btree_classic_plain() -> None:
    """Render the traditional plain-removal case as a standalone transparent WebM."""
    render_webm(
        "btree-classic-plain",
        btree_classic_plain_frames(900, 540, (450.0, 120.0), (250.0, 350.0), (650.0, 350.0)),
        fps=30,
        transparent=True,
    )


def _btree_cascade_slot_frames(width: int, height: int, *, traditional: bool) -> list[str]:
    """Build the cascading-underflow example with B-tree child-slot anchors.

    A child pointer belongs to a gap in the parent array: before the first key,
    between two keys, or after the last key. It never defaults to the parent row
    center merely because the parent happens to contain one key.
    """
    root = (550.0, 100.0)
    left_parent = (300.0, 285.0)
    right_parent = (800.0, 285.0)
    leaves = ((200.0, 510.0), (400.0, 510.0), (700.0, 510.0), (900.0, 510.0))
    merged_leaf = (300.0, 510.0)
    merged_parent = (550.0, 285.0)
    final_root = (550.0, 125.0)
    final_leaves = ((300.0, 380.0), (550.0, 380.0), (800.0, 380.0))

    def row_points(row: tuple[Sequence[str | None], Point, str | None]) -> list[Point]:
        keys, center, _rim = row
        return cell_slots(center, len(keys)) if keys else cell_slots(center, 1)

    def gap(points: Sequence[Point], slot: int) -> Point:
        if slot == 0:
            x = points[0][0] - BTREE_NEON_CELL_W / 2.0
        elif slot == len(points):
            x = points[-1][0] + BTREE_NEON_CELL_W / 2.0
        else:
            x = (points[slot - 1][0] + points[slot][0]) / 2.0
        return x, points[0][1] + BTREE_NEON_CELL_H / 2.0

    def draw(
        rows: Mapping[str, tuple[Sequence[str | None], Point, str | None]],
        links: Sequence[tuple[str, str, int]],
        caption: str = "",
        overlay: str = "",
    ) -> str:
        parts: list[str] = []
        for parent_id, child_id, slot in links:
            parent_points = row_points(rows[parent_id])
            child_points = row_points(rows[child_id])
            start = gap(parent_points, slot)
            end = (sum(point[0] for point in child_points) / len(child_points), child_points[0][1] - BTREE_NEON_CELL_H / 2.0)
            parts.append(btree_neon_edge(start, end))
        for keys, center, rim in rows.values():
            points = row_points((keys, center, rim))
            parts.append(btree_neon_row_at_positions(keys, points, rim=rim))
        if caption:
            parts.append(neon_text(caption, (width / 2.0, height - 58.0), size=22.0, glow=GLOW_BLUE))
        parts.append(overlay)
        return svg("".join(parts), width=width, height=height, color=INK)

    initial_rows: dict[str, tuple[Sequence[str | None], Point, str | None]] = {
        "root": (("80",), root, None),
        "left": (("40",), left_parent, None),
        "right": (("100",), right_parent, None),
        "left_a": (("10",), leaves[0], None),
        "left_b": (("60",), leaves[1], None),
        "right_a": (("90",), leaves[2], None),
        "right_b": (("110",), leaves[3], None),
    }
    initial_links = (
        ("root", "left", 0), ("root", "right", 1),
        ("left", "left_a", 0), ("left", "left_b", 1),
        ("right", "right_a", 0), ("right", "right_b", 1),
    )
    frames: list[str] = [draw(initial_rows, initial_links, "初始状态：还没有删除 10")] * 24

    def strike(point: Point, progress: float) -> str:
        return glow_line(
            (point[0] - 22.0, point[1] - 17.0),
            (point[0] - 22.0 + 44.0 * progress, point[1] - 17.0 + 34.0 * progress),
            color=GLOW_RED,
            width=5.0,
            bloom=GLOW_RED,
            radius=0.0,
        )

    ten = cell_slots(leaves[0], 1)[0]
    if traditional:
        for step in range(1, 19):
            frames.append(draw(initial_rows, initial_links, "先删掉叶节点 10", strike(ten, ease(step / 18.0))))
        frames.extend([draw(initial_rows, initial_links, "先删掉叶节点 10", strike(ten, 1.0))] * 8)
        empty_leaf_rows = dict(initial_rows)
        empty_leaf_rows["left_a"] = ((None,), leaves[0], GLOW_RED)
        frames.extend([draw(empty_leaf_rows, initial_links, "左叶下溢，先看兄弟")] * 18)
        for step in range(36):
            pulse = (0.35, 0.55, 0.8, 0.55)[(step // 3) % 4]
            ring = bloom_rect(cell_slots(leaves[1], 1)[0], BTREE_NEON_CELL_W, BTREE_NEON_CELL_H, GLOW_WHITE, pulse, radius=12.0)
            frames.append(draw(empty_leaf_rows, initial_links, "右兄弟只有 60，不能借", ring))

        merge_start = (cell_slots(left_parent, 1)[0], cell_slots(leaves[1], 1)[0])
        merge_target = cell_slots(merged_leaf, 2)
        for step in range(1, 43):
            t = ease(step / 42.0)
            moving = tuple(lerp_point(start, end, t) for start, end in zip(merge_start, merge_target))
            rows = dict(empty_leaf_rows)
            rows["left_a"] = ((None,), left_parent, GLOW_RED)
            rows["moving"] = (("40", "60"), merged_leaf, None)
            links = (
                ("root", "left", 0), ("root", "right", 1),
                ("left", "moving", 0), ("right", "right_a", 0), ("right", "right_b", 1),
            )
            frames.append(draw(rows, links, "借不到，和分隔键 40 合并"))
    else:
        merge_start = (cell_slots(leaves[0], 1)[0], cell_slots(left_parent, 1)[0], cell_slots(leaves[1], 1)[0])
        merge_target = cell_slots(merged_leaf, 3)
        for step in range(1, 43):
            t = ease(step / 42.0)
            moving = tuple(lerp_point(start, end, t) for start, end in zip(merge_start, merge_target))
            rows = {
                "root": initial_rows["root"],
                "right": initial_rows["right"],
                "right_a": initial_rows["right_a"],
                "right_b": initial_rows["right_b"],
                "moving": (("10", "40", "60"), (sum(point[0] for point in moving) / 3.0, merged_leaf[1]), None),
            }
            links = (("root", "right", 1), ("right", "right_a", 0), ("right", "right_b", 1))
            frames.append(draw(rows, links, "首领 40 回到叶节点，和两个子民合并"))

    merged_keys = ("40", "60")
    merged_points = cell_slots(merged_leaf, 2)
    merged_rows: dict[str, tuple[Sequence[str | None], Point, str | None]] = {
        "root": (("80",), root, None),
        "left": ((None,), left_parent, GLOW_RED if traditional else None),
        "right": (("100",), right_parent, None),
        "merged": (merged_keys, merged_leaf, None),
        "right_a": (("90",), leaves[2], None),
        "right_b": (("110",), leaves[3], None),
    }
    merged_links = (
        ("root", "left", 0), ("root", "right", 1),
        ("left", "merged", 0), ("right", "right_a", 0), ("right", "right_b", 1),
    )
    if traditional:
        frames.extend([draw(merged_rows, merged_links, "合并后，左侧内部节点失去一个孩子")] * 18)
    else:
        ten_merged = cell_slots(merged_leaf, 3)[0]
        for step in range(1, 19):
            frames.append(draw({**merged_rows, "merged": (("10", "40", "60"), merged_leaf, None)}, merged_links, "删除 10", strike(ten_merged, ease(step / 18.0))))
        frames.extend([draw({**merged_rows, "merged": (("10", "40", "60"), merged_leaf, None)}, merged_links, "删除 10", strike(ten_merged, 1.0))] * 8)
        frames.extend([draw(merged_rows, merged_links, "删除后，左侧内部节点下溢")] * 24)

    # The root separator 80 and the right internal key 100 converge into the
    # underflowed left internal node. The three leaf children attach to the
    # resulting [80,100] row at slots 0, 1, and 2.
    parent_before = (cell_slots(root, 1)[0], cell_slots(right_parent, 1)[0])
    parent_after = cell_slots(merged_parent, 2)
    for step in range(1, 43):
        t = ease(step / 42.0)
        parent_points = tuple(lerp_point(start, end, t) for start, end in zip(parent_before, parent_after))
        rows = {
            "parent": (("80", "100"), merged_parent, None),
            "merged": (("40", "60"), merged_leaf, None),
            "right_a": (("90",), leaves[2], None),
            "right_b": (("110",), leaves[3], None),
        }
        rows["parent"] = (("80", "100"), (sum(point[0] for point in parent_points) / 2.0, merged_parent[1]), None)
        links = (("parent", "merged", 0), ("parent", "right_a", 1), ("parent", "right_b", 2))
        frames.append(draw(rows, links, "继续向上合并：80 和 100 进入同一个父节点"))
    parent_rows: dict[str, tuple[Sequence[str | None], Point, str | None]] = {
        "parent": (("80", "100"), merged_parent, None),
        "merged": (("40", "60"), merged_leaf, None),
        "right_a": (("90",), leaves[2], None),
        "right_b": (("110",), leaves[3], None),
    }
    parent_links = (("parent", "merged", 0), ("parent", "right_a", 1), ("parent", "right_b", 2))
    frames.extend([draw(parent_rows, parent_links, "根节点变空，合并完成")] * 18)

    before_nodes = (merged_parent, merged_leaf, leaves[2], leaves[3])
    after_nodes = (final_root, final_leaves[0], final_leaves[1], final_leaves[2])
    for step in range(1, 37):
        t = ease(step / 36.0)
        centers = tuple(lerp_point(start, end, t) for start, end in zip(before_nodes, after_nodes))
        rows = {
            "root": (("80", "100"), centers[0], None),
            "left": (("40", "60"), centers[1], None),
            "middle": (("90",), centers[2], None),
            "right": (("110",), centers[3], None),
        }
        links = (("root", "left", 0), ("root", "middle", 1), ("root", "right", 2))
        frames.append(draw(rows, links, "根收缩，合并节点上升成为新根"))
    final_rows = {
        "root": (("80", "100"), final_root, None),
        "left": (("40", "60"), final_leaves[0], None),
        "middle": (("90",), final_leaves[1], None),
        "right": (("110",), final_leaves[2], None),
    }
    frames.extend([draw(final_rows, (("root", "left", 0), ("root", "middle", 1), ("root", "right", 2)), "父节点下溢已向上修复")] * 90)
    return frames


def _btree_cascade_slot_frames_v2(width: int, height: int, *, traditional: bool) -> list[str]:
    """Render case three with child pointers attached to parent array gaps."""
    root = (550.0, 100.0)
    left_parent = (300.0, 285.0)
    right_parent = (800.0, 285.0)
    leaf_a, leaf_b = (200.0, 510.0), (400.0, 510.0)
    leaf_c, leaf_d = (700.0, 510.0), (900.0, 510.0)
    merged_leaf = (300.0, 510.0)
    merged_parent = (550.0, 285.0)
    final_root = (550.0, 125.0)
    final_leaves = ((300.0, 380.0), (550.0, 380.0), (800.0, 380.0))

    def row(keys, center, rim=None, positions=None):
        return keys, tuple(positions or cell_slots(center, max(1, len(keys)))), rim

    def child_gap(parent_row, slot):
        keys, positions, _rim = parent_row
        if not keys or all(key is None for key in keys):
            return positions[0][0], positions[0][1] + BTREE_NEON_CELL_H / 2.0
        if slot == 0:
            x = positions[0][0] - BTREE_NEON_CELL_W / 2.0
        elif slot == len(keys):
            x = positions[-1][0] + BTREE_NEON_CELL_W / 2.0
        else:
            x = (positions[slot - 1][0] + positions[slot][0]) / 2.0
        return x, positions[0][1] + BTREE_NEON_CELL_H / 2.0

    def ghost_node(node_row, opacity=1.0):
        _keys, positions, _rim = node_row
        left = min(point[0] for point in positions) - BTREE_NEON_CELL_W / 2.0
        right = max(point[0] for point in positions) + BTREE_NEON_CELL_W / 2.0
        top = positions[0][1] - BTREE_NEON_CELL_H / 2.0
        return (
            f'<rect x="{left:.1f}" y="{top:.1f}" width="{right - left:.1f}" '
            f'height="{BTREE_NEON_CELL_H:.1f}" rx="9" fill="none" '
            f'stroke="#94A3B8" stroke-width="2.6" stroke-dasharray="9 7" opacity="{opacity:.3f}"/>'
        )

    def draw(rows, links, caption="", overlay="", ghosts=None):
        ghosts = ghosts or {}
        parts = []
        for parent_id, child_id, slot in links:
            child_positions = rows[child_id][1]
            child_x = sum(point[0] for point in child_positions) / len(child_positions)
            parts.append(btree_neon_edge(
                child_gap(rows[parent_id], slot),
                (child_x, child_positions[0][1] - BTREE_NEON_CELL_H / 2.0),
            ))
        for row_id, row_data in rows.items():
            if row_id in ghosts:
                parts.append(ghost_node(row_data, ghosts[row_id]))
                continue
            keys, positions, rim = row_data
            parts.append(btree_neon_row_at_positions(keys, positions, rim=rim))
        if caption:
            parts.append(neon_text(caption, (width / 2.0, height - 58.0), size=22.0, glow=GLOW_BLUE))
        parts.append(overlay)
        return svg("".join(parts), width=width, height=height, color=INK)

    root_row = row(("80",), root)
    left_row = row(("40",), left_parent)
    right_row = row(("100",), right_parent)
    a_row, b_row = row(("10",), leaf_a), row(("60",), leaf_b)
    c_row, d_row = row(("90",), leaf_c), row(("110",), leaf_d)
    initial_rows = {"root": root_row, "left": left_row, "right": right_row, "a": a_row, "b": b_row, "c": c_row, "d": d_row}
    initial_links = (
        ("root", "left", 0), ("root", "right", 1),
        ("left", "a", 0), ("left", "b", 1),
        ("right", "c", 0), ("right", "d", 1),
    )
    frames = [draw(initial_rows, initial_links, "初始状态：还没有删除 10")] * 24

    def strike(point, progress):
        return glow_line(
            (point[0] - 22.0, point[1] - 17.0),
            (point[0] - 22.0 + 44.0 * progress, point[1] - 17.0 + 34.0 * progress),
            color=GLOW_RED, width=5.0, bloom=GLOW_RED, radius=0.0,
        )

    def row_center(node_row):
        _keys, points, _rim = node_row
        return sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points)

    def move_node(node_row, destination, progress):
        keys, points, rim = node_row
        source = row_center(node_row)
        center = lerp_point(source, destination, progress)
        dx, dy = center[0] - source[0], center[1] - source[1]
        return keys, tuple((point[0] + dx, point[1] + dy) for point in points), rim

    empty_left = row((None,), left_parent, GLOW_RED)
    empty_root = row((None,), root, GLOW_RED)
    ten = a_row[1][0]
    first_ghosts = {"left": 1.0}

    if traditional:
        for step in range(1, 19):
            frames.append(draw(initial_rows, initial_links, "先删除叶节点 10", strike(ten, ease(step / 18.0))))
        frames.extend([draw(initial_rows, initial_links, "先删除叶节点 10", strike(ten, 1.0))] * 8)
        empty_rows = {"root": root_row, "left": left_row, "right": right_row, "a": a_row, "b": b_row, "c": c_row, "d": d_row}
        frames.extend([draw(empty_rows, initial_links, "左叶下溢，检查兄弟", ghosts={"a": 1.0})] * 20)

        targets = cell_slots(merged_leaf, 2)
        for step in range(1, 43):
            progress = ease(step / 42.0)
            leader = move_node(left_row, targets[0], progress)
            sibling = move_node(b_row, targets[1], progress)
            rows = {
                "root": root_row, "left": empty_left, "right": right_row,
                "empty_leaf": a_row, "leader": leader, "sibling": sibling,
                "c": c_row, "d": d_row,
            }
            links = (
                ("root", "left", 0), ("root", "right", 1),
                ("leader", "empty_leaf", 0), ("leader", "sibling", 1),
                ("right", "c", 0), ("right", "d", 1),
            )
            frames.append(draw(rows, links, "兄弟不能借，首领 40 回家", ghosts={"left": 1.0, "empty_leaf": 1.0}))
        merged_leaf_row = row(("40", "60"), merged_leaf)
    else:
        targets = cell_slots(merged_leaf, 3)
        for step in range(1, 43):
            progress = ease(step / 42.0)
            left_child = move_node(a_row, targets[0], progress)
            leader = move_node(left_row, targets[1], progress)
            right_child = move_node(b_row, targets[2], progress)
            rows = {
                "root": root_row, "left": empty_left, "right": right_row,
                "left_child": left_child, "leader": leader, "right_child": right_child,
                "c": c_row, "d": d_row,
            }
            links = (
                ("root", "left", 0), ("root", "right", 1),
                ("leader", "left_child", 0), ("leader", "right_child", 1),
                ("right", "c", 0), ("right", "d", 1),
            )
            frames.append(draw(rows, links, "首领 40 回家，三个节点整体靠拢", ghosts=first_ghosts))
        merged_three = row(("10", "40", "60"), merged_leaf)
        merged_rows = {"root": root_row, "left": empty_left, "right": right_row, "merged": merged_three, "c": c_row, "d": d_row}
        merged_links = (("root", "left", 0), ("root", "right", 1), ("left", "merged", 0), ("right", "c", 0), ("right", "d", 1))
        frames.extend([draw(merged_rows, merged_links, "合并形成 [10,40,60]", ghosts=first_ghosts)] * 18)
        ten_merged = merged_three[1][0]
        for step in range(1, 19):
            frames.append(draw(merged_rows, merged_links, "删除 10", strike(ten_merged, ease(step / 18.0)), ghosts=first_ghosts))
        frames.extend([draw(merged_rows, merged_links, "删除 10", strike(ten_merged, 1.0), ghosts=first_ghosts)] * 8)
        remaining = row(("40", "60"), merged_leaf, positions=merged_three[1][1:])
        for step in range(1, 25):
            progress = ease(step / 24.0)
            moving_remaining = move_node(remaining, merged_leaf, progress)
            rows = {"root": root_row, "left": empty_left, "right": right_row, "merged": moving_remaining, "c": c_row, "d": d_row}
            frames.append(draw(rows, merged_links, "删除完成，合并节点整体居中", ghosts=first_ghosts))
        merged_leaf_row = row(("40", "60"), merged_leaf)

    underflow_rows = {"root": root_row, "left": empty_left, "right": right_row, "merged": merged_leaf_row, "c": c_row, "d": d_row}
    underflow_links = (("root", "left", 0), ("root", "right", 1), ("left", "merged", 0), ("right", "c", 0), ("right", "d", 1))
    frames.extend([draw(underflow_rows, underflow_links, "左侧内部节点下溢，继续向上处理", ghosts=first_ghosts)] * 24)

    parent_targets = cell_slots(merged_parent, 2)
    for step in range(1, 43):
        progress = ease(step / 42.0)
        leader80 = move_node(root_row, parent_targets[0], progress)
        node100 = move_node(right_row, parent_targets[1], progress)
        rows = {
            "root": empty_root, "left_anchor": empty_left,
            "leader": leader80, "right_node": node100,
            "merged": merged_leaf_row, "c": c_row, "d": d_row,
        }
        links = (
            ("leader", "left_anchor", 0), ("leader", "right_node", 1),
            ("left_anchor", "merged", 0),
            ("right_node", "c", 0), ("right_node", "d", 1),
        )
        frames.append(draw(rows, links, "根首领 80 回家，节点整体向中间合并", ghosts={"root": 1.0, "left_anchor": 1.0}))

    parent_row = row(("80", "100"), merged_parent)
    parent_links = (("parent", "left", 0), ("parent", "middle", 1), ("parent", "right", 2))
    parent_rows = {"root_gap": empty_root, "parent": parent_row, "left": merged_leaf_row, "middle": c_row, "right": d_row}
    frames.extend([draw(parent_rows, parent_links, "根节点变空", ghosts={"root_gap": 1.0})] * 18)

    for step in range(1, 37):
        progress = ease(step / 36.0)
        rows = {
            "root_gap": empty_root,
            "parent": move_node(parent_row, final_root, progress),
            "left": move_node(merged_leaf_row, final_leaves[0], progress),
            "middle": move_node(c_row, final_leaves[1], progress),
            "right": move_node(d_row, final_leaves[2], progress),
        }
        frames.append(draw(rows, parent_links, "根收缩，整节点一起上升", ghosts={"root_gap": 1.0 - progress}))
    final_rows = {
        "parent": row(("80", "100"), final_root),
        "left": row(("40", "60"), final_leaves[0]),
        "middle": row(("90",), final_leaves[1]),
        "right": row(("110",), final_leaves[2]),
    }
    frames.extend([draw(final_rows, parent_links, "父节点下溢已向上修复")] * 90)
    return frames


def _btree_cascade_two_deletes_frames_legacy(width: int, height: int, *, traditional: bool) -> list[str]:
    """Legacy case-three renderer retained for reference."""
    if traditional:
        return _btree_cascade_two_deletes_traditional_frames(width, height)

    root = (550.0, 100.0)
    left_parent = (150.0, 285.0)
    middle_parent = (550.0, 285.0)
    right_parent = (950.0, 285.0)
    leaves = ((80.0, 510.0), (220.0, 510.0), (430.0, 510.0), (670.0, 510.0), (830.0, 510.0), (1010.0, 510.0))
    first_leaf_merge = (150.0, 510.0)
    first_parent_merge = (300.0, 285.0)
    second_leaf_merge = (950.0, 510.0)
    final_root = (550.0, 125.0)
    final_leaves = ((180.0, 380.0), (410.0, 380.0), (590.0, 380.0), (820.0, 380.0))

    def row(keys, center, rim=None, positions=None):
        return keys, tuple(positions or cell_slots(center, max(1, len(keys)))), rim

    def center(node_row):
        points = node_row[1]
        return sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points)

    def move_node(node_row, destination, progress):
        source = center(node_row)
        current = lerp_point(source, destination, progress)
        dx, dy = current[0] - source[0], current[1] - source[1]
        return node_row[0], tuple((x + dx, y + dy) for x, y in node_row[1]), node_row[2]

    def ghost(node_row, opacity=1.0):
        _keys, points, _rim = node_row
        left = min(point[0] for point in points) - BTREE_NEON_CELL_W / 2.0
        right = max(point[0] for point in points) + BTREE_NEON_CELL_W / 2.0
        top = points[0][1] - BTREE_NEON_CELL_H / 2.0
        return (
            f'<rect x="{left:.1f}" y="{top:.1f}" width="{right - left:.1f}" '
            f'height="{BTREE_NEON_CELL_H:.1f}" rx="9" fill="none" stroke="#94A3B8" '
            f'stroke-width="2.6" stroke-dasharray="9 7" opacity="{opacity:.3f}"/>'
        )

    def child_gap(parent_row, slot):
        points = parent_row[1]
        keys = parent_row[0]
        if not keys or all(key is None for key in keys):
            return points[0][0], points[0][1] + BTREE_NEON_CELL_H / 2.0
        if slot == 0:
            x = points[0][0] - BTREE_NEON_CELL_W / 2.0
        elif slot == len(keys):
            x = points[-1][0] + BTREE_NEON_CELL_W / 2.0
        else:
            x = (points[slot - 1][0] + points[slot][0]) / 2.0
        return x, points[0][1] + BTREE_NEON_CELL_H / 2.0

    def draw(rows, links, caption="", ghosts=(), overlay=""):
        parts = []
        for parent_id, child_id, slot in links:
            parent_row = rows[parent_id]
            child_row = rows[child_id]
            child_x = sum(point[0] for point in child_row[1]) / len(child_row[1])
            parts.append(btree_neon_edge(
                child_gap(parent_row, slot),
                (child_x, child_row[1][0][1] - BTREE_NEON_CELL_H / 2.0),
            ))
        for row_id, node_row in rows.items():
            if row_id in ghosts:
                parts.append(ghost(node_row, ghosts[row_id] if isinstance(ghosts, dict) else 1.0))
            else:
                parts.append(btree_neon_row_at_positions(node_row[0], node_row[1], rim=node_row[2]))
        if caption:
            parts.append(neon_text(caption, (width / 2.0, height - 58.0), size=22.0, glow=GLOW_BLUE))
        parts.append(overlay)
        return svg("".join(parts), width=width, height=height, color=INK)

    def strike(point, progress):
        return glow_line(
            (point[0] - 22.0, point[1] - 17.0),
            (point[0] - 22.0 + 44.0 * progress, point[1] - 17.0 + 34.0 * progress),
            color=GLOW_RED, width=5.0, bloom=GLOW_RED, radius=0.0,
        )

    root_initial = row(("50", "80"), root)
    left_initial = row(("20",), left_parent)
    middle_initial = row(("60",), middle_parent)
    right_initial = row(("100",), right_parent)
    leaf_rows = [row((key,), point) for key, point in zip(("10", "30", "55", "70", "90", "110"), leaves)]
    initial_rows = {"root": root_initial, "left": left_initial, "middle": middle_initial, "right": right_initial}
    initial_rows.update({f"leaf{index}": value for index, value in enumerate(leaf_rows)})
    initial_links = (
        ("root", "left", 0), ("root", "middle", 1), ("root", "right", 2),
        ("left", "leaf0", 0), ("left", "leaf1", 1),
        ("middle", "leaf2", 0), ("middle", "leaf3", 1),
        ("right", "leaf4", 0), ("right", "leaf5", 1),
    )
    frames = [draw(initial_rows, initial_links, "初始状态：左右都有可回家的首领")] * 24

    def append_delete_leaf(rows, links, leaf_id, caption_text):
        point = rows[leaf_id][1][0]
        for step in range(1, 19):
            frames.append(draw(rows, links, caption_text, overlay=strike(point, ease(step / 18.0))))
        frames.extend([draw(rows, links, caption_text, overlay=strike(point, 1.0))] * 8)

    # First deletion: the left leader returns with both children before 10 is removed.
    append_delete_leaf(initial_rows, initial_links, "leaf0", "第一步：删除 10")
    first_empty_rows = dict(initial_rows)
    first_empty_rows["left"] = row((None,), left_parent, GLOW_RED)
    frames.extend([draw(first_empty_rows, (("root", "middle", 1), ("root", "right", 2), *initial_links[3:]))] * 18)
    first_leaf_targets = cell_slots(first_leaf_merge, 3)
    for step in range(1, 43):
        progress = ease(step / 42.0)
        moving = {
            "leaf0": row(("10",), lerp_point(leaf_rows[0][1][0], first_leaf_targets[0], progress)),
            "leader": row(("20",), lerp_point(left_initial[1][0], first_leaf_targets[1], progress)),
            "leaf1": row(("30",), lerp_point(leaf_rows[1][1][0], first_leaf_targets[2], progress)),
        }
        rows = {"root": root_initial, "middle": middle_initial, "right": right_initial, **moving, "leaf2": leaf_rows[2], "leaf3": leaf_rows[3], "leaf4": leaf_rows[4], "leaf5": leaf_rows[5], "left": row((None,), left_parent, GLOW_RED)}
        links = (("root", "middle", 1), ("root", "right", 2), ("middle", "leaf2", 0), ("middle", "leaf3", 1), ("right", "leaf4", 0), ("right", "leaf5", 1))
        frames.append(draw(rows, links, "左首领 20 回家，10、20、30 独立移动", ghosts={"left": 1.0}))
    merged_first = row(("10", "20", "30"), first_leaf_merge)
    merged_state = {"root": root_initial, "left": row((None,), left_parent, GLOW_RED), "middle": middle_initial, "right": right_initial, "leaf0": merged_first, "leaf2": leaf_rows[2], "leaf3": leaf_rows[3], "leaf4": leaf_rows[4], "leaf5": leaf_rows[5]}
    merged_links = (("root", "middle", 1), ("root", "right", 2), ("middle", "leaf2", 0), ("middle", "leaf3", 1), ("right", "leaf4", 0), ("right", "leaf5", 1))
    frames.extend([draw(merged_state, merged_links, "形成 [10,20,30]")] * 16)
    append_delete_leaf(merged_state, merged_links, "leaf0", "删除合并节点里的 10")
    first_remaining = row(("20", "30"), first_leaf_merge, positions=merged_first[1][1:])
    merged_state["leaf0"] = first_remaining
    frames.extend([draw(merged_state, merged_links, "删除完成，左侧内部节点下溢")] * 20)

    first_parent_targets = cell_slots(first_parent_merge, 2)
    root50 = row(("50",), root_initial[1][0])
    root80 = row(("80",), root_initial[1][1])
    for step in range(1, 43):
        progress = ease(step / 42.0)
        leader50 = move_node(root50, first_parent_merge, progress)
        leader60 = move_node(middle_initial, first_parent_merge, progress)
        rows = {
            "root80": root80,
            "leader": row(("50", "60"), first_parent_merge, positions=(leader50[1][0], leader60[1][0])),
            "left_leaf": first_remaining, "leaf2": leaf_rows[2], "leaf3": leaf_rows[3],
            "right": right_initial, "leaf4": leaf_rows[4], "leaf5": leaf_rows[5],
        }
        links = (("root80", "right", 1), ("leader", "left_leaf", 0), ("leader", "leaf2", 1), ("leader", "leaf3", 2), ("right", "leaf4", 0), ("right", "leaf5", 1))
        frames.append(draw(rows, links, "根的左首领 50 回家，和中间首领 60 合并"))
    first_parent = row(("50", "60"), first_parent_merge)
    first_state = {"root": root80, "parent": first_parent, "left_leaf": first_remaining, "leaf2": leaf_rows[2], "leaf3": leaf_rows[3], "right": right_initial, "leaf4": leaf_rows[4], "leaf5": leaf_rows[5]}
    first_links = (("root", "parent", 0), ("root", "right", 1), ("parent", "left_leaf", 0), ("parent", "leaf2", 1), ("parent", "leaf3", 2), ("right", "leaf4", 0), ("right", "leaf5", 1))
    frames.extend([draw(first_state, first_links, "第一次下溢已向上传递，根仍有首领 80")] * 28)

    # Second deletion: use the right leader 100, then the remaining root leader 80.
    append_delete_leaf(first_state, first_links, "leaf4", "第二步：删除 90")
    empty_right_leaf = row((None,), leaves[4], GLOW_RED)
    second_empty = dict(first_state, leaf4=empty_right_leaf, right=row((None,), right_parent, GLOW_RED))
    frames.extend([draw(second_empty, first_links, "右叶下溢，检查左右兄弟")] * 18)
    second_leaf_targets = cell_slots(second_leaf_merge, 3)
    for step in range(1, 43):
        progress = ease(step / 42.0)
        moving = {
            "leaf4": row(("90",), lerp_point(leaves[4], second_leaf_merge, progress)),
            "leader": row(("100",), lerp_point(right_parent, second_leaf_merge, progress)),
            "leaf5": row(("110",), lerp_point(leaves[5], second_leaf_merge, progress)),
        }
        rows = {"root": root80, "parent": first_parent, "leader": moving["leader"], "leaf4": moving["leaf4"], "leaf5": moving["leaf5"], "left_leaf": first_remaining, "leaf2": leaf_rows[2], "leaf3": leaf_rows[3]}
        links = (("root", "parent", 0), ("root", "leader", 1), ("parent", "left_leaf", 0), ("parent", "leaf2", 1), ("parent", "leaf3", 2), ("leader", "leaf4", 0), ("leader", "leaf5", 1))
        frames.append(draw(rows, links, "右首领 100 回家，和左右子民合并"))
    second_merged = row(("90", "100", "110"), second_leaf_merge)
    second_after_merge = dict(second_empty, leaf4=second_merged)
    frames.extend([draw(second_after_merge, first_links, "形成 [90,100,110]")] * 16)
    append_delete_leaf(second_after_merge, first_links, "leaf4", "删除合并节点里的 90")
    second_remaining = row(("100", "110"), second_leaf_merge, positions=second_merged[1][1:])
    second_underflow = dict(second_empty, leaf4=second_remaining)
    frames.extend([draw(second_underflow, first_links, "删除完成，右侧内部节点下溢")] * 20)

    final_parent_target = cell_slots(final_root, 3)
    root80_single = row(("80",), root80[1][0])
    for step in range(1, 43):
        progress = ease(step / 42.0)
        leader80 = move_node(root80_single, final_root, progress)
        parent = move_node(first_parent, final_root, progress)
        rows = {"root": row((None,), root, GLOW_RED), "leader": leader80, "parent": parent, "left": first_remaining, "middle1": leaf_rows[2], "middle2": leaf_rows[3], "right": second_remaining}
        links = (("leader", "parent", 0), ("leader", "right", 1), ("parent", "left", 0), ("parent", "middle1", 1), ("parent", "middle2", 2))
        frames.append(draw(rows, links, "根首领 80 回家，左右首领合并，根继续下溢", ghosts={"root": 1.0}))

    final_rows = {
        "root": row(("50", "60", "80"), final_root),
        "left": row(("20", "30"), final_leaves[0]),
        "middle1": row(("55",), final_leaves[1]),
        "middle2": row(("70",), final_leaves[2]),
        "right": row(("100", "110"), final_leaves[3]),
    }
    final_links = (("root", "left", 0), ("root", "middle1", 1), ("root", "middle2", 2), ("root", "right", 3))
    frames.extend([draw(final_rows, final_links, "根收缩，第二次下溢也已修复")] * 90)
    return frames


def _btree_cascade_two_deletes_traditional_frames(width: int, height: int) -> list[str]:
    """Traditional sibling-first version of the same two-delete example."""
    root = (550.0, 100.0)
    left_parent, middle_parent, right_parent = (150.0, 285.0), (550.0, 285.0), (950.0, 285.0)
    leaves = ((80.0, 510.0), (220.0, 510.0), (430.0, 510.0), (670.0, 510.0), (830.0, 510.0), (1010.0, 510.0))

    def row(keys, point, rim=None, positions=None):
        return keys, tuple(positions or cell_slots(point, max(1, len(keys)))), rim

    def child_gap(parent_row, slot):
        points, keys = parent_row[1], parent_row[0]
        if not keys or all(key is None for key in keys):
            return points[0][0], points[0][1] + BTREE_NEON_CELL_H / 2.0
        if slot == 0:
            x = points[0][0] - BTREE_NEON_CELL_W / 2.0
        elif slot == len(keys):
            x = points[-1][0] + BTREE_NEON_CELL_W / 2.0
        else:
            x = (points[slot - 1][0] + points[slot][0]) / 2.0
        return x, points[0][1] + BTREE_NEON_CELL_H / 2.0

    def ghost(node_row):
        points = node_row[1]
        left = min(point[0] for point in points) - BTREE_NEON_CELL_W / 2.0
        right = max(point[0] for point in points) + BTREE_NEON_CELL_W / 2.0
        top = points[0][1] - BTREE_NEON_CELL_H / 2.0
        return f'<rect x="{left:.1f}" y="{top:.1f}" width="{right - left:.1f}" height="{BTREE_NEON_CELL_H:.1f}" rx="9" fill="none" stroke="#94A3B8" stroke-width="2.6" stroke-dasharray="9 7"/>'

    def draw(rows, links, caption="", ghost_ids=(), overlay=""):
        parts = []
        for parent_id, child_id, slot in links:
            parent_row, child_row = rows[parent_id], rows[child_id]
            child_x = sum(point[0] for point in child_row[1]) / len(child_row[1])
            parts.append(btree_neon_edge(child_gap(parent_row, slot), (child_x, child_row[1][0][1] - BTREE_NEON_CELL_H / 2.0)))
        for row_id, node_row in rows.items():
            parts.append(ghost(node_row) if row_id in ghost_ids else btree_neon_row_at_positions(node_row[0], node_row[1], rim=node_row[2]))
        if caption:
            parts.append(neon_text(caption, (width / 2.0, height - 58.0), size=22.0, glow=GLOW_BLUE))
        parts.append(overlay)
        return svg("".join(parts), width=width, height=height, color=INK)

    def strike(point, progress):
        return glow_line((point[0] - 22.0, point[1] - 17.0), (point[0] - 22.0 + 44.0 * progress, point[1] - 17.0 + 34.0 * progress), color=GLOW_RED, width=5.0, bloom=GLOW_RED, radius=0.0)

    rows = {
        "root": row(("50", "80"), root), "left": row(("20",), left_parent),
        "middle": row(("60",), middle_parent), "right": row(("100",), right_parent),
        **{f"leaf{i}": row((key,), point) for i, (key, point) in enumerate(zip(("10", "30", "55", "70", "90", "110"), leaves))},
    }
    links = (("root", "left", 0), ("root", "middle", 1), ("root", "right", 2), ("left", "leaf0", 0), ("left", "leaf1", 1), ("middle", "leaf2", 0), ("middle", "leaf3", 1), ("right", "leaf4", 0), ("right", "leaf5", 1))
    frames = [draw(rows, links, "初始状态：左右都有兄弟可检查")] * 24

    def delete_leaf(current_rows, current_links, leaf_id, text):
        point = current_rows[leaf_id][1][0]
        for step in range(1, 19):
            frames.append(draw(current_rows, current_links, text, overlay=strike(point, ease(step / 18.0))))
        frames.extend([draw(current_rows, current_links, text, overlay=strike(point, 1.0))] * 8)

    def merge_leaf(current_rows, current_links, leaf_id, parent_id, sibling_id, separator, target, merged_keys, text):
        empty = row((None,), current_rows[leaf_id][1][0], GLOW_RED)
        hungry = dict(current_rows, **{leaf_id: empty})
        frames.extend([draw(hungry, current_links, f"{text}，下溢，检查左右兄弟", (leaf_id,))] * 18)
        source = (current_rows[leaf_id][1][0], current_rows[parent_id][1][0], current_rows[sibling_id][1][0])
        targets = cell_slots(target, 3)
        for step in range(1, 43):
            progress = ease(step / 42.0)
            points = tuple(lerp_point(start, end, progress) for start, end in zip(source, targets))
            moving = dict(hungry)
            moving[leaf_id] = row((current_rows[leaf_id][0][0],), points[0])
            moving[parent_id] = row((separator,), points[1])
            moving[sibling_id] = row((current_rows[sibling_id][0][0],), points[2])
            frames.append(draw(moving, current_links, f"兄弟不够借，{separator} 下沉，与左右兄弟合并", (leaf_id, parent_id)))
        merged = row(merged_keys, target)
        return dict(hungry, **{leaf_id: merged})

    delete_leaf(rows, links, "leaf0", "第一步：删除 10")
    rows = merge_leaf(rows, links, "leaf0", "left", "leaf1", "20", (150.0, 510.0), ("10", "20", "30"), "删除 10")
    rows["leaf0"] = row(("20", "30"), (150.0, 510.0), positions=rows["leaf0"][1][1:])
    rows["left"] = row((None,), left_parent, GLOW_RED)
    frames.extend([draw(rows, links, "左侧内部节点下溢，继续向上合并", ("left",))] * 20)

    # The root separator 50 joins the left and middle internal nodes.
    parent_target = cell_slots((300.0, 285.0), 2)
    for step in range(1, 43):
        progress = ease(step / 42.0)
        moved50 = row(("50",), lerp_point((550.0, 100.0), (300.0, 285.0), progress))
        moved60 = row(("60",), lerp_point(middle_parent, (300.0, 285.0), progress))
        moving = dict(
            rows,
            root=row(("80",), (root[0] + 280.0, root[1])),
            leader=row(("50", "60"), (moved50[1][0], moved60[1][0]), positions=(moved50[1][0], moved60[1][0])),
        )
        moving.pop("left", None)
        moving.pop("middle", None)
        moving_links = (("root", "right", 1), ("leader", "leaf0", 0), ("leader", "leaf2", 1), ("leader", "leaf3", 2), ("right", "leaf4", 0), ("right", "leaf5", 1))
        frames.append(draw(moving, moving_links, "左侧下溢传到父层，50 与 60 合并"))
    rows = {"root": row(("80",), (830.0, 100.0)), "parent": row(("50", "60"), (300.0, 285.0)), "right": rows["right"], "leaf0": rows["leaf0"], "leaf2": rows["leaf2"], "leaf3": rows["leaf3"], "leaf4": rows["leaf4"], "leaf5": rows["leaf5"]}
    links = (("root", "parent", 0), ("root", "right", 1), ("parent", "leaf0", 0), ("parent", "leaf2", 1), ("parent", "leaf3", 2), ("right", "leaf4", 0), ("right", "leaf5", 1))
    frames.extend([draw(rows, links, "第一次级联合并完成，保留右侧首领 100")] * 28)

    delete_leaf(rows, links, "leaf4", "第二步：删除 90")
    rows["leaf4"] = row((None,), leaves[4], GLOW_RED)
    rows["right"] = row((None,), right_parent, GLOW_RED)
    frames.extend([draw(rows, links, "右叶下溢，检查左兄弟")] * 18)
    target = (550.0, 285.0)
    source = (leaves[4], right_parent, leaves[5])
    for step in range(1, 43):
        progress = ease(step / 42.0)
        points = tuple(lerp_point(start, end, progress) for start, end in zip(source, cell_slots((950.0, 510.0), 3)))
        moving = dict(rows, leaf4=row(("90",), points[0]), leader=row(("100",), points[1]), leaf5=row(("110",), points[2]))
        moving_links = (("root", "parent", 0), ("root", "leader", 1), ("parent", "leaf0", 0), ("parent", "leaf2", 1), ("parent", "leaf3", 2), ("leader", "leaf4", 0), ("leader", "leaf5", 1))
        frames.append(draw(moving, moving_links, "右兄弟不够借，100 下沉，与 90、110 合并"))
    rows["leaf4"] = row(("100", "110"), (950.0, 510.0), positions=cell_slots((950.0, 510.0), 3)[1:])
    rows["right"] = row((None,), right_parent, GLOW_RED)
    frames.extend([draw(rows, links, "右侧内部节点下溢，再与左侧内部节点合并", ("right",))] * 20)

    # Pull the remaining root separator into the two underflowed internal nodes.
    source_root = rows["root"][1][0]
    source_parent = rows["parent"][1]
    source_right = rows["leaf4"][1]
    target_root = cell_slots((550.0, 125.0), 3)
    target_parent = cell_slots((300.0, 380.0), 2)
    target_right = cell_slots((820.0, 380.0), 2)
    for step in range(1, 43):
        progress = ease(step / 42.0)
        root_points = (lerp_point(source_root, target_root[2], progress),)
        parent_points = tuple(lerp_point(point, target, progress) for point, target in zip(source_parent, target_parent))
        right_points = tuple(lerp_point(point, target, progress) for point, target in zip(source_right, target_right))
        moving = {
            "root": row(("80",), root_points[0]),
            "parent": row(("50", "60"), (parent_points[0], parent_points[1]), positions=parent_points),
            "right": row(("100", "110"), (right_points[0], right_points[1]), positions=right_points),
            "left": row(("20", "30"), (180.0, 380.0)),
            "middle1": row(("55",), (410.0, 380.0)),
            "middle2": row(("70",), (590.0, 380.0)),
        }
        moving_links = (("root", "parent", 0), ("root", "right", 1), ("parent", "left", 0), ("parent", "middle1", 1), ("parent", "middle2", 2))
        frames.append(draw(moving, moving_links, "根的 80 下沉，第二次下溢继续合并"))

    final = {"root": row(("50", "60", "80"), (550.0, 125.0)), "left": row(("20", "30"), (180.0, 380.0)), "middle1": row(("55",), (410.0, 380.0)), "middle2": row(("70",), (590.0, 380.0)), "right": row(("100", "110"), (820.0, 380.0))}
    final_links = (("root", "left", 0), ("root", "middle1", 1), ("root", "middle2", 2), ("root", "right", 3))
    frames.extend([draw(final, final_links, "根收缩，第二次级联合并完成")] * 90)
    return frames


def btree_classic_lend_frames(
    width: int,
    height: int,
    root_c: Point,
    left_c: Point,
    right_c: Point,
    captions: Mapping[str, str] | None = None,
) -> list[str]:
    """Traditional deletion case two: the sibling can lend, so one key rises while the separator sinks."""

    def caption(phase: str) -> str:
        if not captions or phase not in captions:
            return ""
        return neon_text(captions[phase], (width / 2.0, height - 130.0))

    def row(keys: Sequence[str], positions: Sequence[Point]) -> str:
        return btree_neon_row_at_positions(keys, positions)

    def ghost_cell(center: Point, opacity: float) -> str:
        left = center[0] - BTREE_NEON_CELL_W / 2.0
        top = center[1] - BTREE_NEON_CELL_H / 2.0
        return (
            f'<rect x="{left:.1f}" y="{top:.1f}" width="{BTREE_NEON_CELL_W:.1f}" '
            f'height="{BTREE_NEON_CELL_H:.1f}" rx="9" fill="none" '
            f'stroke="{NODE_RIM}" stroke-width="1.8" stroke-dasharray="7 6" opacity="{opacity:.3f}"/>'
        )

    def ring(points: Sequence[Point], opacity: float) -> str:
        left = min(point[0] for point in points) - BTREE_NEON_CELL_W / 2.0
        right = max(point[0] for point in points) + BTREE_NEON_CELL_W / 2.0
        return bloom_rect(
            ((left + right) / 2.0, points[0][1]),
            right - left,
            BTREE_NEON_CELL_H,
            GLOW_WHITE,
            opacity,
            radius=12.0,
        )

    def edges(parent_x: float, child_tops: Sequence[Point], opacity: float = 1.0) -> str:
        start = (parent_x, root_c[1] + BTREE_NEON_CELL_H / 2.0)
        return "".join(btree_neon_edge(start, top, opacity=opacity) for top in child_tops)

    def strike_at(point: Point, progress: float) -> str:
        return glow_line(
            (point[0] - 22.0, point[1] - 17.0),
            (point[0] - 22.0 + 44.0 * progress, point[1] - 17.0 + 34.0 * progress),
            color=GLOW_RED,
            width=5.0,
            bloom=GLOW_RED,
            radius=0.0,
        )

    ten_slot = cell_slots(left_c, 1)[0]
    root_one = cell_slots(root_c, 1)[0]
    root_two = cell_slots(root_c, 2)
    right_three = cell_slots(right_c, 3)
    right_two = cell_slots(right_c, 2)
    child_tops = ((left_c[0], left_c[1] - BTREE_NEON_CELL_H / 2.0), (right_c[0], right_c[1] - BTREE_NEON_CELL_H / 2.0))
    pulse = (0.35, 0.55, 0.8, 0.55)
    frames: list[str] = []

    initial_body = edges(root_c[0], child_tops) + row(("10",), (ten_slot,)) + row(("40",), (root_one,)) + row(("50", "60", "70"), right_three)
    frames.extend([svg(initial_body, width=width, height=height, color=INK)] * 24)

    for step in range(1, 19):
        frames.append(svg(initial_body + strike_at(ten_slot, ease(step / 18.0)) + caption("slash"), width=width, height=height, color=INK))
    frames.extend([svg(initial_body + strike_at(ten_slot, 1.0) + caption("slash"), width=width, height=height, color=INK)] * 8)

    for step in range(12):
        body = edges(root_c[0], child_tops) + ghost_cell(ten_slot, (step + 1) / 12.0) + row(("40",), (root_one,)) + row(("50", "60", "70"), right_three)
        frames.append(svg(body + caption("slash"), width=width, height=height, color=INK))
    hungry_body = edges(root_c[0], child_tops) + ghost_cell(ten_slot, 1.0) + row(("40",), (root_one,)) + row(("50", "60", "70"), right_three)
    frames.extend([svg(hungry_body + caption("slash"), width=width, height=height, color=INK)] * 12)

    for step in range(36):
        body = hungry_body + ring(right_three, pulse[(step // 3) % 4]) + caption("ring")
        frames.append(svg(body, width=width, height=height, color=INK))

    for step in range(1, 37):
        t = ease(step / 36.0)
        fifty = lerp_point(right_three[0], root_two[1], t)
        forty = lerp_point(root_one, root_two[0], t)
        sixty = lerp_point(right_three[1], right_two[0], t)
        seventy = lerp_point(right_three[2], right_two[1], t)
        body = (
            edges(root_c[0], child_tops)
            + ghost_cell(ten_slot, 1.0)
            + row(("40",), (forty,))
            + row(("50",), (fifty,))
            + row(("60", "70"), (sixty, seventy))
            + caption("rise")
        )
        frames.append(svg(body, width=width, height=height, color=INK))

    for step in range(1, 37):
        t = ease(step / 36.0)
        forty = lerp_point(root_two[0], ten_slot, t)
        fifty = lerp_point(root_two[1], root_one, t)
        ghost_opacity = 1.0 if step <= 24 else max(0.0, 1.0 - (step - 24) / 12.0)
        body = (
            edges(root_c[0], child_tops)
            + ghost_cell(ten_slot, ghost_opacity)
            + row(("40",), (forty,))
            + row(("50",), (fifty,))
            + row(("60", "70"), right_two)
            + caption("sink")
        )
        frames.append(svg(body, width=width, height=height, color=INK))

    final_body = edges(root_c[0], child_tops) + row(("40",), (ten_slot,)) + row(("50",), (root_one,)) + row(("60", "70"), right_two)
    frames.extend([svg(final_body + caption("sink"), width=width, height=height, color=INK)] * 90)
    return frames


def btree_classic_lend() -> None:
    """Render the traditional lend case as a standalone transparent WebM."""
    render_webm(
        "btree-classic-lend",
        btree_classic_lend_frames(900, 540, (450.0, 120.0), (250.0, 350.0), (650.0, 350.0)),
        fps=30,
        transparent=True,
    )


def btree_classic_merge_frames(
    width: int,
    height: int,
    root_c: Point,
    left_c: Point,
    right_c: Point,
    merged_c: Point,
    captions: Mapping[str, str] | None = None,
) -> list[str]:
    """Traditional deletion case three: the sibling cannot lend, so the separator merges the leaves."""

    def caption(phase: str) -> str:
        if not captions or phase not in captions:
            return ""
        return neon_text(captions[phase], (width / 2.0, height - 130.0))

    def row(keys: Sequence[str], positions: Sequence[Point]) -> str:
        return btree_neon_row_at_positions(keys, positions)

    def ring(points: Sequence[Point], opacity: float) -> str:
        left = min(point[0] for point in points) - BTREE_NEON_CELL_W / 2.0
        right = max(point[0] for point in points) + BTREE_NEON_CELL_W / 2.0
        return bloom_rect(
            ((left + right) / 2.0, points[0][1]),
            right - left,
            BTREE_NEON_CELL_H,
            GLOW_WHITE,
            opacity,
            radius=12.0,
        )

    def strike_at(point: Point, progress: float) -> str:
        return glow_line(
            (point[0] - 22.0, point[1] - 17.0),
            (point[0] - 22.0 + 44.0 * progress, point[1] - 17.0 + 34.0 * progress),
            color=GLOW_RED,
            width=5.0,
            bloom=GLOW_RED,
            radius=0.0,
        )

    ten_slot = cell_slots(left_c, 1)[0]
    forty_slot = cell_slots(root_c, 1)[0]
    sixty_slot = cell_slots(right_c, 1)[0]
    merged_three = cell_slots(merged_c, 3)
    root_two = cell_slots(root_c, 2)
    pulse = (0.35, 0.55, 0.8, 0.55)
    frames: list[str] = []

    initial_rows = [
        (("10",), (ten_slot,)),
        (("40",), (forty_slot,)),
        (("60",), (sixty_slot,)),
    ]

    def tree_rows(rows: Sequence[tuple[Sequence[str], Sequence[Point]]], overlay: str = "") -> str:
        parts: list[str] = []
        parent = (
            sum(point[0] for point in rows[1][1]) / len(rows[1][1]),
            sum(point[1] for point in rows[1][1]) / len(rows[1][1]),
        )
        for child in (rows[0][1], rows[2][1]):
            child_center = (
                sum(point[0] for point in child) / len(child),
                sum(point[1] for point in child) / len(child),
            )
            parts.append(btree_neon_edge(
                (parent[0], parent[1] + BTREE_NEON_CELL_H / 2.0),
                (child_center[0], child_center[1] - BTREE_NEON_CELL_H / 2.0),
            ))
        parts.extend(row(keys, points) for keys, points in rows)
        parts.append(overlay)
        return svg("".join(parts), width=width, height=height, color=INK)

    frames.extend([tree_rows(initial_rows)] * 24)
    for step in range(1, 19):
        frames.append(tree_rows(initial_rows, strike_at(ten_slot, ease(step / 18.0)) + caption("slash")))
    frames.extend([tree_rows(initial_rows, strike_at(ten_slot, 1.0) + caption("slash"))] * 8)

    for step in range(36):
        frames.append(tree_rows(initial_rows, ring((sixty_slot,), pulse[(step // 3) % 4]) + strike_at(ten_slot, 1.0) + caption("ring")))

    merge_sources = (ten_slot, forty_slot, sixty_slot)
    for step in range(1, 43):
        t = ease(step / 42.0)
        ten_now = lerp_point(merge_sources[0], merged_three[0], t)
        forty_now = lerp_point(merge_sources[1], merged_three[1], t)
        sixty_now = lerp_point(merge_sources[2], merged_three[2], t)
        frames.append(tree_rows(
            [(("10",), (ten_now,)), (("40",), (forty_now,)), (("60",), (sixty_now,))],
            strike_at(ten_now, 1.0) + caption("merge"),
        ))
    merged_body = row(("10", "40", "60"), merged_three) + strike_at(merged_three[0], 1.0)
    frames.extend([svg(merged_body + caption("merge"), width=width, height=height, color=INK)] * 18)

    remaining_positions = merged_three[1:]
    frames.extend([svg(row(("40", "60"), remaining_positions) + caption("remove"), width=width, height=height, color=INK)] * 24)
    frames.extend([svg(row(("40", "60"), remaining_positions) + caption("remove"), width=width, height=height, color=INK)] * 18)

    for step in range(1, 37):
        t = ease(step / 36.0)
        raised = tuple(lerp_point(source, target, t) for source, target in zip(remaining_positions, root_two))
        frames.append(svg(row(("40", "60"), raised) + caption("rise"), width=width, height=height, color=INK))
    final = svg(row(("40", "60"), root_two) + caption("rise"), width=width, height=height, color=INK)
    frames.extend([final] * 90)
    return frames


def btree_classic_merge() -> None:
    """Render the traditional merge case as a standalone transparent WebM."""
    render_webm(
        "btree-classic-merge",
        btree_classic_merge_frames(900, 540, (450.0, 120.0), (250.0, 350.0), (650.0, 350.0), (450.0, 350.0)),
        fps=30,
        transparent=True,
    )


def btree_case1_compare() -> None:
    """Play the unified and traditional takes of deletion case one side by side."""
    width, height = 1100, 660
    left_frames = btree_borrow_frames(width, height, (550.0, 120.0), (300.0, 370.0), (820.0, 370.0), (550.0, 370.0))
    right_frames = btree_classic_plain_frames(width, height, (550.0, 120.0), (300.0, 370.0), (820.0, 370.0), captions={
        "slash": "直接在叶节点里删掉 10",
        "settled": "剩 20、30，没有下溢",
        "final": "不用借也不用合，结束",
    })
    frames = btree_side_by_side_frames(
        left_frames,
        right_frames,
        panel_width=width,
        height=height,
        left_title="我们的方法",
        right_title="传统方法",
    )
    render_webm("btree-case1-compare", frames, fps=24, transparent=True, crop_pad=60)


def btree_case2_compare() -> None:
    """Play the unified and traditional takes of deletion case two side by side."""
    width, height = 1100, 660
    left_frames = btree_lend_frames(width, height, (550.0, 120.0), (300.0, 370.0), (820.0, 370.0), (550.0, 370.0))
    right_frames = btree_classic_lend_frames(width, height, (550.0, 120.0), (300.0, 370.0), (820.0, 370.0), captions={
        "slash": "删掉 10，左叶空了——下溢",
        "ring": "看兄弟：50、60、70，够借",
        "rise": "借位：50 升入父节点",
        "sink": "40 下沉补上空位，借位完成",
    })
    frames = btree_side_by_side_frames(
        left_frames,
        right_frames,
        panel_width=width,
        height=height,
        left_title="我们的方法",
        right_title="传统方法",
    )
    render_webm("btree-case2-compare", frames, fps=24, transparent=True, crop_pad=60)


def _btree_cascade_two_deletes_frames_legacy_v3(width: int, height: int, *, traditional: bool) -> list[str]:
    """Build case three from legal B-tree states and explicit merge transitions."""
    root_point = (550.0, 100.0)
    level_two = {"left": (220.0, 285.0), "middle": (550.0, 285.0), "right": (880.0, 285.0)}
    leaf_points = {
        "10": (140.0, 510.0), "30": (300.0, 510.0), "55": (470.0, 510.0),
        "70": (630.0, 510.0), "90": (800.0, 510.0), "110": (960.0, 510.0),
    }
    first_leaf_center = (220.0, 510.0)
    first_parent_center = (385.0, 285.0)
    second_leaf_center = (880.0, 510.0)
    final_root = (550.0, 125.0)
    final_leaf_centers = ((220.0, 380.0), (450.0, 380.0), (630.0, 380.0), (860.0, 380.0))

    def node(keys, center, rim=None, positions=None):
        return keys, tuple(positions or cell_slots(center, max(1, len(keys)))), rim

    def move_positions(positions, targets, progress):
        return tuple(lerp_point(source, target, progress) for source, target in zip(positions, targets))

    def empty_like(node_row):
        return node((None,), node_row[1][0], GLOW_RED)

    def ghost(node_row, opacity=1.0):
        points = node_row[1]
        left = min(point[0] for point in points) - BTREE_NEON_CELL_W / 2.0
        right = max(point[0] for point in points) + BTREE_NEON_CELL_W / 2.0
        top = points[0][1] - BTREE_NEON_CELL_H / 2.0
        return (
            f'<rect x="{left:.1f}" y="{top:.1f}" width="{right - left:.1f}" '
            f'height="{BTREE_NEON_CELL_H:.1f}" rx="9" fill="none" stroke="#94A3B8" '
            f'stroke-width="2.6" stroke-dasharray="9 7" opacity="{opacity:.3f}"/>'
        )

    def child_gap(parent_row, slot):
        keys, positions, _rim = parent_row
        if not keys or all(key is None for key in keys):
            return positions[0][0], positions[0][1] + BTREE_NEON_CELL_H / 2.0
        if slot == 0:
            x = positions[0][0] - BTREE_NEON_CELL_W / 2.0
        elif slot == len(keys):
            x = positions[-1][0] + BTREE_NEON_CELL_W / 2.0
        else:
            x = (positions[slot - 1][0] + positions[slot][0]) / 2.0
        return x, positions[0][1] + BTREE_NEON_CELL_H / 2.0

    def draw(rows, links, caption="", ghosts=(), overlay=""):
        parts = []
        for parent_id, child_id, slot in links:
            parent_row, child_row = rows[parent_id], rows[child_id]
            child_x = sum(point[0] for point in child_row[1]) / len(child_row[1])
            parts.append(btree_neon_edge(
                child_gap(parent_row, slot),
                (child_x, child_row[1][0][1] - BTREE_NEON_CELL_H / 2.0),
            ))
        for row_id, row_data in rows.items():
            if row_id in ghosts:
                opacity = ghosts[row_id] if isinstance(ghosts, dict) else 1.0
                parts.append(ghost(row_data, opacity))
            else:
                parts.append(btree_neon_row_at_positions(row_data[0], row_data[1], rim=row_data[2]))
        if caption:
            parts.append(neon_text(caption, (width / 2.0, height - 58.0), size=22.0, glow=GLOW_BLUE))
        parts.append(overlay)
        return svg("".join(parts), width=width, height=height, color=INK)

    def strike(point, progress):
        return glow_line(
            (point[0] - 22.0, point[1] - 17.0),
            (point[0] - 22.0 + 44.0 * progress, point[1] - 17.0 + 34.0 * progress),
            color=GLOW_RED, width=5.0, bloom=GLOW_RED, radius=0.0,
        )

    root_initial = node(("50", "80"), root_point)
    initial_rows = {
        "root": root_initial,
        "left": node(("20",), level_two["left"]),
        "middle": node(("60",), level_two["middle"]),
        "right": node(("100",), level_two["right"]),
    }
    initial_rows.update({f"leaf{key}": node((key,), point) for key, point in leaf_points.items()})
    initial_links = (
        ("root", "left", 0), ("root", "middle", 1), ("root", "right", 2),
        ("left", "leaf10", 0), ("left", "leaf30", 1),
        ("middle", "leaf55", 0), ("middle", "leaf70", 1),
        ("right", "leaf90", 0), ("right", "leaf110", 1),
    )
    frames = [draw(initial_rows, initial_links, "初始状态：根有左右两个首领")] * 24

    def delete_mark(rows, links, leaf_id, caption):
        point = rows[leaf_id][1][0]
        for step in range(1, 19):
            frames.append(draw(rows, links, caption, overlay=strike(point, ease(step / 18.0))))
        frames.extend([draw(rows, links, caption, overlay=strike(point, 1.0))] * 8)

    def stable_tree(root_row, left_row, middle_row, right_row, leaves, caption, ghosts=()):
        rows = {"root": root_row, "left": left_row, "middle": middle_row, "right": right_row, **leaves}
        return draw(rows, (
            ("root", "left", 0), ("root", "middle", 1), ("root", "right", 2),
            ("left", "leaf10", 0), ("left", "leaf30", 1),
            ("middle", "leaf55", 0), ("middle", "leaf70", 1),
            ("right", "leaf90", 0), ("right", "leaf110", 1),
        ), caption, ghosts)

    if not traditional:
        # 10: the left internal leader 20 returns to its two children.
        delete_mark(initial_rows, initial_links, "leaf10", "第一步：删除 10")
        left_empty = empty_like(initial_rows["left"])
        leaf10_empty = empty_like(initial_rows["leaf10"])
        rows = dict(initial_rows, left=left_empty, leaf10=leaf10_empty)
        frames.extend([draw(rows, initial_links, "左叶下溢，左首领 20 准备回家", ghosts=("left", "leaf10"))] * 18)
        leaf_targets = cell_slots(first_leaf_center, 3)
        for step in range(1, 43):
            progress = ease(step / 42.0)
            moving = dict(rows)
            moving.pop("left", None)
            moving.pop("leaf10", None)
            moving.pop("leaf30", None)
            moving["moving10"] = node(("10",), leaf_points["10"], positions=(lerp_point(leaf_points["10"], leaf_targets[0], progress),))
            moving["moving20"] = node(("20",), level_two["left"], positions=(lerp_point(level_two["left"], leaf_targets[1], progress),))
            moving["moving30"] = node(("30",), leaf_points["30"], positions=(lerp_point(leaf_points["30"], leaf_targets[2], progress),))
            moving_links = (("root", "middle", 1), ("root", "right", 2), ("middle", "leaf55", 0), ("middle", "leaf70", 1), ("right", "leaf90", 0), ("right", "leaf110", 1))
            moving["left_slot"] = left_empty
            frames.append(draw(moving, moving_links, "左首领 20 回家，和左右子民合并", ghosts=("left_slot", "leaf10")))
        merged_leaf = node(("10", "20", "30"), first_leaf_center)
        rows = dict(initial_rows, left=left_empty, leaf10=merged_leaf)
        rows.pop("leaf30", None)
        first_merge_links = (("root", "left", 0), ("root", "middle", 1), ("root", "right", 2), ("left", "leaf10", 0), ("middle", "leaf55", 0), ("middle", "leaf70", 1), ("right", "leaf90", 0), ("right", "leaf110", 1))
        frames.extend([draw(rows, first_merge_links, "形成 [10,20,30]", ghosts=("left",))] * 16)
        delete_mark(rows, first_merge_links, "leaf10", "删除合并节点里的 10")
        first_remaining = node(("20", "30"), first_leaf_center, positions=merged_leaf[1][1:])
        rows = dict(rows, leaf10=first_remaining)
        frames.extend([draw(rows, first_merge_links, "删除完成，左侧内部节点下溢", ghosts=("left",))] * 20)

        # 50 returns with 60. The root is now [80], not the old [50,80].
        root80_start = root_initial[1][1]
        root80_end = cell_slots(root_point, 1)[0]
        parent_targets = cell_slots(first_parent_center, 2)
        for step in range(1, 43):
            progress = ease(step / 42.0)
            parent_positions = (
                lerp_point(root_initial[1][0], parent_targets[0], progress),
                lerp_point(initial_rows["middle"][1][0], parent_targets[1], progress),
            )
            merge_rows = {
                "root": node(("80",), lerp_point(root80_start, root80_end, progress)),
                "parent": node(("50", "60"), first_parent_center, positions=parent_positions),
                "right": initial_rows["right"], "leaf10": first_remaining,
                "leaf55": initial_rows["leaf55"], "leaf70": initial_rows["leaf70"],
                "leaf90": initial_rows["leaf90"], "leaf110": initial_rows["leaf110"],
            }
            merge_links = (("root", "parent", 0), ("root", "right", 1), ("parent", "leaf10", 0), ("parent", "leaf55", 1), ("parent", "leaf70", 2), ("right", "leaf90", 0), ("right", "leaf110", 1))
            frames.append(draw(merge_rows, merge_links, "根的左首领 50 回家，和中间首领 60 合并", ghosts={"left": max(0.0, 1.0 - progress)}))
        first_state = {
            "root": node(("80",), root_point), "parent": node(("50", "60"), first_parent_center),
            "right": initial_rows["right"], "leaf10": first_remaining,
            "leaf55": initial_rows["leaf55"], "leaf70": initial_rows["leaf70"],
            "leaf90": initial_rows["leaf90"], "leaf110": initial_rows["leaf110"],
        }
        first_links = (("root", "parent", 0), ("root", "right", 1), ("parent", "leaf10", 0), ("parent", "leaf55", 1), ("parent", "leaf70", 2), ("right", "leaf90", 0), ("right", "leaf110", 1))
        frames.extend([draw(first_state, first_links, "第一次下溢已传到根，根还剩首领 80")] * 28)

        # 90: the right internal leader 100 returns to its two children.
        delete_mark(first_state, first_links, "leaf90", "第二步：删除 90")
        right_empty = empty_like(first_state["right"])
        leaf90_empty = empty_like(first_state["leaf90"])
        rows = dict(first_state, right=right_empty, leaf90=leaf90_empty)
        frames.extend([draw(rows, first_links, "右叶下溢，右首领 100 准备回家", ghosts=("right", "leaf90"))] * 18)
        leaf_targets = cell_slots(second_leaf_center, 3)
        for step in range(1, 43):
            progress = ease(step / 42.0)
            moving = dict(rows)
            moving.pop("right", None)
            moving.pop("leaf90", None)
            moving.pop("leaf110", None)
            moving["moving90"] = node(("90",), leaf_points["90"], positions=(lerp_point(leaf_points["90"], leaf_targets[0], progress),))
            moving["moving100"] = node(("100",), level_two["right"], positions=(lerp_point(level_two["right"], leaf_targets[1], progress),))
            moving["moving110"] = node(("110",), leaf_points["110"], positions=(lerp_point(leaf_points["110"], leaf_targets[2], progress),))
            moving_links = (("root", "parent", 0), ("parent", "leaf10", 0), ("parent", "leaf55", 1), ("parent", "leaf70", 2))
            moving["right_slot"] = right_empty
            frames.append(draw(moving, moving_links, "右首领 100 回家，和左右子民合并", ghosts=("right_slot", "leaf90")))
        merged_right = node(("90", "100", "110"), second_leaf_center)
        rows = dict(first_state, right=right_empty, leaf90=merged_right)
        frames.extend([draw(rows, first_links, "形成 [90,100,110]", ghosts=("right",))] * 16)
        delete_mark(rows, first_links, "leaf90", "删除合并节点里的 90")
        second_remaining = node(("100", "110"), second_leaf_center, positions=merged_right[1][1:])
        rows = dict(rows, leaf90=second_remaining)
        frames.extend([draw(rows, first_links, "删除完成，右侧内部节点下溢", ghosts=("right",))] * 20)

        # 80 returns to the underflowed right side and becomes the new root.
        source_parent = first_state["parent"][1]
        source_right = second_remaining[1]
        target_root_positions = cell_slots(final_root, 3)
        target_parent_positions = target_root_positions[:2]
        target_right_positions = cell_slots(final_leaf_centers[3], 2)
        for step in range(1, 43):
            progress = ease(step / 42.0)
            root_positions = (
                lerp_point(source_parent[0], target_parent_positions[0], progress),
                lerp_point(source_parent[1], target_parent_positions[1], progress),
                lerp_point(first_state["root"][1][0], target_root_positions[2], progress),
            )
            moving = {
                "root": node(("50", "60", "80"), final_root, positions=root_positions),
                "leaf10": node(("20", "30"), final_leaf_centers[0], positions=move_positions(first_remaining[1], cell_slots(final_leaf_centers[0], 2), progress)),
                "leaf55": node(("55",), lerp_point(initial_rows["leaf55"][1][0], final_leaf_centers[1], progress)),
                "leaf70": node(("70",), lerp_point(initial_rows["leaf70"][1][0], final_leaf_centers[2], progress)),
                "leaf90": node(("100", "110"), final_leaf_centers[3], positions=move_positions(source_right, target_right_positions, progress)),
            }
            final_links = (("root", "leaf10", 0), ("root", "leaf55", 1), ("root", "leaf70", 2), ("root", "leaf90", 3))
            frames.append(draw(moving, final_links, "根首领 80 回家，根收缩为新的根", ghosts={"root": 1.0 - progress}))
        final_rows = {"root": node(("50", "60", "80"), final_root), "leaf10": node(("20", "30"), final_leaf_centers[0]), "leaf55": node(("55",), final_leaf_centers[1]), "leaf70": node(("70",), final_leaf_centers[2]), "leaf90": node(("100", "110"), final_leaf_centers[3])}
        frames.extend([draw(final_rows, (("root", "leaf10", 0), ("root", "leaf55", 1), ("root", "leaf70", 2), ("root", "leaf90", 3)), "根收缩，第二次下溢也已修复")] * 90)
        return frames

    # Traditional path: deletion happens first, and only then does the separator fall.
    delete_mark(initial_rows, initial_links, "leaf10", "第一步：直接删除 10")
    left_empty = empty_like(initial_rows["left"])
    leaf10_empty = empty_like(initial_rows["leaf10"])
    rows = dict(initial_rows, leaf10=leaf10_empty)
    frames.extend([draw(rows, initial_links, "左叶下溢，检查左右兄弟", ghosts=("leaf10",))] * 18)
    first_targets = cell_slots(first_leaf_center, 2)
    for step in range(1, 43):
        progress = ease(step / 42.0)
        moving = dict(rows, left=left_empty)
        moving.pop("left", None)
        moving.pop("leaf10", None)
        moving.pop("leaf30", None)
        moving["moving20"] = node(("20",), level_two["left"], positions=(lerp_point(level_two["left"], first_targets[0], progress),))
        moving["moving30"] = node(("30",), leaf_points["30"], positions=(lerp_point(leaf_points["30"], first_targets[1], progress),))
        moving["left_slot"] = left_empty
        moving_links = (("middle", "leaf55", 0), ("middle", "leaf70", 1), ("right", "leaf90", 0), ("right", "leaf110", 1))
        frames.append(draw(moving, moving_links, "兄弟不够借，20 下沉与 30 合并", ghosts=("left_slot", "leaf10")))
    first_remaining = node(("20", "30"), first_leaf_center)
    rows = dict(initial_rows, left=left_empty, leaf10=first_remaining)
    frames.extend([draw(rows, initial_links, "左侧内部节点下溢，继续向上合并", ghosts=("left", "leaf10"))] * 20)

    parent_targets = cell_slots(first_parent_center, 2)
    for step in range(1, 43):
        progress = ease(step / 42.0)
        parent_positions = (lerp_point(root_initial[1][0], parent_targets[0], progress), lerp_point(initial_rows["middle"][1][0], parent_targets[1], progress))
        moving = {"root": node(("80",), lerp_point(root_initial[1][1], root_point, progress)), "parent": node(("50", "60"), first_parent_center, positions=parent_positions), "right": initial_rows["right"], "leaf10": first_remaining, "leaf55": initial_rows["leaf55"], "leaf70": initial_rows["leaf70"], "leaf90": initial_rows["leaf90"], "leaf110": initial_rows["leaf110"]}
        links = (("root", "parent", 0), ("root", "right", 1), ("parent", "leaf10", 0), ("parent", "leaf55", 1), ("parent", "leaf70", 2), ("right", "leaf90", 0), ("right", "leaf110", 1))
        frames.append(draw(moving, links, "父节点下溢，50 下沉与 60 合并", ghosts={"left": 1.0 - progress}))
    first_state = {"root": node(("80",), root_point), "parent": node(("50", "60"), first_parent_center), "right": initial_rows["right"], "leaf10": first_remaining, "leaf55": initial_rows["leaf55"], "leaf70": initial_rows["leaf70"], "leaf90": initial_rows["leaf90"], "leaf110": initial_rows["leaf110"]}
    first_links = (("root", "parent", 0), ("root", "right", 1), ("parent", "leaf10", 0), ("parent", "leaf55", 1), ("parent", "leaf70", 2), ("right", "leaf90", 0), ("right", "leaf110", 1))
    frames.extend([draw(first_state, first_links, "第一次级联合并完成，根还剩 80")] * 28)

    delete_mark(first_state, first_links, "leaf90", "第二步：直接删除 90")
    right_empty = empty_like(first_state["right"])
    leaf90_empty = empty_like(first_state["leaf90"])
    rows = dict(first_state, right=right_empty, leaf90=leaf90_empty)
    frames.extend([draw(rows, first_links, "右叶下溢，检查左右兄弟", ghosts=("right", "leaf90"))] * 18)
    second_targets = cell_slots(second_leaf_center, 2)
    for step in range(1, 43):
        progress = ease(step / 42.0)
        moving = dict(rows)
        moving.pop("right", None)
        moving.pop("leaf90", None)
        moving.pop("leaf110", None)
        moving["moving100"] = node(("100",), level_two["right"], positions=(lerp_point(level_two["right"], second_targets[0], progress),))
        moving["moving110"] = node(("110",), leaf_points["110"], positions=(lerp_point(leaf_points["110"], second_targets[1], progress),))
        moving["right_slot"] = right_empty
        moving_links = (("root", "parent", 0), ("parent", "leaf10", 0), ("parent", "leaf55", 1), ("parent", "leaf70", 2))
        frames.append(draw(moving, moving_links, "兄弟不够借，100 下沉与 110 合并", ghosts=("right_slot", "leaf90")))
    second_remaining = node(("100", "110"), second_leaf_center)
    rows = dict(first_state, right=right_empty, leaf90=second_remaining)
    frames.extend([draw(rows, first_links, "右侧内部节点下溢，再向上合并", ghosts=("right", "leaf90"))] * 20)

    target_root_positions = cell_slots(final_root, 3)
    parent_targets = target_root_positions[:2]
    right_targets = cell_slots(final_leaf_centers[3], 2)
    for step in range(1, 43):
        progress = ease(step / 42.0)
        merged_root = node(("50", "60", "80"), final_root, positions=(
            lerp_point(first_state["parent"][1][0], parent_targets[0], progress),
            lerp_point(first_state["parent"][1][1], parent_targets[1], progress),
            lerp_point(first_state["root"][1][0], target_root_positions[2], progress),
        ))
        moving = {"root": merged_root, "leaf10": node(("20", "30"), final_leaf_centers[0]), "leaf55": node(("55",), final_leaf_centers[1]), "leaf70": node(("70",), final_leaf_centers[2]), "leaf90": node(("100", "110"), final_leaf_centers[3], positions=move_positions(second_remaining[1], right_targets, progress))}
        links = (("root", "leaf10", 0), ("root", "leaf55", 1), ("root", "leaf70", 2), ("root", "leaf90", 3))
        frames.append(draw(moving, links, "第二次下溢传到根，80 下沉并使根收缩", ghosts={"root": 1.0 - progress}))
    final_rows = {"root": node(("50", "60", "80"), final_root), "leaf10": node(("20", "30"), final_leaf_centers[0]), "leaf55": node(("55",), final_leaf_centers[1]), "leaf70": node(("70",), final_leaf_centers[2]), "leaf90": node(("100", "110"), final_leaf_centers[3])}
    frames.extend([draw(final_rows, (("root", "leaf10", 0), ("root", "leaf55", 1), ("root", "leaf70", 2), ("root", "leaf90", 3)), "根收缩，第二次级联合并完成")] * 90)
    return frames


def _btree_case3_frames_correct(width: int, height: int, *, traditional: bool) -> list[str]:
    """Render case three from explicit legal states, not mixed before/after rows."""
    root = (550.0, 100.0)
    level_two = {"left": (220.0, 285.0), "middle": (550.0, 285.0), "right": (880.0, 285.0)}
    leaves = {"10": (140.0, 510.0), "30": (300.0, 510.0), "55": (470.0, 510.0), "70": (630.0, 510.0), "90": (800.0, 510.0), "110": (960.0, 510.0)}
    first_leaf = (220.0, 510.0)
    second_leaf = (880.0, 510.0)
    upper_parent = (385.0, 285.0)
    final_root = (550.0, 125.0)
    final_leaves = ((180.0, 380.0), (410.0, 380.0), (590.0, 380.0), (820.0, 380.0))

    def row(keys, center=None, positions=None, rim=None):
        points = tuple(positions or cell_slots(center, max(1, len(keys))))
        return tuple(keys), points, rim

    def center(node_row):
        points = node_row[1]
        return sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points)

    def move(node_row, target, progress):
        source = center(node_row)
        current = lerp_point(source, target, progress)
        dx, dy = current[0] - source[0], current[1] - source[1]
        return node_row[0], tuple((x + dx, y + dy) for x, y in node_row[1]), node_row[2]

    def empty(node_row):
        return row((None,), positions=(node_row[1][0],), rim=GLOW_RED)

    def ghost(node_row, opacity=1.0):
        points = node_row[1]
        left = min(point[0] for point in points) - BTREE_NEON_CELL_W / 2.0
        right = max(point[0] for point in points) + BTREE_NEON_CELL_W / 2.0
        top = points[0][1] - BTREE_NEON_CELL_H / 2.0
        return f'<rect x="{left:.1f}" y="{top:.1f}" width="{right - left:.1f}" height="{BTREE_NEON_CELL_H:.1f}" rx="9" fill="none" stroke="#94A3B8" stroke-width="2.6" stroke-dasharray="9 7" opacity="{opacity:.3f}"/>'

    def child_gap(parent_row, slot):
        points = parent_row[1]
        keys = parent_row[0]
        if not keys or all(key is None for key in keys):
            return points[0][0], points[0][1] + BTREE_NEON_CELL_H / 2.0
        if slot == 0:
            x = points[0][0] - BTREE_NEON_CELL_W / 2.0
        elif slot == len(keys):
            x = points[-1][0] + BTREE_NEON_CELL_W / 2.0
        else:
            x = (points[slot - 1][0] + points[slot][0]) / 2.0
        return x, points[0][1] + BTREE_NEON_CELL_H / 2.0

    def draw(rows, links=(), caption="", ghosts=(), overlay=""):
        parts = []
        for parent_id, child_id, slot in links:
            parent_row, child_row = rows[parent_id], rows[child_id]
            child_x = sum(point[0] for point in child_row[1]) / len(child_row[1])
            parts.append(btree_neon_edge(child_gap(parent_row, slot), (child_x, child_row[1][0][1] - BTREE_NEON_CELL_H / 2.0)))
        for row_id, node_row in rows.items():
            if row_id in ghosts:
                opacity = ghosts[row_id] if isinstance(ghosts, dict) else 1.0
                parts.append(ghost(node_row, opacity))
            else:
                parts.append(btree_neon_row_at_positions(node_row[0], node_row[1], rim=node_row[2]))
        if caption:
            parts.append(neon_text(caption, (width / 2.0, height - 58.0), size=22.0, glow=GLOW_BLUE))
        parts.append(overlay)
        return svg("".join(parts), width=width, height=height, color=INK)

    def slash(point, progress):
        return glow_line((point[0] - 22.0, point[1] - 17.0), (point[0] - 22.0 + 44.0 * progress, point[1] - 17.0 + 34.0 * progress), color=GLOW_RED, width=5.0, bloom=GLOW_RED, radius=0.0)

    root_row = row(("50", "80"), root)
    left_row = row(("20",), level_two["left"])
    middle_row = row(("60",), level_two["middle"])
    right_row = row(("100",), level_two["right"])
    initial = {
        "root": root_row, "left": left_row, "middle": middle_row, "right": right_row,
        "leaf10": row(("10",), leaves["10"]), "leaf30": row(("30",), leaves["30"]),
        "leaf55": row(("55",), leaves["55"]), "leaf70": row(("70",), leaves["70"]),
        "leaf90": row(("90",), leaves["90"]), "leaf110": row(("110",), leaves["110"]),
    }
    initial_links = (("root", "left", 0), ("root", "middle", 1), ("root", "right", 2), ("left", "leaf10", 0), ("left", "leaf30", 1), ("middle", "leaf55", 0), ("middle", "leaf70", 1), ("right", "leaf90", 0), ("right", "leaf110", 1))
    frames = [draw(initial, initial_links, "初始状态：根有左右两个首领")] * 30

    def delete_leaf(rows, links, leaf_id, caption):
        point = rows[leaf_id][1][0]
        for step in range(1, 25):
            frames.append(draw(rows, links, caption, overlay=slash(point, ease(step / 24.0))))
        frames.extend([draw(rows, links, caption, overlay=slash(point, 1.0))] * 8)

    def first_ours():
        frames.extend([draw(initial, initial_links, "第一步：先让左首领 20 回家")] * 18)
        left_empty = empty(left_row)
        target10, target20, target30 = cell_slots(first_leaf, 3)
        for step in range(1, 49):
            progress = ease(step / 48.0)
            rows = dict(initial, left=left_empty,
                        moving10=move(initial["leaf10"], target10, progress),
                        moving20=move(left_row, target20, progress),
                        moving30=move(initial["leaf30"], target30, progress))
            rows.pop("leaf10", None); rows.pop("leaf30", None)
            links = (("root", "left", 0), ("root", "middle", 1), ("root", "right", 2),
                     ("moving20", "moving10", 0), ("moving20", "moving30", 1),
                     ("middle", "leaf55", 0), ("middle", "leaf70", 1),
                     ("right", "leaf90", 0), ("right", "leaf110", 1))
            frames.append(draw(rows, links, "左首领 20 回家，带着 10 和 30 合并", ghosts={"left": 1.0}))
        merged = row(("10", "20", "30"), first_leaf)
        state = {"root": root_row, "left": left_empty, "middle": middle_row, "right": right_row,
                 "leaf20_30": merged, "leaf55": initial["leaf55"], "leaf70": initial["leaf70"],
                 "leaf90": initial["leaf90"], "leaf110": initial["leaf110"]}
        links = (("root", "left", 0), ("root", "middle", 1), ("root", "right", 2),
                 ("left", "leaf20_30", 0), ("middle", "leaf55", 0), ("middle", "leaf70", 1),
                 ("right", "leaf90", 0), ("right", "leaf110", 1))
        frames.extend([draw(state, links, "形成 [10,20,30]")] * 22)
        delete_leaf(state, links, "leaf20_30", "第二步：删除 10")
        state["leaf20_30"] = row(("20", "30"), first_leaf, positions=merged[1][1:])
        frames.extend([draw(state, links, "删除完成，左侧内部节点下溢", ghosts=("left",))] * 20)
        return state

    def first_traditional():
        delete_leaf(initial, initial_links, "leaf10", "第一步：直接删除 10")
        deleted = dict(initial, leaf10=empty(initial["leaf10"]))
        frames.extend([draw(deleted, initial_links, "左叶下溢，检查左右兄弟", ghosts=("leaf10",))] * 22)
        separator_start = left_row
        target20, target30 = cell_slots(first_leaf, 2)
        for step in range(1, 49):
            progress = ease(step / 48.0)
            moving20 = move(separator_start, target20, progress)
            moving30 = move(deleted["leaf30"], target30, progress)
            rows = dict(deleted, moving20=moving20, moving30=moving30)
            rows.pop("left", None); rows.pop("leaf30", None)
            links = (("root", "middle", 1), ("root", "right", 2), ("right", "leaf90", 0), ("right", "leaf110", 1))
            frames.append(draw(rows, links, "兄弟不够借，分隔键 20 下沉与 30 合并", ghosts={"left": 1.0, "leaf10": 1.0}))
        merged = row(("20", "30"), first_leaf)
        state = {"root": row(("50", "80"), root), "middle": middle_row, "right": right_row, "leaf20_30": merged, "leaf55": initial["leaf55"], "leaf70": initial["leaf70"], "leaf90": initial["leaf90"], "leaf110": initial["leaf110"]}
        links = (("root", "middle", 1), ("root", "right", 2), ("middle", "leaf55", 0), ("middle", "leaf70", 1), ("right", "leaf90", 0), ("right", "leaf110", 1))
        frames.extend([draw(state, links, "合并完成，左侧内部节点下溢")] * 22)
        return state

    state = first_traditional() if traditional else first_ours()

    def upper_merge(state):
        root80 = row(("80",), (550.0, 100.0))
        source50 = row(("50",), positions=(root_row[1][0],))
        source60 = state["middle"]
        target = cell_slots(upper_parent, 2)
        for step in range(1, 49):
            progress = ease(step / 48.0)
            moving50 = move(source50, target[0], progress)
            moving60 = move(source60, target[1], progress)
            rows = {"root80": root80, "moving50": moving50, "moving60": moving60, "right": state["right"], "leaf20_30": state["leaf20_30"], "leaf55": state["leaf55"], "leaf70": state["leaf70"], "leaf90": state["leaf90"], "leaf110": state["leaf110"]}
            links = (("root80", "right", 1), ("moving50", "leaf20_30", 0), ("moving60", "leaf55", 0), ("moving60", "leaf70", 1), ("right", "leaf90", 0), ("right", "leaf110", 1))
            frames.append(draw(rows, links, "上层空缺继续传递，50 与 60 合并", ghosts={"root80": 0.0}))
        parent = row(("50", "60"), upper_parent)
        next_state = {"root": root80, "parent": parent, "right": state["right"], "leaf20_30": state["leaf20_30"], "leaf55": state["leaf55"], "leaf70": state["leaf70"], "leaf90": state["leaf90"], "leaf110": state["leaf110"]}
        links = (("root", "parent", 0), ("root", "right", 1), ("parent", "leaf20_30", 0), ("parent", "leaf55", 1), ("parent", "leaf70", 2), ("right", "leaf90", 0), ("right", "leaf110", 1))
        frames.extend([draw(next_state, links, "第一次下溢传到根，根还剩 80")] * 28)
        return next_state, links

    state, links = upper_merge(state)
    frames.extend([draw(state, links, "第二步：先让右首领 100 回家")] * 18)
    right_empty = empty(right_row)
    state = dict(state, right=right_empty)
    target100, target110 = cell_slots(second_leaf, 2)
    target90, target100 = cell_slots(second_leaf, 3)[0], cell_slots(second_leaf, 3)[1]
    for step in range(1, 49):
        progress = ease(step / 48.0)
        rows = dict(state,
                    moving90=move(initial["leaf90"], target90, progress),
                    moving100=move(right_row, target100, progress),
                    moving110=move(initial["leaf110"], cell_slots(second_leaf, 3)[2], progress))
        rows.pop("leaf90", None); rows.pop("leaf110", None)
        move_links = (("root", "parent", 0), ("root", "right", 1),
                      ("parent", "leaf20_30", 0), ("parent", "leaf55", 1), ("parent", "leaf70", 2),
                      ("moving100", "moving90", 0), ("moving100", "moving110", 1))
        frames.append(draw(rows, move_links, "右首领 100 回家，带着 90 和 110 合并", ghosts={"right": 1.0}))
    right_merged = row(("90", "100", "110"), second_leaf)
    state = dict(state, right=right_empty, right_leaf=right_merged)
    links = (("root", "parent", 0), ("root", "right", 1),
             ("parent", "leaf20_30", 0), ("parent", "leaf55", 1), ("parent", "leaf70", 2),
             ("right", "right_leaf", 0))
    frames.extend([draw(state, links, "形成 [90,100,110]")] * 22)
    delete_leaf(state, links, "right_leaf", "第二步：删除 90")
    state["right_leaf"] = row(("100", "110"), second_leaf, positions=right_merged[1][1:])
    frames.extend([draw(state, links, "删除完成，右侧内部节点下溢", ghosts=("right",))] * 20)

    target_root = cell_slots(final_root, 3)
    source_parent = state["parent"]
    source80 = state["root"]
    source_right = state["right_leaf"]
    for step in range(1, 55):
        progress = ease(step / 54.0)
        root_row_now = row(("50", "60", "80"), positions=(
            lerp_point(source_parent[1][0], target_root[0], progress),
            lerp_point(source_parent[1][1], target_root[1], progress),
            lerp_point(source80[1][0], target_root[2], progress),
        ))
        rows = {"root": root_row_now,
                "leaf20_30": move(state["leaf20_30"], final_leaves[0], progress),
                "leaf55": move(state["leaf55"], final_leaves[1], progress),
                "leaf70": move(state["leaf70"], final_leaves[2], progress),
                "right_leaf": move(source_right, final_leaves[3], progress)}
        final_links = (("root", "leaf20_30", 0), ("root", "leaf55", 1), ("root", "leaf70", 2), ("root", "right_leaf", 3))
        frames.append(draw(rows, final_links, "根首领 80 回家，根收缩为 [50,60,80]"))
    final = {"root": row(("50", "60", "80"), final_root), "leaf20_30": row(("20", "30"), final_leaves[0]), "leaf55": row(("55",), final_leaves[1]), "leaf70": row(("70",), final_leaves[2]), "right_leaf": row(("100", "110"), final_leaves[3])}
    frames.extend([draw(final, final_links, "根收缩，第二次下溢也已修复")] * 90)
    return frames


def _btree_case3_frames_reference(width: int, height: int, *, traditional: bool) -> list[str]:
    """Keep the earlier case-three experiment available for comparison only."""
    root_point = (550.0, 100.0)
    left_point, middle_point, right_point = (220.0, 285.0), (550.0, 285.0), (880.0, 285.0)
    leaf_points = {
        "10": (140.0, 510.0), "30": (300.0, 510.0), "55": (470.0, 510.0),
        "70": (630.0, 510.0), "90": (800.0, 510.0), "110": (960.0, 510.0),
    }
    first_leaf_point = (220.0, 510.0)
    second_leaf_point = (880.0, 510.0)
    first_parent_point = (450.0, 285.0)
    final_root_point = (550.0, 125.0)
    final_leaf_points = ((160.0, 380.0), (400.0, 380.0), (700.0, 380.0), (940.0, 380.0))

    def row(keys, center=None, *, positions=None, rim=None):
        points = tuple(positions or cell_slots(center, max(1, len(keys))))
        return tuple(keys), points, rim

    def move(node_row, target, progress):
        points = node_row[1]
        source = (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )
        current = lerp_point(source, target, progress)
        delta = current[0] - source[0], current[1] - source[1]
        return node_row[0], tuple((x + delta[0], y + delta[1]) for x, y in points), node_row[2]

    def empty(node_row):
        return row((None,), positions=(node_row[1][0],), rim=GLOW_RED)

    def ghost(node_row, opacity=1.0):
        points = node_row[1]
        left = min(point[0] for point in points) - BTREE_NEON_CELL_W / 2.0
        right = max(point[0] for point in points) + BTREE_NEON_CELL_W / 2.0
        top = points[0][1] - BTREE_NEON_CELL_H / 2.0
        return (
            f'<rect x="{left:.1f}" y="{top:.1f}" width="{right - left:.1f}" '
            f'height="{BTREE_NEON_CELL_H:.1f}" rx="9" fill="none" stroke="#94A3B8" '
            f'stroke-width="2.6" stroke-dasharray="9 7" opacity="{opacity:.3f}"/>'
        )

    def child_gap(parent_row, slot):
        keys, points, _rim = parent_row
        if not keys or all(key is None for key in keys):
            return points[0][0], points[0][1] + BTREE_NEON_CELL_H / 2.0
        if slot == 0:
            x = points[0][0] - BTREE_NEON_CELL_W / 2.0
        elif slot == len(keys):
            x = points[-1][0] + BTREE_NEON_CELL_W / 2.0
        else:
            x = (points[slot - 1][0] + points[slot][0]) / 2.0
        return x, points[0][1] + BTREE_NEON_CELL_H / 2.0

    def draw(rows, links=(), caption="", ghosts=(), overlay=""):
        parts = []
        for parent_id, child_id, slot in links:
            parent_row, child_row = rows[parent_id], rows[child_id]
            child_x = sum(point[0] for point in child_row[1]) / len(child_row[1])
            parts.append(btree_neon_edge(
                child_gap(parent_row, slot),
                (child_x, child_row[1][0][1] - BTREE_NEON_CELL_H / 2.0),
            ))
        for row_id, node_row in rows.items():
            if row_id in ghosts:
                opacity = ghosts[row_id] if isinstance(ghosts, dict) else 1.0
                parts.append(ghost(node_row, opacity))
            else:
                parts.append(btree_neon_row_at_positions(node_row[0], node_row[1], rim=node_row[2]))
        if caption:
            parts.append(neon_text(caption, (width / 2.0, height - 58.0), size=22.0, glow=GLOW_BLUE))
        parts.append(overlay)
        return svg("".join(parts), width=width, height=height, color=INK)

    def slash(point, progress):
        return glow_line(
            (point[0] - 22.0, point[1] - 17.0),
            (point[0] - 22.0 + 44.0 * progress, point[1] - 17.0 + 34.0 * progress),
            color=GLOW_RED, width=5.0, bloom=GLOW_RED, radius=0.0,
        )

    root_row = row(("50", "80"), root_point)
    left_row = row(("20",), left_point)
    middle_row = row(("60",), middle_point)
    right_row = row(("100",), right_point)
    initial = {
        "root": root_row, "left": left_row, "middle": middle_row, "right": right_row,
        "leaf10": row(("10",), leaf_points["10"]), "leaf30": row(("30",), leaf_points["30"]),
        "leaf55": row(("55",), leaf_points["55"]), "leaf70": row(("70",), leaf_points["70"]),
        "leaf90": row(("90",), leaf_points["90"]), "leaf110": row(("110",), leaf_points["110"]),
    }
    initial_links = (
        ("root", "left", 0), ("root", "middle", 1), ("root", "right", 2),
        ("left", "leaf10", 0), ("left", "leaf30", 1),
        ("middle", "leaf55", 0), ("middle", "leaf70", 1),
        ("right", "leaf90", 0), ("right", "leaf110", 1),
    )
    frames = [draw(initial, initial_links, "初始状态：根有左右两个首领")] * 30

    def delete_mark(state, links, leaf_id, caption):
        point = state[leaf_id][1][0]
        for step in range(1, 25):
            frames.append(draw(state, links, caption, overlay=slash(point, ease(step / 24.0))))
        frames.extend([draw(state, links, caption, overlay=slash(point, 1.0))] * 8)

    def first_delete_ours():
        first_targets = cell_slots(first_leaf_point, 3)
        left_empty = empty(left_row)
        frames.extend([draw(initial, initial_links, "第一步：左首领 20 准备回家")] * 18)

        # First beat: only the complete leader moves; both child nodes stay put.
        for step in range(1, 37):
            progress = ease(step / 36.0)
            moving = dict(initial, left=left_empty, moving20=move(left_row, first_targets[1], progress))
            moving.pop("left", None)
            links = (
                ("root", "middle", 1), ("root", "right", 2),
                ("moving20", "leaf10", 0), ("moving20", "leaf30", 1),
                ("middle", "leaf55", 0), ("middle", "leaf70", 1),
                ("right", "leaf90", 0), ("right", "leaf110", 1),
            )
            moving["left_slot"] = left_empty
            frames.append(draw(moving, links, "左首领 20 回家，和两个子民保持两根线", ghosts={"left_slot": 1.0}))

        # Second beat: the children dock into the leader's two slots.
        for step in range(1, 37):
            progress = ease(step / 36.0)
            moving = dict(initial, left=left_empty,
                          moving20=row(("20",), positions=(first_targets[1],)),
                          moving10=move(initial["leaf10"], first_targets[0], progress),
                          moving30=move(initial["leaf30"], first_targets[2], progress))
            moving.pop("left", None); moving.pop("leaf10", None); moving.pop("leaf30", None)
            moving["left_slot"] = left_empty
            links = (
                ("root", "middle", 1), ("root", "right", 2),
                ("moving20", "moving10", 0), ("moving20", "moving30", 1),
                ("middle", "leaf55", 0), ("middle", "leaf70", 1),
                ("right", "leaf90", 0), ("right", "leaf110", 1),
            )
            frames.append(draw(moving, links, "10 和 30 向 20 的左右槽位靠拢", ghosts={"left_slot": 1.0}))

        merged = row(("10", "20", "30"), positions=first_targets)
        state = {
            "root": root_row, "left_slot": left_empty, "middle": middle_row, "right": right_row,
            "merged": merged, "leaf55": initial["leaf55"], "leaf70": initial["leaf70"],
            "leaf90": initial["leaf90"], "leaf110": initial["leaf110"],
        }
        links = (
            ("root", "middle", 1), ("root", "right", 2),
            ("left_slot", "merged", 0), ("middle", "leaf55", 0), ("middle", "leaf70", 1),
            ("right", "leaf90", 0), ("right", "leaf110", 1),
        )
        frames.extend([draw(state, links, "形成 [10,20,30]")] * 18)
        delete_mark(state, links, "merged", "第二步：删除合并节点里的 10")
        state["merged"] = row(("20", "30"), positions=first_targets[1:])
        frames.extend([draw(state, links, "删除完成，左侧内部节点下溢", ghosts=("left_slot",))] * 20)
        return state

    def first_delete_traditional():
        delete_mark(initial, initial_links, "leaf10", "第一步：直接删除 10")
        empty_leaf = empty(initial["leaf10"])
        state = dict(initial, leaf10=empty_leaf)
        frames.extend([draw(state, initial_links, "左叶下溢，检查兄弟", ghosts=("leaf10",))] * 18)
        targets = cell_slots(first_leaf_point, 2)
        # The separator 20 detaches from the parent; the sibling row stays complete.
        for step in range(1, 37):
            progress = ease(step / 36.0)
            moving = dict(state, left_slot=empty(left_row), moving20=move(left_row, targets[0], progress), moving30=move(initial["leaf30"], targets[1], progress))
            moving.pop("left", None); moving.pop("leaf10", None); moving.pop("leaf30", None)
            links = (
                ("root", "middle", 1), ("root", "right", 2),
                ("middle", "leaf55", 0), ("middle", "leaf70", 1),
                ("right", "leaf90", 0), ("right", "leaf110", 1),
            )
            frames.append(draw(moving, links, "兄弟不够借，分隔键 20 下沉与 30 合并", ghosts={"left_slot": 1.0, "leaf10": 1.0}))
        merged = row(("20", "30"), positions=targets)
        state = {"root": root_row, "left_slot": empty(left_row), "middle": middle_row, "right": right_row,
                 "merged": merged, "leaf55": initial["leaf55"], "leaf70": initial["leaf70"],
                 "leaf90": initial["leaf90"], "leaf110": initial["leaf110"]}
        links = (("root", "left_slot", 0), ("root", "middle", 1), ("root", "right", 2),
                 ("left_slot", "merged", 0), ("middle", "leaf55", 0), ("middle", "leaf70", 1),
                 ("right", "leaf90", 0), ("right", "leaf110", 1))
        frames.extend([draw(state, links, "合并完成，左侧内部节点下溢", ghosts=("left_slot",))] * 18)
        return state

    state = first_delete_traditional() if traditional else first_delete_ours()

    def merge_first_internal(state):
        root50_source = root_row[1][0]
        root80_source = root_row[1][1]
        target_parent = cell_slots(first_parent_point, 2)
        root80_start = row(("80",), positions=(root80_source,))
        moving50_start = row(("50",), positions=(root50_source,))
        moving60_start = state["middle"]
        for step in range(1, 43):
            progress = ease(step / 42.0)
            moving = {
                "root80": move(root80_start, (550.0, 100.0), progress),
                "root50_slot": row((None,), positions=(root50_source,), rim=GLOW_RED),
                "middle_slot": empty(moving60_start),
                "moving50": move(moving50_start, target_parent[0], progress),
                "moving60": move(moving60_start, target_parent[1], progress),
                "right": state["right"], "merged": state["merged"],
                "leaf55": state["leaf55"], "leaf70": state["leaf70"],
                "leaf90": state["leaf90"], "leaf110": state["leaf110"],
            }
            links = (
                ("root80", "right", 1),
                ("moving50", "merged", 0),
                ("moving60", "leaf55", 0), ("moving60", "leaf70", 1),
                ("right", "leaf90", 0), ("right", "leaf110", 1),
            )
            frames.append(draw(moving, links, "上层空缺继续传递，50 和 60 合并", ghosts={"root50_slot": 1.0, "middle_slot": 1.0}))
        parent = row(("50", "60"), positions=target_parent)
        next_state = {
            "root": row(("80",), positions=((550.0, 100.0),)), "parent": parent, "right": state["right"],
            "merged": state["merged"], "leaf55": state["leaf55"], "leaf70": state["leaf70"],
            "leaf90": state["leaf90"], "leaf110": state["leaf110"],
        }
        links = (
            ("root", "parent", 0), ("root", "right", 1),
            ("parent", "merged", 0), ("parent", "leaf55", 1), ("parent", "leaf70", 2),
            ("right", "leaf90", 0), ("right", "leaf110", 1),
        )
        frames.extend([draw(next_state, links, "第一次下溢传到根，根还剩 80")] * 26)
        return next_state, links

    state, links = merge_first_internal(state)

    def second_leaf_merge(state, state_links):
        delete_mark(state, state_links, "leaf90", "第三步：删除 90")
        right_empty = empty(right_row)
        state = dict(state, right=right_empty, leaf90=empty(state["leaf90"]))
        frames.extend([draw(state, state_links, "右叶下溢，右首领 100 准备回家", ghosts=("right", "leaf90"))] * 18)
        targets = cell_slots(second_leaf_point, 3)
        for step in range(1, 37):
            progress = ease(step / 36.0)
            moving = dict(state,
                          moving90=move(initial["leaf90"], targets[0], progress),
                          moving100=move(right_row, targets[1], progress),
                          moving110=move(initial["leaf110"], targets[2], progress))
            moving.pop("leaf90", None); moving.pop("leaf110", None)
            links = (
                ("root", "parent", 0), ("root", "right", 1),
                ("parent", "merged", 0), ("parent", "leaf55", 1), ("parent", "leaf70", 2),
                ("moving100", "moving90", 0), ("moving100", "moving110", 1),
            )
            frames.append(draw(moving, links, "右首领 100 回家，和 90、110 合并", ghosts={"right": 1.0}))
        merged = row(("90", "100", "110"), positions=targets)
        state = dict(state, right=right_empty, right_leaf=merged)
        links = (
            ("root", "parent", 0), ("root", "right", 1),
            ("parent", "merged", 0), ("parent", "leaf55", 1), ("parent", "leaf70", 2),
            ("right", "right_leaf", 0),
        )
        frames.extend([draw(state, links, "形成 [90,100,110]")] * 18)
        delete_mark(state, links, "right_leaf", "第四步：删除合并节点里的 90")
        state["right_leaf"] = row(("100", "110"), positions=targets[1:])
        frames.extend([draw(state, links, "删除完成，右侧内部节点下溢", ghosts=("right",))] * 20)
        return state

    state = second_leaf_merge(state, links)

    # The remaining root leader 80 goes down between [50,60] and [100,110].
    merged_parent_point = (
        sum(point[0] for point in (state["merged"][1][0], state["leaf55"][1][0], state["leaf70"][1][0], state["right_leaf"][1][0])) / 4.0,
        285.0,
    )
    merged_parent_targets = cell_slots(merged_parent_point, 3)
    root80_source = state["root"][1][0]
    for step in range(1, 43):
        progress = ease(step / 42.0)
        moving = {
            "root_gap": empty(state["root"]),
            "moving_parent": move(state["parent"], (merged_parent_point[0] - BTREE_NEON_CELL_W / 2.0, 285.0), progress),
            "moving80": move(row(("80",), positions=(root80_source,)), merged_parent_targets[2], progress),
            "merged": state["merged"], "leaf55": state["leaf55"], "leaf70": state["leaf70"],
            "right_leaf": state["right_leaf"],
        }
        links = (
            ("moving_parent", "merged", 0), ("moving_parent", "leaf55", 1), ("moving_parent", "leaf70", 2),
            ("moving80", "right_leaf", 0),
        )
        frames.append(draw(moving, links, "根的 80 回家，和两侧内部节点合并", ghosts={"root_gap": 1.0}))
    merged_root_row = row(("50", "60", "80"), positions=merged_parent_targets)
    merged_state = {
        "merged_root": merged_root_row, "merged": state["merged"], "leaf55": state["leaf55"],
        "leaf70": state["leaf70"], "right_leaf": state["right_leaf"],
    }
    merged_links = (
        ("merged_root", "merged", 0), ("merged_root", "leaf55", 1),
        ("merged_root", "leaf70", 2), ("merged_root", "right_leaf", 3),
    )
    frames.extend([draw(merged_state, merged_links, "合并完成，根节点变空")] * 18)

    before_children = (state["merged"], state["leaf55"], state["leaf70"], state["right_leaf"])
    after_children = (
        row(("20", "30"), final_leaf_points[0]), row(("55",), final_leaf_points[1]),
        row(("70",), final_leaf_points[2]), row(("100", "110"), final_leaf_points[3]),
    )
    for step in range(1, 37):
        progress = ease(step / 36.0)
        root_now = move(merged_root_row, final_root_point, progress)
        rows = {"root": root_now}
        for index, (source, target) in enumerate(zip(before_children, after_children)):
            rows[f"child{index}"] = move(source, target[1][0] if len(target[1]) == 1 else (
                sum(point[0] for point in target[1]) / len(target[1]), target[1][0][1]
            ), progress)
        links = (("root", "child0", 0), ("root", "child1", 1), ("root", "child2", 2), ("root", "child3", 3))
        frames.append(draw(rows, links, "根收缩，合并节点整体上升成为新根"))
    final = {"root": row(("50", "60", "80"), final_root_point),
             "child0": after_children[0], "child1": after_children[1],
             "child2": after_children[2], "child3": after_children[3]}
    frames.extend([draw(final, (("root", "child0", 0), ("root", "child1", 1), ("root", "child2", 2), ("root", "child3", 3)), "根收缩，第二次下溢也已修复")] * 90)
    return frames


def _btree_case3_frames_verified(width: int, height: int, *, traditional: bool) -> list[str]:
    """Render case three from explicit states and shot-local moving rows."""
    root_point = (550.0, 100.0)
    left_point, middle_point, right_point = (220.0, 285.0), (550.0, 285.0), (880.0, 285.0)
    leaf_points = {
        "10": (140.0, 510.0), "30": (300.0, 510.0), "55": (470.0, 510.0),
        "70": (630.0, 510.0), "90": (800.0, 510.0), "110": (960.0, 510.0),
    }
    first_leaf_point, second_leaf_point = (220.0, 510.0), (880.0, 510.0)
    parent_point = (300.0, 285.0)
    final_root_point = (550.0, 125.0)
    final_children = ((170.0, 380.0), (400.0, 380.0), (700.0, 380.0), (930.0, 380.0))

    def row(keys, center=None, *, positions=None, rim=None):
        return tuple(keys), tuple(positions or cell_slots(center, max(1, len(keys)))), rim

    def translate(node_row, destination, progress):
        points = node_row[1]
        source = (sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points))
        current = lerp_point(source, destination, progress)
        dx, dy = current[0] - source[0], current[1] - source[1]
        return node_row[0], tuple((x + dx, y + dy) for x, y in points), node_row[2]

    def empty(node_row):
        return row((None,), positions=(node_row[1][0],), rim=GLOW_RED)

    def ghost(node_row, opacity=1.0):
        points = node_row[1]
        left = min(point[0] for point in points) - BTREE_NEON_CELL_W / 2.0
        right = max(point[0] for point in points) + BTREE_NEON_CELL_W / 2.0
        top = points[0][1] - BTREE_NEON_CELL_H / 2.0
        return (
            f'<rect x="{left:.1f}" y="{top:.1f}" width="{right - left:.1f}" '
            f'height="{BTREE_NEON_CELL_H:.1f}" rx="9" fill="none" stroke="#94A3B8" '
            f'stroke-width="2.6" stroke-dasharray="9 7" opacity="{opacity:.3f}"/>'
        )

    def child_gap(parent_row, slot):
        keys, points, _rim = parent_row
        if not keys or all(key is None for key in keys):
            return points[0][0], points[0][1] + BTREE_NEON_CELL_H / 2.0
        if slot == 0:
            x = points[0][0] - BTREE_NEON_CELL_W / 2.0
        elif slot == len(keys):
            x = points[-1][0] + BTREE_NEON_CELL_W / 2.0
        else:
            x = (points[slot - 1][0] + points[slot][0]) / 2.0
        return x, points[0][1] + BTREE_NEON_CELL_H / 2.0

    def draw(rows, links=(), caption="", ghosts=(), overlay=""):
        parts = []
        for parent_id, child_id, slot in links:
            parent_row, child_row = rows[parent_id], rows[child_id]
            child_x = sum(point[0] for point in child_row[1]) / len(child_row[1])
            parts.append(btree_neon_edge(
                child_gap(parent_row, slot),
                (child_x, child_row[1][0][1] - BTREE_NEON_CELL_H / 2.0),
            ))
        for row_id, node_row in rows.items():
            if row_id in ghosts:
                opacity = ghosts[row_id] if isinstance(ghosts, dict) else 1.0
                parts.append(ghost(node_row, opacity))
            else:
                parts.append(btree_neon_row_at_positions(node_row[0], node_row[1], rim=node_row[2]))
        if caption:
            parts.append(neon_text(caption, (width / 2.0, height - 58.0), size=22.0, glow=GLOW_BLUE))
        parts.append(overlay)
        return svg("".join(parts), width=width, height=height, color=INK)

    def strike(point, progress):
        return glow_line(
            (point[0] - 22.0, point[1] - 17.0),
            (point[0] - 22.0 + 44.0 * progress, point[1] - 17.0 + 34.0 * progress),
            color=GLOW_RED, width=5.0, bloom=GLOW_RED, radius=0.0,
        )

    initial = {
        "root": row(("50", "80"), root_point),
        "left": row(("20",), left_point), "middle": row(("60",), middle_point),
        "right": row(("100",), right_point),
        "leaf10": row(("10",), leaf_points["10"]), "leaf30": row(("30",), leaf_points["30"]),
        "leaf55": row(("55",), leaf_points["55"]), "leaf70": row(("70",), leaf_points["70"]),
        "leaf90": row(("90",), leaf_points["90"]), "leaf110": row(("110",), leaf_points["110"]),
    }
    initial_links = (
        ("root", "left", 0), ("root", "middle", 1), ("root", "right", 2),
        ("left", "leaf10", 0), ("left", "leaf30", 1),
        ("middle", "leaf55", 0), ("middle", "leaf70", 1),
        ("right", "leaf90", 0), ("right", "leaf110", 1),
    )
    frames = [draw(initial, initial_links, "初始状态：根有左右两个首领")] * 45

    def mark_delete(state, links, node_id, caption):
        point = state[node_id][1][0]
        for step in range(1, 25):
            frames.append(draw(state, links, caption, overlay=strike(point, ease(step / 24.0))))
        frames.extend([draw(state, links, caption, overlay=strike(point, 1.0))] * 8)

    def leader_home(state, leader_id, child_ids, target_point, caption, slot_id, root_links):
        target = cell_slots(target_point, 3)
        leader = state[leader_id]
        moving_ids = (child_ids[0], leader_id, child_ids[1])
        source_rows = (state[child_ids[0]], leader, state[child_ids[1]])
        for step in range(1, 73):
            progress = ease(step / 72.0)
            moving = dict(state)
            for moving_id, source, destination in zip(moving_ids, source_rows, target):
                moving[moving_id] = translate(source, destination, progress)
            moving[slot_id] = empty(state[leader_id])
            for moving_id in moving_ids:
                moving.pop(moving_id if moving_id != leader_id else leader_id, None)
            # Reinsert the three complete moving rows under stable temporary IDs.
            moving["home_left"] = translate(source_rows[0], target[0], progress)
            moving["home_leader"] = translate(source_rows[1], target[1], progress)
            moving["home_right"] = translate(source_rows[2], target[2], progress)
            links = tuple(root_links) + (
                ("home_leader", "home_left", 0), ("home_leader", "home_right", 1),
            )
            frames.append(draw(moving, links, caption, ghosts={slot_id: 1.0}))
        return row((source_rows[0][0][0], source_rows[1][0][0], source_rows[2][0][0]), positions=target)

    if traditional:
        empty10 = empty(initial["leaf10"])
        for step in range(1, 25):
            frames.append(draw(initial, initial_links, "先删除叶节点 10", overlay=strike(initial["leaf10"][1][0], ease(step / 24.0))))
        state = dict(initial, leaf10=empty10)
        frames.extend([draw(state, initial_links, "左叶下溢，检查左右兄弟", ghosts=("leaf10",))] * 24)
        target = cell_slots(first_leaf_point, 2)
        for step in range(1, 73):
            progress = ease(step / 72.0)
            moving = dict(
                state,
                sep=translate(initial["left"], target[0], progress),
                sibling=translate(initial["leaf30"], target[1], progress),
            )
            moving.pop("left", None)
            moving.pop("leaf30", None)
            links = (
                ("root", "middle", 1),
                ("root", "right", 2),
                ("middle", "leaf55", 0),
                ("middle", "leaf70", 1),
                ("right", "leaf90", 0),
                ("right", "leaf110", 1),
            )
            frames.append(
                draw(
                    moving,
                    links,
                    "兄弟不够借，分隔键 20 下沉与 30 合并",
                    ghosts={"leaf10": 1.0, "left": 1.0},
                )
            )
        merged = row(("20", "30"), positions=target)
        state = {"root": row(("50", "80"), root_point), "middle": initial["middle"], "right": initial["right"], "merged": merged, "leaf55": initial["leaf55"], "leaf70": initial["leaf70"], "leaf90": initial["leaf90"], "leaf110": initial["leaf110"]}
    else:
        frames.extend([draw(initial, initial_links, "第一步：左首领 20 脱离原槽位")] * 15)
        merged = leader_home(initial, "left", ("leaf10", "leaf30"), first_leaf_point, "左首领 20 回家，带着左右两个子民", "left_slot", (("root", "middle", 1), ("root", "right", 2)))
        state = {"root": row(("50", "80"), root_point), "middle": initial["middle"], "right": initial["right"], "merged": merged, "leaf55": initial["leaf55"], "leaf70": initial["leaf70"], "leaf90": initial["leaf90"], "leaf110": initial["leaf110"]}
        links = (("root", "middle", 1), ("root", "right", 2), ("middle", "leaf55", 0), ("middle", "leaf70", 1), ("right", "leaf90", 0), ("right", "leaf110", 1))
        frames.extend([draw(state, links, "形成 [10,20,30]")] * 18)
        mark_delete(state, links, "merged", "第二步：删除合并节点里的 10")
        state["merged"] = row(("20", "30"), positions=merged[1][1:])

    # The first internal underflow removes the left root slot and pulls 50 into [50,60].
    root80 = row(("80",), root_point)
    parent_target = cell_slots(parent_point, 2)
    source_parent = row(("50", "60"), positions=(initial["root"][1][0], initial["middle"][1][0]))
    for step in range(1, 73):
        progress = ease(step / 72.0)
        moving = {
            "root80": root80,
            "moving_parent": row(("50", "60"), positions=tuple(lerp_point(source, target, progress) for source, target in zip(source_parent[1], parent_target))),
            "merged": state["merged"], "leaf55": state["leaf55"], "leaf70": state["leaf70"],
            "right": state["right"], "leaf90": state["leaf90"], "leaf110": state["leaf110"],
        }
        links = (("moving_parent", "merged", 0), ("moving_parent", "leaf55", 1), ("moving_parent", "leaf70", 2), ("root80", "right", 1), ("right", "leaf90", 0), ("right", "leaf110", 1))
        frames.append(draw(moving, links, "左侧下溢继续向上，根首领 50 回家"))
    state = {"root": root80, "parent": row(("50", "60"), positions=parent_target), "right": state["right"], "merged": state["merged"], "leaf55": state["leaf55"], "leaf70": state["leaf70"], "leaf90": state["leaf90"], "leaf110": state["leaf110"]}
    links = (("root", "parent", 0), ("root", "right", 1), ("parent", "merged", 0), ("parent", "leaf55", 1), ("parent", "leaf70", 2), ("right", "leaf90", 0), ("right", "leaf110", 1))
    frames.extend([draw(state, links, "第一次下溢传递完成，根只剩 80")] * 24)

    if traditional:
        empty90 = empty(state["leaf90"])
        state = dict(state, leaf90=empty90, right=empty(state["right"]))
        frames.extend([draw(state, links, "第二次删除 90，右叶下溢，检查左兄弟", ghosts=("leaf90", "right"))] * 24)
        right_targets = cell_slots(second_leaf_point, 2)
        for step in range(1, 73):
            progress = ease(step / 72.0)
            moving = dict(state,
                          separator=translate(initial["right"], right_targets[0], progress),
                          sibling=translate(initial["leaf110"], right_targets[1], progress))
            moving.pop("right", None); moving.pop("leaf90", None); moving.pop("leaf110", None)
            links = (("root", "parent", 0), ("parent", "merged", 0), ("parent", "leaf55", 1), ("parent", "leaf70", 2))
            frames.append(draw(moving, links, "兄弟不够借，分隔键 100 下沉与 110 合并", ghosts={"right": 1.0, "leaf90": 1.0}))
        state = dict(state, right_leaf=row(("100", "110"), positions=right_targets))
        state.pop("leaf90", None); state.pop("leaf110", None)
        frames.extend([draw(state, links, "右侧内部节点再次下溢，继续向上合并")] * 20)
        state["right_merged"] = state.pop("right_leaf")
    # The right leader performs the same home operation before deleting 90.
    else:
        frames.extend([draw(state, links, "第三步：右首领 100 准备回家")] * 15)
        right_merged = leader_home(state, "right", ("leaf90", "leaf110"), second_leaf_point, "右首领 100 回家，带着左右两个子民", "right_slot", (("root", "parent", 0),))
        state = {"root": state["root"], "parent": state["parent"], "right_slot": empty(state["right"]), "right_merged": right_merged, "merged": state["merged"], "leaf55": state["leaf55"], "leaf70": state["leaf70"]}
        links = (("root", "parent", 0), ("parent", "merged", 0), ("parent", "leaf55", 1), ("parent", "leaf70", 2))
        frames.extend([draw(state, links, "形成 [90,100,110]")] * 18)
        mark_delete(state, links, "right_merged", "第四步：删除合并节点里的 90")
        state["right_merged"] = row(("100", "110"), positions=right_merged[1][1:])

    # Root contraction: keep the moving rows visible until the four final children dock.
    final_root = row(("50", "60", "80"), final_root_point)
    final_rows = {
        "root": final_root, "child0": row(("20", "30"), final_children[0]), "child1": row(("55",), final_children[1]),
        "child2": row(("70",), final_children[2]), "child3": row(("100", "110"), final_children[3]),
    }
    final_links = (("root", "child0", 0), ("root", "child1", 1), ("root", "child2", 2), ("root", "child3", 3))
    target_root_points = cell_slots(final_root_point, 3)
    target_parent_points = target_root_points[:2]
    target_80_point = target_root_points[2]
    for step in range(1, 73):
        progress = ease(step / 72.0)
        moving = {
            "moving_parent": row(("50", "60"), positions=tuple(
                lerp_point(source, target, progress)
                for source, target in zip(state["parent"][1], target_parent_points)
            )),
            "moving80": translate(state["root"], target_80_point, progress),
            "child0": translate(state["merged"], final_children[0], progress),
            "child1": translate(state["leaf55"], final_children[1], progress),
            "child2": translate(state["leaf70"], final_children[2], progress),
            "child3": translate(state["right_merged"], final_children[3], progress),
        }
        transition_links = (
            ("moving_parent", "child0", 0), ("moving_parent", "child1", 1),
            ("moving_parent", "child2", 2), ("moving80", "child3", 0),
        )
        frames.append(draw(moving, transition_links, "根首领 80 回家，根收缩为 [50,60,80]"))
    frames.extend([draw(final_rows, final_links, "根收缩，第二次下溢也已修复")] * 90)
    return frames


def _btree_case3_frames_final(width: int, height: int, *, traditional: bool) -> list[str]:
    """Render case three from legal states without mixing pre/post-delete trees."""
    root_point = (550.0, 100.0)
    parent_points = {
        "left": (220.0, 285.0),
        "middle": (550.0, 285.0),
        "right": (880.0, 285.0),
    }
    leaf_points = {
        "10": (140.0, 510.0), "30": (300.0, 510.0),
        "55": (470.0, 510.0), "70": (630.0, 510.0),
        "90": (800.0, 510.0), "110": (960.0, 510.0),
    }
    first_merge_point = (260.0, 510.0)
    second_merge_point = (920.0, 510.0)
    final_root_point = (550.0, 125.0)
    final_leaf_points = ((170.0, 380.0), (400.0, 380.0), (700.0, 380.0), (930.0, 380.0))

    Row = tuple[tuple[str | None, ...], tuple[Point, ...], str | None]

    def row(keys: Sequence[str | None], center: Point | None = None, *, positions: Sequence[Point] | None = None, rim: str | None = None) -> Row:
        return tuple(keys), tuple(positions or cell_slots(center, max(1, len(keys)))), rim

    def move_row(node_row: Row, targets: Sequence[Point], progress: float) -> Row:
        points = tuple(lerp_point(source, target, progress) for source, target in zip(node_row[1], targets))
        return node_row[0], points, node_row[2]

    def translate(node_row: Row, target: Point, progress: float) -> Row:
        source = (
            sum(point[0] for point in node_row[1]) / len(node_row[1]),
            sum(point[1] for point in node_row[1]) / len(node_row[1]),
        )
        current = lerp_point(source, target, progress)
        dx, dy = current[0] - source[0], current[1] - source[1]
        return node_row[0], tuple((x + dx, y + dy) for x, y in node_row[1]), node_row[2]

    def ghost(node_row: Row, opacity: float = 1.0) -> str:
        points = node_row[1]
        left = min(point[0] for point in points) - BTREE_NEON_CELL_W / 2.0
        right = max(point[0] for point in points) + BTREE_NEON_CELL_W / 2.0
        top = points[0][1] - BTREE_NEON_CELL_H / 2.0
        return (
            f'<rect x="{left:.1f}" y="{top:.1f}" width="{right - left:.1f}" '
            f'height="{BTREE_NEON_CELL_H:.1f}" rx="9" fill="none" stroke="{GLOW_RED}" '
            f'stroke-width="3.2" stroke-dasharray="9 7" opacity="{opacity:.3f}"/>'
        )

    def outline(node_row: Row, opacity: float = 1.0, slot: int | None = None) -> str:
        points = node_row[1] if slot is None else (node_row[1][slot],)
        left = min(point[0] for point in points) - BTREE_NEON_CELL_W / 2.0 - 5.0
        right = max(point[0] for point in points) + BTREE_NEON_CELL_W / 2.0 + 5.0
        top = points[0][1] - BTREE_NEON_CELL_H / 2.0 - 5.0
        return (
            f'<rect x="{left:.1f}" y="{top:.1f}" width="{right - left:.1f}" '
            f'height="{BTREE_NEON_CELL_H + 10.0:.1f}" rx="9" fill="none" stroke="{GLOW_RED}" '
            f'stroke-width="3.2" stroke-dasharray="9 7" opacity="{opacity:.3f}"/>'
        )

    def child_gap(parent_row: Row, slot: int) -> Point:
        keys, points, _rim = parent_row
        if not keys or all(key is None for key in keys):
            return points[0][0], points[0][1] + BTREE_NEON_CELL_H / 2.0
        if slot == 0:
            x = points[0][0] - BTREE_NEON_CELL_W / 2.0
        elif slot == len(keys):
            x = points[-1][0] + BTREE_NEON_CELL_W / 2.0
        else:
            x = (points[slot - 1][0] + points[slot][0]) / 2.0
        return x, points[0][1] + BTREE_NEON_CELL_H / 2.0

    def draw(rows: Mapping[str, Row], links: Sequence[tuple[str, str, int]] = (), caption: str = "", ghosts: Mapping[str, float] | Sequence[str] = (), outlines: Mapping[str, float] | Sequence[str] = (), outline_slots: Mapping[str, tuple[int, float]] | None = None, overlay: str = "") -> str:
        ghost_map = ghosts if isinstance(ghosts, Mapping) else {row_id: 1.0 for row_id in ghosts}
        outline_map = outlines if isinstance(outlines, Mapping) else {row_id: 1.0 for row_id in outlines}
        outline_slot_map = outline_slots or {}
        parts: list[str] = []
        for parent_id, child_id, slot in links:
            parent_row, child_row = rows[parent_id], rows[child_id]
            child_center = (
                sum(point[0] for point in child_row[1]) / len(child_row[1]),
                sum(point[1] for point in child_row[1]) / len(child_row[1]),
            )
            parts.append(btree_neon_edge(child_gap(parent_row, slot), (child_center[0], child_row[1][0][1] - BTREE_NEON_CELL_H / 2.0)))
        for row_id, node_row in rows.items():
            if row_id in ghost_map:
                parts.append(ghost(node_row, float(ghost_map[row_id])))
            else:
                parts.append(btree_neon_row_at_positions(node_row[0], node_row[1], rim=node_row[2]))
                if row_id in outline_map:
                    parts.append(outline(node_row, float(outline_map[row_id])))
                if row_id in outline_slot_map:
                    slot, opacity = outline_slot_map[row_id]
                    parts.append(outline(node_row, opacity, slot=slot))
        if caption:
            parts.append(neon_text(caption, (width / 2.0, height - 58.0), size=22.0, glow=GLOW_BLUE))
        parts.append(overlay)
        return svg("".join(parts), width=width, height=height, color=INK)

    root = row(("50", "80"), root_point)
    left = row(("20",), parent_points["left"])
    middle = row(("60",), parent_points["middle"])
    right = row(("100",), parent_points["right"])
    leaves = {key: row((key,), point) for key, point in leaf_points.items()}
    initial = {"root": root, "left": left, "middle": middle, "right": right, **leaves}
    initial_links = (
        ("root", "left", 0), ("root", "middle", 1), ("root", "right", 2),
        ("left", "10", 0), ("left", "30", 1),
        ("middle", "55", 0), ("middle", "70", 1),
        ("right", "90", 0), ("right", "110", 1),
    )
    frames: list[str] = [draw(initial, initial_links, "初始状态：根为 [50,80]，左右都有首领")] * 45

    def mark(rows: Mapping[str, Row], links: Sequence[tuple[str, str, int]], node_id: str, caption: str) -> None:
        row_keys = rows[node_id][0]
        slot = row_keys.index(node_id) if node_id in row_keys else None
        for step in range(1, 25):
            progress = ease(step / 24.0)
            if slot is None:
                frames.append(draw(rows, links, caption, outlines={node_id: progress}))
            else:
                frames.append(draw(rows, links, caption, outline_slots={node_id: (slot, progress)}))
        if slot is None:
            frames.extend([draw(rows, links, caption, outlines=(node_id,))] * 8)
        else:
            frames.extend([draw(rows, links, caption, outline_slots={node_id: (slot, 1.0)})] * 8)

    if traditional:
        mark(initial, initial_links, "10", "先删除叶节点 10")
        empty10 = row((None,), positions=leaves["10"][1], rim=GLOW_RED)
        after_delete = dict(initial, **{"10": empty10})
        frames.extend([draw(after_delete, initial_links, "删除 10 后，原位置保留为空节点", ghosts=("10",))] * 30)

        target = cell_slots(first_merge_point, 2)
        for step in range(1, 61):
            progress = ease(step / 60.0)
            moving = dict(after_delete)
            moving["separator"] = translate(left, target[0], progress)
            moving["sibling"] = translate(leaves["30"], target[1], progress)
            moving.pop("left", None)
            moving.pop("30", None)
            moving_links = (
                ("root", "separator", 0), ("separator", "10", 0), ("separator", "sibling", 1),
                ("root", "middle", 1), ("root", "right", 2),
                ("middle", "55", 0), ("middle", "70", 1),
                ("right", "90", 0), ("right", "110", 1),
            )
            frames.append(draw(moving, moving_links, "兄弟不能借，分隔键 20 下沉，与 30 合并", ghosts={"10": 1.0, "left": 1.0}))
        merged_left = row(("20", "30"), positions=target)
        left_slot = row((None,), positions=(parent_points["left"],), rim=GLOW_RED)
        state = {"root": root, "left_slot": left_slot, "middle": middle, "right": right, "merged_left": merged_left, "10": empty10, "55": leaves["55"], "70": leaves["70"], "90": leaves["90"], "110": leaves["110"]}
        links = (("root", "left_slot", 0), ("root", "middle", 1), ("root", "right", 2), ("left_slot", "merged_left", 0), ("left_slot", "10", 1), ("middle", "55", 0), ("middle", "70", 1), ("right", "90", 0), ("right", "110", 1))
        frames.extend([draw(state, links, "合并完成，左侧内部节点下溢，空槽继续保留")] * 24)
    else:
        mark(initial, initial_links, "10", "先删除叶节点 10")
        empty10 = row((None,), positions=leaves["10"][1], rim=GLOW_RED)
        after_delete = dict(initial, **{"10": empty10})
        frames.extend([draw(after_delete, initial_links, "删除 10 后，原位置保留为空节点", ghosts=("10",))] * 30)

        home_targets = (leaves["10"][1][0], cell_slots(first_merge_point, 3)[1], leaves["30"][1][0])
        for step in range(1, 61):
            progress = ease(step / 60.0)
            moving = {key: value for key, value in after_delete.items() if key not in {"left", "30"}}
            moving["home20"] = translate(left, home_targets[1], progress)
            moving["home30"] = translate(leaves["30"], home_targets[2], progress)
            moving["left_slot"] = left
            links = (("root", "home20", 0), ("home20", "10", 0), ("home20", "home30", 1), ("root", "middle", 1), ("root", "right", 2), ("middle", "55", 0), ("middle", "70", 1), ("right", "90", 0), ("right", "110", 1))
            frames.append(draw(moving, links, "删除 10 后，左首领 20 回到空槽，与 30 合并", ghosts={"10": 1.0, "left_slot": 1.0}))
        merged = row(("20", "30"), positions=(home_targets[1], home_targets[2]))
        left_slot = row((None,), positions=left[1], rim=GLOW_RED)
        state = {"root": root, "middle": middle, "right": right, "left_slot": left_slot, "merged": merged, "10": empty10, "55": leaves["55"], "70": leaves["70"], "90": leaves["90"], "110": leaves["110"]}
        links = (("root", "left_slot", 0), ("root", "middle", 1), ("root", "right", 2), ("left_slot", "merged", 0), ("left_slot", "10", 1), ("middle", "55", 0), ("middle", "70", 1), ("right", "90", 0), ("right", "110", 1))
        frames.extend([draw(state, links, "到位后形成 [20,30]，左侧内部槽仍为空")] * 18)

    # Both routes now have the same legal post-first-delete state.
    parent_target = cell_slots((300.0, 285.0), 2)
    if traditional:
        left_child = state["merged_left"]
        child_rows = {"left_child": left_child, "55": state["55"], "70": state["70"]}
    else:
        child_rows = {"left_child": state["merged"], "55": state["55"], "70": state["70"]}
    root50_source = row(("50",), positions=(root[1][0],))
    empty_left_slot = row((None,), positions=(parent_points["left"],), rim=GLOW_RED)
    empty_root50_slot = row((None,), positions=(root[1][0],), rim=GLOW_RED)
    for step in range(1, 61):
        progress = ease(step / 60.0)
        moving = {
            "root80": translate(row(("80",), root[1][1]), root_point, progress),
            "moving50": translate(root50_source, parent_target[0], progress),
            "moving60": translate(middle, parent_target[1], progress),
            "left_slot": empty_left_slot,
            "root50_slot": empty_root50_slot,
            "right": right,
            "90": leaves["90"],
            "110": leaves["110"],
            "10": state["10"],
            "left_slot": state["left_slot"],
            **child_rows,
        }
        moving_links = (
            ("root80", "moving50", 0), ("root80", "right", 1),
            ("moving50", "left_child", 0),
            ("moving60", "55", 0), ("moving60", "70", 1),
        )
        frames.append(draw(moving, moving_links, "左侧内部节点下溢，50 与 60 独立回到同一层" , ghosts={"left_slot": 1.0, "root50_slot": 1.0}))
    state = {"root": row(("80",), root_point), "parent": row(("50", "60"), positions=parent_target), "left_child": child_rows["left_child"], "55": child_rows["55"], "70": child_rows["70"], "right": right, "90": leaves["90"], "110": leaves["110"], "left_slot": empty_left_slot}
    links = (("root", "parent", 0), ("root", "right", 1), ("parent", "left_child", 0), ("parent", "55", 1), ("parent", "70", 2), ("right", "90", 0), ("right", "110", 1))
    frames.extend([draw(state, links, "第一次级联合并完成，根只剩 [80]")] * 24)

    if traditional:
        mark(state, links, "90", "再删除右侧叶节点 90")
        empty90 = row((None,), positions=leaves["90"][1], rim=GLOW_RED)
        after_delete = dict(state, **{"90": empty90, "right": row((None,), positions=right[1], rim=GLOW_RED)})
        frames.extend([draw(after_delete, links, "删除 90 后，原位置保留为空节点", ghosts={"90": 1.0, "right": 1.0})] * 30)
        target = cell_slots(second_merge_point, 2)
        for step in range(1, 61):
            progress = ease(step / 60.0)
            moving = dict(after_delete)
            moving["separator"] = translate(right, target[0], progress)
            moving["sibling"] = translate(leaves["110"], target[1], progress)
            moving.pop("right", None); moving.pop("110", None)
            moving_links = (
                ("root", "parent", 0), ("root", "separator", 1),
                ("separator", "90", 0), ("separator", "sibling", 1),
                ("parent", "left_child", 0), ("parent", "55", 1), ("parent", "70", 2),
            )
            frames.append(draw(moving, moving_links, "兄弟不能借，分隔键 100 下沉，与 110 合并", ghosts={"90": 1.0, "right": 1.0}))
        state["right_child"] = row(("100", "110"), positions=target)
        state["right_slot"] = state.pop("right")
        state["90"] = empty90
        state.pop("110", None)
        links = (("root", "parent", 0), ("root", "right_slot", 1), ("parent", "left_child", 0), ("parent", "55", 1), ("parent", "70", 2), ("right_slot", "right_child", 0), ("right_slot", "90", 1))
        frames.extend([draw(state, links, "右侧内部节点再次下溢，继续向上合并")] * 24)
    else:
        frames.extend([draw(state, links, "目标是 90：先让右首领 100 回家")] * 15)
        home_targets = cell_slots(second_merge_point, 3)
        for step in range(1, 61):
            progress = ease(step / 60.0)
            moving = {key: value for key, value in state.items() if key not in {"right", "110"}}
            moving["home90"] = translate(leaves["90"], home_targets[0], progress)
            moving["home100"] = translate(right, home_targets[1], progress)
            moving["home110"] = translate(leaves["110"], home_targets[2], progress)
            moving["right_slot"] = right
            links = (("root", "parent", 0), ("parent", "left_child", 0), ("parent", "55", 1), ("parent", "70", 2), ("home100", "90", 0), ("home100", "home110", 1))
            frames.append(draw(moving, links, "右首领 100 脱离原槽位，90、100、110 独立回家", ghosts={"right_slot": 1.0}))
        merged = row(("90", "100", "110"), positions=home_targets)
        right_slot = row((None,), positions=right[1], rim=GLOW_RED)
        state = {key: value for key, value in state.items() if key not in {"right", "110"}}
        state["right_slot"] = right_slot
        state["merged_right"] = merged
        links = (("root", "parent", 0), ("root", "right_slot", 1), ("parent", "left_child", 0), ("parent", "55", 1), ("parent", "70", 2), ("right_slot", "merged_right", 0))
        frames.extend([draw(state, links, "到位后形成 [90,100,110]")] * 18)
        mark(state, links, "merged_right", "合并完成后，删除 90")
        state["merged_right"] = row(("100", "110"), positions=home_targets[1:])
        frames.extend([draw(state, links, "删除完成，右侧内部节点下溢")] * 24)

    final_root = row(("50", "60", "80"), final_root_point)
    final_children = {
        "child0": row(("20", "30"), final_leaf_points[0]),
        "child1": row(("55",), final_leaf_points[1]),
        "child2": row(("70",), final_leaf_points[2]),
        "child3": row(("100", "110"), final_leaf_points[3]),
    }
    if traditional:
        right_child = state["right_child"]
    else:
        right_child = state["merged_right"]
    source_parent = state["parent"]
    source_root = state["root"]
    final_root_slots = cell_slots(final_root_point, 3)
    for step in range(1, 73):
        progress = ease(step / 72.0)
        moving = {
            "moving_parent": move_row(source_parent, final_root_slots[:2], progress),
            "moving80": translate(source_root, final_root_slots[2], progress),
            "child0": translate(state["left_child"], final_leaf_points[0], progress),
            "child1": translate(state["55"], final_leaf_points[1], progress),
            "child2": translate(state["70"], final_leaf_points[2], progress),
            "child3": translate(right_child, final_leaf_points[3], progress),
        }
        contraction_links = (
            ("moving80", "moving_parent", 0), ("moving80", "child3", 1),
            ("moving_parent", "child0", 0), ("moving_parent", "child1", 1), ("moving_parent", "child2", 2),
        )
        frames.append(draw(moving, contraction_links, "根首领 80 回家，根收缩为 [50,60,80]", ghosts={"left_slot": 1.0, "10": 1.0, "right_slot": 1.0} if "right_slot" in state else {"left_slot": 1.0, "10": 1.0}))
    final_links = (("root", "child0", 0), ("root", "child1", 1), ("root", "child2", 2), ("root", "child3", 3))
    frames.extend([draw({"root": final_root, **final_children}, final_links, "根收缩完成：四个孩子回到新根下面")] * 90)
    return frames


def _btree_case3_frames_red_legacy(width: int, height: int, *, traditional: bool) -> list[str]:
    """Render case three with persistent red empty slots and connected motion."""
    root_point = (550.0, 100.0)
    parent_points = {"left": (220.0, 285.0), "middle": (550.0, 285.0), "right": (880.0, 285.0)}
    leaf_points = {"10": (140.0, 510.0), "30": (300.0, 510.0), "55": (470.0, 510.0), "70": (630.0, 510.0), "90": (800.0, 510.0), "110": (960.0, 510.0)}
    first_merge = (220.0, 510.0)
    second_merge = (880.0, 510.0)
    final_root = (550.0, 125.0)
    final_leaves = ((170.0, 380.0), (400.0, 380.0), (700.0, 380.0), (930.0, 380.0))
    Row = tuple[tuple[str | None, ...], tuple[Point, ...], str | None]

    def row(keys: Sequence[str | None], center: Point | None = None, *, positions: Sequence[Point] | None = None) -> Row:
        return tuple(keys), tuple(positions or cell_slots(center, max(1, len(keys)))), GLOW_RED if all(key is None for key in keys) else None

    def move(node_row: Row, target: Point, progress: float) -> Row:
        source = (sum(point[0] for point in node_row[1]) / len(node_row[1]), sum(point[1] for point in node_row[1]) / len(node_row[1]))
        current = lerp_point(source, target, progress)
        dx, dy = current[0] - source[0], current[1] - source[1]
        return node_row[0], tuple((x + dx, y + dy) for x, y in node_row[1]), node_row[2]

    def move_slots(node_row: Row, targets: Sequence[Point], progress: float) -> Row:
        return node_row[0], tuple(lerp_point(source, target, progress) for source, target in zip(node_row[1], targets)), node_row[2]

    def empty(node_row: Row) -> Row:
        return tuple(None for _ in node_row[0]), node_row[1], GLOW_RED

    def child_gap(node_row: Row, slot: int) -> Point:
        keys, points, _rim = node_row
        if slot == 0:
            x = points[0][0] - BTREE_NEON_CELL_W / 2.0
        elif slot == len(keys):
            x = points[-1][0] + BTREE_NEON_CELL_W / 2.0
        else:
            x = (points[slot - 1][0] + points[slot][0]) / 2.0
        return x, points[0][1] + BTREE_NEON_CELL_H / 2.0

    def red_frame(node_row: Row, opacity: float = 1.0) -> str:
        left = min(point[0] for point in node_row[1]) - BTREE_NEON_CELL_W / 2.0 - 5.0
        right = max(point[0] for point in node_row[1]) + BTREE_NEON_CELL_W / 2.0 + 5.0
        top = node_row[1][0][1] - BTREE_NEON_CELL_H / 2.0 - 5.0
        return f'<rect x="{left:.1f}" y="{top:.1f}" width="{right - left:.1f}" height="{BTREE_NEON_CELL_H + 10:.1f}" rx="9" fill="none" stroke="{GLOW_RED}" stroke-width="3.2" stroke-dasharray="9 7" opacity="{opacity:.3f}"/>'

    def ghost(node_row: Row, opacity: float = 1.0) -> str:
        left = min(point[0] for point in node_row[1]) - BTREE_NEON_CELL_W / 2.0
        right = max(point[0] for point in node_row[1]) + BTREE_NEON_CELL_W / 2.0
        top = node_row[1][0][1] - BTREE_NEON_CELL_H / 2.0
        return f'<rect x="{left:.1f}" y="{top:.1f}" width="{right - left:.1f}" height="{BTREE_NEON_CELL_H:.1f}" rx="9" fill="none" stroke="{GLOW_RED}" stroke-width="3.2" stroke-dasharray="9 7"/>'

    def draw(rows: Mapping[str, Row], links: Sequence[tuple[str, str, int]], caption: str, *, selected: Mapping[str, float] = (), ghosts: Iterable[str] = ()) -> str:
        selected_map = selected if isinstance(selected, Mapping) else {key: 1.0 for key in selected}
        ghost_set = set(ghosts)
        parts: list[str] = []
        for parent_id, child_id, slot in links:
            if parent_id not in rows or child_id not in rows:
                raise RuntimeError(f"case3 link endpoint missing: {parent_id}->{child_id}")
            parent_row, child_row = rows[parent_id], rows[child_id]
            child_center = (sum(point[0] for point in child_row[1]) / len(child_row[1]), sum(point[1] for point in child_row[1]) / len(child_row[1]))
            parts.append(btree_neon_edge(child_gap(parent_row, slot), (child_center[0], child_row[1][0][1] - BTREE_NEON_CELL_H / 2.0)))
        for row_id, node_row in rows.items():
            if row_id in ghost_set or all(key is None for key in node_row[0]):
                parts.append(ghost(node_row))
            else:
                parts.append(btree_neon_row_at_positions(node_row[0], node_row[1], rim=node_row[2]))
                if row_id in selected_map:
                    parts.append(red_frame(node_row, float(selected_map[row_id])))
        parts.append(neon_text(caption, (width / 2.0, height - 58.0), size=22.0, glow=GLOW_BLUE))
        return svg("".join(parts), width=width, height=height, color=INK)

    root = row(("50", "80"), root_point)
    left = row(("20",), parent_points["left"])
    middle = row(("60",), parent_points["middle"])
    right = row(("100",), parent_points["right"])
    leaves = {key: row((key,), point) for key, point in leaf_points.items()}
    initial = {"root": root, "left": left, "middle": middle, "right": right, **leaves}
    initial_links = (("root", "left", 0), ("root", "middle", 1), ("root", "right", 2), ("left", "10", 0), ("left", "30", 1), ("middle", "55", 0), ("middle", "70", 1), ("right", "90", 0), ("right", "110", 1))
    frames: list[str] = [draw(initial, initial_links, "初始状态：根为 [50,80]，左右都有首领")] * 45

    def select(rows: Mapping[str, Row], links: Sequence[tuple[str, str, int]], node_id: str, caption: str) -> None:
        for step in range(1, 25):
            frames.append(draw(rows, links, caption, selected={node_id: ease(step / 24.0)}))
        frames.extend([draw(rows, links, caption, selected=(node_id,))] * 8)

    empty10 = empty(leaves["10"])
    if traditional:
        select(initial, initial_links, "10", "先删除叶节点 10")
        after_delete = dict(initial, **{"10": empty10})
        frames.extend([draw(after_delete, initial_links, "删除 10 后，原位置保留为空节点", ghosts=("10",))] * 30)
        target = cell_slots(first_merge, 2)
        for step in range(1, 61):
            progress = ease(step / 60.0)
            moving = dict(after_delete)
            moving["separator"] = move(left, target[0], progress)
            moving["sibling"] = move(leaves["30"], target[1], progress)
            moving["10"] = move(empty10, target[0], progress)
            moving["left_slot"] = empty(left)
            moving.pop("left", None); moving.pop("30", None)
            links = (("root", "left_slot", 0), ("separator", "10", 0), ("separator", "sibling", 1), ("root", "middle", 1), ("root", "right", 2), ("middle", "55", 0), ("middle", "70", 1), ("right", "90", 0), ("right", "110", 1))
            frames.append(draw(moving, links, "兄弟不能借，分隔键 20 下沉，与 30 合并", ghosts=("10", "left_slot")))
        merged_left = row(("20", "30"), positions=target)
        state = {"root": root, "left_slot": empty(left), "middle": middle, "right": right, "merged_left": merged_left, "55": leaves["55"], "70": leaves["70"], "90": leaves["90"], "110": leaves["110"]}
        links = (("root", "left_slot", 0), ("left_slot", "merged_left", 0), ("root", "middle", 1), ("root", "right", 2), ("middle", "55", 0), ("middle", "70", 1), ("right", "90", 0), ("right", "110", 1))
        frames.extend([draw(state, links, "合并完成，左侧内部槽继续保留")] * 24)
    else:
        select(initial, initial_links, "10", "先删除叶节点 10")
        after_delete = dict(initial, **{"10": empty10})
        frames.extend([draw(after_delete, initial_links, "删除 10 后，原位置保留为空节点", ghosts=("10",))] * 30)
        target = cell_slots(first_merge, 2)
        for step in range(1, 61):
            progress = ease(step / 60.0)
            moving = dict(after_delete)
            moving["home20"] = move(left, target[0], progress)
            moving["home30"] = move(leaves["30"], target[1], progress)
            moving["10"] = move(empty10, target[0], progress)
            moving["left_slot"] = empty(left)
            moving.pop("left", None); moving.pop("30", None)
            links = (("root", "left_slot", 0), ("home20", "10", 0), ("home20", "home30", 1), ("root", "middle", 1), ("root", "right", 2), ("middle", "55", 0), ("middle", "70", 1), ("right", "90", 0), ("right", "110", 1))
            frames.append(draw(moving, links, "删除 10 后，左首领 20 回到空槽，与 30 合并", ghosts=("10", "left_slot")))
        merged = row(("20", "30"), positions=target)
        state = {"root": root, "left_slot": empty(left), "middle": middle, "right": right, "merged": merged, "55": leaves["55"], "70": leaves["70"], "90": leaves["90"], "110": leaves["110"]}
        links = (("root", "left_slot", 0), ("left_slot", "merged", 0), ("root", "middle", 1), ("root", "right", 2), ("middle", "55", 0), ("middle", "70", 1), ("right", "90", 0), ("right", "110", 1))
        frames.extend([draw(state, links, "到位后形成 [20,30]，空槽继续保留")] * 18)

    child = state["merged_left"] if traditional else state["merged"]
    parent_target = cell_slots((300.0, 285.0), 2)
    empty_left = empty(left)
    moving_state = {"root80": row(("80",), positions=(root[1][1],)), "moving50": move(row(("50",), positions=(root[1][0],)), parent_target[0], 0.0), "moving60": middle, "left_slot": empty_left, "left_child": child, "middle55": state["55"], "middle70": state["70"], "right": right, "90": state["90"], "110": state["110"]}
    for step in range(1, 61):
        progress = ease(step / 60.0)
        moving = dict(moving_state)
        moving["moving50"] = move(row(("50",), positions=(root[1][0],)), parent_target[0], progress)
        moving["moving60"] = move(middle, parent_target[1], progress)
        links = (("root80", "left_slot", 0), ("root80", "right", 1), ("moving50", "left_child", 0), ("moving60", "middle55", 0), ("moving60", "middle70", 1), ("right", "90", 0), ("right", "110", 1))
        frames.append(draw(moving, links, "左侧内部节点下溢，空槽与 60 把 50 拉回同一层", ghosts=("left_slot",)))
    state = {"root": row(("80",), positions=(root[1][1],)), "parent": row(("50", "60"), positions=parent_target), "left_child": child, "55": state["55"], "70": state["70"], "right": right, "90": state["90"], "110": state["110"]}
    links = (("root", "parent", 0), ("root", "right", 1), ("parent", "left_child", 0), ("parent", "55", 1), ("parent", "70", 2), ("right", "90", 0), ("right", "110", 1))
    frames.extend([draw(state, links, "第一次级联合并完成，根只剩 [80]")] * 24)

    if traditional:
        select(state, links, "90", "再删除右侧叶节点 90")
        empty90 = empty(leaves["90"])
        after_delete = dict(state, **{"90": empty90})
        frames.extend([draw(after_delete, links, "删除 90 后，原位置保留为空节点", ghosts=("90",))] * 30)
        target = cell_slots(second_merge, 2)
        for step in range(1, 61):
            progress = ease(step / 60.0)
            moving = dict(after_delete)
            moving["separator"] = move(right, target[0], progress)
            moving["sibling"] = move(leaves["110"], target[1], progress)
            moving["90"] = move(empty90, target[0], progress)
            moving["right_slot"] = empty(right)
            moving.pop("right", None); moving.pop("110", None)
            moving_links = (("root", "right_slot", 1), ("separator", "90", 0), ("separator", "sibling", 1), ("root", "parent", 0), ("parent", "left_child", 0), ("parent", "55", 1), ("parent", "70", 2))
            frames.append(draw(moving, moving_links, "兄弟不能借，分隔键 100 下沉，与 110 合并", ghosts=("90", "right_slot")))
        right_child = row(("100", "110"), positions=target)
        state = {
            "root": state["root"], "parent": state["parent"],
            "left_child": state["left_child"], "55": state["55"], "70": state["70"],
            "right_slot": empty(right), "right_child": right_child,
        }
        links = (("root", "parent", 0), ("root", "right_slot", 1), ("parent", "left_child", 0), ("parent", "55", 1), ("parent", "70", 2))
        frames.extend([draw(state, links, "右侧内部节点再次下溢，空槽继续保留")] * 24)
    else:
        frames.extend([draw(state, links, "目标是 90：先让右首领 100 回家")] * 15)
        select(state, links, "90", "先删除叶节点 90")
        empty90 = empty(leaves["90"])
        after_delete = dict(state, **{"90": empty90})
        frames.extend([draw(after_delete, links, "删除 90 后，原位置保留为空节点", ghosts=("90",))] * 30)
        target = cell_slots(second_merge, 2)
        for step in range(1, 61):
            progress = ease(step / 60.0)
            moving = dict(after_delete)
            moving["home100"] = move(right, target[0], progress)
            moving["home110"] = move(leaves["110"], target[1], progress)
            moving["90"] = move(empty90, target[0], progress)
            moving["right_slot"] = empty(right)
            moving.pop("right", None); moving.pop("110", None)
            moving_links = (("root", "parent", 0), ("root", "right_slot", 1), ("home100", "90", 0), ("home100", "home110", 1), ("parent", "left_child", 0), ("parent", "55", 1), ("parent", "70", 2))
            frames.append(draw(moving, moving_links, "删除 90 后，右首领 100 回到空槽，与 110 合并", ghosts=("90", "right_slot")))
        right_child = row(("100", "110"), positions=target)
        state = {key: value for key, value in state.items() if key not in {"right", "90", "110"}}
        state.update({"right_slot": empty(right), "right_child": right_child})
        links = (("root", "parent", 0), ("root", "right_slot", 1), ("right_slot", "right_child", 0), ("parent", "left_child", 0), ("parent", "55", 1), ("parent", "70", 2))
        frames.extend([draw(state, links, "到位后形成 [100,110]，空槽继续保留")] * 18)

    final_root_row = row(("50", "60", "80"), final_root)
    final_children = {"child0": row(("20", "30"), final_leaves[0]), "child1": row(("55",), final_leaves[1]), "child2": row(("70",), final_leaves[2]), "child3": row(("100", "110"), final_leaves[3])}
    right_child = state["right_child"]
    source_parent, source_root = state["parent"], state["root"]
    final_slots = cell_slots(final_root, 3)
    for step in range(1, 73):
        progress = ease(step / 72.0)
        moving = {"moving_parent": move_slots(source_parent, final_slots[:2], progress), "moving80": move(source_root, final_slots[2], progress), "child0": move(state["left_child"], final_leaves[0], progress), "child1": move(state["55"], final_leaves[1], progress), "child2": move(state["70"], final_leaves[2], progress), "child3": move(right_child, final_leaves[3], progress)}
        ghost_rows = {name: state[name] for name in ("10", "left_slot", "root50_slot", "90", "right_slot") if name in state}
        moving.update(ghost_rows)
        contraction_links = (("moving80", "moving_parent", 0), ("moving80", "child3", 1), ("moving_parent", "child0", 0), ("moving_parent", "child1", 1), ("moving_parent", "child2", 2))
        frames.append(draw(moving, contraction_links, "根首领 80 回家，根收缩为 [50,60,80]", ghosts=ghost_rows))
    final_links = (("root", "child0", 0), ("root", "child1", 1), ("root", "child2", 2), ("root", "child3", 3))
    frames.extend([draw({"root": final_root_row, **final_children}, final_links, "根收缩完成：四个孩子回到新根下面")] * 90)
    return frames


def _btree_case3_frames_semantic(width: int, height: int, *, traditional: bool) -> list[str]:
    """Render case three with underflow marks that follow the unresolved problem."""
    root_point = (550.0, 100.0)
    parent_points = {
        "left": (220.0, 285.0),
        "middle": (550.0, 285.0),
        "right": (880.0, 285.0),
    }
    leaf_points = {
        "10": (140.0, 510.0),
        "30": (300.0, 510.0),
        "55": (470.0, 510.0),
        "70": (630.0, 510.0),
        "90": (800.0, 510.0),
        "110": (960.0, 510.0),
    }
    first_merge = (220.0, 510.0)
    second_merge = (880.0, 510.0)
    parent_merge = (300.0, 285.0)
    final_root = (550.0, 125.0)
    final_leaves = (
        (170.0, 380.0),
        (400.0, 380.0),
        (700.0, 380.0),
        (930.0, 380.0),
    )
    Row = tuple[tuple[str | None, ...], tuple[Point, ...], str | None]

    def row(keys: Sequence[str | None], *, center: Point | None = None, positions: Sequence[Point] | None = None) -> Row:
        points = tuple(positions or cell_slots(center, max(1, len(keys))))
        rim = GLOW_RED if all(key is None for key in keys) else None
        return tuple(keys), points, rim

    def empty(node_row: Row) -> Row:
        return row(tuple(None for _ in node_row[0]), positions=node_row[1])

    def move(node_row: Row, target: Point, progress: float) -> Row:
        source = (
            sum(point[0] for point in node_row[1]) / len(node_row[1]),
            sum(point[1] for point in node_row[1]) / len(node_row[1]),
        )
        current = lerp_point(source, target, progress)
        dx, dy = current[0] - source[0], current[1] - source[1]
        return node_row[0], tuple((x + dx, y + dy) for x, y in node_row[1]), node_row[2]

    def move_slots(node_row: Row, targets: Sequence[Point], progress: float) -> Row:
        return node_row[0], tuple(
            lerp_point(source, target, progress)
            for source, target in zip(node_row[1], targets)
        ), node_row[2]

    def child_gap(node_row: Row, slot: int) -> Point:
        points = node_row[1]
        if slot == 0:
            x = points[0][0] - BTREE_NEON_CELL_W / 2.0
        elif slot == len(points):
            x = points[-1][0] + BTREE_NEON_CELL_W / 2.0
        else:
            x = (points[slot - 1][0] + points[slot][0]) / 2.0
        return x, points[0][1] + BTREE_NEON_CELL_H / 2.0

    def red_frame(node_row: Row, opacity: float = 1.0) -> str:
        left = min(point[0] for point in node_row[1]) - BTREE_NEON_CELL_W / 2.0 - 5.0
        right = max(point[0] for point in node_row[1]) + BTREE_NEON_CELL_W / 2.0 + 5.0
        top = node_row[1][0][1] - BTREE_NEON_CELL_H / 2.0 - 5.0
        return (
            f'<rect x="{left:.1f}" y="{top:.1f}" width="{right - left:.1f}" '
            f'height="{BTREE_NEON_CELL_H + 10:.1f}" rx="9" fill="none" '
            f'stroke="{GLOW_RED}" stroke-width="3.2" stroke-dasharray="9 7" '
            f'opacity="{opacity:.3f}"/>'
        )

    def ghost(node_row: Row, opacity: float = 1.0) -> str:
        left = min(point[0] for point in node_row[1]) - BTREE_NEON_CELL_W / 2.0
        right = max(point[0] for point in node_row[1]) + BTREE_NEON_CELL_W / 2.0
        top = node_row[1][0][1] - BTREE_NEON_CELL_H / 2.0
        return (
            f'<rect x="{left:.1f}" y="{top:.1f}" width="{right - left:.1f}" '
            f'height="{BTREE_NEON_CELL_H:.1f}" rx="9" fill="none" '
            f'stroke="{GLOW_RED}" stroke-width="3.2" stroke-dasharray="9 7" opacity="{opacity:.3f}"/>'
        )

    def draw(
        rows: Mapping[str, Row],
        links: Sequence[tuple[str, str, int] | tuple[str, str, int, float]],
        caption: str,
        *,
        selected: Mapping[str, float] | Iterable[str] = (),
        ghosts: Iterable[str] | Mapping[str, float] = (),
        extra: str = "",
    ) -> str:
        selected_map = selected if isinstance(selected, Mapping) else {key: 1.0 for key in selected}
        ghost_opacity = ghosts if isinstance(ghosts, Mapping) else {key: 1.0 for key in ghosts}
        parts: list[str] = []
        for link in links:
            parent_id, child_id, slot = link[:3]
            opacity = float(link[3]) if len(link) == 4 else 1.0
            if parent_id not in rows or child_id not in rows:
                raise RuntimeError(f"case3 semantic link endpoint missing: {parent_id}->{child_id}")
            parent_row, child_row = rows[parent_id], rows[child_id]
            # An empty red node represents the unresolved vacancy. It can be
            # pulled by an upper node, but it never owns a stale lower edge.
            if all(key is None for key in parent_row[0]):
                continue
            if traditional and all(key is None for key in child_row[0]):
                continue
            child_center = (
                sum(point[0] for point in child_row[1]) / len(child_row[1]),
                sum(point[1] for point in child_row[1]) / len(child_row[1]),
            )
            parts.append(btree_neon_edge(
                child_gap(parent_row, slot),
                (child_center[0], child_row[1][0][1] - BTREE_NEON_CELL_H / 2.0),
                opacity=opacity,
            ))
        parts.append(extra)
        for row_id, node_row in rows.items():
            if row_id in ghost_opacity or all(key is None for key in node_row[0]):
                if traditional:
                    continue
                parts.append(ghost(node_row, float(ghost_opacity.get(row_id, 1.0))))
            else:
                parts.append(btree_neon_row_at_positions(node_row[0], node_row[1], rim=node_row[2]))
                if row_id in selected_map:
                    parts.append(red_frame(node_row, float(selected_map[row_id])))
        parts.append(neon_text(caption, (width / 2.0, height - 58.0), size=22.0, glow=GLOW_BLUE))
        return svg("".join(parts), width=width, height=height, color=INK)

    root = row(("50", "80"), center=root_point)
    left = row(("20",), center=parent_points["left"])
    middle = row(("60",), center=parent_points["middle"])
    right = row(("100",), center=parent_points["right"])
    leaves = {key: row((key,), center=point) for key, point in leaf_points.items()}
    initial = {"root": root, "left": left, "middle": middle, "right": right, **leaves}
    initial_links = (
        ("root", "left", 0), ("root", "middle", 1), ("root", "right", 2),
        ("left", "10", 0), ("left", "30", 1),
        ("middle", "55", 0), ("middle", "70", 1),
        ("right", "90", 0), ("right", "110", 1),
    )
    frames: list[str] = [draw(initial, initial_links, "初始状态：根为 [50,80]，左右都有首领")] * 45

    def select(rows, links, node_id: str, caption: str) -> None:
        if traditional:
            frames.extend([draw(rows, links, caption)] * 32)
            return
        for step in range(1, 25):
            frames.append(draw(rows, links, caption, selected={node_id: ease(step / 24.0)}))
        frames.extend([draw(rows, links, caption, selected=(node_id,))] * 8)

    def select_cell(rows, links, cell_point, caption: str) -> None:
        marker = row(("x",), center=cell_point)
        if traditional:
            frames.extend([draw(rows, links, caption)] * 32)
            return
        for step in range(1, 25):
            frames.append(draw(rows, links, caption, extra=red_frame(marker, ease(step / 24.0))))
        frames.extend([draw(rows, links, caption, extra=red_frame(marker, 1.0))] * 8)

    mid_merge = (550.0, 510.0)
    left_merge = (220.0, 510.0)
    trio_slots = cell_slots(mid_merge, 3)
    pair_mid = (trio_slots[0], trio_slots[1])
    left_trio = cell_slots(left_merge, 3)
    pair_left = (left_trio[1], left_trio[2])
    parent_target = cell_slots(parent_merge, 2)
    root80_row = row(("80",), positions=(root[1][1],))
    empty70 = empty(leaves["70"])

    if traditional:
        select(initial, initial_links, "70", "先删除叶节点 70")
        after_delete = dict(initial, **{"70": empty70})
        frames.extend([draw(after_delete, initial_links, "删除 70 后，检查左右兄弟")] * 30)
        for step in range(1, 61):
            progress = ease(step / 60.0)
            moving = dict(after_delete)
            moving["sep60"] = move(middle, trio_slots[1], progress)
            moving["sibling55"] = move(leaves["55"], trio_slots[0], progress)
            moving.pop("middle", None)
            moving.pop("55", None)
            moving.pop("70", None)
            links = (
                ("root", "sep60", 1),
                ("root", "left", 0), ("root", "right", 2),
                ("left", "10", 0), ("left", "30", 1),
                ("right", "90", 0), ("right", "110", 1),
            )
            frames.append(draw(moving, links, "兄弟不能借，分隔键 60 下沉，与 55 合并"))
        merged_mid = row(("55", "60"), positions=pair_mid)
        state = {
            "root": root, "left": left, "right": right, "merged_mid": merged_mid,
            "10": leaves["10"], "30": leaves["30"],
            "90": leaves["90"], "110": leaves["110"],
        }
        links = (
            ("root", "left", 0), ("root", "right", 2),
            ("left", "10", 0), ("left", "30", 1),
            ("right", "90", 0), ("right", "110", 1),
        )
        frames.extend([draw(state, links, "叶层合并完成，中间内部槽位下溢")] * 18)
        for step in range(1, 61):
            progress = ease(step / 60.0)
            moving = dict(state)
            moving["root80"] = root80_row
            moving["sep50"] = move(row(("50",), positions=(root[1][0],)), parent_target[1], progress)
            moving["sibling20"] = move(left, parent_target[0], progress)
            moving.pop("root", None)
            moving.pop("left", None)
            links = (
                ("root80", "sep50", 0),
                ("root80", "right", 1),
                ("sibling20", "10", 0), ("sibling20", "30", 1),
                ("right", "90", 0), ("right", "110", 1),
            )
            frames.append(draw(moving, links, "内部下溢，分隔键 50 下沉，与 20 合并"))
        state = {
            "root": root80_row, "parent": row(("20", "50"), positions=parent_target),
            "merged_mid": merged_mid,
            "10": leaves["10"], "30": leaves["30"],
            "right": right, "90": leaves["90"], "110": leaves["110"],
        }
        links = (
            ("root", "parent", 0), ("root", "right", 1),
            ("parent", "10", 0), ("parent", "30", 1), ("parent", "merged_mid", 2),
            ("right", "90", 0), ("right", "110", 1),
        )
        frames.extend([draw(state, links, "形成 [20,50]，根变为 [80]")] * 24)
        select(state, links, "10", "再删除叶节点 10")
        after10 = dict(state, **{"10": empty(leaves["10"])})
        frames.extend([draw(after10, links, "删除 10 后，检查左右兄弟")] * 30)
        parent50_row = row(("50",), positions=(parent_target[1],))
        for step in range(1, 61):
            progress = ease(step / 60.0)
            moving = dict(after10)
            moving["parent50"] = parent50_row
            moving["sep20"] = move(row(("20",), positions=(parent_target[0],)), left_trio[1], progress)
            moving["sibling30"] = move(leaves["30"], left_trio[2], progress)
            moving.pop("parent", None)
            moving.pop("10", None)
            moving.pop("30", None)
            links = (
                ("root", "parent50", 0), ("root", "right", 1),
                ("parent50", "sep20", 0), ("parent50", "merged_mid", 1),
                ("right", "90", 0), ("right", "110", 1),
            )
            frames.append(draw(moving, links, "兄弟不能借，分隔键 20 下沉，与 30 合并"))
        state = {
            "root": root80_row, "parent": parent50_row,
            "final_left": row(("20", "30"), positions=pair_left),
            "merged_mid": merged_mid,
            "right": right, "90": leaves["90"], "110": leaves["110"],
        }
        links = (
            ("root", "parent", 0), ("root", "right", 1),
            ("parent", "final_left", 0), ("parent", "merged_mid", 1),
            ("right", "90", 0), ("right", "110", 1),
        )
        frames.extend([draw(state, links, "分隔键下沉完成，树恢复平衡")] * 90)
        return frames

    frames.extend([draw(initial, initial_links, "目标是 70：先让首领 60 回家")] * 15)
    select(initial, initial_links, "70", "先描边叶节点 70")
    for step in range(1, 61):
        progress = ease(step / 60.0)
        moving = dict(initial)
        moving["home60"] = move(middle, trio_slots[1], progress)
        moving["home55"] = move(leaves["55"], trio_slots[0], progress)
        moving["home70"] = move(leaves["70"], trio_slots[2], progress)
        moving["middle_slot"] = empty(middle)
        moving.pop("middle", None)
        moving.pop("55", None)
        moving.pop("70", None)
        links = (
            ("root", "left", 0), ("root", "middle_slot", 1), ("root", "right", 2),
            ("home60", "home55", 0), ("home60", "home70", 1),
            ("left", "10", 0), ("left", "30", 1),
            ("right", "90", 0), ("right", "110", 1),
        )
        frames.append(draw(moving, links, "首领 60 回家，55、70 完整跟随"))
    trio = row(("55", "60", "70"), positions=trio_slots)
    state = {
        "root": root, "left": left, "middle_slot": empty(middle), "right": right,
        "trio": trio, "10": leaves["10"], "30": leaves["30"],
        "90": leaves["90"], "110": leaves["110"],
    }
    links = (
        ("root", "left", 0), ("root", "middle_slot", 1), ("root", "right", 2),
        ("left", "10", 0), ("left", "30", 1),
        ("right", "90", 0), ("right", "110", 1),
    )
    frames.extend([draw(state, links, "首领 60 回家，与 55、70 合并")] * 18)
    select_cell(state, links, trio_slots[2], "删除 70")
    merged_mid = row(("55", "60"), positions=pair_mid)
    state = {
        "root": root, "left": left, "middle_slot": empty(middle), "right": right,
        "trio": merged_mid, "10": leaves["10"], "30": leaves["30"],
        "90": leaves["90"], "110": leaves["110"],
    }
    frames.extend([draw(state, links, "删除 70，[60] 原槽位下溢")] * 18)
    root50_slot = row((None,), positions=(root[1][0],))
    for step in range(1, 61):
        progress = ease(step / 60.0)
        moving = dict(state)
        moving["root80"] = root80_row
        moving["root50_slot"] = root50_slot
        moving["moving50"] = move(row(("50",), positions=(root[1][0],)), parent_target[1], progress)
        moving["moving20"] = move(left, parent_target[0], progress)
        moving["middle_slot"] = move(empty(middle), parent_target[1], progress)
        moving.pop("root", None)
        moving.pop("left", None)
        links = (
            ("root80", "right", 1),
            ("moving50", "middle_slot", 0),
            ("moving20", "moving50", 0),
            ("moving20", "10", 0), ("moving20", "30", 1),
            ("right", "90", 0), ("right", "110", 1),
        )
        frames.append(draw(moving, links, "空槽与 20 把 50 拉回同一层"))
    state = {
        "root": root80_row, "parent": row(("20", "50"), positions=parent_target),
        "merged_mid": merged_mid,
        "10": leaves["10"], "30": leaves["30"],
        "right": right, "90": leaves["90"], "110": leaves["110"],
    }
    links = (
        ("root", "parent", 0), ("root", "right", 1),
        ("parent", "10", 0), ("parent", "30", 1), ("parent", "merged_mid", 2),
        ("right", "90", 0), ("right", "110", 1),
    )
    frames.extend([draw(state, links, "首领 50 到位，形成 [20,50]，空槽解决")] * 18)
    frames.extend([draw(state, links, "目标是 10：先让首领 20 回家")] * 15)
    select(state, links, "10", "先描边叶节点 10")
    parent50_row = row(("50",), positions=(parent_target[1],))
    for step in range(1, 61):
        progress = ease(step / 60.0)
        moving = dict(state)
        moving["parent50"] = parent50_row
        moving["home20"] = move(row(("20",), positions=(parent_target[0],)), left_trio[1], progress)
        moving["home10"] = move(leaves["10"], left_trio[0], progress)
        moving["home30"] = move(leaves["30"], left_trio[2], progress)
        moving.pop("parent", None)
        moving.pop("10", None)
        moving.pop("30", None)
        links = (
            ("root", "parent50", 0), ("root", "right", 1),
            ("parent50", "merged_mid", 1),
            ("home20", "home10", 0), ("home20", "home30", 1),
            ("right", "90", 0), ("right", "110", 1),
        )
        frames.append(draw(moving, links, "首领 20 回家，10、30 完整跟随"))
    trio_left_row = row(("10", "20", "30"), positions=left_trio)
    state = {
        "root": root80_row, "parent": parent50_row,
        "trio_left": trio_left_row, "merged_mid": merged_mid,
        "right": right, "90": leaves["90"], "110": leaves["110"],
    }
    links = (
        ("root", "parent", 0), ("root", "right", 1),
        ("parent", "trio_left", 0), ("parent", "merged_mid", 1),
        ("right", "90", 0), ("right", "110", 1),
    )
    frames.extend([draw(state, links, "首领 20 回家，与 10、30 合并")] * 18)
    select_cell(state, links, left_trio[0], "删除 10")
    state = {
        "root": root80_row, "parent": parent50_row,
        "trio_left": row(("20", "30"), positions=pair_left),
        "merged_mid": merged_mid,
        "right": right, "90": leaves["90"], "110": leaves["110"],
    }
    frames.extend([draw(state, links, "删除 10，首领回家完成，树始终合法")] * 90)
    return frames


def btree_case3_compare() -> None:
    """Play two deletions so both left/right leaders and root underflow are visible."""
    width, height = 1100, 660
    frames = btree_side_by_side_frames(
        _btree_case3_frames_semantic(width, height, traditional=False),
        _btree_case3_frames_semantic(width, height, traditional=True),
        panel_width=width,
        height=height,
        left_title="我们的方法",
        right_title="传统方法",
    )
    render_webm("btree-case3-compare", frames, fps=24, transparent=True, crop_pad=60)


def btree_delete_complex_broken() -> None:
    """Top-down deletion: make each target child safe before descending."""
    width, height = 1300, 700

    def positions(groups: Mapping[str, tuple[Sequence[str], Point]]) -> dict[str, Point]:
        return {
            key: point
            for members, center in groups.values()
            for key, point in zip(members, cell_slots(center, len(members)))
        }

    def render(
        groups: Mapping[str, tuple[Sequence[str], Point]],
        edges: Sequence[tuple[str, str]],
        *,
        strike: str | None = None,
        moved: Mapping[str, Point] | None = None,
    ) -> str:
        pos = positions(groups)
        if moved:
            pos.update(moved)
        parts: list[str] = []
        for parent, child in edges:
            parent_members, parent_center = groups[parent]
            child_members, child_center = groups[child]
            parent_points = [pos[key] for key in parent_members]
            child_points = [pos[key] for key in child_members]
            parent_x = sum(point[0] for point in parent_points) / len(parent_points)
            child_x = sum(point[0] for point in child_points) / len(child_points)
            parts.append(btree_neon_edge(
                (parent_x, parent_center[1] + CELL_H / 2.0),
                (child_x, child_center[1] - CELL_H / 2.0),
            ))
        for members, _center in groups.values():
            parts.append(btree_neon_row_at_positions(members, [pos[key] for key in members]))
        if strike is not None:
            point = pos[strike]
            parts.append(glow_line(
                (point[0] - 22.0, point[1] - 17.0),
                (point[0] + 22.0, point[1] + 17.0),
                color=GLOW_RED,
                width=5.0,
                bloom=GLOW_RED,
                radius=0.0,
            ))
        return svg("".join(parts), width=width, height=height, color=INK)

    def delete_step(
        frames: list[str],
        before_groups: Mapping[str, tuple[Sequence[str], Point]],
        after_groups: Mapping[str, tuple[Sequence[str], Point]],
        before_edges: Sequence[tuple[str, str]],
        after_edges: Sequence[tuple[str, str]],
        deleted: str,
        *,
        setup_groups: Mapping[str, tuple[Sequence[str], Point]] | None = None,
        setup_edges: Sequence[tuple[str, str]] | None = None,
    ) -> None:
        if setup_groups is not None:
            frames.extend([render(setup_groups, setup_edges or before_edges)] * 10)
            before_groups = setup_groups
            before_edges = setup_edges or before_edges
        frames.extend([render(before_groups, before_edges)] * 10)
        for _ in range(18):
            frames.append(render(before_groups, before_edges, strike=deleted))
        before_pos = positions(before_groups)
        after_pos = positions(after_groups)
        shared = set(before_pos) & set(after_pos)
        for step in range(1, 31):
            progress = ease(step / 30.0)
            moved = {
                key: lerp_point(before_pos[key], after_pos[key], progress)
                for key in shared
                if key != deleted
            }
            frames.append(render(after_groups, after_edges, moved=moved))
        frames.extend([render(after_groups, after_edges)] * 12)

    root = (650.0, 80.0)
    a, b, c = (230.0, 270.0), (650.0, 270.0), (1060.0, 270.0)
    a1, a2, a3 = (100.0, 480.0), (230.0, 480.0), (360.0, 480.0)
    b1, b2, b3 = (530.0, 480.0), (650.0, 480.0), (770.0, 480.0)
    c1, c2, c3 = (930.0, 480.0), (1060.0, 480.0), (1190.0, 480.0)
    edges = (
        ("root", "a"), ("root", "b"), ("root", "c"),
        ("a", "a1"), ("a", "a2"), ("a", "a3"),
        ("b", "b1"), ("b", "b2"), ("b", "b3"),
        ("c", "c1"), ("c", "c2"), ("c", "c3"),
    )
    groups = {
        "root": (("60", "120"), root),
        "a": (("20", "40"), a), "b": (("90", "100"), b), "c": (("150", "170"), c),
        "a1": (("5", "10"), a1), "a2": (("25", "30"), a2), "a3": (("45", "50"), a3),
        "b1": (("65", "70"), b1), "b2": (("95", "110"), b2), "b3": (("115", "118"), b3),
        "c1": (("130", "140"), c1), "c2": (("155", "160"), c2), "c3": (("175", "180"), c3),
    }
    frames: list[str] = []
    frames.extend([render(groups, edges)] * 24)

    # 1. The target leaf is already safe: descend, then delete 10.
    g1 = {**groups, "a1": (("5",), a1)}
    delete_step(frames, groups, g1, edges, edges, "10")

    # 2. Target a2 is a 2-node, sibling a1 has an extra key: borrow before descending.
    borrow_a = {**g1, "a": (("30", "40"), a), "a1": (("5", "20"), a1), "a2": (("25",), a2)}
    delete_step(frames, g1, borrow_a, edges, edges, "25")

    # 3. Target a3 is a 2-node and both adjacent children are minimal: merge before descending.
    merged_a = {
        **borrow_a,
        "a": (("30",), a),
        "a2": (("25", "40", "45", "50"), (300.0, 480.0)),
        "a3": ((), a3),
    }
    merged_a_edges = tuple(edge for edge in edges if edge not in (("a", "a3"),))
    delete_step(frames, borrow_a, merged_a, edges, merged_a_edges, "45")

    # 4. The right branch repeats the top-down choice: borrow, then descend.
    borrow_b = {
        **merged_a,
        "b": (("90", "100"), b), "b1": (("65", "80"), b1), "b2": (("95",), b2),
    }
    delete_step(frames, merged_a, borrow_b, merged_a_edges, merged_a_edges, "95")

    # 5. A deeper target is made safe by merging before the descent.
    merged_b = {
        **borrow_b,
        "b": (("90",), b), "b2": (("80", "100", "110", "115"), (710.0, 480.0)), "b3": ((), b3),
    }
    merged_b_edges = tuple(edge for edge in merged_a_edges if edge not in (("b", "b3"),))
    delete_step(frames, borrow_b, merged_b, merged_a_edges, merged_b_edges, "110")

    # 6. Direct leaf deletion after the previous repair.
    direct = {**merged_b, "c1": (("130",), c1)}
    delete_step(frames, merged_b, direct, merged_b_edges, merged_b_edges, "140")

    # 7. Borrow on the right branch before descending again.
    borrow_c = {**direct, "c": (("150", "160"), c), "c1": (("130", "145"), c1), "c2": (("155",), c2)}
    delete_step(frames, direct, borrow_c, merged_b_edges, merged_b_edges, "155")

    # 8. Internal target: prepare the child first, then remove 90 from the safe node.
    internal_safe = {**borrow_c, "b": (("100",), b), "b2": (("80", "90", "100", "115"), (710.0, 480.0))}
    delete_step(frames, borrow_c, internal_safe, merged_b_edges, merged_b_edges, "90")

    frames.extend([render(internal_safe, merged_b_edges)] * 90)
    render_webm("btree-delete-complex", frames, fps=30, transparent=True)


def btree_delete_complex_algorithm_old() -> None:
    """Use the top-down deletion invariant on a three-level order-4 tree."""
    width, height = 1300, 700

    def positions(groups: Mapping[str, tuple[Sequence[str], Point]]) -> dict[str, Point]:
        return {
            key: point
            for members, center in groups.values()
            for key, point in zip(members, cell_slots(center, len(members)))
        }

    def render(
        groups: Mapping[str, tuple[Sequence[str], Point]],
        edges: Sequence[tuple[str, str]],
        *,
        moved: Mapping[str, Point] | None = None,
        strike: str | None = None,
    ) -> str:
        pos = positions(groups)
        if moved:
            pos.update(moved)
        parts: list[str] = []
        for parent, child in edges:
            parent_members, parent_center = groups[parent]
            child_members, child_center = groups[child]
            parent_points = [pos[key] for key in parent_members]
            child_points = [pos[key] for key in child_members]
            parent_x = sum(point[0] for point in parent_points) / len(parent_points)
            child_x = sum(point[0] for point in child_points) / len(child_points)
            parts.append(btree_neon_edge(
                (parent_x, parent_center[1] + CELL_H / 2.0),
                (child_x, child_center[1] - CELL_H / 2.0),
            ))
        for members, _center in groups.values():
            parts.append(btree_neon_row_at_positions(members, [pos[key] for key in members]))
        if strike is not None:
            point = pos[strike]
            parts.append(glow_line(
                (point[0] - 22.0, point[1] - 17.0),
                (point[0] + 22.0, point[1] + 17.0),
                color=GLOW_RED,
                width=5.0,
                bloom=GLOW_RED,
                radius=0.0,
            ))
        return svg("".join(parts), width=width, height=height, color=INK)

    def animate_to(
        frames: list[str],
        before_groups: Mapping[str, tuple[Sequence[str], Point]],
        before_edges: Sequence[tuple[str, str]],
        after_groups: Mapping[str, tuple[Sequence[str], Point]],
        after_edges: Sequence[tuple[str, str]],
    ) -> None:
        before_pos = positions(before_groups)
        after_pos = positions(after_groups)
        shared = set(before_pos) & set(after_pos)
        for step in range(1, 31):
            progress = ease(step / 30.0)
            moved = {
                key: lerp_point(before_pos[key], after_pos[key], progress)
                for key in shared
            }
            frames.append(render(after_groups, after_edges, moved=moved))

    def delete_after_prepare(
        frames: list[str],
        prepared_groups: Mapping[str, tuple[Sequence[str], Point]],
        prepared_edges: Sequence[tuple[str, str]],
        after_groups: Mapping[str, tuple[Sequence[str], Point]],
        after_edges: Sequence[tuple[str, str]],
        deleted: str,
    ) -> None:
        frames.extend([render(prepared_groups, prepared_edges)] * 14)
        frames.extend([render(prepared_groups, prepared_edges, strike=deleted)] * 18)
        animate_to(frames, prepared_groups, prepared_edges, after_groups, after_edges)
        frames.extend([render(after_groups, after_edges)] * 12)

    root = (650.0, 80.0)
    a, b, c = (230.0, 270.0), (650.0, 270.0), (1060.0, 270.0)
    a1, a2, a3 = (100.0, 480.0), (230.0, 480.0), (360.0, 480.0)
    b1, b2 = (530.0, 480.0), (770.0, 480.0)
    c1, c2, c3 = (930.0, 480.0), (1060.0, 480.0), (1190.0, 480.0)
    tree_edges = (
        ("root", "a"), ("root", "b"), ("root", "c"),
        ("a", "a1"), ("a", "a2"), ("a", "a3"),
        ("b", "b1"), ("b", "b2"), ("c", "c1"), ("c", "c2"), ("c", "c3"),
    )
    groups = {
        "root": (("60", "120"), root),
        "a": (("20", "40"), a), "b": (("90",), b), "c": (("150", "170"), c),
        "a1": (("5", "10"), a1), "a2": (("25",), a2), "a3": (("45", "50"), a3),
        "b1": (("65", "70"), b1), "b2": (("100", "110"), b2),
        "c1": (("130",), c1), "c2": (("155", "160"), c2), "c3": (("175", "180"), c3),
    }
    frames: list[str] = [render(groups, tree_edges)] * 24

    # 1. The target leaf is safe: descend, then remove 5.
    s1 = {**groups, "a1": (("10",), a1)}
    delete_after_prepare(frames, groups, tree_edges, s1, tree_edges, "5")

    # 2. Target a1 is now minimal; merge it with a2 through separator 20 first.
    merge_a = {
        "root": groups["root"], "a": (("40",), a), "b": groups["b"], "c": groups["c"],
        "am": (("10", "20", "25"), (180.0, 480.0)), "a3": groups["a3"],
        "b1": groups["b1"], "b2": groups["b2"], "c1": groups["c1"], "c2": groups["c2"], "c3": groups["c3"],
    }
    merge_a_edges = (
        ("root", "a"), ("root", "b"), ("root", "c"), ("a", "am"), ("a", "a3"),
        ("b", "b1"), ("b", "b2"), ("c", "c1"), ("c", "c2"), ("c", "c3"),
    )
    after_merge_a = {**merge_a, "am": (("20", "25"), (180.0, 480.0))}
    delete_after_prepare(frames, merge_a, merge_a_edges, after_merge_a, merge_a_edges, "10")

    # 3. a3 is safe: remove 45 directly.
    s3 = {**after_merge_a, "a3": (("50",), a3)}
    delete_after_prepare(frames, after_merge_a, merge_a_edges, s3, merge_a_edges, "45")

    # 4. a3 is minimal; borrow from am before descending to remove 50.
    borrow_a = {
        **s3, "a": (("25",), a), "am": (("20",), (180.0, 480.0)), "a3": (("40", "50"), a3),
    }
    delete_after_prepare(frames, s3, merge_a_edges, borrow_a, merge_a_edges, "50")

    # 5. b1 is safe: remove 65 directly.
    s5 = {**borrow_a, "b1": (("70",), b1)}
    delete_after_prepare(frames, borrow_a, merge_a_edges, s5, merge_a_edges, "65")

    # 6. b1 is minimal; borrow from b2 before descending to remove 70.
    borrow_b = {
        **s5, "b": (("100",), b), "b1": (("70", "90"), b1), "b2": (("110",), b2),
    }
    delete_after_prepare(frames, s5, merge_a_edges, borrow_b, merge_a_edges, "70")

    # 7. Before entering minimal internal node b, borrow from c at the root.
    root_borrow = {
        **borrow_b,
        "root": (("60", "150"), root), "b": (("100", "120"), b), "c": (("170",), c),
        "b3": (("130",), (890.0, 480.0)), "c2": groups["c2"], "c3": groups["c3"],
    }
    root_borrow_edges = (
        ("root", "a"), ("root", "b"), ("root", "c"),
        ("a", "am"), ("a", "a3"), ("b", "b1"), ("b", "b2"), ("b", "b3"),
        ("c", "c2"), ("c", "c3"),
    )
    # The middle child b2 is now minimal; merge it with b3 through separator 120.
    merge_b = {
        **root_borrow, "b": (("100",), b), "bm": (("110", "120", "130"), (820.0, 480.0)),
    }
    merge_b_edges = (
        ("root", "a"), ("root", "b"), ("root", "c"),
        ("a", "am"), ("a", "a3"), ("b", "b1"), ("b", "bm"),
        ("c", "c2"), ("c", "c3"),
    )
    after_merge_b = {**merge_b, "bm": (("120", "130"), (820.0, 480.0))}
    delete_after_prepare(frames, root_borrow, root_borrow_edges, merge_b, merge_b_edges, "110")
    frames.extend([render(after_merge_b, merge_b_edges)] * 12)

    # 8. c2 is safe: remove 155 directly.
    final = {**after_merge_b, "c2": (("160",), c2)}
    delete_after_prepare(frames, after_merge_b, merge_b_edges, final, merge_b_edges, "155")
    frames.extend([render(final, merge_b_edges)] * 90)
    render_webm("btree-delete-complex", frames, fps=30, transparent=True)


def btree_delete_complex_legacy() -> None:
    """Generate a three-level deletion lesson directly from the top-down algorithm."""
    from dataclasses import dataclass, field

    @dataclass
    class BNode:
        keys: list[int] = field(default_factory=list)
        children: list["BNode"] = field(default_factory=list)
        node_id: int = 0

        @property
        def leaf(self) -> bool:
            return not self.children

    @dataclass
    class VisualEvent:
        before: BNode
        after: BNode
        kind: str
        key: int | None = None
        pivot: int | None = None
        donor: int | None = None
        replacement: int | None = None
        orange_key: int | None = None
        target_node_id: int | None = None
        target_index: int | None = None
        replacement_node_id: int | None = None
        replacement_index: int | None = None
        orange_keys: tuple[int, ...] = ()
        parent_id: int | None = None
        left_id: int | None = None
        right_id: int | None = None
        pivot_index: int | None = None
        promoted: int | None = None

    def clone(node: BNode) -> BNode:
        return BNode(node.keys[:], [clone(child) for child in node.children], node.node_id)

    def split_child(parent: BNode, index: int) -> None:
        child = parent.children[index]
        middle = child.keys[1]
        right = BNode([child.keys[2]], child.children[2:] if child.children else [])
        child.keys = child.keys[:1]
        child.children = child.children[:2] if child.children else []
        parent.keys.insert(index, middle)
        parent.children.insert(index + 1, right)

    def insert(root: BNode | None, key: int) -> BNode:
        if root is None:
            return BNode([key])
        if len(root.keys) == 3:
            new_root = BNode([], [root])
            split_child(new_root, 0)
            root = new_root
        node = root
        while not node.leaf:
            index = 0
            while index < len(node.keys) and key > node.keys[index]:
                index += 1
            if len(node.children[index].keys) == 3:
                split_child(node, index)
                if key > node.keys[index]:
                    index += 1
            node = node.children[index]
        node.keys.append(key)
        node.keys.sort()
        return root

    def leaf_keys(node: BNode) -> list[int]:
        if node.leaf:
            return node.keys[:]
        return [key for child in node.children for key in leaf_keys(child)]

    # Keep the example genuinely three levels deep: root, internal nodes, leaves.
    # This is the fixed state from which the top-down deletion sequence starts.
    root: BNode | None = BNode(
        [80],
        [
            BNode(
                [40, 60],
                [BNode([10, 20, 30]), BNode([50]), BNode([70])],
            ),
            BNode(
                [120, 160],
                [BNode([90]), BNode([130]), BNode([170, 180])],
            ),
        ],
    )

    next_node_id = 1

    def assign_ids(node: BNode) -> None:
        nonlocal next_node_id
        node.node_id = next_node_id
        next_node_id += 1
        for child in node.children:
            assign_ids(child)

    assign_ids(root)

    events: list[VisualEvent] = []

    def snapshot() -> BNode:
        assert root is not None
        if not root.keys and root.children:
            return clone(root.children[0])
        return clone(root)

    def record(
        kind: str,
        before: BNode,
        *,
        key: int | None = None,
        pivot: int | None = None,
        donor: int | None = None,
        replacement: int | None = None,
        orange_key: int | None = None,
        target_node_id: int | None = None,
        target_index: int | None = None,
        replacement_node_id: int | None = None,
        replacement_index: int | None = None,
        orange_keys: Sequence[int] = (),
        parent_id: int | None = None,
        left_id: int | None = None,
        right_id: int | None = None,
        pivot_index: int | None = None,
        promoted: int | None = None,
    ) -> None:
        events.append(
            VisualEvent(
                before,
                snapshot(),
                kind,
                key=key,
                pivot=pivot,
                donor=donor,
                replacement=replacement,
                orange_key=orange_key,
                target_node_id=target_node_id,
                target_index=target_index,
                replacement_node_id=replacement_node_id,
                replacement_index=replacement_index,
                orange_keys=tuple(orange_keys),
                parent_id=parent_id,
                left_id=left_id,
                right_id=right_id,
                pivot_index=pivot_index,
                promoted=promoted,
            )
        )

    assert root is not None
    target = root
    successor = root.children[1].children[0]
    before = snapshot()
    target.keys[0], successor.keys[0] = successor.keys[0], target.keys[0]
    record(
        "replace",
        before,
        key=80,
        replacement=90,
        target_node_id=target.node_id,
        target_index=0,
        replacement_node_id=successor.node_id,
        replacement_index=0,
        orange_keys=(80, 90),
    )

    def find_leaf_parent(
        node: BNode,
        key: int,
        parent: BNode | None = None,
        child_index: int = -1,
    ) -> tuple[BNode, BNode, int]:
        if node.leaf:
            if key in node.keys:
                assert parent is not None
                return node, parent, child_index
            raise KeyError(key)
        for index, child in enumerate(node.children):
            try:
                return find_leaf_parent(child, key, node, index)
            except KeyError:
                continue
        raise KeyError(key)

    def delete_leaf(
        key: int,
        *,
        sibling_side: str,
        orange_keys: Sequence[int] = (),
    ) -> None:
        leaf, parent, child_index = find_leaf_parent(root, key)
        assert sibling_side in ("left", "right")
        if sibling_side == "right":
            assert child_index + 1 < len(parent.children)
            sibling_index = child_index + 1
            pivot_index = child_index
        else:
            assert child_index > 0
            sibling_index = child_index - 1
            pivot_index = child_index - 1
        target = parent.children[child_index]
        sibling = parent.children[sibling_index]
        assert target.leaf and sibling.leaf
        pivot = parent.keys[pivot_index]
        before = snapshot()
        assert key in target.keys
        target.keys = sorted([pivot, *target.keys])
        donor: int | None = None
        if len(sibling.keys) > 1:
            donor = sibling.keys.pop(0) if sibling_side == "right" else sibling.keys.pop()
            parent.keys[pivot_index] = donor
            target.keys.remove(key)
        else:
            target.keys = [
                item
                for item in target.keys
                if item != key
            ]
            target.keys.extend([*sibling.keys])
            target.keys.sort()
            parent.keys.pop(pivot_index)
            parent.children.pop(sibling_index)

        record(
            "leaf_delete",
            before,
            key=key,
            pivot=pivot,
            orange_keys=orange_keys,
            parent_id=parent.node_id,
            left_id=(target.node_id if sibling_side == "right" else sibling.node_id),
            right_id=(sibling.node_id if sibling_side == "right" else target.node_id),
            pivot_index=pivot_index,
            donor=donor,
        )

    delete_leaf(80, sibling_side="right")
    delete_leaf(50, sibling_side="left")

    width, height = 1500, 700

    def layout(tree: BNode) -> tuple[dict[int, tuple[tuple[int, ...], Point]], list[tuple[int, int]]]:
        groups: dict[int, tuple[tuple[int, ...], Point]] = {}
        links: list[tuple[int, int]] = []
        # Leave room for temporary three-cell merge rows. Their width can be
        # larger than the source leaf row, so the global transparent crop must
        # never clip a valid action at the left edge.
        cursor = 170.0

        def visit(node: BNode, depth: int) -> Point:
            nonlocal cursor
            y = (90.0, 300.0, 510.0)[min(depth, 2)]
            if node.leaf:
                center = (cursor, y)
                cursor += max(140.0, CELL_W * len(node.keys) + 56.0)
            else:
                children = [visit(child, depth + 1) for child in node.children]
                center = (sum(point[0] for point in children) / len(children), y)
                links.extend((node.node_id, child.node_id) for child in node.children)
            groups[node.node_id] = (tuple(node.keys), center)
            return center

        visit(tree, 0)
        return groups, links

    def link_centers(
        groups: Mapping[int, tuple[tuple[int, ...], Point]],
        links: Sequence[tuple[int, int]],
        parent_id: int,
        child_id: int,
        *,
        parent_center: Point | None = None,
        child_center: Point | None = None,
    ) -> tuple[Point, Point]:
        siblings = [child for parent, child in links if parent == parent_id]
        slot = siblings.index(child_id)
        keys, original_center = groups[parent_id]
        source_center = parent_center or original_center
        destination = child_center or groups[child_id][1]
        gap = btree_row_gap(cell_slots(source_center, len(keys)), slot)
        return (gap, destination)

    def all_link_centers(
        groups: Mapping[int, tuple[tuple[int, ...], Point]],
        links: Sequence[tuple[int, int]],
        *,
        omitted: set[int] = set(),
        parent_centers: Mapping[int, Point] = {},
        child_centers: Mapping[int, Point] = {},
    ) -> list[tuple[Point, Point]]:
        return [
            link_centers(
                groups,
                links,
                parent,
                child,
                parent_center=parent_centers.get(parent),
                child_center=child_centers.get(child),
            )
            for parent, child in links
            if parent not in omitted and child not in omitted
        ]

    def render(
        tree: BNode,
        strike: int | None = None,
        moved: Mapping[int, Point] | None = None,
        text_layers: Mapping[tuple[int, int], Sequence[tuple[str, float, str]]] | None = None,
        orange_keys: Sequence[int] = (),
    ) -> str:
        groups, links = layout(tree)
        if moved:
            groups = {
                node_id: (keys, moved.get(node_id, center))
                for node_id, (keys, center) in groups.items()
            }
        body: list[str] = []
        body.extend(
            btree_neon_edge(
                (start[0], start[1] + CELL_H / 2.0),
                (end[0], end[1] - CELL_H / 2.0),
            )
            for start, end in all_link_centers(groups, links)
        )
        orange = set(orange_keys)
        for node_id, (keys, center) in groups.items():
            layers: dict[int, Sequence[tuple[str, float, str]]] = {}
            for index, key in enumerate(keys):
                if (node_id, index) in (text_layers or {}):
                    layers[index] = (text_layers or {})[(node_id, index)]
                elif key in orange:
                    layers[index] = ((str(key), 1.0, GLOW_ORANGE),)
            body.append(
                btree_neon_row_at_positions(
                    [str(key) for key in keys],
                    cell_slots(center, len(keys)),
                    text_layers=layers,
                )
            )
        if strike is not None:
            strike_group = next(
                (center for keys, center in groups.values() if strike in keys),
                None,
            )
            if strike_group is None:
                return svg("".join(body), width=width, height=height, color=INK)
            key_index = next(
                index
                for keys, _center in groups.values()
                for index, key in enumerate(keys)
                if key == strike
            )
            point = cell_slots(strike_group, len(next(keys for keys, center in groups.values() if center == strike_group)))[key_index]
            body.append(glow_line(
                (point[0] - 22.0, point[1] - 17.0),
                (point[0] + 22.0, point[1] + 17.0),
                color=GLOW_RED,
                width=5.0,
                bloom=GLOW_RED,
                radius=0.0,
            ))
        return svg("".join(body), width=width, height=height, color=INK)

    def find_key(groups: Mapping[int, tuple[tuple[int, ...], Point]], key: int) -> tuple[int, int]:
        for node_id, (keys, _center) in groups.items():
            if key in keys:
                return node_id, keys.index(key)
        raise KeyError(key)

    def group_position(
        groups: Mapping[int, tuple[tuple[int, ...], Point]],
        node_id: int,
        index: int,
    ) -> Point:
        keys, center = groups[node_id]
        return cell_slots(center, len(keys))[index]

    def row_center(points: Sequence[Point]) -> Point:
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )

    def after_transition(frames: list[str], event: VisualEvent) -> None:
        before_groups, _ = layout(event.before)
        after_groups, _ = layout(event.after)
        shared = set(before_groups) & set(after_groups)
        for step in range(1, 25):
            progress = ease(step / 24.0)
            moved = {
                node_id: lerp_point(before_groups[node_id][1], after_groups[node_id][1], progress)
                for node_id in shared
            }
            frames.append(render(event.after, moved=moved))

    def animate_replace(frames: list[str], event: VisualEvent) -> None:
        assert event.key is not None and event.replacement is not None
        assert event.target_node_id is not None and event.target_index is not None
        assert event.replacement_node_id is not None and event.replacement_index is not None
        before_groups, before_links = layout(event.before)
        target_point = group_position(before_groups, event.target_node_id, event.target_index)
        replacement_point = group_position(
            before_groups,
            event.replacement_node_id,
            event.replacement_index,
        )
        base = render(event.before)
        for step in range(1, 91):
            progress = ease(step / 90.0)
            layers = {
                (event.target_node_id, event.target_index): (
                    (str(event.key), 1.0 - progress, INK),
                    (str(event.replacement), progress, GLOW_ORANGE),
                ),
                (event.replacement_node_id, event.replacement_index): (
                    (str(event.replacement), 1.0 - progress, INK),
                    (str(event.key), progress, GLOW_ORANGE),
                ),
            }
            frames.append(render(event.before, text_layers=layers))
        # The new orange value remains fully visible for one second before the
        # old white value is removed from its original leaf position.
        frames.extend([render(event.after, orange_keys=(event.key, event.replacement))] * 30)

    def animate_borrow_explicit(frames: list[str], event: VisualEvent) -> None:
        """Show borrow as pull-down first, then whole-cell promotion."""
        before_groups, before_links = layout(event.before)
        after_groups, _ = layout(event.after)
        assert event.pivot is not None and event.donor is not None

        parent_id, parent_index = find_key(before_groups, event.pivot)
        donor_id, donor_index = find_key(before_groups, event.donor)
        target_id, target_index = find_key(after_groups, event.pivot)
        after_parent_id, after_parent_index = find_key(after_groups, event.donor)
        after_donor_id = donor_id

        parent_keys, parent_center = before_groups[parent_id]
        donor_keys, donor_center = before_groups[donor_id]
        target_before_keys, target_before_center = before_groups[target_id]
        target_after_keys, target_after_center = after_groups[target_id]
        parent_after_keys, parent_after_center = after_groups[after_parent_id]
        donor_after_keys, donor_after_center = after_groups[after_donor_id]

        parent_points = cell_slots(parent_center, len(parent_keys))
        donor_points = cell_slots(donor_center, len(donor_keys))
        target_before_points = cell_slots(target_before_center, len(target_before_keys))
        target_after_points = cell_slots(target_after_center, len(target_after_keys))
        parent_after_points = cell_slots(parent_after_center, len(parent_after_keys))
        donor_after_points = cell_slots(donor_after_center, len(donor_after_keys))

        pivot_before = parent_points[parent_index]
        pivot_after = target_after_points[target_index]
        donor_before = donor_points[donor_index]
        donor_after = parent_after_points[after_parent_index]
        parent_remaining_keys = tuple(key for key in parent_keys if key != event.pivot)
        parent_remaining_points = tuple(
            point for index, point in enumerate(parent_after_points)
            if index != after_parent_index
        )
        donor_remaining_keys = tuple(key for key in donor_keys if key != event.donor)
        donor_remaining_points_before = tuple(
            point for index, point in enumerate(donor_points)
            if index != donor_index
        )
        donor_remaining_points_after = tuple(
            point for point in donor_after_points
        )
        target_existing_points = tuple(
            point for index, point in enumerate(target_after_points)
            if index != target_index
        )
        active = {parent_id, target_id, donor_id}

        def row_edge(start: Point, end: Point) -> str:
            return btree_neon_edge(
                (start[0], start[1] + CELL_H / 2.0),
                (end[0], end[1] - CELL_H / 2.0),
            )

        def draw(
            rows: Sequence[tuple[Sequence[int | None], Sequence[Point]]],
            edges: Sequence[tuple[Point, Point]],
        ) -> str:
            body = [row_edge(start, end) for start, end in edges]
            body.extend(
                btree_neon_row_at_positions(
                    [str(key) if key is not None else None for key in keys],
                    points,
                )
                for keys, points in rows
                if keys
            )
            return svg("".join(body), width=width, height=height, color=INK)

        def static_rows() -> list[tuple[Sequence[int | None], Sequence[Point]]]:
            return [
                (keys, cell_slots(center, len(keys)))
                for node_id, (keys, center) in before_groups.items()
                if node_id not in active and keys
            ]

        def static_edges() -> list[tuple[Point, Point]]:
            return all_link_centers(before_groups, before_links, omitted=active)

        parent_child_ids = [child for parent, child in before_links if parent == parent_id]

        def action_edges(
            pivot_point: Point,
            target_center: Point,
            donor_center_now: Point,
            *,
            relation: str,
        ) -> list[tuple[Point, Point]]:
            edges = static_edges()
            for grand, child in before_links:
                if child == parent_id:
                    edges.append(link_centers(before_groups, before_links, grand, child))
            target_slot = parent_child_ids.index(target_id)
            donor_slot = parent_child_ids.index(donor_id)
            edges.append((btree_row_gap(parent_points, target_slot), target_center))
            edges.append((btree_row_gap(parent_points, donor_slot), donor_center_now))
            for parent, child in before_links:
                if parent == target_id and child not in active:
                    edges.append(link_centers(before_groups, before_links, parent, child))
                elif parent == donor_id and child not in active:
                    edges.append(link_centers(
                        before_groups,
                        before_links,
                        parent,
                        child,
                        parent_center=donor_center_now,
                    ))
            if relation == "pull":
                edges.append((pivot_point, target_center))
            elif relation == "promote":
                edges.append((donor_center_now, pivot_point))
            return edges

        # Pull the parent separator down while the target and donor remain
        # complete rows in their original layer.
        for step in range(1, 43):
            progress = ease(step / 42.0)
            pivot_point = lerp_point(pivot_before, pivot_after, progress)
            target_points = tuple(
                lerp_point(source, target, progress)
                for source, target in zip(target_before_points, target_existing_points)
            )
            target_center = row_center(target_points)
            rows = static_rows()
            if parent_remaining_keys:
                rows.append((parent_remaining_keys, parent_remaining_points))
            rows.extend([
                (target_before_keys, target_points),
                ((event.pivot,), (pivot_point,)),
                (donor_keys, donor_points),
            ])
            frames.append(draw(
                rows,
                action_edges(pivot_point, target_center, donor_center, relation="pull"),
            ))

        # The target row has now received the pulled cell. Keep this complete
        # row stable before starting the sibling promotion.
        rows = static_rows()
        if parent_remaining_keys:
            rows.append((parent_remaining_keys, parent_remaining_points))
        rows.append((target_after_keys, target_after_points))
        rows.append((donor_keys, donor_points))
        frames.extend([draw(rows, static_edges())] * 10)

        # Promote the sibling boundary cell as a complete one-cell node. The
        # remainder of the donor also stays a contiguous row throughout.
        for step in range(1, 43):
            progress = ease(step / 42.0)
            donor_point = lerp_point(donor_before, donor_after, progress)
            donor_remaining_points = tuple(
                lerp_point(source, target, progress)
                for source, target in zip(donor_remaining_points_before, donor_remaining_points_after)
            )
            target_center = row_center(target_after_points)
            donor_center_now = row_center(donor_remaining_points)
            rows = static_rows()
            if parent_remaining_keys:
                rows.append((parent_remaining_keys, parent_remaining_points))
            rows.extend([
                (target_after_keys, target_after_points),
                (donor_remaining_keys, donor_remaining_points),
                ((event.donor,), (donor_point,)),
            ])
            frames.append(draw(
                rows,
                action_edges(donor_point, target_center, donor_center_now, relation="promote"),
            ))
        after_transition(frames, event)

    def animate_merge(frames: list[str], event: VisualEvent) -> None:
        before_groups, before_links = layout(event.before)
        after_groups, _ = layout(event.after)
        assert event.pivot is not None
        parent_id, pivot_index = find_key(before_groups, event.pivot)
        child_ids = [child for parent, child in before_links if parent == parent_id]
        left_id = child_ids[pivot_index]
        right_id = child_ids[pivot_index + 1]
        target_id, _ = find_key(after_groups, event.pivot)
        target_keys = after_groups[target_id][0]
        left_keys = before_groups[left_id][0]
        right_keys = before_groups[right_id][0]
        # Merge at the old child level first. Root contraction is a separate
        # after-transition: the complete merged row then rises to the root.
        destination_center = (
            before_groups[left_id][1][0] + CELL_W,
            before_groups[left_id][1][1],
        )
        destination = cell_slots(destination_center, len(target_keys))
        target_points = destination[:len(left_keys)]
        pivot_point = destination[len(left_keys)]
        right_points = destination[len(left_keys) + 1:]
        parent_all_keys = before_groups[parent_id][0]
        parent_keys = tuple(key for key in parent_all_keys if key != event.pivot)
        parent_point = group_position(before_groups, parent_id, pivot_index)
        parent_points = cell_slots(before_groups[parent_id][1], len(parent_all_keys))
        parent_remaining_points = tuple(point for index, point in enumerate(parent_points) if index != pivot_index)
        left_points = cell_slots(before_groups[left_id][1], len(left_keys))
        right_source_points = cell_slots(before_groups[right_id][1], len(right_keys))
        hidden = {parent_id, left_id, right_id}

        def row_edge(start: Point, end: Point) -> str:
            return btree_neon_edge(
                (start[0], start[1] + CELL_H / 2.0),
                (end[0], end[1] - CELL_H / 2.0),
            )

        def draw(
            rows: Sequence[tuple[Sequence[int | None], Sequence[Point]]],
            edges: Sequence[tuple[Point, Point]],
        ) -> str:
            body = [row_edge(start, end) for start, end in edges]
            body.extend(
                btree_neon_row_at_positions(
                    [str(key) for key in keys],
                    points,
                )
                for keys, points in rows
                if keys
            )
            return svg("".join(body), width=width, height=height, color=INK)

        def static_rows() -> list[tuple[Sequence[int], Sequence[Point]]]:
            return [
                (keys, cell_slots(center, len(keys)))
                for node_id, (keys, center) in before_groups.items()
                if node_id not in hidden and keys
            ]

        def structural_edges(parent_center: Point | None) -> list[tuple[Point, Point]]:
            edges: list[tuple[Point, Point]] = []
            for parent, child in before_links:
                if parent in hidden or child in hidden:
                    continue
                edges.append(link_centers(before_groups, before_links, parent, child))
            if parent_center is not None:
                for grand, child in before_links:
                    if child == parent_id:
                        edges.append(link_centers(
                            before_groups,
                            before_links,
                            grand,
                            child,
                            child_center=parent_center,
                        ))
                for parent, child in before_links:
                    if parent == parent_id and child not in hidden:
                        edges.append(link_centers(
                            before_groups,
                            before_links,
                            parent,
                            child,
                            parent_center=parent_center,
                        ))
            return edges

        parent_remaining_center = (
            row_center(parent_remaining_points)
            if parent_remaining_points
            else None
        )
        left_child_centers = [
            before_groups[child][1]
            for parent, child in before_links
            if parent == left_id
        ]
        right_child_centers = [
            before_groups[child][1]
            for parent, child in before_links
            if parent == right_id
        ]

        # Beat 1: pull the separator out of the parent row and down to the
        # child level. The two child rows stay complete and stationary.
        for step in range(1, 37):
            progress = ease(step / 36.0)
            pivot_moving = lerp_point(parent_point, pivot_point, progress)
            rows = static_rows()
            if parent_keys:
                rows.append((parent_keys, parent_remaining_points))
            rows.extend([
                (left_keys, left_points),
                (right_keys, right_source_points),
                ((event.pivot,), (pivot_moving,)),
            ])
            edges = structural_edges(parent_remaining_center)
            edges.append((pivot_moving, before_groups[left_id][1]))
            edges.append((pivot_moving, before_groups[right_id][1]))
            edges.extend((before_groups[left_id][1], child) for child in left_child_centers)
            edges.extend((before_groups[right_id][1], child) for child in right_child_centers)
            frames.append(draw(rows, edges))

        # Beat 2: keep the pulled separator in place while both complete
        # child arrays move toward their final contiguous slots.
        for step in range(1, 43):
            progress = ease(step / 42.0)
            left_moving = tuple(
                lerp_point(source, target, progress)
                for source, target in zip(left_points, target_points)
            )
            right_moving = tuple(
                lerp_point(source, target, progress)
                for source, target in zip(right_source_points, right_points)
            )
            left_center = row_center(left_moving)
            right_center = row_center(right_moving)
            rows = static_rows()
            if parent_keys:
                rows.append((parent_keys, parent_remaining_points))
            rows.extend([
                (left_keys, left_moving),
                (right_keys, right_moving),
                ((event.pivot,), (pivot_point,)),
            ])
            edges = structural_edges(parent_remaining_center)
            edges.append((pivot_point, left_center))
            edges.append((pivot_point, right_center))
            edges.extend((left_center, child) for child in left_child_centers)
            edges.extend((right_center, child) for child in right_child_centers)
            frames.append(draw(rows, edges))

        # Beat 3: one continuous merged node, then let the normal after-state
        # transition handle sibling/root movement and layer contraction.
        rows = static_rows()
        if parent_keys:
            rows.append((parent_keys, parent_remaining_points))
        rows.append((target_keys, destination))
        edges = structural_edges(parent_remaining_center)
        if parent_remaining_center is not None:
            edges.append((parent_remaining_center, row_center(destination)))
        edges.extend((row_center(destination), child) for child in left_child_centers + right_child_centers)
        frames.extend([draw(rows, edges)] * 12)
        after_transition(frames, event)

    def animate_leaf_delete_old(frames: list[str], event: VisualEvent) -> None:
        assert event.key is not None
        assert event.parent_id is not None
        assert event.left_id is not None and event.right_id is not None
        assert event.pivot_index is not None
        before_groups, before_links = layout(event.before)
        after_groups, after_links = layout(event.after)
        parent_id = event.parent_id
        left_id = event.left_id
        right_id = event.right_id
        parent_keys, parent_center = before_groups[parent_id]
        left_keys, left_center = before_groups[left_id]
        right_keys, right_center = before_groups[right_id]
        parent_points = cell_slots(parent_center, len(parent_keys))
        left_points = cell_slots(left_center, len(left_keys))
        right_points = cell_slots(right_center, len(right_keys))
        pivot_point = parent_points[event.pivot_index]
        empty_parent_points = tuple(
            point for index, point in enumerate(parent_points)
            if index != event.pivot_index
        )
        target_keys = tuple(key for key in left_keys if key != event.key)
        target_keys = tuple(target_keys) + tuple(
            key for key in right_keys if key != event.key
        )
        parent_remaining_keys = tuple(
            key for index, key in enumerate(parent_keys)
            if index != event.pivot_index
        )
        hidden = {parent_id, left_id, right_id}

        def row_edge(start: Point, end: Point) -> str:
            return btree_neon_edge(
                (start[0], start[1] + CELL_H / 2.0),
                (end[0], end[1] - CELL_H / 2.0),
            )

        def static_rows() -> list[tuple[Sequence[int | None], Sequence[Point]]]:
            return [
                (keys, cell_slots(center, len(keys)))
                for node_id, (keys, center) in before_groups.items()
                if node_id not in hidden and keys
            ]

        def static_edges() -> list[tuple[Point, Point]]:
            return all_link_centers(before_groups, before_links, omitted=hidden)

        def draw(
            rows: Sequence[tuple[Sequence[int | None], Sequence[Point]]],
            edges: Sequence[tuple[Point, Point]],
        ) -> str:
            body = [row_edge(start, end) for start, end in edges]
            body.extend(
                btree_neon_row_at_positions(
                    [str(key) if key is not None else None for key in keys],
                    points,
                )
                for keys, points in rows
                if keys
            )
            return svg("".join(body), width=width, height=height, color=INK)

        # Pull the parent separator down to the leaf level, but keep an empty
        # slot in the parent row. The source parent row is never removed.
        for step in range(1, 61):
            progress = ease(step / 60.0)
            pulled = lerp_point(
                pivot_point,
                (row_center(left_points)[0], row_center(left_points)[1]),
                progress,
            )
            target_center = row_center(left_points)
            rows = static_rows()
            if parent_remaining_keys:
                rows.append((parent_remaining_keys, empty_parent_points))
            rows.extend([
                (left_keys, left_points),
                (right_keys, right_points),
                ((event.pivot,), (pulled,)),
            ])
            edges = static_edges()
            edges.append((pulled, target_center))
            frames.append(draw(rows, edges))

        # The target leaf is now stable with the pulled separator included;
        # hold the parent empty slot before deleting the requested key.
        rows = static_rows()
        if parent_remaining_keys:
            rows.append((parent_remaining_keys, empty_parent_points))
        merged_keys = tuple(left_keys) + (event.pivot,)
        merged_points = cell_slots(row_center(left_points), len(merged_keys))
        rows.extend([
            (merged_keys, merged_points),
            (right_keys, right_points),
        ])
        frames.extend([draw(rows, static_edges())] * 12)

        # Strike the key, then remove it without moving the other cells.
        strike_point = merged_points[tuple(left_keys).index(event.key)] if event.key in left_keys else merged_points[0]
        for step in range(1, 19):
            progress = ease(step / 18.0)
            rows = static_rows()
            if parent_remaining_keys:
                rows.append((parent_remaining_keys, empty_parent_points))
            rows.extend([
                (merged_keys, merged_points),
                (right_keys, right_points),
            ])
            slash = glow_line(
                (strike_point[0] - 22.0, strike_point[1] - 17.0),
                (strike_point[0] + 22.0, strike_point[1] + 17.0),
                color=GLOW_RED,
                width=5.0 * progress,
                bloom=GLOW_RED,
                radius=0.0,
            )
            body = draw(rows, static_edges())
            frames.append(body.replace("</svg>", slash + "</svg>"))

        final_parent_keys = after_groups[parent_id][0] if parent_id in after_groups else ()
        final_parent_center = after_groups[parent_id][1] if parent_id in after_groups else parent_center
        final_rows: list[tuple[Sequence[int | None], Sequence[Point]]] = static_rows()
        if final_parent_keys:
            final_rows.append((final_parent_keys, cell_slots(final_parent_center, len(final_parent_keys))))
        final_rows.append((after_groups[left_id][0] if left_id in after_groups else target_keys, cell_slots(after_groups[left_id][1] if left_id in after_groups else left_center, len(after_groups[left_id][0] if left_id in after_groups else target_keys))))
        if right_id in after_groups:
            final_rows.append((after_groups[right_id][0], cell_slots(after_groups[right_id][1], len(after_groups[right_id][0]))))
        frames.extend([draw(final_rows, static_edges())] * 12)
        after_transition(frames, event)

    def animate_leaf_delete(frames: list[str], event: VisualEvent) -> None:
        assert event.key is not None
        assert event.parent_id is not None
        assert event.left_id is not None and event.right_id is not None
        assert event.pivot is not None and event.pivot_index is not None

        before_groups, before_links = layout(event.before)
        parent_id = event.parent_id
        left_id, right_id = event.left_id, event.right_id
        target_id = left_id if event.key in before_groups[left_id][0] else right_id
        sibling_id = right_id if target_id == left_id else left_id
        parent_keys, parent_center = before_groups[parent_id]
        target_keys, target_center = before_groups[target_id]
        sibling_keys, sibling_center = before_groups[sibling_id]
        parent_points = cell_slots(parent_center, len(parent_keys))
        target_points = cell_slots(target_center, len(target_keys))
        sibling_points = cell_slots(sibling_center, len(sibling_keys))
        parent_blank: list[int | None] = list(parent_keys)
        parent_blank[event.pivot_index] = None
        active = {parent_id, target_id, sibling_id}

        def row_edge(start: Point, end: Point) -> str:
            return btree_neon_edge(
                (start[0], start[1] + CELL_H / 2.0),
                (end[0], end[1] - CELL_H / 2.0),
            )

        def static_rows() -> list[tuple[Sequence[int | None], Sequence[Point]]]:
            return [
                (keys, cell_slots(center, len(keys)))
                for node_id, (keys, center) in before_groups.items()
                if node_id not in active and keys
            ]

        def structure_edges(
            *,
            target_center_now: Point | None = None,
            sibling_center_now: Point | None = None,
            tether: Sequence[tuple[Point, Point]] = (),
        ) -> list[tuple[Point, Point]]:
            edges = list(all_link_centers(before_groups, before_links, omitted=active))
            for grand, child in before_links:
                if child == parent_id:
                    edges.append(link_centers(before_groups, before_links, grand, child))
            for parent, child in before_links:
                if parent != parent_id or child in active:
                    continue
                slot = [item for item in before_links if item[0] == parent_id].index((parent, child))
                edges.append((btree_row_gap(parent_points, slot), before_groups[child][1]))
            if target_center_now is not None and event.pivot_index is not None:
                edges.append((btree_row_gap(parent_points, event.pivot_index), target_center_now))
            if sibling_center_now is not None:
                sibling_slot = [item for item in before_links if item[0] == parent_id].index((parent_id, sibling_id))
                edges.append((btree_row_gap(parent_points, sibling_slot), sibling_center_now))
            edges.extend(tether)
            return edges

        def draw(
            rows: Sequence[tuple[Sequence[int | None], Sequence[Point]]],
            edges: Sequence[tuple[Point, Point]],
            *,
            strike: Point | None = None,
        ) -> str:
            body = [row_edge(start, end) for start, end in edges]
            body.extend(
                btree_neon_row_at_positions(
                    [str(key) if key is not None else None for key in keys],
                    points,
                )
                for keys, points in rows
                if keys
            )
            if strike is not None:
                body.append(
                    glow_line(
                        (strike[0] - 22.0, strike[1] - 17.0),
                        (strike[0] + 22.0, strike[1] + 17.0),
                        color=GLOW_RED,
                        width=5.0,
                        bloom=GLOW_RED,
                        radius=0.0,
                    )
                )
            return svg("".join(body), width=width, height=height, color=INK)

        merged_keys = tuple(sorted((*target_keys, event.pivot, *sibling_keys)))
        merged_center = (
            (target_center[0] + sibling_center[0]) / 2.0,
            target_center[1],
        )
        merged_points = cell_slots(merged_center, len(merged_keys))
        pivot_destination = merged_points[merged_keys.index(event.pivot)]
        target_destination = tuple(merged_points[merged_keys.index(key)] for key in target_keys)
        sibling_destination = tuple(merged_points[merged_keys.index(key)] for key in sibling_keys)
        pivot_start = parent_points[event.pivot_index]

        # Pull the parent separator down while its original slot remains blank.
        for step in range(1, 61):
            progress = ease(step / 60.0)
            pivot_now = lerp_point(pivot_start, pivot_destination, progress)
            rows = static_rows() + [
                (tuple(parent_blank), parent_points),
                (target_keys, target_points),
                (sibling_keys, sibling_points),
                ((event.pivot,), (pivot_now,)),
            ]
            edges = structure_edges(
                tether=((pivot_now, target_center), (pivot_now, sibling_center))
            )
            frames.append(draw(rows, edges))

        if event.donor is None:
            # Both children are minimum-sized: let the complete rows meet the
            # pulled separator before they become one continuous node.
            for step in range(1, 43):
                progress = ease(step / 42.0)
                target_now = tuple(
                    lerp_point(source, destination, progress)
                    for source, destination in zip(target_points, target_destination)
                )
                sibling_now = tuple(
                    lerp_point(source, destination, progress)
                    for source, destination in zip(sibling_points, sibling_destination)
                )
                pivot_now = pivot_destination
                rows = static_rows() + [
                    (tuple(parent_blank), parent_points),
                    (target_keys, target_now),
                    (sibling_keys, sibling_now),
                    ((event.pivot,), (pivot_now,)),
                ]
                edges = structure_edges(
                    tether=((pivot_now, row_center(target_now)), (pivot_now, row_center(sibling_now)))
                )
                frames.append(draw(rows, edges))
            rows = static_rows() + [(tuple(parent_blank), parent_points), (merged_keys, merged_points)]
            edges = structure_edges(target_center_now=merged_center)
            frames.extend([draw(rows, edges)] * 15)
            strike_point = merged_points[merged_keys.index(event.key)]
            for step in range(1, 19):
                progress = ease(step / 18.0)
                body = draw(rows, edges)
                slash = glow_line(
                    (strike_point[0] - 22.0, strike_point[1] - 17.0),
                    (strike_point[0] + 22.0, strike_point[1] + 17.0),
                    color=GLOW_RED,
                    width=5.0 * progress,
                    bloom=GLOW_RED,
                    radius=0.0,
                )
                frames.append(body.replace("</svg>", slash + "</svg>"))
            survivors = tuple(key for key in merged_keys if key != event.key)
            survivor_points = tuple(
                point for key, point in zip(merged_keys, merged_points) if key != event.key
            )
            rows = static_rows() + [(tuple(parent_blank), parent_points), (survivors, survivor_points)]
            frames.extend([draw(rows, structure_edges(target_center_now=row_center(survivor_points)))] * 15)
        else:
            target_with_pivot = tuple(sorted((*target_keys, event.pivot)))
            target_with_pivot_points = tuple(
                merged_points[merged_keys.index(key)] for key in target_with_pivot
            )
            rows = static_rows() + [
                (tuple(parent_blank), parent_points),
                (target_with_pivot, target_with_pivot_points),
                (sibling_keys, sibling_points),
            ]
            edges = structure_edges(
                target_center_now=row_center(target_with_pivot_points),
                sibling_center_now=sibling_center,
            )
            frames.extend([draw(rows, edges)] * 15)
            strike_point = target_with_pivot_points[target_with_pivot.index(event.key)]
            for step in range(1, 19):
                progress = ease(step / 18.0)
                body = draw(rows, edges)
                slash = glow_line(
                    (strike_point[0] - 22.0, strike_point[1] - 17.0),
                    (strike_point[0] + 22.0, strike_point[1] + 17.0),
                    color=GLOW_RED,
                    width=5.0 * progress,
                    bloom=GLOW_RED,
                    radius=0.0,
                )
                frames.append(body.replace("</svg>", slash + "</svg>"))
            survivor_keys = tuple(key for key in target_with_pivot if key != event.key)
            survivor_points = tuple(
                point for key, point in zip(target_with_pivot, target_with_pivot_points) if key != event.key
            )
            donor_index = sibling_keys.index(event.donor)
            remaining_sibling_keys = tuple(key for index, key in enumerate(sibling_keys) if index != donor_index)
            remaining_sibling_points = tuple(point for index, point in enumerate(sibling_points) if index != donor_index)
            donor_start = sibling_points[donor_index]
            donor_end = parent_points[event.pivot_index]
            for step in range(1, 61):
                progress = ease(step / 60.0)
                donor_now = lerp_point(donor_start, donor_end, progress)
                rows = static_rows() + [
                    (tuple(parent_blank), parent_points),
                    (survivor_keys, survivor_points),
                    (remaining_sibling_keys, remaining_sibling_points),
                    ((event.donor,), (donor_now,)),
                ]
                frames.append(draw(rows, structure_edges(
                    target_center_now=row_center(survivor_points),
                    sibling_center_now=row_center(remaining_sibling_points),
                    tether=((donor_now, parent_points[event.pivot_index]),),
                )))

        after_transition(frames, event)

    frames: list[str] = []
    initial_tree = events[0].before if events else root
    frames.extend([render(initial_tree)] * 24)
    for event in events:
        frames.extend([render(event.before)] * 12)
        if event.kind == "borrow":
            animate_borrow_explicit(frames, event)
        elif event.kind == "merge":
            animate_merge(frames, event)
        elif event.kind == "replace":
            animate_replace(frames, event)
        elif event.kind == "leaf_delete":
            animate_leaf_delete(frames, event)
        else:
            assert event.key is not None
            frames.extend([render(event.before, strike=event.key)] * 18)
            after_transition(frames, event)
        if event.kind == "replace":
            assert event.key is not None and event.replacement is not None
            frames.extend([render(event.after, orange_keys=(event.key, event.replacement))] * 12)
        else:
            frames.extend([render(event.after)] * 12)
    final_tree = events[-1].after if events else root
    frames.extend([render(final_tree)] * 90)
    render_webm("btree-delete-complex", frames, fps=30, transparent=True)


def btree_delete_complex_discarded() -> None:
    """Show internal replacement followed by two leaf-deletion preparations."""
    from dataclasses import dataclass, field

    @dataclass
    class BNode:
        keys: list[int] = field(default_factory=list)
        children: list["BNode"] = field(default_factory=list)
        node_id: int = 0

        @property
        def leaf(self) -> bool:
            return not self.children

    @dataclass
    class Event:
        before: BNode
        after: BNode
        kind: str
        key: int | None = None
        replacement: int | None = None
        parent_id: int | None = None
        target_id: int | None = None
        sibling_id: int | None = None
        pivot: int | None = None
        pivot_index: int | None = None
        sibling_side: str = "right"
        donor: int | None = None

    def clone(node: BNode) -> BNode:
        return BNode(node.keys[:], [clone(child) for child in node.children], node.node_id)

    root = BNode(
        [80],
        [
            BNode(
                [40, 60],
                [BNode([10, 20, 30]), BNode([50]), BNode([70])],
            ),
            BNode(
                [120, 160],
                [BNode([90]), BNode([130, 140, 150]), BNode([170])],
            ),
        ],
    )
    next_id = 1

    def assign_ids(node: BNode) -> None:
        nonlocal next_id
        node.node_id = next_id
        next_id += 1
        for child in node.children:
            assign_ids(child)

    assign_ids(root)
    events: list[Event] = []

    # The root key 80 and its successor 90 exchange places first. The old 80
    # is now physically located in the successor leaf and will be deleted there.
    before = clone(root)
    successor = root.children[1].children[0]
    root.keys[0], successor.keys[0] = successor.keys[0], root.keys[0]
    events.append(Event(before, clone(root), "replace", key=80, replacement=90))

    def locate(node: BNode, node_id: int) -> BNode:
        if node.node_id == node_id:
            return node
        for child in node.children:
            try:
                return locate(child, node_id)
            except KeyError:
                pass
        raise KeyError(node_id)

    def leaf_delete(
        target_id: int,
        *,
        key: int,
        sibling_side: str,
    ) -> None:
        parent: BNode | None = None
        target: BNode | None = None
        child_index = -1

        def walk(node: BNode) -> None:
            nonlocal parent, target, child_index
            for index, child in enumerate(node.children):
                if child.node_id == target_id:
                    parent, target, child_index = node, child, index
                    return
                walk(child)
                if target is not None:
                    return

        walk(root)
        assert parent is not None and target is not None and target.leaf
        pivot_index = child_index if sibling_side == "right" else child_index - 1
        sibling_index = child_index + 1 if sibling_side == "right" else child_index - 1
        sibling = parent.children[sibling_index]
        pivot = parent.keys[pivot_index]
        before = clone(root)

        # Pull the separator into the target leaf, then delete the key from
        # this now-safe leaf. The sibling supplies one key only when it has
        # more than the minimum; otherwise it joins the target row.
        pulled = sorted(target.keys + [pivot])
        pulled.remove(key)
        donor: int | None = None
        if len(sibling.keys) > 1:
            donor = sibling.keys.pop(0) if sibling_side == "right" else sibling.keys.pop()
            parent.keys[pivot_index] = donor
            target.keys = pulled
        else:
            target.keys = sorted(pulled + sibling.keys)
            parent.keys.pop(pivot_index)
            parent.children.pop(sibling_index)

        events.append(
            Event(
                before,
                clone(root),
                "leaf_delete",
                key=key,
                parent_id=parent.node_id,
                target_id=target_id,
                sibling_id=sibling.node_id,
                pivot=pivot,
                pivot_index=pivot_index,
                sibling_side=sibling_side,
                donor=donor,
            )
        )

    # First leaf deletion borrows from a fuller sibling and visibly promotes
    # its boundary key. The second one has minimum siblings and removes the
    # empty parent slot without promotion.
    leaf_delete(successor.node_id, key=80, sibling_side="right")
    first_after = events[-1].after
    first_target = first_after.children[1].children[0]
    leaf_delete(first_target.node_id, key=120, sibling_side="right")
    second_after = events[-1].after
    second_target = second_after.children[1].children[1]
    leaf_delete(second_target.node_id, key=150, sibling_side="left")

    width, height = 1500, 700

    def layout(tree: BNode) -> tuple[dict[int, tuple[tuple[int, ...], Point]], list[tuple[int, int]]]:
        groups: dict[int, tuple[tuple[int, ...], Point]] = {}
        links: list[tuple[int, int]] = []
        cursor = 170.0

        def visit(node: BNode, depth: int) -> Point:
            nonlocal cursor
            y = (90.0, 300.0, 510.0)[min(depth, 2)]
            if node.leaf:
                center = (cursor, y)
                cursor += max(140.0, CELL_W * max(1, len(node.keys)) + 56.0)
            else:
                children = [visit(child, depth + 1) for child in node.children]
                center = (sum(point[0] for point in children) / len(children), y)
                links.extend((node.node_id, child.node_id) for child in node.children)
            groups[node.node_id] = (tuple(node.keys), center)
            return center

        visit(tree, 0)
        return groups, links

    def link_segment(
        groups: Mapping[int, tuple[tuple[int, ...], Point]],
        links: Sequence[tuple[int, int]],
        parent_id: int,
        child_id: int,
        *,
        parent_points: Sequence[Point] | None = None,
        child_center: Point | None = None,
    ) -> tuple[Point, Point]:
        siblings = [child for parent, child in links if parent == parent_id]
        slot = siblings.index(child_id)
        parent_keys, parent_center = groups[parent_id]
        points = parent_points or cell_slots(parent_center, len(parent_keys))
        return btree_row_gap(points, slot), child_center or groups[child_id][1]

    def edge(start: Point, end: Point) -> str:
        return btree_neon_edge(
            (start[0], start[1] + CELL_H / 2.0),
            (end[0], end[1] - CELL_H / 2.0),
        )

    def render_tree(tree: BNode, *, orange: Sequence[int] = ()) -> str:
        groups, links = layout(tree)
        body = [edge(start, end) for parent, child in links for start, end in [link_segment(groups, links, parent, child)]]
        orange_set = set(orange)
        for node_id, (keys, center) in groups.items():
            layers = {
                index: ((str(key), 1.0, GLOW_ORANGE),)
                for index, key in enumerate(keys)
                if key in orange_set
            }
            body.append(
                btree_neon_row_at_positions(
                    [str(key) for key in keys],
                    cell_slots(center, len(keys)),
                    text_layers=layers,
                )
            )
        return svg("".join(body), width=width, height=height, color=INK)

    def animate_replace(frames: list[str], event: Event) -> None:
        before_groups, _ = layout(event.before)
        assert event.key is not None and event.replacement is not None
        target_id, target_index = next(
            (node_id, keys.index(event.key))
            for node_id, (keys, _center) in before_groups.items()
            if event.key in keys
        )
        source_id, source_index = next(
            (node_id, keys.index(event.replacement))
            for node_id, (keys, _center) in before_groups.items()
            if event.replacement in keys
        )

        def swapped_frame(old_opacity: float, new_opacity: float) -> str:
            groups, links = layout(event.before)
            text_layers = {
                (target_id, target_index): (
                    (str(event.key), old_opacity, INK),
                    (str(event.replacement), new_opacity, GLOW_ORANGE),
                ),
                (source_id, source_index): (
                    (str(event.replacement), old_opacity, INK),
                    (str(event.key), new_opacity, GLOW_ORANGE),
                ),
            }
            body = [
                edge(start, end)
                for parent, child in links
                for start, end in [link_segment(groups, links, parent, child)]
            ]
            for node_id, (keys, center) in groups.items():
                node_layers = {
                    index: text_layers[(node_id, index)]
                    for index in range(len(keys))
                    if (node_id, index) in text_layers
                }
                body.append(
                    btree_neon_row_at_positions(
                        [str(key) for key in keys],
                        cell_slots(center, len(keys)),
                        text_layers=node_layers,
                    )
                )
            return svg("".join(body), width=width, height=height, color=INK)

        for step in range(1, 91):
            t = ease(step / 90.0)
            frames.append(swapped_frame(1.0, t))
        # Keep both the old white labels and the fully visible orange labels
        # together for one second, then remove the old labels.
        frames.extend([swapped_frame(1.0, 1.0)] * 30)

    def animate_leaf(frames: list[str], event: Event) -> None:
        assert event.parent_id is not None and event.target_id is not None and event.sibling_id is not None
        assert event.pivot is not None and event.pivot_index is not None and event.key is not None
        before_groups, before_links = layout(event.before)
        parent_keys, parent_center = before_groups[event.parent_id]
        target_keys, target_center = before_groups[event.target_id]
        sibling_keys, sibling_center = before_groups[event.sibling_id]
        parent_points = cell_slots(parent_center, len(parent_keys))
        target_points = cell_slots(target_center, len(target_keys))
        sibling_points = cell_slots(sibling_center, len(sibling_keys))
        parent_blank: list[int | None] = list(parent_keys)
        parent_blank[event.pivot_index] = None
        active = {event.parent_id, event.target_id, event.sibling_id}
        target_with_pivot = tuple(target_keys) + (event.pivot,)
        target_with_pivot_points = tuple(target_points) + ((target_points[-1][0] + CELL_W, target_center[1]),)
        pivot_start = parent_points[event.pivot_index]
        pivot_end = target_with_pivot_points[-1]
        orange = (event.key,)

        def static_rows() -> list[tuple[Sequence[int | None], Sequence[Point]]]:
            return [
                (keys, cell_slots(center, len(keys)))
                for node_id, (keys, center) in before_groups.items()
                if node_id not in active and keys
            ]

        def static_edges() -> list[tuple[Point, Point]]:
            return [
                link_segment(before_groups, before_links, parent, child)
                for parent, child in before_links
                if parent not in active and child not in active
            ]

        ancestor_edges = [
            link_segment(before_groups, before_links, parent, child)
            for parent, child in before_links
            if child == event.parent_id
        ]
        child_edges = [
            link_segment(
                before_groups,
                before_links,
                event.parent_id,
                child,
                parent_points=parent_points,
            )
            for parent, child in before_links
            if parent == event.parent_id and child not in active
        ]

        def draw(
            rows: Sequence[tuple[Sequence[int | None], Sequence[Point]]],
            edges: Sequence[tuple[Point, Point]],
            *,
            strike: Point | None = None,
            donor_opacity: float = 1.0,
        ) -> str:
            body = [edge(start, end) for start, end in edges]
            for keys, points in rows:
                layers = {
                    index: ((str(key), 1.0, GLOW_ORANGE),)
                    for index, key in enumerate(keys)
                    if key in orange
                }
                body.append(btree_neon_row_at_positions([str(key) if key is not None else None for key in keys], points, text_layers=layers))
            if strike is not None:
                body.append(glow_line((strike[0] - 22.0, strike[1] - 17.0), (strike[0] + 22.0, strike[1] + 17.0), color=GLOW_RED, width=5.0, bloom=GLOW_RED, radius=0.0))
            return svg("".join(body), width=width, height=height, color=INK)

        # Pull the parent separator while its parent slot remains visibly blank.
        for step in range(1, 61):
            t = ease(step / 60.0)
            moving = lerp_point(pivot_start, pivot_end, t)
            rows = static_rows()
            rows.append((tuple(parent_blank), parent_points))
            rows.extend(((target_keys, target_points), (sibling_keys, sibling_points)))
            edges = static_edges() + ancestor_edges + child_edges
            edges.append((parent_points[event.pivot_index], moving))
            frames.append(draw(rows + [((event.pivot,), (moving,))], edges))

        rows = static_rows()
        rows.append((tuple(parent_blank), parent_points))
        rows.extend(((target_with_pivot, target_with_pivot_points), (sibling_keys, sibling_points)))
        edges = static_edges() + ancestor_edges + child_edges
        edges.append((btree_row_gap(parent_points, event.pivot_index), target_center))
        frames.extend([draw(rows, edges)] * 12)

        strike_index = target_with_pivot.index(event.key)
        strike_point = target_with_pivot_points[strike_index]
        for step in range(1, 19):
            t = ease(step / 18.0)
            rows = static_rows()
            rows.append((tuple(parent_blank), parent_points))
            rows.extend(((target_with_pivot, target_with_pivot_points), (sibling_keys, sibling_points)))
            frames.append(draw(rows, edges, strike=(strike_point[0], strike_point[1])) if t >= 0 else draw(rows, edges))

        survivor_keys = tuple(key for key in target_with_pivot if key != event.key)
        survivor_points = tuple(point for key, point in zip(target_with_pivot, target_with_pivot_points) if key != event.key)
        if event.donor is not None:
            donor_index = 0 if event.sibling_side == "right" else len(sibling_keys) - 1
            donor_start = sibling_points[donor_index]
            donor_end = parent_points[event.pivot_index]
            remaining_keys = tuple(key for index, key in enumerate(sibling_keys) if index != donor_index)
            remaining_points = tuple(point for index, point in enumerate(sibling_points) if index != donor_index)
            for step in range(1, 61):
                t = ease(step / 60.0)
                donor_point = lerp_point(donor_start, donor_end, t)
                rows = static_rows()
                rows.append((tuple(parent_blank), parent_points))
                rows.extend(((survivor_keys, survivor_points), (remaining_keys, remaining_points), ((event.donor,), (donor_point,))))
                frames.append(draw(rows, static_edges() + ancestor_edges + child_edges))
        else:
            merged_keys = survivor_keys + tuple(sibling_keys)
            merged_points = survivor_points + tuple(sibling_points)
            rows = static_rows()
            rows.append((merged_keys, merged_points))
            frames.extend([draw(rows, static_edges() + ancestor_edges)] * 30)
        frames.extend([render_tree(event.after, orange=orange)] * 18)

    frames: list[str] = [render_tree(events[0].before)] * 30
    for event in events:
        if event.kind == "replace":
            animate_replace(frames, event)
        else:
            animate_leaf(frames, event)
    frames.extend([render_tree(events[-1].after)] * 90)
    render_webm("btree-delete-complex", frames, fps=30, transparent=True)


def rb_encoding_legacy() -> None:
    """Show one B-tree becoming a temporarily invalid binary encoding."""
    width, height = 1400, 700
    node_w, node_h = BTREE_NEON_CELL_W, BTREE_NEON_CELL_H
    node_half = node_w / 2.0

    # The source is one tree, not a gallery of local shapes. It has ordinary
    # one-, two-, and three-key nodes plus two temporary four-key leaf
    # overflows. The left overflow uses a non-crossing flat encoding; the
    # right one uses the crossing variant before both split upward.
    groups = {
        "root": ((50,), (700.0, 86.0)),
        "left": ((15, 30), (350.0, 242.0)),
        "right": ((70, 90), (1050.0, 242.0)),
        "l0": ((5,), (90.0, 464.0)),
        "l1": ((20, 25), (250.0, 464.0)),
        "l2": ((35, 40, 45, 47), (490.0, 464.0)),
        "r0": ((55, 57, 60), (760.0, 464.0)),
        "r1": ((75,), (900.0, 464.0)),
        "r2": ((95, 100, 102, 105), (1140.0, 464.0)),
    }
    child_groups = {
        "root": ("left", "right"),
        "left": ("l0", "l1", "l2"),
        "right": ("r0", "r1", "r2"),
    }
    initial_positions = {
        key: point
        for keys, center in groups.values()
        for key, point in zip(keys, btree_neon_slots(center, len(keys)), strict=True)
    }
    flat_positions = {
        50: (700.0, 86.0),
        15: (311.0, 242.0), 30: (389.0, 242.0),
        70: (1011.0, 242.0), 90: (1089.0, 242.0),
        5: (90.0, 464.0),
        20: (211.0, 464.0), 25: (289.0, 464.0),
        35: (373.0, 464.0), 40: (451.0, 464.0), 45: (529.0, 464.0), 47: (607.0, 464.0),
        55: (682.0, 464.0), 57: (760.0, 464.0), 60: (838.0, 464.0),
        75: (900.0, 464.0),
        95: (1023.0, 464.0), 100: (1101.0, 464.0), 102: (1179.0, 464.0), 105: (1257.0, 464.0),
    }
    source_red = {
        15, 70, 25, 35, 40, 47, 55, 60, 95, 102, 105,
    }
    final_positions = {
        50: (700.0, 76.0),
        30: (390.0, 204.0), 90: (1010.0, 204.0),
        15: (230.0, 332.0), 45: (550.0, 332.0), 70: (850.0, 332.0),
        5: (100.0, 464.0), 20: (315.0, 464.0), 40: (470.0, 464.0), 47: (630.0, 464.0),
        57: (780.0, 464.0), 75: (920.0, 464.0), 100: (1170.0, 332.0), 105: (1240.0, 464.0),
        25: (345.0, 590.0), 35: (440.0, 590.0), 55: (735.0, 590.0), 60: (825.0, 590.0), 95: (1050.0, 464.0), 102: (1170.0, 590.0),
    }
    member_edges = (
        (20, 25, 0.0), (35, 40, -12.0), (40, 45, -12.0), (45, 47, -12.0),
        (55, 57, 0.0), (57, 60, 0.0), (95, 100, -12.0), (102, 105, 0.0),
    )
    overlay_member_edges = ((100, 105, -12.0),)
    # Every B-tree node has two independent surfaces. Incoming routes land on
    # the black member at its upper surface; outgoing routes leave its lower
    # surface through the corresponding B-tree child gap. Red members never
    # become vertical routing endpoints merely because they move apart.
    black_key = {
        "root": 50,
        "left": 30,
        "right": 90,
        "l0": 5,
        "l1": 20,
        "l2": 45,
        "r0": 57,
        "r1": 75,
        "r2": 100,
    }
    binary_edges = (
        (50, 30), (50, 90),
        (30, 15), (30, 45), (15, 5), (15, 20), (20, 25),
        (45, 40), (45, 47), (40, 35),
        (90, 70), (90, 100), (70, 57), (70, 75), (57, 55), (57, 60),
        (100, 95), (100, 105), (105, 102),
    )
    leaf_member_edges = (
        (20, 25, 0.0),
        (35, 40, -12.0), (40, 45, -12.0), (45, 47, -12.0),
        (55, 57, 0.0), (57, 60, 0.0),
        (95, 100, -12.0), (102, 105, 0.0),
    )
    internal_member_edges = ((15, 30, 0.0), (70, 90, 0.0))

    def colored_node(point: Point, key: int, red: bool, opacity: float = 1.0) -> str:
        glow = RB_RED_GLOW if red else RB_BLACK_GLOW
        fill, rim = (RB_RED, RB_RED_GLOW) if red else (RB_BLACK_FILL, RB_BLACK_INK)
        left = point[0] - node_half
        top = point[1] - node_h / 2.0
        body = bloom_rect(point, node_w, node_h, glow, opacity * 0.85, radius=9.0)
        body += (
            f'<rect x="{left:.1f}" y="{top:.1f}" width="{node_w:.1f}" height="{node_h:.1f}" '
            f'rx="9" fill="{fill}" stroke="{rim}" stroke-width="1.8" opacity="{opacity:.3f}"/>'
        )
        return body + (
            f'<text x="{point[0]:.1f}" y="{point[1]:.1f}" fill="#FFFFFF" font-size="19" font-weight="600" '
            f'text-anchor="middle" dominant-baseline="middle" font-family="Noto Sans CJK SC,system-ui,sans-serif" '
            f'opacity="{opacity:.3f}">{key}</text>'
        )

    def group_points(positions: Mapping[int, Point], name: str) -> tuple[Point, ...]:
        keys, _center = groups[name]
        return tuple(positions[key] for key in keys)

    def lower_gap(points: Sequence[Point], slot: int) -> Point:
        if slot == 0:
            x = points[0][0] - node_half
        elif slot == len(points):
            x = points[-1][0] + node_half
        else:
            x = (points[slot - 1][0] + points[slot][0]) / 2.0
        return x, points[0][1] + node_h / 2.0

    def btree_surface_edges(
        positions: Mapping[int, Point],
        opacity: float,
        parents: Sequence[str] | None = None,
        slots_by_parent: Mapping[str, Sequence[int]] | None = None,
    ) -> str:
        body: list[str] = []
        source_parents = parents if parents is not None else tuple(child_groups)
        for parent in source_parents:
            children = child_groups[parent]
            for slot, child in enumerate(children):
                if slots_by_parent is not None and slot not in slots_by_parent.get(parent, ()):
                    continue
                child_black = positions[black_key[child]]
                body.append(glow_line(
                    lower_surface_gap(positions, parent, slot),
                    (child_black[0], child_black[1] - node_h / 2.0),
                    color=INK,
                    bloom=GLOW_WHITE,
                    width=3.4,
                    radius=0.0,
                    opacity=opacity,
                ))
        return "".join(body)

    def stable_red_child_edges(positions: Mapping[int, Point]) -> str:
        """Keep each red member's two child routes as one persistent edge."""
        return binary_edge_body(
            positions,
            ((15, 5), (15, 20), (70, 57), (70, 75)),
            1.0,
        )

    def stable_root_edges(positions: Mapping[int, Point]) -> str:
        """Keep the two root routes attached to the root and child nodes."""
        return binary_edge_body(positions, ((50, 30), (50, 90)), 1.0)

    def stable_black_child_edges(positions: Mapping[int, Point]) -> str:
        """Draw the child route owned by each internal black member."""
        return binary_edge_body(positions, ((30, 45), (90, 100)), 1.0)

    def lower_surface_gap(positions: Mapping[int, Point], node_id: str, slot: int) -> Point:
        """Return a B-tree child gap after its keys have split into cards.

        Red members own two adjacent child gaps, so both outgoing lines track
        that red card when it separates. A black member owns only the outer
        gap on its side; a one-key black node owns its usual two outer gaps.
        """
        keys, _center = groups[node_id]
        points = group_points(positions, node_id)
        if len(keys) == 1:
            return lower_gap(points, slot)

        black_index = keys.index(black_key[node_id])
        if len(keys) == 2:
            if black_index == 0:
                # [black, red]: black-left, red-left, red-right.
                anchors = (
                    points[0][0] - node_half,
                    points[1][0] - node_half,
                    points[1][0] + node_half,
                )
                owners = (0, 1, 1)
            else:
                # [red, black]: red-left, red-right, black-right.
                anchors = (
                    points[0][0] - node_half,
                    points[0][0] + node_half,
                    points[1][0] + node_half,
                )
                owners = (0, 0, 1)
        elif len(keys) == 3 and black_index == 1:
            # [red, black, red]: each red member supplies its two gaps.
            anchors = (
                points[0][0] - node_half,
                points[0][0] + node_half,
                points[2][0] - node_half,
                points[2][0] + node_half,
            )
            owners = (0, 0, 2, 2)
        else:
            # Temporary four-key overflow nodes have no children in this
            # scene; preserve a sensible fallback for future reuse.
            return lower_gap(points, slot)
        owner = points[owners[slot]]
        return anchors[slot], owner[1] + node_h / 2.0

    def horizontal_edge(
        positions: Mapping[int, Point],
        edge: tuple[int, int, float],
        opacity: float,
    ) -> str:
        left_key, right_key, lane = edge
        left, right = sorted((positions[left_key][0], positions[right_key][0]))
        y = positions[left_key][1] + lane
        return glow_line(
            (left + node_half, y),
            (right - node_half, y),
            color=INK,
            bloom=GLOW_WHITE,
            width=3.4,
            radius=0.0,
            opacity=opacity,
        )

    def blue_tree(opacity: float) -> str:
        body = btree_surface_edges(initial_positions, opacity)
        for keys, center in groups.values():
            row, _slots = btree_neon_row(
                tuple(str(key) for key in keys),
                center,
                overflow=len(keys) == 4,
            )
            body += f'<g opacity="{opacity:.3f}">{row}</g>'
        return body

    def colored_btree(opacity: float) -> str:
        """Stage one: colour while preserving B-tree surface routing."""
        body = btree_surface_edges(initial_positions, opacity)
        return body + "".join(
            colored_node(initial_positions[key], key, key in source_red, opacity)
            for key in sorted(initial_positions)
        )

    def colored_flat(positions: Mapping[int, Point], opacity: float) -> str:
        # Existing member and root links use node boundaries from this stage
        # onward. They therefore keep the same attachment when an internal
        # member later moves into its binary position.
        body = btree_surface_edges(
            positions,
            opacity,
            parents=("left", "right"),
            slots_by_parent={"left": (2,), "right": (2,)},
        )
        body += binary_edge_body(
            positions,
            ((50, 30), (50, 90), (30, 15), (90, 70),
             (15, 5), (15, 20), (70, 57), (70, 75)),
            opacity,
        )
        body += "".join(horizontal_edge(positions, edge, opacity) for edge in member_edges)
        body += "".join(colored_node(positions[key], key, key in source_red, opacity) for key in sorted(positions))
        body += "".join(horizontal_edge(positions, edge, opacity) for edge in overlay_member_edges)
        return body

    def binary_edge_body(
        positions: Mapping[int, Point],
        edges: Sequence[tuple[int, int]],
        opacity: float,
    ) -> str:
        return "".join(
            rb_edge_fragment(positions[parent], positions[child], opacity, False)
            for parent, child in edges
        )

    def route_edge(
        positions: Mapping[int, Point],
        parent_key: int,
        child_key: int,
    ) -> str:
        """Draw an edge whose endpoints are owned by the current key nodes."""
        x1, y1, x2, y2 = _box_trim(positions[parent_key], positions[child_key])
        return glow_line((x1, y1), (x2, y2), color=INK, bloom=GLOW_WHITE, width=3.4, radius=0.0)

    def route_edges(positions: Mapping[int, Point]) -> str:
        routes = (
            (50, 30), (50, 90),
            (15, 5), (15, 20), (30, 45),
            (70, 57), (70, 75), (90, 100),
        )
        return "".join(route_edge(positions, *route) for route in routes)

    def colored_binary_nodes(positions: Mapping[int, Point]) -> str:
        # Binary conversion never changes colours. It is intentionally allowed
        # to leave red-red links for the following repair stage.
        return "".join(
            colored_node(positions[key], key, key in source_red)
            for key in sorted(positions)
        )

    def frame(body: str) -> str:
        return svg(body, width=width, height=height, color=INK)

    frames: list[str] = [frame(blue_tree(1.0))] * 32

    # Step 1: colour each member without changing the B-tree's routing shape.
    for step in range(1, 43):
        t = ease(step / 42.0)
        frames.append(frame(blue_tree(1.0 - t) + colored_btree(t)))
    frames.extend([frame(colored_btree(1.0))] * 20)

    # Step 1b: while every B-tree node is still compact, make its internal
    # member links continuous. This gives the temporary four-key overflow its
    # crossing link before the keys start to move apart.
    for step in range(1, 25):
        t = ease(step / 24.0)
        frames.append(frame(colored_btree(1.0 - t) + colored_flat(initial_positions, t)))
    frames.extend([frame(colored_flat(initial_positions, 1.0))] * 36)

    # Step 2: every B-tree node opens at the same time. It is one global
    # operation, not a level-by-level change.
    for step in range(1, 49):
        t = ease(step / 48.0)
        positions = {
            key: lerp_point(initial_positions[key], flat_positions[key], t)
            for key in initial_positions
        }
        frames.append(frame(colored_flat(positions, 1.0)))
    frames.extend([frame(colored_flat(flat_positions, 1.0))] * 38)

    # Step 3a: descend from the root by converting the two source nodes on the
    # next B-tree level. Their outgoing routes remain attached to the still
    # compact leaf B-tree nodes until that lower level is converted.
    internal_source_keys = (15, 30, 70, 90)
    root_binary_edges = ((50, 30), (50, 90))
    internal_binary_edges = ((30, 15), (90, 70))
    # These member links exist before and after leaf conversion. One geometry
    # function owns each link throughout so no line fragment gets stranded.
    persistent_leaf_member_edges = (
        (20, 25), (35, 40), (40, 45), (45, 47),
        (55, 57), (57, 60), (95, 100), (100, 105), (105, 102),
    )
    for step in range(1, 61):
        t = ease(step / 60.0)
        positions = {
            key: lerp_point(flat_positions[key], final_positions[key], t)
            if key in internal_source_keys else flat_positions[key]
            for key in flat_positions
        }
        # The two multi-key parents are only converting their internal
        # member links in this stage. Their red members still own the left and
        # right B-tree child slots, so keep those lines attached to the same
        # slots while the black members move upward.
        body = stable_root_edges(positions)
        body += stable_red_child_edges(positions)
        body += stable_black_child_edges(positions)
        # [15,30] and [70,90] keep the same relationship in binary form.
        # Draw one endpoint-following edge for each from the first moving frame.
        body += binary_edge_body(positions, internal_binary_edges, 1.0)
        body += "".join(horizontal_edge(positions, edge, 1.0) for edge in leaf_member_edges)
        body += "".join(horizontal_edge(positions, edge, 1.0) for edge in overlay_member_edges)
        body += colored_binary_nodes(positions)
        frames.append(frame(body))

    internal_binary_positions = {
        key: final_positions[key] if key in internal_source_keys else flat_positions[key]
        for key in flat_positions
    }
    internal_binary_body = (
        stable_root_edges(internal_binary_positions)
        + stable_red_child_edges(internal_binary_positions)
        + stable_black_child_edges(internal_binary_positions)
        + "".join(horizontal_edge(internal_binary_positions, edge, 1.0) for edge in leaf_member_edges)
        + "".join(horizontal_edge(internal_binary_positions, edge, 1.0) for edge in overlay_member_edges)
        + binary_edge_body(internal_binary_positions, internal_binary_edges, 1.0)
        + colored_binary_nodes(internal_binary_positions)
    )
    frames.extend([frame(internal_binary_body)] * 20)

    # Step 3b: only after the internal source nodes are binary, convert the
    # compact leaf B-tree nodes. Their former parent routes fade continuously
    # into their final binary edges; no node becomes temporarily disconnected.
    leaf_keys = tuple(key for key in final_positions if key not in {50, *internal_source_keys})
    for step in range(1, 73):
        t = ease(step / 72.0)
        positions = {
            key: lerp_point(internal_binary_positions[key], final_positions[key], t)
            if key in leaf_keys else internal_binary_positions[key]
            for key in flat_positions
        }
        body = stable_root_edges(positions)
        body += stable_red_child_edges(positions)
        body += stable_black_child_edges(positions)
        # Member links are structural edges too: recompute their endpoints
        # from the current node positions on every frame.
        body += binary_edge_body(
            positions,
            persistent_leaf_member_edges,
            1.0,
        )
        body += binary_edge_body(positions, internal_binary_edges, 1.0)
        body += colored_binary_nodes(positions)
        frames.append(frame(body))

    final_body = stable_root_edges(final_positions)
    final_body += stable_red_child_edges(final_positions)
    final_body += stable_black_child_edges(final_positions)
    final_body += binary_edge_body(final_positions, internal_binary_edges, 1.0)
    final_body += binary_edge_body(final_positions, persistent_leaf_member_edges, 1.0)
    final_body += colored_binary_nodes(final_positions)
    frames.extend([frame(final_body)] * 75)
    render_webm("rb-encoding", frames, fps=30, transparent=True, crop_pad=24)


def rb_encoding() -> None:
    """B 树外观(蓝白) -> 染色 -> 拉伸 -> 逐层展开, one continuous morph.

    Edges are strictly subordinate to nodes: each of the nineteen lines is a
    pure function of the current positions of the two nodes it connects.
    Nothing about an edge is animated directly -- node distance grows, the
    edge grows; the node geometry turns, the edge turns with it.
    """
    width, height = 1400, 700
    groups = {
        "root": ((50,), (700.0, 86.0)),
        "left": ((15, 30), (350.0, 242.0)),
        "right": ((70, 90), (1050.0, 242.0)),
        "l0": ((5,), (90.0, 464.0)),
        "l1": ((20, 25), (250.0, 464.0)),
        "l2": ((35, 40, 45, 47), (490.0, 464.0)),
        "r0": ((55, 57, 60), (760.0, 464.0)),
        "r1": ((75,), (900.0, 464.0)),
        "r2": ((95, 100, 102, 105), (1140.0, 464.0)),
    }
    compact = {
        key: point
        for keys, center in groups.values()
        for key, point in zip(keys, btree_neon_slots(center, len(keys)), strict=True)
    }

    def spread_row(keys: tuple[int, ...], center: Point) -> dict[int, Point]:
        if len(keys) == 1:
            return {keys[0]: center}
        step = 88.0
        x0 = center[0] - step * (len(keys) - 1) / 2
        return {key: (x0 + i * step, center[1]) for i, key in enumerate(keys)}

    # Stretch layout keeps every pair of cells >=12px apart across group
    # boundaries, so neighbouring rows never collide while spread.
    spread_centers = {
        "root": (700.0, 86.0),
        "left": (350.0, 242.0),
        "right": (1050.0, 242.0),
        "l0": (90.0, 464.0),
        "l1": (202.0, 464.0),
        "l2": (534.0, 464.0),
        "r0": (822.0, 464.0),
        "r1": (978.0, 464.0),
        "r2": (1178.0, 464.0),
    }
    spread = {
        key: point
        for name, (keys, _) in groups.items()
        for key, point in spread_row(keys, spread_centers[name]).items()
    }
    final = {
        50: (700.0, 76.0),
        30: (390.0, 204.0), 90: (1010.0, 204.0),
        15: (230.0, 332.0), 45: (550.0, 332.0),
        70: (850.0, 332.0), 100: (1170.0, 332.0),
        5: (100.0, 464.0), 20: (315.0, 464.0), 40: (470.0, 464.0),
        47: (630.0, 464.0), 57: (780.0, 464.0), 75: (920.0, 464.0),
        95: (1050.0, 464.0), 105: (1240.0, 464.0),
        25: (345.0, 590.0), 35: (440.0, 590.0),
        55: (735.0, 590.0), 60: (825.0, 590.0), 102: (1170.0, 590.0),
    }
    red_keys = {15, 70, 25, 35, 40, 47, 55, 60, 95, 102, 105}
    # Bottom-up expansion: the leaf rows disband first, the upper levels
    # (reds 15/70 dropping, blacks 30/90/50 rising) settle afterwards.
    wave1_keys = {5, 20, 25, 35, 40, 45, 47, 55, 57, 60, 75, 95, 100, 102, 105}

    color_win = (30, 75)
    stretch_win = (93, 153)
    wave1_win = (171, 261)
    wave2_win = (279, 369)
    total = 417

    def seg(f: int, a: int, b: int) -> float:
        if f <= a:
            return 0.0
        if f >= b:
            return 1.0
        u = (f - a) / (b - a)
        return u * u * (3.0 - 2.0 * u)

    def position(key: int, f: int) -> Point:
        base = lerp_point(compact[key], spread[key], seg(f, *stretch_win))
        window = wave1_win if key in wave1_keys else wave2_win
        return lerp_point(base, final[key], seg(f, *window))

    # Each route is (parent, child, semantic side of the child). The same
    # pure rule renders every stage: with both keys on one row the anchors
    # degenerate to the facing sides (horizontal through-line), and as the
    # child descends they slide along the node borders into the binary
    # parent-child edge -- bottom far-corner on the parent, top-centre on
    # the child. 100 -> 105 uses the raised lane over 102 while the row is
    # flat, then follows the same geometry as 100 rises.
    routes = (
        (50, 30, -1.0), (50, 90, +1.0),
        (30, 15, -1.0), (30, 45, +1.0),
        (15, 5, -1.0), (15, 20, +1.0), (20, 25, +1.0),
        (45, 40, -1.0), (45, 47, +1.0), (40, 35, -1.0),
        (90, 70, -1.0), (90, 100, +1.0),
        (70, 57, -1.0), (70, 75, +1.0),
        (57, 55, -1.0), (57, 60, +1.0),
        (100, 95, -1.0), (100, 105, +1.0), (105, 102, -1.0),
    )

    def frame(f: int) -> str:
        pos = {key: position(key, f) for key in compact}
        blend = seg(f, *color_win)
        body = ""
        for parent, child, side in routes:
            a, b = pos[parent], pos[child]
            hinge = min(abs(b[1] - a[1]) / (RB_NODE_H + 20.0), 1.0)
            inset = (1.0 - hinge) * 4.0
            if parent == 100 and child == 105:
                # The semantic 100 -> 105 through-line rides a lane just above
                # the member links (hidden behind 102), then rotates into the
                # binary edge as the pair separates.
                lane = (1.0 - hinge) * 10.0
                start = (a[0] + side * (RB_NODE_W / 2 - inset), a[1] + hinge * RB_NODE_H / 2 - lane)
                end = (b[0] - side * (RB_NODE_W / 2 - inset) * (1.0 - hinge), b[1] - hinge * RB_NODE_H / 2 - lane)
            else:
                start = (a[0] + side * (RB_NODE_W / 2 - inset), a[1] + hinge * RB_NODE_H / 2)
                end = (b[0] - side * (RB_NODE_W / 2 - inset) * (1.0 - hinge), b[1] - hinge * RB_NODE_H / 2)
            length = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
            opacity = min(1.0, length / 24.0)
            if opacity <= 0.0:
                continue
            if blend < 1.0:
                body += glow_line(
                    start, end, opacity=opacity * (1.0 - blend),
                    color=INK, bloom=GLOW_BLUE, width=3.4, radius=0.0,
                )
            if blend > 0.0:
                body += glow_line(
                    start, end, opacity=opacity * blend,
                    color=INK, bloom=GLOW_WHITE, width=3.4, radius=0.0,
                )
        if blend < 1.0:
            for keys, _ in groups.values():
                body += btree_neon_row_at_positions(
                    [str(key) for key in keys],
                    [pos[key] for key in keys],
                    opacity=1.0 - blend,
                )
        if blend > 0.0:
            for key in sorted(pos):
                body += rb_node(pos[key], str(key), opacity=blend, red=key in red_keys)
        return svg(body, width=width, height=height, color=INK)

    render_webm(
        "rb-encoding",
        [frame(f) for f in range(total)],
        fps=30,
        transparent=True,
        crop_pad=24,
    )


def rb_encoding_static_assets() -> None:
    """Render flat B-tree-style snapshots between multiway and binary views."""
    node_width = BTREE_NEON_CELL_W
    node_height = BTREE_NEON_CELL_H
    node_half = node_width / 2.0

    # Each edge is (left key, right key, vertical lane). The lane changes only
    # where two links would otherwise overlap; every key itself stays level.
    def flat_link(start: Point, end: Point, lane: float) -> str:
        left, right = sorted((start[0], end[0]))
        y = start[1] + lane
        return glow_line(
            (left + node_half, y),
            (right - node_half, y),
            color=INK,
            bloom=GLOW_WHITE,
            width=3.4,
            radius=0.0,
        )

    def flat_node(point: Point, key: str, red: bool) -> str:
        x, y = point
        glow = RB_RED_GLOW if red else RB_BLACK_GLOW
        fill, rim = (RB_RED, RB_RED_GLOW) if red else (RB_BLACK_FILL, RB_BLACK_INK)
        body = bloom_rect(point, node_width, node_height, glow, 0.85, radius=9.0)
        body += (
            f'<rect x="{x - node_half:.1f}" y="{y - node_height / 2.0:.1f}" '
            f'width="{node_width:.1f}" height="{node_height:.1f}" rx="9" '
            f'fill="{fill}" stroke="{rim}" stroke-width="1.8"/>'
        )
        return body + (
            f'<text x="{x:.1f}" y="{y:.1f}" fill="{INK}" font-size="19" font-weight="600" '
            f'text-anchor="middle" dominant-baseline="middle" '
            f'font-family="Noto Sans CJK SC,system-ui,sans-serif">{esc(key)}</text>'
        )

    def flat_body(
        nodes: Sequence[tuple[str, Point, bool]],
        edges: Sequence[tuple[str, str, float]],
        *,
        dx: float = 0.0,
        dy: float = 0.0,
        overlay_edges: Sequence[tuple[str, str, float]] = (),
    ) -> str:
        positions = {
            key: (point[0] + dx, point[1] + dy)
            for key, point, _red in nodes
        }
        body = "".join(
            flat_link(positions[left], positions[right], lane)
            for left, right, lane in edges
        )
        # Every link belongs behind the nodes, including a direct link that
        # passes behind an intervening key. This matches the video layering.
        body += "".join(
            flat_link(positions[left], positions[right], lane)
            for left, right, lane in overlay_edges
        )
        body += "".join(
            flat_node(positions[key], key, red)
            for key, _point, red in nodes
        )
        return body

    def write_flat(
        name: str,
        nodes: Sequence[tuple[str, Point, bool]],
        edges: Sequence[tuple[str, str, float]],
        *,
        overlay_edges: Sequence[tuple[str, str, float]] = (),
        width: int,
        height: int,
    ) -> None:
        ASSETS.joinpath(name).write_text(
            svg(
                flat_body(nodes, edges, overlay_edges=overlay_edges),
                width=width,
                height=height,
                color=INK,
            ),
            encoding="utf-8",
        )

    single = (("b", (90.0, 86.0), False),)
    pair_left = (
        ("a", (80.0, 86.0), True),
        ("b", (200.0, 86.0), False),
    )
    pair_right = (
        ("a", (80.0, 86.0), False),
        ("b", (200.0, 86.0), True),
    )
    pair_edges = (("a", "b", 0.0),)
    triple = (
        ("a", (80.0, 86.0), True),
        ("b", (200.0, 86.0), False),
        ("c", (320.0, 86.0), True),
    )
    triple_edges = (("a", "b", 0.0), ("b", "c", 0.0))

    write_flat("rb-encoding-single.svg", single, (), width=180, height=160)
    write_flat("rb-encoding-pair-left.svg", pair_left, pair_edges, width=280, height=160)
    write_flat("rb-encoding-pair-right.svg", pair_right, pair_edges, width=280, height=160)
    write_flat("rb-encoding-triple.svg", triple, triple_edges, width=400, height=160)

    pair_body = flat_body(pair_left, pair_edges) + flat_body(pair_right, pair_edges, dx=320.0)
    ASSETS.joinpath("rb-encoding-pair.svg").write_text(
        svg(pair_body, width=600, height=160, color=INK),
        encoding="utf-8",
    )

    # Four keys are an overflow state. The four flat connection patterns are
    # the four sketches: the nodes remain in one row while a direct link can
    # cross an intervening node on a separate, explicitly overlaid lane.
    overflow_nodes = (
        ("a", (42.0, 94.0), True),
        ("b", (132.0, 94.0), True),
        ("c", (222.0, 94.0), False),
        ("d", (312.0, 94.0), True),
    )
    overflow_nodes_black_b = (
        ("a", (42.0, 94.0), True),
        ("b", (132.0, 94.0), False),
        ("c", (222.0, 94.0), True),
        ("d", (312.0, 94.0), True),
    )
    overflow_cases = (
        (
            overflow_nodes,
            (("a", "b", -12.0), ("b", "c", -12.0), ("c", "d", -12.0)),
            (),
        ),
        (
            overflow_nodes_black_b,
            (("a", "b", 0.0), ("b", "c", 0.0), ("c", "d", 0.0)),
            (),
        ),
        (
            overflow_nodes,
            (("a", "b", 14.0), ("c", "d", -14.0)),
            (("a", "c", -14.0),),
        ),
        (
            overflow_nodes_black_b,
            (("a", "b", -12.0), ("c", "d", 14.0)),
            (("b", "d", -12.0),),
        ),
    )
    for index, (nodes, edges, overlay_edges) in enumerate(overflow_cases, start=1):
        write_flat(
            f"rb-encoding-overflow-{index}.svg",
            nodes,
            edges,
            overlay_edges=overlay_edges,
            width=360,
            height=190,
        )
    overflow_body = "".join(
        flat_body(nodes, edges, dx=index * 372.0, overlay_edges=overlay_edges)
        for index, (nodes, edges, overlay_edges) in enumerate(overflow_cases)
    )
    ASSETS.joinpath("rb-encoding-overflow.svg").write_text(
        svg(overflow_body, width=1488, height=190, color=INK),
        encoding="utf-8",
    )


def rb_insert() -> None:
    """Insert into a sparse tree and hit every red-black insertion case.

    The tree is the abstract 2-3-4 view with red-black coloring: the
    leftmost key of a node is black, extra members are red, and a full
    4-node carries red members on both sides of its black middle.
    Structural edges leave the owning key's left or right lower side and land
    at the black key of the child group. Same-row member edges are drawn first,
    behind the keys, so an inserted red key can cover an existing through-line
    without turning that line into an independent moving object. Every overflow
    promotes the upper median (third of four keys), matching the B-tree
    chapter's split convention.

    52  black parent: the red key lands horizontally beside 51.  (父黑直挂)
    54  black uncle, straight line: first insert and fold while the
         old endpoints remain, then rotate to the single-line form,
         then recolour 52 black / 51 and 54 red.
    22  black uncle, zigzag: first insert 22 below 23 and fold it back
         into the row with the two old relations, then double-rotate
         to the single-line form, then recolour 22 black / 21 and 23 red.
    37  red uncle: the colour flip is a split; the promoted      (叔红)
         black keys cascade upward without changing any endpoint pair;
         each key turns red only after it reaches its next row, while
         the two split child connection keys turn black.
    """
    width, height = 1900, 820
    cell_w, cell_h = 54.0, 44.0
    inner_gap = 26.0
    stretch_gap = 78.0
    kid_gap = 78.0
    level_y = (104.0, 272.0, 440.0, 608.0)
    pre_shift = 146.0

    def N(keys, cols, kids=()):
        return (tuple(keys), tuple(cols), tuple(kids))

    def base_tree():
        return {
            "R": N((30, 49, 70), "rbr", ("A", "B", "C", "D")),
            "A": N((20,), "b", ("A0", "A1")),
            "A0": N((15,), "b"),
            "A1": N((21, 23), "br"),
            "B": N((35, 40, 45), "rbr", ("B0", "B1", "B2", "B3")),
            "B0": N((31,), "b"),
            "B1": N((36, 38, 39), "rbr"),
            "B2": N((42,), "b"),
            "B3": N((47,), "b"),
            "C": N((55,), "b", ("C0", "C1")),
            "C0": N((51,), "b"),
            "C1": N((57,), "b"),
            "D": N((80,), "b", ("D0", "D1")),
            "D0": N((75,), "b"),
            "D1": N((85,), "b"),
        }

    S: dict[str, dict] = {}
    S["s0"] = base_tree()
    tree = base_tree()
    tree["C0"] = N((51, 52), "br")
    S["s1"] = tree
    S["s1b"] = base_tree()
    S["s1b"]["C0"] = N((51, 52), "br")
    tree = base_tree()
    tree["C0"] = N((51, 52, 54), "brr")
    S["s2a"] = tree
    tree = base_tree()
    tree["C0"] = N((51, 52, 54), "rbr")
    S["s2b"] = tree
    tree = base_tree()
    tree["A1"] = N((21, 22, 23), "brr")
    tree["C0"] = N((51, 52, 54), "rbr")
    S["s3a"] = tree
    tree = base_tree()
    tree["A1"] = N((21, 22, 23), "rbr")
    tree["C0"] = N((51, 52, 54), "rbr")
    S["s3b"] = tree
    tree = base_tree()
    tree["A1"] = N((21, 22, 23), "rbr")
    tree["C0"] = N((51, 52, 54), "rbr")
    tree["B1"] = N((36, 37, 38, 39), "rrbr")
    S["s4a"] = tree
    tree = base_tree()
    tree["A1"] = N((21, 22, 23), "rbr")
    tree["C0"] = N((51, 52, 54), "rbr")
    tree["B"] = N((35, 38, 40, 45), "rbbr", ("B0", "B1L", "B1R", "B2", "B3"))
    tree.pop("B1")
    tree["B1L"] = N((36, 37), "rr")
    tree["B1R"] = N((39,), "r")
    S["s4c_pre"] = tree
    tree = base_tree()
    tree["A1"] = N((21, 22, 23), "rbr")
    tree["C0"] = N((51, 52, 54), "rbr")
    tree["B"] = N((35, 38, 40, 45), "rrbr", ("B0", "B1L", "B1R", "B2", "B3"))
    tree.pop("B1")
    tree["B1L"] = N((36, 37), "br")
    tree["B1R"] = N((39,), "b")
    S["s4c"] = tree
    tree = base_tree()
    tree["A1"] = N((21, 22, 23), "rbr")
    tree["C0"] = N((51, 52, 54), "rbr")
    tree["R"] = N((30, 40, 49, 70), "rbbr", ("A", "AL", "AR", "C", "D"))
    tree.pop("B")
    tree["AL"] = N((35, 38), "rr", ("B0", "B1L", "B1R"))
    tree["AR"] = N((45,), "r", ("B2", "B3"))
    tree.pop("B1")
    tree["B1L"] = N((36, 37), "br")
    tree["B1R"] = N((39,), "b")
    S["s4d_pre"] = tree
    tree = base_tree()
    tree["A1"] = N((21, 22, 23), "rbr")
    tree["C0"] = N((51, 52, 54), "rbr")
    tree["R"] = N((30, 40, 49, 70), "rrbr", ("A", "AL", "AR", "C", "D"))
    tree.pop("B")
    tree["AL"] = N((35, 38), "br", ("B0", "B1L", "B1R"))
    tree["AR"] = N((45,), "b", ("B2", "B3"))
    tree.pop("B1")
    tree["B1L"] = N((36, 37), "br")
    tree["B1R"] = N((39,), "b")
    S["s4d"] = tree
    tree = base_tree()
    tree["A1"] = N((21, 22, 23), "rbr")
    tree["C0"] = N((51, 52, 54), "rbr")
    tree.pop("R")
    tree["RT"] = N((49,), "b", ("RL", "RR"))
    tree["RL"] = N((30, 40), "rr", ("A", "AL", "AR"))
    tree["RR"] = N((70,), "r", ("C", "D"))
    tree.pop("B")
    tree["AL"] = N((35, 38), "br", ("B0", "B1L", "B1R"))
    tree["AR"] = N((45,), "b", ("B2", "B3"))
    tree.pop("B1")
    tree["B1L"] = N((36, 37), "br")
    tree["B1R"] = N((39,), "b")
    S["s4e_pre"] = tree
    tree = base_tree()
    tree["A1"] = N((21, 22, 23), "rbr")
    tree["C0"] = N((51, 52, 54), "rbr")
    tree.pop("R")
    tree["RT"] = N((49,), "b", ("RL", "RR"))
    tree["RL"] = N((30, 40), "br", ("A", "AL", "AR"))
    tree["RR"] = N((70,), "b", ("C", "D"))
    tree.pop("B")
    tree["AL"] = N((35, 38), "br", ("B0", "B1L", "B1R"))
    tree["AR"] = N((45,), "b", ("B2", "B3"))
    tree.pop("B1")
    tree["B1L"] = N((36, 37), "br")
    tree["B1R"] = N((39,), "b")
    S["s4e"] = tree
    tree = base_tree()
    tree["A1"] = N((21, 22, 23), "rbr")
    tree["C0"] = N((50, 51, 52, 54), "rrbr")
    tree.pop("R")
    tree["RT"] = N((49,), "b", ("RL", "RR"))
    tree["RL"] = N((30, 40), "br", ("A", "AL", "AR"))
    tree["RR"] = N((70,), "b", ("C", "D"))
    tree.pop("B")
    tree["AL"] = N((35, 38), "br", ("B0", "B1L", "B1R"))
    tree["AR"] = N((45,), "b", ("B2", "B3"))
    tree.pop("B1")
    tree["B1L"] = N((36, 37), "br")
    tree["B1R"] = N((39,), "b")
    S["s5a"] = tree
    tree = base_tree()
    tree["A1"] = N((21, 22, 23), "rbr")
    tree["C"] = N((52, 55), "bb", ("C0L", "C0R", "C1"))
    tree["C0L"] = N((50, 51), "rr")
    tree["C0R"] = N((54,), "r")
    tree.pop("C0")
    tree.pop("R")
    tree["RT"] = N((49,), "b", ("RL", "RR"))
    tree["RL"] = N((30, 40), "br", ("A", "AL", "AR"))
    tree["RR"] = N((70,), "b", ("C", "D"))
    tree.pop("B")
    tree["AL"] = N((35, 38), "br", ("B0", "B1L", "B1R"))
    tree["AR"] = N((45,), "b", ("B2", "B3"))
    tree.pop("B1")
    tree["B1L"] = N((36, 37), "br")
    tree["B1R"] = N((39,), "b")
    S["s5b_pre"] = tree
    tree = base_tree()
    tree["A1"] = N((21, 22, 23), "rbr")
    tree["C"] = N((52, 55), "rb", ("C0L", "C0R", "C1"))
    tree["C0L"] = N((50, 51), "rb")
    tree["C0R"] = N((54,), "b")
    tree.pop("C0")
    tree.pop("R")
    tree["RT"] = N((49,), "b", ("RL", "RR"))
    tree["RL"] = N((30, 40), "br", ("A", "AL", "AR"))
    tree["RR"] = N((70,), "b", ("C", "D"))
    tree.pop("B")
    tree["AL"] = N((35, 38), "br", ("B0", "B1L", "B1R"))
    tree["AR"] = N((45,), "b", ("B2", "B3"))
    tree.pop("B1")
    tree["B1L"] = N((36, 37), "br")
    tree["B1R"] = N((39,), "b")
    S["s5b"] = tree

    def subtree_span(tree, nid, stretch=None):
        """Width and in-order key centres of a subtree, measured from 0.

        Every key sits exactly on the boundary between the child spans
        that surround it in sorted order, so each key is mounted above
        its own in-order gap, as in the red-black tree itself.
        """
        keys, cols, kids = tree[nid]
        if not kids:
            centers = []
            cursor = 0.0
            for key in keys:
                centers.append(cursor + cell_w / 2)
                cursor += cell_w + inner_gap
                if stretch and stretch[0] == nid and key == stretch[1]:
                    cursor += stretch[2]
            return cursor - inner_gap, centers
        spans = [subtree_span(tree, kid, stretch) for kid in kids]
        starts = []
        cursor = 0.0
        for kid_width, _ in spans:
            starts.append(cursor)
            cursor += kid_width + kid_gap
        total = cursor - kid_gap
        centers = [starts[j] + spans[j][0] + kid_gap / 2 for j in range(len(keys))]
        # Geometry is independent of colour. Recolouring must never move a key
        # or indirectly change any edge endpoint.
        return total, centers

    def layout(tree, grown, stretch=None):
        pos: dict[str, Point] = {}
        root = next(nid for nid in tree if nid in ("R", "RT"))
        total, _ = subtree_span(tree, root, stretch)

        def place(nid, left, depth):
            keys, cols, kids = tree[nid]
            y = level_y[depth] + (0.0 if grown else pre_shift)
            span_width, _ = subtree_span(tree, nid, stretch)
            cursor = left
            for kid in kids:
                cursor += place(kid, cursor, depth + 1) + kid_gap
            pos[nid] = (left + span_width / 2, y)
            return span_width

        place(root, (width - total) / 2, 0)
        return pos

    def key_centers(tree, nid, pos, stretch=None):
        span_width, centers = subtree_span(tree, nid, stretch)
        anchor = pos[nid][0] - span_width / 2
        return [c + anchor for c in centers]

    def spread_bloom(tree, nid, pos, stretch, opacity):
        centers = key_centers(tree, nid, pos, stretch)
        cx = (centers[0] + centers[-1]) / 2
        return bloom_rect(
            (cx, pos[nid][1]), centers[-1] - centers[0] + cell_w, cell_h,
            GLOW_RED, opacity, radius=12.0,
        )

    def tokens(tree, pos, stretch=None):
        out: dict[int, tuple[float, float, str]] = {}
        for nid, (keys, cols, kids) in tree.items():
            centers = key_centers(tree, nid, pos, stretch)
            y = pos[nid][1]
            for key, col, cx in zip(keys, cols, centers):
                out[key] = (cx, y, col)
        return out

    def square(x, y, value, col, opacity):
        red = col == "r"
        glow = RB_RED_GLOW if red else RB_BLACK_GLOW
        fill, rim = (RB_RED, RB_RED_GLOW) if red else (RB_BLACK_FILL, RB_BLACK_INK)
        left, top = x - cell_w / 2, y - cell_h / 2
        body = bloom_rect((x, y), cell_w, cell_h, glow, opacity * 0.85, radius=9.0)
        body += (
            f'<rect fill="{fill}" stroke="{rim}" stroke-width="1.8" opacity="{opacity:.3f}" '
            f'x="{left:.1f}" y="{top:.1f}" width="{cell_w:.1f}" height="{cell_h:.1f}" rx="9"/>'
        )
        return body + (
            f'<text x="{x:.1f}" y="{y + 1.0:.1f}" fill="#FFFFFF" font-size="19" font-weight="600" '
            f'text-anchor="middle" dominant-baseline="middle" '
            f'font-family="Noto Sans CJK SC,system-ui,sans-serif" '
            f'opacity="{opacity:.3f}">{esc(str(value))}</text>'
        )

    def caption(text):
        return (
            f'<text x="{width / 2:.1f}" y="48" fill="{INK}" font-size="30" font-weight="600" '
            f'text-anchor="middle" '
            f'font-family="Noto Sans CJK SC,system-ui,sans-serif">{esc(text)}</text>'
        )

    frames: list[str] = []

    def semantic_edge_fragment(parent_key, child_key, tk, opacity=1.0, lane=0.0):
        """Draw one persistent parent/child relation from current node positions.

        The endpoint pair is the identity of the edge.  Geometry is derived
        from those two nodes only.  A lane is an explicit property of this
        relation in a temporary folded state; it makes overlapping old edges
        visible without changing either endpoint pair.
        """
        if parent_key not in tk or child_key not in tk or opacity <= 0.0:
            return ""
        px, py = tk[parent_key][:2]
        cx, cy = tk[child_key][:2]
        side = -1.0 if cx < px else 1.0
        hinge = min(abs(cy - py) / (cell_h + 20.0), 1.0)
        inset = (1.0 - hinge) * 4.0

        # A same-row relation is a through-line.  Its explicit lane is part of
        # the temporary visual state, not a route inferred from other nodes.
        start = (
            px + side * (cell_w / 2.0 - inset),
            py + hinge * cell_h / 2.0 - lane * (1.0 - hinge),
        )
        end = (
            cx - side * (cell_w / 2.0 - inset) * (1.0 - hinge),
            cy - hinge * cell_h / 2.0 - lane * (1.0 - hinge),
        )
        length = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
        return glow_line(
            start,
            end,
            color=INK,
            bloom=GLOW_WHITE,
            width=3.2,
            radius=0.0,
            opacity=opacity * min(1.0, length / 22.0),
        )

    def overflow_rows(tree):
        return {tuple(keys) for keys, _cols, _kids in tree.values() if len(keys) >= 4}

    def semantic_scene(tk, edges, *, caption_text=None, row_opacity=None, node_opacity=None,
                       edge_lanes=None):
        """Render explicit edge identities first and nodes afterwards."""
        row_opacity = row_opacity or {}
        node_opacity = node_opacity or {}
        parts: list[str] = []
        for keys, opacity in row_opacity.items():
            visible = [tk[key] for key in keys if key in tk]
            if len(visible) != len(keys) or opacity <= 0.0:
                continue
            xs = [token[0] for token in visible]
            ys = [token[1] for token in visible]
            parts.append(bloom_rect(
                ((min(xs) + max(xs)) / 2.0, sum(ys) / len(ys)),
                max(xs) - min(xs) + cell_w,
                cell_h,
                GLOW_RED,
                0.8 * opacity,
                radius=12.0,
            ))
        for edge in edges:
            if len(edge) == 2:
                parent, child = edge
                opacity = 1.0
            else:
                parent, child, opacity = edge
            lane = 0.0 if edge_lanes is None else edge_lanes.get(frozenset((parent, child)), 0.0)
            parts.append(semantic_edge_fragment(parent, child, tk, opacity, lane))
        for key in sorted(tk):
            x, y, col_a, *rest = tk[key]
            opacity = node_opacity.get(key, 1.0)
            if rest:
                col_b, blend = rest
                if col_a == col_b:
                    parts.append(square(x, y, key, col_b, opacity))
                else:
                    parts.append(square(x, y, key, col_a, opacity * (1.0 - blend)))
                    parts.append(square(x, y, key, col_b, opacity * blend))
            else:
                parts.append(square(x, y, key, col_a, opacity))
        return svg("".join(parts), width=width, height=height, color=INK)

    def snapshot(tree, *, grown=False, stretch=None):
        return tokens(tree, layout(tree, grown, stretch), stretch)

    def row_mix(tree_a, tree_b, t):
        old_rows = overflow_rows(tree_a)
        new_rows = overflow_rows(tree_b)
        rows = {keys: 1.0 for keys in old_rows & new_rows}
        rows.update({keys: 1.0 - t for keys in old_rows - new_rows})
        rows.update({keys: t for keys in new_rows - old_rows})
        return rows

    def hold_semantic(tree, edges, n, *, grown=False, stretch=None, caption_text=None,
                      edge_lanes=None):
        tk = snapshot(tree, grown=grown, stretch=stretch)
        rows = {keys: 1.0 for keys in overflow_rows(tree)}
        frame = semantic_scene(
            tk, edges, caption_text=caption_text, row_opacity=rows, edge_lanes=edge_lanes,
        )
        frames.extend([frame] * n)

    def animate_semantic(tree_a, tree_b, edges, n, *, grown_a=False, grown_b=False,
                         stretch_a=None, stretch_b=None, caption_text=None,
                         recolor=True, edge_lanes=None,
                         edge_lanes_a=None, edge_lanes_b=None):
        tk_a = snapshot(tree_a, grown=grown_a, stretch=stretch_a)
        tk_b = snapshot(tree_b, grown=grown_b, stretch=stretch_b)
        if tk_a.keys() != tk_b.keys():
            raise ValueError("semantic animation requires the same key identities")
        if edge_lanes is not None and (edge_lanes_a is not None or edge_lanes_b is not None):
            raise ValueError("use either fixed or interpolated edge lanes")
        for step in range(1, n + 1):
            t = ease(step / n)
            live = {}
            for key, (bx, by, col_b) in tk_b.items():
                ax, ay, col_a = tk_a[key]
                live[key] = (
                    ax + (bx - ax) * t,
                    ay + (by - ay) * t,
                    col_a,
                    col_b if recolor else col_a,
                    t if recolor else 0.0,
                )
            live_lanes = edge_lanes
            if edge_lanes_a is not None or edge_lanes_b is not None:
                lanes_a = edge_lanes_a or {}
                lanes_b = edge_lanes_b or {}
                live_lanes = {
                    pair: lanes_a.get(pair, 0.0) +
                    (lanes_b.get(pair, 0.0) - lanes_a.get(pair, 0.0)) * t
                    for pair in lanes_a.keys() | lanes_b.keys()
                }
            frames.append(semantic_scene(
                live,
                edges,
                caption_text=caption_text,
                row_opacity=row_mix(tree_a, tree_b, t),
                edge_lanes=live_lanes,
            ))

    def move_semantic(tree_a, tree_b, edges, n, *, grown_a=False, grown_b=False,
                      stretch_a=None, stretch_b=None, caption_text=None, edge_lanes=None,
                      edge_lanes_a=None, edge_lanes_b=None):
        """Move nodes while keeping their colours and endpoint pairs fixed."""
        animate_semantic(
            tree_a, tree_b, edges, n,
            grown_a=grown_a, grown_b=grown_b,
            stretch_a=stretch_a, stretch_b=stretch_b,
            caption_text=caption_text, recolor=False, edge_lanes=edge_lanes,
            edge_lanes_a=edge_lanes_a, edge_lanes_b=edge_lanes_b,
        )

    def recolor_semantic(tree_a, tree_b, edges, n, *, grown=False, stretch=None,
                         caption_text=None, edge_lanes=None):
        """Change colours after geometry/topology has already settled."""
        before = snapshot(tree_a, grown=grown, stretch=stretch)
        after = snapshot(tree_b, grown=grown, stretch=stretch)
        if any(before[key][:2] != after[key][:2] for key in before):
            raise ValueError("recolour phase must not move node coordinates")
        animate_semantic(
            tree_a, tree_b, edges, n,
            grown_a=grown, grown_b=grown, stretch_a=stretch, stretch_b=stretch,
            caption_text=caption_text,
            edge_lanes=edge_lanes,
        )

    def insert_and_fold(tree_a, tree_b, edges_before, edges_after, value, parent_key, side, stretch_key,
                        *, caption_text, edge_lanes_after=None, grown=False):
        """Insert as a real BST child, then fold it into the member row."""
        src_st = stretch_src(stretch_key)
        dst_st = stretch_dst(stretch_key)
        animate_semantic(
            tree_a, tree_a, edges_before, 14,
            grown_a=grown, grown_b=grown, stretch_b=src_st, caption_text=caption_text,
        )
        base = snapshot(tree_a, grown=grown, stretch=src_st)
        destination = snapshot(tree_b, grown=grown, stretch=dst_st)
        px, py = base[parent_key][:2]
        child_point = (px + side * 72.0, py + 104.0)
        start_point = (px + side * 14.0, py + cell_h / 2.0 + 4.0)
        new_pair = frozenset((parent_key, value))

        for step in range(1, 19):
            t = ease(step / 18.0)
            live = dict(base)
            x, y = lerp_point(start_point, child_point, t)
            live[value] = (x, y, "r")
            edge_frames = [
                (parent, child, t if frozenset((parent, child)) == new_pair else 1.0)
                for parent, child in edges_after
            ]
            frames.append(semantic_scene(
                live,
                edge_frames,
                caption_text=caption_text,
                node_opacity={value: t},
                edge_lanes=edge_lanes_after,
            ))
        child_tk = dict(base)
        child_tk[value] = (*child_point, "r")
        child_frame = semantic_scene(
            child_tk, edges_after, caption_text=caption_text, edge_lanes=edge_lanes_after,
        )
        frames.extend([child_frame] * 14)

        for step in range(1, 29):
            t = ease(step / 28.0)
            live = {}
            for key, (bx, by, col_b) in destination.items():
                if key == value:
                    ax, ay, col_a = (*child_point, "r")
                else:
                    ax, ay, col_a = base[key]
                live[key] = (
                    ax + (bx - ax) * t,
                    ay + (by - ay) * t,
                    col_a,
                    col_b,
                    t,
                )
            frames.append(semantic_scene(
                live,
                edges_after,
                caption_text=caption_text,
                row_opacity={keys: t for keys in overflow_rows(tree_b)},
                edge_lanes=edge_lanes_after,
            ))
        hold_semantic(
            tree_b, edges_after, 18, grown=grown, stretch=dst_st, caption_text=caption_text,
            edge_lanes=edge_lanes_after,
        )
        animate_semantic(
            tree_b, tree_b, edges_after, 18,
            grown_a=grown, grown_b=grown, stretch_a=dst_st,
            caption_text=caption_text, edge_lanes=edge_lanes_after,
        )

    def rewire_semantic(tree, old_edges, new_edges, n, *, stretch=None,
                        caption_text, old_edge_lanes=None, new_edge_lanes=None):
        """Commit one rotation as an atomic endpoint-pair replacement.

        Old and new relations must never coexist or cross-fade: an edge has one
        endpoint pair at every frame.  The first half exposes the complete
        pre-rotation topology; the second half exposes the complete
        post-rotation topology.  This helper is called once per actual
        rotation, so a zigzag case has two explicit calls. Colour changes are
        deliberately handled by the following animation.
        """
        if not old_edges or not new_edges:
            raise ValueError("rotation cannot replace an empty edge set")
        tk = snapshot(tree, stretch=stretch)
        rows = {keys: 1.0 for keys in overflow_rows(tree)}
        switch_frame = n // 2
        for step in range(n):
            live_edges = old_edges if step < switch_frame else new_edges
            live_lanes = old_edge_lanes if step < switch_frame else new_edge_lanes
            frames.append(semantic_scene(
                tk,
                live_edges,
                caption_text=caption_text,
                row_opacity=rows,
                edge_lanes=live_lanes,
            ))

    cap1 = "插入 52：先作为 51 的右孩子落下，再保持同一条边窝回成员行。"
    cap2a = "插入 54：先作为 52 的右孩子落下，原有连接保持不变。"
    cap2b = "单旋发生：先改接到新的同层黑键 52，线条连接只在旋转时改变。"
    cap2c = "连接已经稳定；最后才变色：52 变黑，51、54 变红。"
    cap3a = "插入 22：先作为 23 的左孩子落下，再带着 23→22 原边窝回同层。"
    cap3fold = "22 窝回完成：旧的两条连接先同时保留，明确停在双线状态。"
    cap3b1 = "第一次旋转：窝回后的两条原边先改成 21→22→23，父边仍连 21。"
    cap3b2 = "第二次旋转：父边才改连新的同层黑键 22，形成最终单线连接。"
    cap3c = "连接已经稳定；最后才变色：22 变黑，21、23 变红。"
    cap4a = "插入 37：先作为 36 的右孩子落下；窝回时每条边仍连接原来的节点。"
    cap4fold = "37 窝回完成：两条旧连接明确停住；这里没有旋转，不改连接对象。"
    cap4b = "黑键 38 向上推举并窝入上层；已有边随节点伸缩，不改连接对象。"
    cap4b_color = "38 抵达后才变红；它连接的分裂位置 36、39 同步变黑。"
    cap4c = "黑键 40 直接向上推举；30→40、40→35、40→45 全程保持。"
    cap4c_color = "40 抵达后才变红；下方连接位置 35、45 同步变黑。"
    cap4d = "黑键 49 直接升为新根；原有 49→30、49→70 两条边始终保持。"
    cap4d_color = "49 抵达根位后，30、70 同步变黑，树长高一层。"

    st1 = ("C0", 51)
    st2 = ("C0", 52)
    st3 = ("A1", 21)
    st4 = ("B1", 36)

    def stretch_src(st):
        """Room reserved in the tree that does not yet hold the new key.

        One full key slot plus the closing distance, so the followers sit
        exactly where they will rest after the insertion and the landing
        slot stays empty instead of covering the next key.
        """
        return (st[0], st[1], cell_w + stretch_gap)

    def stretch_dst(st):
        """Room kept in the tree that already holds the new key."""
        return (st[0], st[1], stretch_gap - inner_gap)

    E0 = frozenset({
        (49, 30), (49, 70), (30, 20), (30, 40),
        (20, 15), (20, 21), (21, 23),
        (40, 35), (40, 45), (35, 31), (35, 38),
        (38, 36), (38, 39), (45, 42), (45, 47),
        (70, 55), (70, 80), (55, 51), (55, 57),
        (80, 75), (80, 85),
    })
    E1 = E0 | {(51, 52)}
    E2_INSERT = E1 | {(52, 54)}
    E2 = (E2_INSERT - {(55, 51), (51, 52)}) | {(55, 52), (52, 51)}
    E3_INSERT = E2 | {(23, 22)}
    E3_ROT1 = (
        E3_INSERT - {(21, 23), (23, 22)}
    ) | {(21, 22), (22, 23)}
    E3 = (
        E3_ROT1 - {(20, 21), (21, 22)}
    ) | {(20, 22), (22, 21), (22, 23)}
    E4 = E3 | {(36, 37)}
    E5_INSERT = E4 | {(51, 50)}
    # The promotion changes coordinates only.  The existing 55→52 relation
    # naturally becomes the 52—55 member line when 52 docks beside 55.
    E5 = E5_INSERT

    # During folding, the old through-line stays on the member-row baseline
    # while the newly inserted relation uses a small parallel offset. This
    # makes the two real relations visible in the gaps between the keys. Once
    # a rotation commits, the lane map is omitted and the line returns to the
    # ordinary single-line geometry.
    fold_22_lanes = {
        frozenset((21, 23)): 0.0,
        frozenset((23, 22)): -8.0,
    }
    fold_37_lanes = {
        frozenset((38, 36)): 0.0,
        frozenset((36, 37)): -8.0,
    }
    fold_54_lanes = {
        frozenset((51, 52)): 0.0,
        frozenset((52, 54)): -8.0,
    }
    promote_38_lanes = {
        frozenset((40, 35)): 0.0,
        frozenset((35, 38)): -8.0,
    }
    promote_40_lanes = {
        frozenset((49, 30)): 0.0,
        frozenset((30, 40)): -8.0,
    }

    # Insertion adds one edge; only a rotation may replace endpoint pairs.
    assert E1 - E0 == {(51, 52)}
    assert E2_INSERT - E1 == {(52, 54)}
    assert E3_INSERT - E2 == {(23, 22)}
    assert E3_ROT1 - E3_INSERT == {(21, 22), (22, 23)}
    assert E3_INSERT - E3_ROT1 == {(21, 23), (23, 22)}
    assert E4 - E3 == {(36, 37)}
    assert E5_INSERT - E4 == {(51, 50)}
    assert E5 == E5_INSERT
    assert E2_INSERT - E2 == {(55, 51), (51, 52)}
    assert E2 - E2_INSERT == {(55, 52), (52, 51)}
    assert E3_ROT1 - E3 == {(20, 21), (21, 22)}
    assert E3 - E3_ROT1 == {(20, 22), (22, 21)}

    hold_semantic(S["s0"], E0, 36)

    insert_and_fold(S["s0"], S["s1b"], E0, E1, 52, 51, +1, st1, caption_text=cap1)
    hold_semantic(S["s1b"], E1, 36, caption_text=cap1)

    insert_and_fold(
        S["s1b"], S["s2a"], E1, E2_INSERT, 54, 52, +1, st2,
        caption_text=cap2a, edge_lanes_after=fold_54_lanes,
    )
    hold_semantic(
        S["s2a"], E2_INSERT, 30,
        caption_text="54 窝回完成：原有连接与新插入连接同时保留，先停在双线状态。",
        edge_lanes=fold_54_lanes,
    )
    rewire_semantic(
        S["s2a"], E2_INSERT, E2, 30, caption_text=cap2b,
        old_edge_lanes=fold_54_lanes,
    )
    hold_semantic(S["s2a"], E2, 18, caption_text=cap2b)
    recolor_semantic(S["s2a"], S["s2b"], E2, 22, caption_text=cap2c)
    hold_semantic(S["s2b"], E2, 38, caption_text=cap2c)

    insert_and_fold(
        S["s2b"], S["s3a"], E2, E3_INSERT, 22, 23, -1, st3,
        caption_text=cap3a, edge_lanes_after=fold_22_lanes,
    )
    # Folding is its own visible state. Both old relations remain attached;
    # the first rotation starts only after this double-line hold.
    hold_semantic(
        S["s3a"], E3_INSERT, 30, stretch=stretch_dst(st3),
        caption_text=cap3fold, edge_lanes=fold_22_lanes,
    )
    rewire_semantic(
        S["s3a"], E3_INSERT, E3_ROT1, 22, stretch=stretch_dst(st3),
        caption_text=cap3b1,
        old_edge_lanes=fold_22_lanes,
    )
    hold_semantic(
        S["s3a"], E3_ROT1, 18, stretch=stretch_dst(st3), caption_text=cap3b1,
    )
    rewire_semantic(
        S["s3a"], E3_ROT1, E3, 22, stretch=stretch_dst(st3), caption_text=cap3b2,
    )
    hold_semantic(
        S["s3a"], E3, 18, stretch=stretch_dst(st3), caption_text=cap3b2,
    )
    recolor_semantic(
        S["s3a"], S["s3b"], E3, 22, stretch=stretch_dst(st3), caption_text=cap3c,
    )
    hold_semantic(S["s3b"], E3, 40, caption_text=cap3c)

    insert_and_fold(
        S["s3b"], S["s4a"], E3, E4, 37, 36, +1, st4,
        caption_text=cap4a, edge_lanes_after=fold_37_lanes,
    )
    hold_semantic(
        S["s4a"], E4, 30, stretch=stretch_dst(st4),
        caption_text=cap4fold, edge_lanes=fold_37_lanes,
    )

    # From here through the new root, E4 is immutable.  Promotion moves black
    # keys with their existing relations; each following colour flip changes
    # only node colours.
    move_semantic(
        S["s4a"], S["s4c_pre"], E4, 42, caption_text=cap4b,
        edge_lanes_a=fold_37_lanes, edge_lanes_b=promote_38_lanes,
    )
    hold_semantic(
        S["s4c_pre"], E4, 18, caption_text=cap4b, edge_lanes=promote_38_lanes,
    )
    recolor_semantic(
        S["s4c_pre"], S["s4c"], E4, 20, caption_text=cap4b_color,
        edge_lanes=promote_38_lanes,
    )
    hold_semantic(
        S["s4c"], E4, 30, caption_text=cap4b_color, edge_lanes=promote_38_lanes,
    )

    move_semantic(
        S["s4c"], S["s4d_pre"], E4, 42, caption_text=cap4c,
        edge_lanes_a=promote_38_lanes, edge_lanes_b=promote_40_lanes,
    )
    hold_semantic(
        S["s4d_pre"], E4, 18, caption_text=cap4c, edge_lanes=promote_40_lanes,
    )
    recolor_semantic(
        S["s4d_pre"], S["s4d"], E4, 20, caption_text=cap4c_color,
        edge_lanes=promote_40_lanes,
    )
    hold_semantic(
        S["s4d"], E4, 30, caption_text=cap4c_color, edge_lanes=promote_40_lanes,
    )

    move_semantic(
        S["s4d"], S["s4e_pre"], E4, 50,
        grown_b=True, caption_text=cap4d,
        edge_lanes_a=promote_40_lanes, edge_lanes_b={},
    )
    hold_semantic(S["s4e_pre"], E4, 18, grown=True, caption_text=cap4d)
    recolor_semantic(
        S["s4e_pre"], S["s4e"], E4, 20,
        grown=True, caption_text=cap4d_color,
    )
    hold_semantic(S["s4e"], E4, 96, grown=True, caption_text=cap4d_color)

    st5 = ("C0", 51)
    fold_50_lanes = {frozenset((51, 50)): -8.0}
    insert_and_fold(
        S["s4e"], S["s5a"], E4, E5_INSERT, 50, 51, -1, st5,
        caption_text=None, edge_lanes_after=fold_50_lanes, grown=True,
    )
    hold_semantic(S["s5a"], E5_INSERT, 30, grown=True, edge_lanes=fold_50_lanes)
    move_semantic(
        S["s5a"], S["s5b_pre"], E5_INSERT, 42,
        grown_a=True, grown_b=True,
        edge_lanes_a=fold_50_lanes, edge_lanes_b={},
    )
    hold_semantic(S["s5b_pre"], E5, 18, grown=True)
    recolor_semantic(S["s5b_pre"], S["s5b"], E5, 22, grown=True)
    hold_semantic(S["s5b"], E5, 72, grown=True)

    render_webm("rb-insert-v4", frames, fps=30, transparent=True)


def rb_color_flip() -> None:
    """Uncle-red fix in real colors: node 5 arrives red, then the flip recolors without rotating."""
    pos = {"20": (450.0, 140.0), "10": (280.0, 320.0), "30": (620.0, 320.0), "5": (170.0, 480.0)}

    def page(body: str) -> str:
        return svg(body, width=900, height=560, color=INK)

    base_nodes = (("20", pos["20"], False), ("10", pos["10"], True), ("30", pos["30"], True))
    base_edges = (("20", "10", True), ("20", "30", True))

    def scene_body(extra: str = "") -> str:
        body = "".join(rb_edge_fragment(pos[a], pos[b], 1.0, red) for a, b, red in base_edges)
        body += "".join(rb_node(pnt, key, 1.0, red=red) for key, pnt, red in base_nodes)
        return body + extra

    frames: list[str] = []
    frames.extend([page(scene_body())] * 16)

    # Node 5 arrives red as a child of red 10; uncle 30 is red, so no rotation happens.
    for step in range(1, 19):
        t = ease(step / 18.0)
        body = scene_body()
        body += rb_edge_fragment(pos["10"], pos["5"], min(1.0, max(0.0, (t - 0.6) / 0.4)), True)
        body += rb_node(lerp_point((pos["5"][0], -40.0), pos["5"], t), "5", 1.0, red=True)
        frames.append(page(body))
    violation = page(scene_body(rb_edge_fragment(pos["10"], pos["5"], 1.0, True) + rb_node(pos["5"], "5", 1.0, red=True)))
    frames.extend([violation] * 20)

    # Color flip: both red members turn black and the middle key turns red.
    for step in range(1, 33):
        t = ease(step / 32.0)
        body = rb_crossfade_edge(pos["20"], pos["10"], True, False, t)
        body += rb_crossfade_edge(pos["20"], pos["30"], True, False, t)
        body += rb_edge_fragment(pos["10"], pos["5"], 1.0, True)
        body += rb_crossfade_square(pos["10"], "10", True, False, t)
        body += rb_crossfade_square(pos["30"], "30", True, False, t)
        body += rb_crossfade_square(pos["20"], "20", False, True, t)
        body += rb_node(pos["5"], "5", 1.0, red=True)
        frames.append(page(body))
    final = rb_scene(
        [("20", pos["20"], 1.0, True), ("10", pos["10"], 1.0, False), ("30", pos["30"], 1.0, False), ("5", pos["5"], 1.0, True)],
        [("20", "10", 1.0, False), ("20", "30", 1.0, False), ("10", "5", 1.0, True)],
        width=900,
        height=560,
    )
    frames.extend([final] * 26)
    render_webm("rb-color-flip", frames, fps=30, transparent=True)


def rb_delete() -> None:
    """Delete node 10 in real colors, show the double-black debt, then repair by rotation."""
    pos_20a = (450.0, 130.0)
    pos_10 = (280.0, 310.0)
    pos_30a = (620.0, 310.0)
    pos_40a = (760.0, 480.0)
    pos_30b = (450.0, 130.0)
    pos_20b = (280.0, 310.0)
    pos_40b = (620.0, 310.0)

    def page(nodes, edges, nil=None) -> str:
        return rb_scene(list(nodes), list(edges), nil=nil, width=900, height=560)

    initial_nodes = (("20", pos_20a, 1.0, False), ("10", pos_10, 1.0, False), ("30", pos_30a, 1.0, False), ("40", pos_40a, 1.0, True))
    initial_edges = (("20", "10", 1.0, False), ("20", "30", 1.0, False), ("30", "40", 1.0, True))

    frames: list[str] = []
    frames.extend([page(initial_nodes, initial_edges)] * 22)

    # Delete black 10; the double-black NIL marker records the missing black layer.
    for step in range(1, 17):
        t = ease(step / 16.0)
        nodes = (("20", pos_20a, 1.0, False), ("10", pos_10, 1.0 - t, False), ("30", pos_30a, 1.0, False), ("40", pos_40a, 1.0, True))
        edges = (("20", "10", 1.0 - t, False), ("20", "30", 1.0, False), ("30", "40", 1.0, True))
        if t > 0.25:
            edges += (("20", "NIL", min(1.0, max(0.0, (t - 0.25) / 0.75)), False),)
        frames.append(page(nodes, edges, nil=(pos_10, t)))
    underflow_nodes = (("20", pos_20a, 1.0, False), ("30", pos_30a, 1.0, False), ("40", pos_40a, 1.0, True))
    underflow_edges = (("20", "30", 1.0, False), ("30", "40", 1.0, True), ("20", "NIL", 1.0, False))
    frames.extend([page(underflow_nodes, underflow_edges, nil=(pos_10, 1.0))] * 22)

    # Repair by rotation: 30 rises to the root, 20 takes its place as left child.
    for step in range(1, 43):
        t = ease(step / 42.0)
        fade_out = max(0.0, 1.0 - 2.8 * t)
        edge_in = min(1.0, max(0.0, 2.4 * t - 1.32))
        nil_opacity = max(0.0, 1.0 - 2.0 * t)
        parts = [
            rb_edge_fragment(pos_20a, pos_30a, fade_out, False),
            rb_edge_fragment(pos_30a, pos_40a, fade_out, True),
            rb_edge_fragment(pos_20a, pos_10, fade_out, False),
            rb_edge_fragment(pos_30b, pos_20b, edge_in, False),
            rb_edge_fragment(pos_30b, pos_40b, edge_in, True),
            rb_node(lerp_point(pos_20a, pos_20b, t), "20", 1.0, red=False),
            rb_node(lerp_point(pos_30a, pos_30b, t), "30", 1.0, red=False),
            rb_node(lerp_point(pos_40a, pos_40b, t), "40", 1.0, red=True),
        ]
        if nil_opacity > 0.02:
            parts.append(rb_nil_fragment(pos_10, nil_opacity))
        frames.append(svg("".join(parts), width=900, height=560, color=INK))
    final_nodes = (("20", pos_20b, 1.0, False), ("30", pos_30b, 1.0, False), ("40", pos_40b, 1.0, True))
    final_edges = (("30", "20", 1.0, False), ("30", "40", 1.0, True))
    frames.extend([page(final_nodes, final_edges)] * 28)
    render_webm("rb-delete", frames, fps=30, transparent=True)


def avl_balance_contrast_svg() -> str:
    """One frame contrasting the unbalanced example with a balanced arrangement of the same keys."""
    def edge(a: Point, b: Point) -> str:
        return glow_line(a, b, width=4.2, radius=28.0)

    def tree_body(nodes: dict[str, Point], edges: list[tuple[str, str]]) -> str:
        body = "".join(edge(nodes[a], nodes[b]) for a, b in edges)
        body += "".join(glow_square(k, p, size=58.0) for k, p in nodes.items())
        return body

    def title(cx: float, cy: float, text: str, color: str) -> str:
        return f'<text fill="{color}" font-size="28px" font-weight="600" text-anchor="middle" dominant-baseline="middle" font-family="Noto Sans CJK SC,system-ui,sans-serif" x="{cx:.1f}" y="{cy:.1f}">{esc(text)}</text>'

    def badge(cx: float, cy: float, text: str, color: str, width: float) -> str:
        return (
            f'<rect fill="none" stroke="{color}" stroke-width="2.5" rx="9" x="{cx - width / 2:.1f}" y="{cy - 24:.1f}" width="{width:.1f}" height="48"/>'
            f'<text fill="{color}" font-size="23px" text-anchor="middle" dominant-baseline="middle" font-family="Noto Sans CJK SC,system-ui,sans-serif" x="{cx:.1f}" y="{cy:.1f}">{esc(text)}</text>'
        )

    def measure(x: float, y_top: float, y_bottom: float, label: str, label_x: float, label_y: float) -> str:
        return (
            f'<line stroke="#94A3B8" stroke-width="3.2" stroke-dasharray="8 7" stroke-linecap="round" x1="{x:.1f}" y1="{y_top:.1f}" x2="{x:.1f}" y2="{y_bottom:.1f}"/>'
            f'<text fill="#94A3B8" font-size="22px" text-anchor="middle" dominant-baseline="middle" font-family="Noto Sans CJK SC,system-ui,sans-serif" x="{label_x:.1f}" y="{label_y:.1f}">{esc(label)}</text>'
        )

    left_nodes = {
        "5": (285.0, 145.0),
        "3": (140.0, 275.0),
        "9": (430.0, 275.0),
        "6": (345.0, 405.0),
        "14": (495.0, 405.0),
        "17": (575.0, 535.0),
    }
    left_edges = [("5", "3"), ("5", "9"), ("9", "6"), ("9", "14"), ("14", "17")]
    right_nodes = {
        "6": (940.0, 155.0),
        "5": (795.0, 295.0),
        "14": (1085.0, 295.0),
        "3": (730.0, 435.0),
        "9": (1005.0, 435.0),
        "17": (1170.0, 435.0),
    }
    right_edges = [("6", "5"), ("6", "14"), ("5", "3"), ("14", "9"), ("14", "17")]

    body = (
        title(285.0, 62.0, "失衡", RB_RED)
        + tree_body(left_nodes, left_edges)
        + measure(78.0, 255.0, 300.0, "高 1", 78.0, 230.0)
        + measure(620.0, 255.0, 555.0, "高 3", 620.0, 230.0)
        + badge(285.0, 585.0, "左右高度差 2 > 1：失衡", RB_RED, 360.0)
        + title(940.0, 62.0, "平衡", "#34D399")
        + tree_body(right_nodes, right_edges)
        + measure(700.0, 290.0, 475.0, "高 2", 700.0, 265.0)
        + measure(1215.0, 290.0, 475.0, "高 2", 1215.0, 265.0)
        + badge(940.0, 585.0, "左右高度差 0 ≤ 1：平衡", "#34D399", 360.0)
    )
    return svg(body, width=1240, height=640, color=INK)


def avl_example_rotation() -> None:
    """Lesson example one: detach 3 / 6 / 14→17, spin the bare 5—9 lever, reattach left-middle-right."""
    import math

    start = {"5": (430.0, 140.0), "3": (280.0, 280.0), "9": (580.0, 280.0), "6": (500.0, 420.0), "14": (660.0, 420.0), "17": (725.0, 550.0)}
    wait = {"3": (130.0, 480.0), "6": (320.0, 530.0), "14": (720.0, 460.0), "17": (785.0, 555.0)}
    final = {"9": (425.0, 135.0), "5": (285.0, 285.0), "3": (170.0, 425.0), "6": (400.0, 425.0), "14": (560.0, 270.0), "17": (625.0, 405.0)}

    def page(body: str) -> str:
        return svg(body, width=900, height=620, color=INK)

    def circle(key: str, point: Point, cls: str = "node") -> str:
        glow = GLOW_WHITE if "focus-node" in cls else GLOW_BLUE
        return glow_square(key, point, glow=glow)

    def link(a: Point, b: Point, *, cls: str = "edge", opacity: float = 1.0) -> str:
        if cls == "focus-edge":
            return glow_line(a, b, opacity=opacity, bloom=GLOW_WHITE, width=3.6)
        x1, y1, x2, y2 = endpoints(a, b)
        return f'<line stroke="{INK}" stroke-width="3.4" stroke-linecap="round" opacity="{opacity:.3f}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>'

    def scene(pos: dict[str, Point], *, lever_cls: str = "edge", edges: Sequence[tuple[str, str, float]]) -> str:
        body = "".join(
            link(pos[a], pos[b], cls=lever_cls if {a, b} == {"5", "9"} else "edge", opacity=op)
            for a, b, op in edges
        )
        order = ("17", "14", "6", "3", "9", "5")
        return body + "".join(
            circle(k, pos[k], "node focus-node" if k in ("5", "9") and lever_cls != "edge" else "node")
            for k in order
        )

    def cargo_positions(progress_36: float, progress_group: float) -> dict[str, Point]:
        pos: dict[str, Point] = {}
        for k in ("3", "6"):
            moved = lerp_point(start[k], wait[k], progress_36)
            pos[k] = moved
        dx = (wait["14"][0] - start["14"][0]) * progress_group
        dy = (wait["14"][1] - start["14"][1]) * progress_group
        pos["14"] = (start["14"][0] + dx, start["14"][1] + dy)
        pos["17"] = (start["17"][0] + dx, start["17"][1] + dy)
        return pos

    frames: list[str] = []
    frames.extend([page(scene(start, edges=[(a, b, 1.0) for a, b in (("5", "3"), ("5", "9"), ("9", "6"), ("9", "14"), ("14", "17"))]))] * 12)

    # Select the 5—9 lever.
    frames.extend([page(scene(start, lever_cls="focus-edge", edges=[(a, b, 1.0) for a, b in (("5", "3"), ("5", "9"), ("9", "6"), ("9", "14"), ("14", "17"))]))] * 16)

    # Detach the three cargos; they stay waiting beside the lever.
    for step in range(1, 25):
        t = ease(step / 24.0)
        pos = dict(start)
        pos.update(cargo_positions(t, t))
        edges = [("5", "9", 1.0), ("14", "17", 1.0), ("5", "3", 1.0 - t), ("9", "6", 1.0 - t), ("9", "14", 1.0 - t)]
        frames.append(page(scene(pos, edges=edges)))
    detached = dict(start)
    detached.update(cargo_positions(1.0, 1.0))
    frames.extend([page(scene(detached, edges=[("5", "9", 1.0), ("14", "17", 1.0)]))] * 18)

    # Spin the bare lever while the cargos wait.
    m1, m2 = (505.0, 210.0), (355.0, 210.0)
    for step in range(1, 37):
        t = ease(step / 36.0)
        angle = math.radians(-90.0 * t)
        c, sn = math.cos(angle), math.sin(angle)
        cx = m1[0] + (m2[0] - m1[0]) * t
        cy = m1[1] + (m2[1] - m1[1]) * t
        rvx = 75.0 * c - 70.0 * sn
        rvy = 75.0 * sn + 70.0 * c
        pos = dict(cargo_positions(1.0, 1.0))
        pos["9"] = (cx + rvx, cy + rvy)
        pos["5"] = (cx - rvx, cy - rvy)
        frames.append(page(scene(pos, edges=[("5", "9", 1.0), ("14", "17", 1.0)])))
    rotated = dict(cargo_positions(1.0, 1.0))
    rotated.update({"5": final["5"], "9": final["9"]})
    frames.extend([page(scene(rotated, edges=[("5", "9", 1.0), ("14", "17", 1.0)]))] * 14)

    # Reattach left, middle, right — every cargo returns to its own side.
    for step in range(1, 25):
        t = ease(step / 24.0)
        pos = {}
        for k in ("3", "6"):
            pos[k] = lerp_point(wait[k], final[k], t)
        dx = (final["14"][0] - wait["14"][0]) * t
        dy = (final["14"][1] - wait["14"][1]) * t
        pos["14"] = (wait["14"][0] + dx, wait["14"][1] + dy)
        pos["17"] = (wait["17"][0] + dx, wait["17"][1] + dy)
        pos["5"], pos["9"] = final["5"], final["9"]
        edges = [("5", "9", 1.0), ("14", "17", 1.0), ("5", "3", t), ("5", "6", t), ("9", "14", t)]
        frames.append(page(scene(pos, edges=edges)))
    frames.extend([page(scene(final, edges=[(a, b, 1.0) for a, b in (("9", "5"), ("5", "3"), ("5", "6"), ("9", "14"), ("14", "17"))]))] * 26)
    render_webm("avl-example-left-rotation", frames, fps=30, transparent=True)


def static_avl_example_one() -> None:
    ASSETS.joinpath("avl-example-one.svg").write_text(
        avl_example_one_svg(),
        encoding="utf-8",
    )


def static_avl_balance_contrast() -> None:
    ASSETS.joinpath("avl-balance-contrast.svg").write_text(
        avl_balance_contrast_svg(),
        encoding="utf-8",
    )


def avl_no_growth_insert_svg() -> str:
    """Insert 3 into 2(left:1): BST landing spot is free, no rotation, yet height stays 2."""
    positions = {
        "2": (225.0, 55.0),
        "1": (140.0, 155.0),
        "3": (310.0, 155.0),
    }
    body = "".join(glow_line(positions[a], positions[b]) for a, b in (("2", "1"),))
    body += glow_square("2", positions["2"])
    body += glow_square("1", positions["1"])
    body += glow_square("3", positions["3"], glow=GLOW_WHITE)
    return svg(body, width=450, height=230, color=INK)


def static_avl_no_growth_insert() -> None:
    ASSETS.joinpath("avl-no-growth-insert.svg").write_text(
        avl_no_growth_insert_svg(),
        encoding="utf-8",
    )


def static_avl_walk_up_four() -> None:
    """Insert 80 into a 4-level AVL tree: imbalance first shows at level 3.

    Four straight left boundaries (one per subtree root: 75 ⊂ 60 ⊂ 45 ⊂ whole tree 30);
    every line sits left of the new node 80, so 80 belongs to all four levels.
    The first two checks pass, the third check at 45 finds the imbalance, and the
    root 30 is explicitly left unchecked because insertion repair stops there.
    """
    sp = {  # spine node positions
        "30": (520.0, 210.0),
        "45": (760.0, 340.0),
        "60": (900.0, 470.0),
        "75": (980.0, 600.0),
        "80": (1060.0, 730.0),
    }
    off = {  # off-path node positions
        "10": (440.0, 340.0),
        "20": (515.0, 470.0),
        "35": (676.0, 470.0),
        "50": (830.0, 600.0),
    }
    spine_edges = (("30", "45"), ("45", "60"), ("60", "75"), ("75", "80"))
    off_edges = (("30", "10"), ("10", "20"), ("45", "35"), ("60", "50"))
    all_pts = {**sp, **off}
    lines = (  # straight left boundaries — the left edge of each subtree's triangle, outermost first;
               # top end level with the subtree root, bottom end on the shared baseline,
               # bottom ends step right as subtrees shrink; every line stays left of node 80
               # and clears every node's halo (verified against bloom extents)
         ((476, 184), (110, 795), "#7A7A7A", 0.55, 2.5),   # whole tree rooted at 30; not checked
         ((664, 314), (400, 795), "#FF6B62", 0.65, 2.0),   # subtree rooted at 45; first imbalance
         ((858, 444), (694, 795), "#A3BCF7", 0.80, 2.0),   # subtree rooted at 60
         ((938, 574), (866, 795), "#A3BCF7", 0.95, 2.0),   # subtree rooted at 75
    )
    body = "".join(
        f'<line x1="{xt}" y1="{yt}" x2="{xb}" y2="{yb}" stroke="{stroke}" '
        f'stroke-width="{w}" stroke-opacity="{op}"/>'
        for (xt, yt), (xb, yb), stroke, op, w in lines
    )
    body += "".join(
        glow_line(sp[a], sp[b], bloom=GLOW_BLUE) for a, b in spine_edges
    )
    body += "".join(glow_line(all_pts[a], all_pts[b], opacity=0.55, width=2.4) for a, b in off_edges)
    for key, point in {**off, **{k: sp[k] for k in ("30", "45", "60", "75")}}.items():
        body += glow_square(key, point)
    body += glow_ring(sp["45"], color=GLOW_RED)
    body += glow_square("80", sp["80"], glow=GLOW_WHITE)
    body += '<text class="t1" x="64" y="82">插入80</text>'
    for anchor in ("30", "45", "60", "75"):
        x, y = sp[anchor]
        body += (
            f'<line x1="{x + 30:.0f}" y1="{y:.0f}" x2="1148" y2="{int(y) - 4}" '
            'stroke="#5A5A5A" stroke-width="1.5" stroke-dasharray="4 6"/>'
        )
    ok_cards = (  # (y, level, key, left-h, right-h) — the taller side gets a blue tint
        (436, "第 2 层", "60", 1, 2),
        (584, "第 1 层", "75", 0, 1),
    )
    for y, level, key, lh, rh in ok_cards:
        body += (
            f'<rect x="1160" y="{y}" width="440" height="116" fill="#000000" stroke="#3F3F3F" stroke-width="1.5"/>'
            f'<rect x="1160" y="{y + 18}" width="4" height="80" fill="#FFFFFF"/>'
            f'<text x="1194" y="{y + 38}" font-size="23" font-weight="600">{level} · 查 {key}</text>'
            f'<text x="1194" y="{y + 70}" font-size="22">左子树高 {lh}，右子树高 '
            f'<tspan fill="#A3BCF7" font-weight="700">{rh}</tspan></text>'
            f'<text x="1194" y="{y + 100}" font-size="21" fill="#9A9A9A">高度差 1，平衡，继续向上</text>'
        )
    body += (
        '<rect x="1160" y="140" width="440" height="116" fill="#000000" stroke="#3F3F3F" stroke-width="1.5"/>'
        '<rect x="1160" y="158" width="4" height="80" fill="#5A5A5A"/>'
        '<text x="1194" y="178" font-size="19" font-weight="600" letter-spacing="3" fill="#9A9A9A">第 4 层 · 根 30（未检查）</text>'
        '<text x="1194" y="210" font-size="23" font-weight="700" fill="#C9D4E8">45 已失衡，不再向上</text>'
        '<text x="1194" y="240" font-size="21" fill="#9A9A9A">插入调整在第 3 层停止</text>'
    )
    body += (
        '<rect x="1160" y="288" width="440" height="116" fill="#000000" stroke="#B04A50" stroke-width="1.8"/>'
        '<rect x="1160" y="306" width="4" height="80" fill="#FF6B62"/>'
        '<text x="1194" y="326" font-size="19" font-weight="600" letter-spacing="3" fill="#FF6B62">第 3 层 · 查 45</text>'
        '<text x="1194" y="358" font-size="25" font-weight="700">左子树高 1，右子树高 '
        '<tspan fill="#FF6B62" font-weight="700">3</tspan></text>'
        '<text x="1194" y="388" font-size="21" fill="#FF6B62">高度差 2，发现失衡！</text>'
    )
    svg_text = '''<svg xmlns="http://www.w3.org/2000/svg" width="1620" height="920" viewBox="0 0 1620 920" role="img" aria-labelledby="title desc">
  <title id="title">插入 80 后沿来路逐层检查</title>
  <desc id="desc">新节点 80 落在最右边，沿 75、60、45 向上检查；75 和 60 平衡，在倒数第二层的 45 首次发现高度差 2，根 30 尚未检查。</desc>
  <style>
    text { font-family: "Noto Sans CJK SC", system-ui, sans-serif; fill: ''' + INK + '''; }
    .t1 { font-size: 40px; font-weight: 700; }
    .t2 { font-size: 24px; fill: #9A9A9A; }
    .nt { font-size: 20px; fill: #7A7A7A; }
  </style>
''' + body + '''
</svg>'''
    ASSETS.joinpath("avl-walk-up-four.svg").write_text(svg_text, encoding="utf-8")


def avl_delete_three_levels_svg() -> str:
    """Show one deletion whose height loss triggers three ancestor repairs."""
    width, height = 1920, 1080
    children: dict[int, tuple[int | None, int | None]] = {
        1: (None, None), 2: (1, 3), 3: (None, 4), 4: (None, None),
        5: (2, 8), 6: (None, None), 7: (6, None),
        8: (7, 11), 9: (None, None), 10: (9, None),
        11: (10, 12), 12: (None, None), 13: (5, 21),
        14: (None, None), 15: (14, None), 16: (15, 17),
        17: (None, None), 18: (16, 20), 19: (None, None),
        20: (19, None), 21: (18, 29), 22: (None, None),
        23: (22, None), 24: (23, 25), 25: (None, None),
        26: (24, 28), 27: (None, None), 28: (27, None),
        29: (26, 32), 30: (None, None), 31: (30, None),
        32: (31, 33), 33: (None, None),
    }
    path_nodes = {1, 2, 5, 13}
    path_edges = {(1, 2), (2, 5), (5, 13)}

    depths: dict[int, int] = {}

    def visit(key: int, depth: int) -> None:
        depths[key] = depth
        left, right = children[key]
        if left is not None:
            visit(left, depth + 1)
        if right is not None:
            visit(right, depth + 1)

    visit(13, 0)
    tree_left = 72.0
    tree_step = 25.0
    tree_top = 184.0
    level_step = 104.0
    positions = {
        key: (tree_left + (key - 1) * tree_step, tree_top + depths[key] * level_step)
        for key in children
    }
    node_size = 31.0

    def edge(a: tuple[float, float], b: tuple[float, float], *, red: bool = False) -> str:
        x1, y1 = a
        x2, y2 = b
        dx, dy = x2 - x1, y2 - y1
        distance = hypot(dx, dy)
        inset = node_size * 0.48
        if distance:
            x1 += dx * inset / distance
            y1 += dy * inset / distance
            x2 -= dx * inset / distance
            y2 -= dy * inset / distance
        color = "#FF7070" if red else "#6D788E"
        width = 4.2 if red else 2.0
        return (
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{color}" stroke-width="{width:.1f}" stroke-linecap="round"/>'
        )

    def tree_node(key: int) -> str:
        x, y = positions[key]
        focused = key in path_nodes
        deleted = key == 1
        fill = "#8A343F" if deleted else NODE_FILL
        rim = GLOW_RED if focused else NODE_RIM
        body = ""
        if focused:
            body += (
                f'<rect x="{x - 24:.1f}" y="{y - 24:.1f}" width="48" height="48" rx="12" '
                f'fill="none" stroke="{GLOW_RED}" stroke-width="2.4" opacity="0.72"/>'
            )
        body += (
            f'<rect x="{x - node_size / 2:.1f}" y="{y - node_size / 2:.1f}" '
            f'width="{node_size:.1f}" height="{node_size:.1f}" rx="7" fill="{fill}" '
            f'stroke="{rim}" stroke-width="1.5"/>'
            f'<text x="{x:.1f}" y="{y + 1:.1f}" class="key">{key}</text>'
        )
        return body

    tree_body = ""
    for parent, (left, right) in children.items():
        for child in (left, right):
            if child is not None:
                tree_body += edge(positions[parent], positions[child], red=(parent, child) in path_edges)
    tree_body += "".join(tree_node(key) for key in sorted(children))
    x1, y1 = positions[1]
    tree_body += (
        f'<path d="M {x1 + 26:.1f} {y1 + 2:.1f} C {x1 + 70:.1f} {y1 + 20:.1f}, '
        f'{x1 + 84:.1f} {y1 + 52:.1f}, {x1 + 118:.1f} {y1 + 66:.1f}" '
        'fill="none" stroke="#FF7070" stroke-width="1.8" stroke-dasharray="5 5"/>'
        f'<text x="{x1 + 126:.1f}" y="{y1 + 72:.1f}" class="delete-label">删除 1</text>'
    )

    def mini_node(x: float, y: float, label: str, *, red: bool = False, wide: bool = False) -> str:
        box_w = 78.0 if wide else 34.0
        box_h = 34.0
        fill = "#8A343F" if red else NODE_FILL
        rim = GLOW_RED if red else NODE_RIM
        return (
            f'<rect x="{x - box_w / 2:.1f}" y="{y - box_h / 2:.1f}" width="{box_w:.1f}" '
            f'height="{box_h:.1f}" rx="7" fill="{fill}" stroke="{rim}" stroke-width="1.5"/>'
            f'<text x="{x:.1f}" y="{y + 1:.1f}" class="mini-key">{esc(label)}</text>'
        )

    def mini_edge(x1: float, y1: float, x2: float, y2: float, *, red: bool = False) -> str:
        color = "#FF7070" if red else "#718096"
        return (
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{color}" stroke-width="{2.4 if red else 1.8:.1f}" '
            f'stroke-linecap="round"/>'
        )

    def mini_arrow(x1: float, y: float, x2: float) -> str:
        return (
            f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{x2 - 12:.1f}" y2="{y:.1f}" '
            'stroke="#C9D4E8" stroke-width="2.2" marker-end="url(#delete-arrow)"/>'
            f'<text x="{(x1 + x2) / 2:.1f}" y="{y - 14:.1f}" class="rotate-label">左旋</text>'
        )

    def card_one(y: float) -> str:
        body = (
            f'<rect x="1000" y="{y:.1f}" width="860" height="250" rx="12" class="card"/>'
            f'<rect x="1000" y="{y + 18:.1f}" width="5" height="214" rx="2" fill="#FF7070"/>'
            f'<text x="1032" y="{y + 36:.1f}" class="card-title">第 1 层：节点 2</text>'
            f'<text x="1032" y="{y + 65:.1f}" class="card-sub">删掉 1 后，2 左空、右高 2，先在 2 处失衡</text>'
            f'<text x="1115" y="{y + 96:.1f}" class="mini-caption">调整前　h = 3 · bf = −2</text>'
            f'<text x="1490" y="{y + 96:.1f}" class="mini-caption">调整后　h = 2</text>'
        )
        root_y = y + 143
        body += mini_edge(1088, root_y + 17, 1050, root_y + 57, red=True)
        body += mini_edge(1088, root_y + 17, 1140, root_y + 57)
        body += mini_edge(1140, root_y + 74, 1184, root_y + 108)
        body += (
            f'<circle cx="1050" cy="{root_y + 74:.1f}" r="14" fill="none" stroke="#FF7070" '
            'stroke-width="1.8" stroke-dasharray="4 4"/>'
            f'<text x="1050" y="{root_y + 106:.1f}" class="slot-label">1 的位置</text>'
        )
        body += mini_node(1088, root_y, "2")
        body += mini_node(1140, root_y + 57, "3")
        body += mini_node(1184, root_y + 108, "4")
        body += mini_arrow(1248, root_y + 62, 1365)
        body += mini_node(1485, root_y, "3")
        body += mini_node(1440, root_y + 57, "2")
        body += mini_node(1530, root_y + 57, "4")
        body += mini_edge(1485, root_y + 17, 1440, root_y + 40)
        body += mini_edge(1485, root_y + 17, 1530, root_y + 40)
        return body

    def card_compact(y: float, *, level: str, root: str, before: tuple[str, str, str],
                     after: tuple[str, str, str], before_height: str, after_height: str,
                     sentence: str) -> str:
        body = (
            f'<rect x="1000" y="{y:.1f}" width="860" height="250" rx="12" class="card"/>'
            f'<rect x="1000" y="{y + 18:.1f}" width="5" height="214" rx="2" fill="#FF7070"/>'
            f'<text x="1032" y="{y + 36:.1f}" class="card-title">{esc(level)}：节点 {esc(root)}</text>'
            f'<text x="1032" y="{y + 65:.1f}" class="card-sub">{esc(sentence)}</text>'
            f'<text x="1115" y="{y + 96:.1f}" class="mini-caption">调整前　h = {before_height} · bf = −2</text>'
            f'<text x="1490" y="{y + 96:.1f}" class="mini-caption">调整后　h = {after_height}</text>'
        )
        root_y = y + 143
        left_x, right_x = 1065, 1165
        body += mini_edge(1115, root_y + 17, left_x, root_y + 57)
        body += mini_edge(1115, root_y + 17, right_x, root_y + 57)
        body += mini_node(1115, root_y, before[0], wide=True)
        body += mini_node(left_x, root_y + 57, before[1], wide=True)
        body += mini_node(right_x, root_y + 57, before[2], wide=True)
        body += mini_arrow(1248, root_y + 62, 1365)
        body += mini_edge(1510, root_y + 17, 1460, root_y + 57)
        body += mini_edge(1510, root_y + 17, 1560, root_y + 57)
        body += mini_node(1510, root_y, after[0], wide=True)
        body += mini_node(1460, root_y + 57, after[1], wide=True)
        body += mini_node(1560, root_y + 57, after[2], wide=True)
        return body

    body = tree_body
    body += card_one(140)
    body += card_compact(
        420, level="第 2 层", root="5", before=("5 · h5", "3 · h2", "8 · h4"),
        after=("8 · h4", "5 · h3", "11 · h3"), before_height="5", after_height="4",
        sentence="第一层旋转后，5 的左高 2、右高 4，继续失衡；左旋后子树高 5 → 4",
    )
    body += card_compact(
        700, level="第 3 层（根）", root="13", before=("13 · h7", "8 · h4", "21 · h6"),
        after=("21 · h6", "13 · h5", "29 · h5"), before_height="7", after_height="6",
        sentence="第二层旋转后，13 的左高 4、右高 6，继续失衡；左旋后子树高 7 → 6",
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">删除 1 后连续调整三层的 AVL 反例</title>
  <desc id="desc">左侧是 33 个节点、树高 7 的合法 AVL，删除左侧路径 13、5、2 下的叶子 1。右侧依次展示节点 2、5、13 处的三次左旋：局部子树高度分别从 3 降到 2、从 5 降到 4、从 7 降到 6。整棵树只降低一层，但同一次删除连续调整了三层。</desc>
  <defs>
    <marker id="delete-arrow" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto">
      <path d="M 0 0 L 10 5 L 0 10 Z" fill="#C9D4E8"/>
    </marker>
  </defs>
  <style>
    text {{ font-family: "Noto Sans CJK SC", system-ui, sans-serif; fill: #F8FAFC; }}
    .title {{ font-size: 40px; font-weight: 700; }}
    .subtitle {{ font-size: 22px; fill: #9A9A9A; }}
    .section {{ font-size: 23px; font-weight: 650; }}
    .key {{ font-size: 13px; font-weight: 700; text-anchor: middle; dominant-baseline: middle; }}
    .delete-label {{ font-size: 17px; font-weight: 650; fill: #FF7070; }}
    .card {{ fill: #000000; stroke: #3F3F3F; stroke-width: 1.5; }}
    .card-title {{ font-size: 24px; font-weight: 700; fill: #FF7070; }}
    .card-sub {{ font-size: 18px; fill: #D6DCE7; }}
    .mini-caption {{ font-size: 16px; fill: #9A9A9A; text-anchor: middle; }}
    .mini-key {{ font-size: 15px; font-weight: 650; text-anchor: middle; dominant-baseline: middle; }}
    .rotate-label {{ font-size: 17px; fill: #C9D4E8; text-anchor: middle; }}
    .slot-label {{ font-size: 13px; fill: #FF7070; text-anchor: middle; }}
    .foot {{ font-size: 20px; fill: #C4CAD4; }}
    .foot-red {{ font-size: 20px; font-weight: 650; fill: #FF7070; }}
  </style>
  <rect width="{width}" height="{height}" fill="#000000"/>
  <line x1="960" y1="136" x2="960" y2="970" stroke="#242424" stroke-width="1"/>
  <text x="64" y="68" class="title">删除 1：一次删除，连续调整三层</text>
  <text x="64" y="106" class="subtitle">一棵合法 AVL，树高 7；删除的是 2 的左孩子 1，最深的 22 并没有被删除</text>
   <text x="64" y="146" class="section">删除前：33 个节点 · 树高 7</text>
{body}
  <text x="64" y="1014" class="foot">三次调整：2 → 5 → 13。每次局部子树都下降一层，整棵树只从 7 层降到 6 层。</text>
</svg>'''


def static_avl_delete_three_levels() -> None:
    ASSETS.joinpath("avl-delete-three-levels.svg").write_text(
        avl_delete_three_levels_svg(),
        encoding="utf-8",
    )


def avl_delete_height_flow_svg() -> str:
    """Deletion flow: BST removal first, then the station-by-station upward loop.

    Square-corner enlarged redesign (user review): no rounded corners, no
    kicker/subtitle small print — 站点 labels, the "如果是" chip, and the top
    subtitle are gone; every remaining line is readable at video size. The
    repair connector is a straight full arrow, not a hooked concave curve.
    """
    green = "#7EE0A6"
    green_border = "#3F7A58"
    green_pale = "#A8E6C3"
    green_deep = "#58C98B"
    red = "#E5646C"
    red_soft = "#F08A8A"
    gray = "#9AA3AF"
    card_bg = "#0E1319"
    card_border = "#262D38"
    station_bg = "#0D1512"
    divider = "#232A33"
    chip_ink = "#06281A"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1450" height="780" viewBox="0 0 1450 780" role="img" aria-labelledby="title desc">
  <title id="title">AVL 删除：先删除，再沿来路向上检查</title>
  <desc id="desc">二叉搜索树决定怎么摘下节点；AVL 逐层判断失衡与高度变化，决定旋转与停止时机。</desc>
  <defs>
    <marker id="ag" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0 L10 5 L0 10 Z" fill="{green_pale}"/>
    </marker>
    <marker id="ar" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0 L10 5 L0 10 Z" fill="{red}"/>
    </marker>
    <marker id="ay" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0 L10 5 L0 10 Z" fill="{gray}"/>
    </marker>
  </defs>
  <style>
    text {{ font-family: "Noto Sans CJK SC", system-ui, sans-serif; fill: #F8FAFC; }}
  </style>
  <rect width="1450" height="780" fill="#000000"/>
  <text x="28" y="54" font-size="40" font-weight="700">AVL 删除：先删除，再沿来路向上检查</text>

  <rect x="24" y="92" width="420" height="568" fill="{card_bg}" stroke="{card_border}" stroke-width="2"/>
  <rect x="30" y="112" width="6" height="528" fill="{green}"/>
  <text x="56" y="132" font-size="22" fill="{green}" letter-spacing="2">第一步</text>
  <text x="56" y="172" font-size="30" font-weight="700">按二叉搜索树规则删除</text>
  <circle cx="76" cy="214" r="17" fill="{green_deep}"/>
  <text x="76" y="221" font-size="20" font-weight="700" fill="{chip_ink}" text-anchor="middle">0</text>
  <text x="110" y="222" font-size="27" font-weight="600">0 个孩子</text>
  <text x="110" y="258" font-size="20" fill="{gray}">叶节点直接摘除，留下空位</text>
  <line x1="48" y1="288" x2="420" y2="288" stroke="{divider}" stroke-width="1.5"/>
  <circle cx="76" cy="330" r="17" fill="{green_deep}"/>
  <text x="76" y="337" font-size="20" font-weight="700" fill="{chip_ink}" text-anchor="middle">1</text>
  <text x="110" y="338" font-size="27" font-weight="600">1 个孩子</text>
  <text x="110" y="374" font-size="20" fill="{gray}">独子直接接替它的位置</text>
  <line x1="48" y1="404" x2="420" y2="404" stroke="{divider}" stroke-width="1.5"/>
  <circle cx="76" cy="446" r="17" fill="{green_deep}"/>
  <text x="76" y="453" font-size="20" font-weight="700" fill="{chip_ink}" text-anchor="middle">2</text>
  <text x="110" y="454" font-size="27" font-weight="600">2 个孩子</text>
  <text x="110" y="490" font-size="20" fill="{gray}">后继顶替关键字，再删后继原位</text>
  <rect x="48" y="524" width="372" height="68" fill="#0F1D16" stroke="{green_border}" stroke-width="1.6"/>
  <text x="234" y="566" font-size="23" fill="{green}" text-anchor="middle">删除完成，从实际删点开始回溯</text>

  <path d="M 452 148 L 792 148" fill="none" stroke="{green_pale}" stroke-width="3" marker-end="url(#ag)"/>

  <rect x="800" y="92" width="400" height="116" fill="{station_bg}" stroke="{green_border}" stroke-width="2.4"/>
  <text x="828" y="142" font-size="34" font-weight="700">到达当前层</text>
  <text x="828" y="182" font-size="22" fill="{gray}">从删点或更高祖先进去</text>

  <path d="M 1160 212 C 1225 242, 1252 262, 1240 296" fill="none" stroke="{green_pale}" stroke-width="3" marker-end="url(#ag)"/>

  <rect x="1040" y="300" width="390" height="116" fill="{station_bg}" stroke="{green_border}" stroke-width="2.4"/>
  <text x="1068" y="350" font-size="34" font-weight="700">这一层失衡?</text>
  <text x="1068" y="390" font-size="22" fill="{gray}">失衡才需要旋转</text>

  <path d="M 1235 420 L 1235 516" fill="none" stroke="{red}" stroke-width="3" marker-end="url(#ar)"/>
  <text x="1256" y="474" font-size="24" fill="{red_soft}">是</text>

  <rect x="1040" y="522" width="390" height="116" fill="#1A0E10" stroke="#B04A50" stroke-width="2.4"/>
  <text x="1068" y="572" font-size="34" font-weight="700">旋转修复</text>
  <text x="1068" y="612" font-size="22" fill="{gray}">修复后仍要检查高度</text>

  <path d="M 1032 580 L 928 580" fill="none" stroke="{red}" stroke-width="3" marker-end="url(#ar)"/>
  <text x="980" y="556" font-size="22" fill="{red_soft}" text-anchor="middle">修复后</text>

  <path d="M 1036 386 C 950 424, 852 462, 800 516" fill="none" stroke="{gray}" stroke-width="2.2" marker-end="url(#ay)"/>
  <text x="915" y="448" font-size="24" fill="{gray}">否</text>

  <rect x="530" y="522" width="390" height="116" fill="{station_bg}" stroke="{green_border}" stroke-width="2.4"/>
  <text x="558" y="572" font-size="34" font-weight="700">局部高度变小?</text>
  <text x="558" y="612" font-size="22" fill="{gray}">决定停止，还是继续向上</text>

  <path d="M 725 642 L 725 678" fill="none" stroke="{gray}" stroke-width="2.2" marker-end="url(#ay)"/>
  <text x="746" y="666" font-size="24" fill="{gray}">否</text>
  <text x="725" y="714" font-size="30" font-weight="700" text-anchor="middle">出：停止回溯</text>
  <text x="725" y="750" font-size="22" fill="{gray}" text-anchor="middle">高度不再下降，删除影响到此为止</text>

  <path d="M 528 594 C 452 545, 478 212, 792 172" fill="none" stroke="{green_pale}" stroke-width="3" marker-end="url(#ag)"/>
  <text x="548" y="356" font-size="26" font-weight="700" fill="{green_pale}">是：继续向上</text>
  <text x="548" y="390" font-size="22" fill="{gray}">到更高祖先，再入下一轮</text>
</svg>'''


def static_avl_delete_height_flow() -> None:
    ASSETS.joinpath("avl-delete-height-flow.svg").write_text(
        avl_delete_height_flow_svg(),
        encoding="utf-8",
    )


def write_static_assets() -> None:
    ASSETS.joinpath("btree-order-4.svg").write_text(
        btree_node_states_svg(),
        encoding="utf-8",
    )
    ASSETS.joinpath("btree-order-5.svg").write_text(
        btree_order_5_svg(),
        encoding="utf-8",
    )
    ASSETS.joinpath("btree-delete-cases.svg").write_text(
        btree_delete_cases_svg(),
        encoding="utf-8",
    )
    static_avl_example_one()
    static_avl_no_growth_insert()
    static_avl_walk_up_four()
    static_avl_delete_height_flow()
    static_avl_delete_three_levels()
    ASSETS.joinpath("btree-search.svg").write_text(
        btree_search_svg(),
        encoding="utf-8",
    )
    ASSETS.joinpath("btree-order-scaling.svg").write_text(
        btree_order_scaling_svg(),
        encoding="utf-8",
    )
    ASSETS.joinpath("avl-deep-subtrees.svg").write_text(
        avl_deep_subtrees_svg(),
    )
    static_avl_balance_contrast()
    rb_encoding_static_assets()
    course = '''<text class="bkey" x="450" y="90">BST</text><line class="edge" x1="450" y1="120" x2="450" y2="200"/><text class="bkey" x="250" y="260">AVL</text><text class="bkey" x="650" y="260">B tree</text><line class="edge" x1="420" y1="210" x2="280" y2="240"/><line class="edge" x1="480" y1="210" x2="620" y2="240"/><line class="edge" x1="650" y1="290" x2="650" y2="375"/><text class="bkey" x="650" y="435">2-3-4 tree</text><line class="edge" x1="650" y1="465" x2="650" y2="530"/><text class="bkey" x="650" y="580">red-black tree</text>'''
    ASSETS.joinpath("course-route.svg").write_text(svg(course, color=SKY_BLUE), encoding="utf-8")


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    write_static_assets()
    bst_increasing()
    avl_single_left()
    avl_right_rotation()
    avl_right_left()
    avl_delete()
    avl_delete_to_root()
    avl_insertion()
    btree_insert()
    btree_borrow()
    btree_merge()
    btree_lend()
    btree_classic_plain()
    btree_classic_lend()
    btree_classic_merge()
    btree_case1_compare()
    btree_case2_compare()
    btree_case3_compare()
    btree_delete_5()
    rb_encoding()
    rb_insert()
    rb_ll_rr()
    rb_lr_rl()
    rb_overflow()
    rb_color_flip()
    rb_delete()


if __name__ == "__main__":
    import inspect
    import sys

    scenes = {
        name: fn
        for name, fn in sorted(globals().items())
        if inspect.isfunction(fn)
        and fn.__module__ == __name__
        and not name.startswith("_")
        and not inspect.signature(fn).parameters
    }
    if len(sys.argv) > 1:
        for name in sys.argv[1:]:
            scenes[name]()
    else:
        main()
