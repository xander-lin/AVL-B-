"""Independent B-tree visual renderer.

The geometry is intentionally expressed here instead of reusing the media
generator or its rendered frames.  It reproduces the reference visual grammar:
one continuous rounded key row, a navy inset, white dividers, and a three-layer
blue/white edge.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


W, H = 1588, 1080
# The source composition is a 900x600 scene rendered at 2x and cropped by
# 106px on the left.  Keep scene descriptions in that small coordinate space
# and convert them once here; this prevents a second, unrelated layout scale.
SCALE = 2.0
CROP_X = 106.0
CELL_W, CELL_H = 112.0, 88.0
FILL = (59, 91, 165)
RIM = (143, 169, 232)
BLUE = (163, 188, 247)
WHITE = (248, 250, 252)
RED = (255, 112, 112)
FONT = "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"


@dataclass(frozen=True)
class Group:
    name: str
    keys: tuple[str, ...]
    center: tuple[float, float]
    overflow: bool = False


@dataclass(frozen=True)
class Scene:
    groups: tuple[Group, ...]
    edges: tuple[tuple[str, str, int, int], ...]


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size)


def _ease(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _slots(center: tuple[float, float], count: int) -> list[tuple[float, float]]:
    return [
        (center[0] + (index - (count - 1) / 2.0) * CELL_W, center[1])
        for index in range(count)
    ]


def _lerp(a: tuple[float, float], b: tuple[float, float], amount: float) -> tuple[float, float]:
    return (a[0] + (b[0] - a[0]) * amount, a[1] + (b[1] - a[1]) * amount)


def _group_box(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    left = min(point[0] for point in points) - CELL_W / 2.0
    right = max(point[0] for point in points) + CELL_W / 2.0
    return left, min(point[1] for point in points) - CELL_H / 2.0, right, max(point[1] for point in points) + CELL_H / 2.0


def _alpha(color: tuple[int, int, int], opacity: float) -> tuple[int, int, int, int]:
    return (*color, round(max(0.0, min(1.0, opacity)) * 255.0))


def _line(draw: ImageDraw.ImageDraw, start: tuple[float, float], end: tuple[float, float], color: tuple[int, int, int], width: float, opacity: float = 1.0) -> None:
    draw.line((round(start[0]), round(start[1]), round(end[0]), round(end[1])), fill=_alpha(color, opacity), width=max(1, round(width)), joint="curve")


def _edge_points(parent: list[tuple[float, float]], child: list[tuple[float, float]], slot: int, total: int) -> tuple[tuple[float, float], tuple[float, float]]:
    pl, _pt, pr, pb = _group_box(parent)
    cl, ct, cr, _cb = _group_box(child)
    x = min(pl + slot * CELL_W, pr)
    return (x, pb), ((cl + cr) / 2.0, ct)


def _draw_edge(layer: Image.Image, start: tuple[float, float], end: tuple[float, float], opacity: float = 1.0) -> None:
    # The reference edge is a solid pale-blue rail with a white core.  The
    # rail must not become a dark translucent halo after black compositing.
    _line(ImageDraw.Draw(layer, "RGBA"), start, end, BLUE, 13.8, opacity)
    _line(ImageDraw.Draw(layer, "RGBA"), start, end, WHITE, 6.8, opacity)


def _draw_group(layer: Image.Image, keys: tuple[str, ...], points: list[tuple[float, float]], *, overflow: bool = False, opacity: float = 1.0) -> None:
    if not keys or opacity <= 0.0:
        return
    draw = ImageDraw.Draw(layer, "RGBA")
    left, top, right, bottom = _group_box(points)
    shell = RED if overflow else BLUE
    # The reference's visible body is a pale-blue shell.  The navy fill is an
    # inset, not the shell itself; confusing these two layers produces the
    # old dark AVL-looking square style.
    draw.rounded_rectangle(
        (round(left), round(top), round(right), round(bottom)),
        radius=18, fill=_alpha(shell, opacity), outline=_alpha(shell, opacity), width=2,
    )
    inset = 12.0
    draw.rounded_rectangle(
        (round(left + inset), round(top + inset), round(right - inset), round(bottom - inset)),
        radius=10, fill=_alpha(FILL, opacity), outline=_alpha(RIM, opacity), width=2,
    )
    for index in range(1, len(points)):
        divider = (points[index - 1][0] + points[index][0]) / 2.0
        _line(draw, (divider, top + inset), (divider, bottom - inset), WHITE, 3.0, opacity)
    font = _font(36)
    for key, point in zip(keys, points):
        draw.text((round(point[0]), round(point[1] + 1)), key, font=font, fill=_alpha(WHITE, opacity), anchor="mm")


def _scene_maps(scene: Scene) -> tuple[dict[str, Group], dict[str, tuple[float, float]]]:
    groups = {group.name: group for group in scene.groups}
    positions: dict[str, tuple[float, float]] = {}
    for group in scene.groups:
        center = (group.center[0] * SCALE - CROP_X, group.center[1] * SCALE)
        positions.update(dict(zip(group.keys, _slots(center, len(group.keys)))))
    return groups, positions


def _render_between(first: Scene, second: Scene, progress: float) -> Image.Image:
    progress = _ease(progress)
    first_groups, first_positions = _scene_maps(first)
    second_groups, second_positions = _scene_maps(second)
    keys = set(first_positions) | set(second_positions)
    positions = {}
    for key in keys:
        before = first_positions.get(key, second_positions.get(key))
        after = second_positions.get(key, first_positions.get(key))
        if before is None or after is None:
            continue
        positions[key] = _lerp(before, after, progress)
    image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # Edges follow the moving endpoints.  The new topology becomes visible
    # only after the split starts, avoiding the old dark square-node grammar.
    groups = second_groups if progress >= 0.18 else first_groups
    edges = second.edges if progress >= 0.18 else first.edges
    for parent, child, slot, total in edges:
        parent_points = [positions[key] for key in groups[parent].keys]
        child_points = [positions[key] for key in groups[child].keys]
        start, end = _edge_points(parent_points, child_points, slot, total)
        _draw_edge(image, start, end)
    for group in groups.values():
        points = [positions[key] for key in group.keys]
        _draw_group(image, group.keys, points, overflow=group.overflow)
    return image


def _state(groups: Iterable[Group], edges: Iterable[tuple[str, str, int, int]]) -> Scene:
    return Scene(tuple(groups), tuple(edges))


def _leaf(name: str, keys: tuple[str, ...], x: float) -> Group:
    return Group(name, keys, (x, 505.0))


def _insert_scenes() -> list[Scene]:
    empty = _state((), ())
    leaf = lambda keys, overflow=False: _state((Group("leaf", keys, (450.0, 505.0), overflow),), ())
    s: list[Scene] = [empty]
    for keys in (("10",), ("10", "20"), ("10", "20", "30"), ("10", "20", "30", "40")):
        s.append(leaf(keys, len(keys) == 4))
    s.extend([
        _state((_leaf("left", ("10", "20"), 250.0), Group("root", ("30",), (450.0, 305.0)), _leaf("right", ("40",), 650.0)), (("root", "left", 0, 2), ("root", "right", 1, 2))),
    ])
    return s


def _full_scenes() -> list[Scene]:
    s = _insert_scenes()
    s.extend([
        _state((Group("left", ("10", "20"), (150.0, 505.0)), Group("root", ("30",), (450.0, 305.0)), Group("right", ("40", "50"), (650.0, 505.0))), (("root", "left", 0, 2), ("root", "right", 1, 2))),
        _state((Group("left", ("10", "20"), (150.0, 505.0)), Group("root", ("30",), (450.0, 305.0)), Group("right", ("40", "50", "60"), (650.0, 505.0))), (("root", "left", 0, 2), ("root", "right", 1, 2))),
        _state((Group("left", ("10", "20"), (150.0, 505.0)), Group("root", ("30",), (450.0, 305.0)), Group("right", ("40", "50", "60", "70"), (650.0, 505.0), True)), (("root", "left", 0, 2), ("root", "right", 1, 2))),
        _state((Group("left", ("10", "20"), (150.0, 505.0)), Group("root", ("30", "50"), (450.0, 305.0)), Group("mid", ("40",), (450.0, 505.0)), Group("right", ("70",), (750.0, 505.0))), (("root", "left", 0, 3), ("root", "mid", 1, 3), ("root", "right", 2, 3))),
        _state((Group("left", ("10", "20"), (150.0, 505.0)), Group("root", ("30", "50"), (450.0, 305.0)), Group("mid", ("40", "45"), (450.0, 505.0)), Group("right", ("70",), (750.0, 505.0))), (("root", "left", 0, 3), ("root", "mid", 1, 3), ("root", "right", 2, 3))),
        _state((Group("left", ("10", "20"), (150.0, 505.0)), Group("root", ("30", "50"), (450.0, 305.0)), Group("mid", ("40", "45", "55"), (450.0, 505.0)), Group("right", ("70",), (750.0, 505.0))), (("root", "left", 0, 3), ("root", "mid", 1, 3), ("root", "right", 2, 3))),
        _state((Group("left", ("10", "20"), (150.0, 505.0)), Group("root", ("30", "50", "60"), (450.0, 305.0)), Group("a", ("40", "45"), (330.0, 505.0)), Group("b", ("55",), (450.0, 505.0)), Group("right", ("70",), (750.0, 505.0))), (("root", "left", 0, 4), ("root", "a", 1, 4), ("root", "b", 2, 4), ("root", "right", 3, 4))),
        _state((Group("left", ("10", "20"), (150.0, 505.0)), Group("root", ("30", "50", "60"), (450.0, 305.0)), Group("a", ("40", "45"), (330.0, 505.0)), Group("b", ("55",), (450.0, 505.0)), Group("right", ("70", "80", "90", "100"), (650.0, 505.0), True)), (("root", "left", 0, 4), ("root", "a", 1, 4), ("root", "b", 2, 4), ("root", "right", 3, 4))),
        _state((Group("root", ("60",), (450.0, 110.0)), Group("left", ("30", "50"), (330.0, 305.0)), Group("right", ("90",), (650.0, 305.0)), _leaf("a", ("10", "20"), 150.0), _leaf("b", ("40", "45"), 330.0), _leaf("c", ("55",), 450.0), _leaf("d", ("70", "80"), 650.0), _leaf("e", ("100",), 800.0)), (("root", "left", 0, 2), ("root", "right", 1, 2), ("left", "a", 0, 3), ("left", "b", 1, 3), ("left", "c", 2, 3), ("right", "d", 0, 2), ("right", "e", 1, 2))),
    ])
    return s


def render(local_time: float, *, full: bool) -> Image.Image:
    scenes = _full_scenes() if full else _insert_scenes()
    if full:
        # Sixteen semantic stages over the spoken insertion explanation.
        stage = min(len(scenes) - 1, max(0, int(local_time / 1.65)))
        phase = (local_time / 1.65) - stage
    else:
        stage = min(len(scenes) - 1, max(0, int(local_time / 1.55)))
        phase = (local_time / 1.55) - stage
    if stage >= len(scenes) - 1:
        return _render_between(scenes[-1], scenes[-1], 1.0)
    return _render_between(scenes[stage], scenes[stage + 1], phase)
