"""Keyframe animation system for the insertion section (root redesign).

Every node position, edge alpha, ring and header is authored ONCE as
continuous tracks when the film starts, then sampled per frame. Structural
facts that make jumps impossible:

- Node x comes from the FINAL tree's in-order slot and never changes.
  Rotations preserve in-order order, and insertions only fill empty slots,
  so no node ever reflows horizontally.
- Node y is the depth in the current tree. A rotation swaps the depths of
  exactly the lever pair; everyone else keeps their depth.
- The lever pair travels on a single arc around the pair midpoint, rotated
  by the EXACT angle that maps the pre-adjustment geometry onto the
  post-adjustment geometry (derived from where the pair must land, never a
  fixed 90 degrees). One sweep, lands precisely, nothing to undo.
- Edges reference node ids and sample node positions live, so they follow
  every motion; they only fade for attachment changes.
"""
from __future__ import annotations

import math

from engine import (  # noqa: F401
    BLACK,
    GLOW_ORANGE,
    GLOW_WHITE,
    HEIGHT,
    INDIGO,
    INDIGO_GLOW,
    INK,
    KEYS5,
    NODE_RIM,
    ORANGE,
    Point,
    QUEUE_SLOTS,
    SOFT,
    WIDTH,
    clamp,
    draw_text,
    edge,
    ease,
    glow_node,
    lerp_pt,
    text_w,
)

ROW_H = 142.0
TOP_Y = 315.0
TREE_LEFT = 190.0
TREE_RIGHT = 1450.0
DIP = 66.0

DETACH_END = 0.16                     # goods down
SPIN_A, SPIN_B = 0.24, 0.50           # lever sweeps the solved angle
GLIDE_A, GLIDE_B = 0.50, 0.62         # radial settle, angle fixed
REATTACH_A, REATTACH_B = 0.62, 0.88   # goods land on their new depths


def _ease_out(u: float) -> float:
    return 1.0 - (1.0 - u) ** 3


def _rotate(p: Point, pivot: Point, angle: float) -> Point:
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    dx, dy = p[0] - pivot[0], p[1] - pivot[1]
    return (pivot[0] + dx * cos_a - dy * sin_a, pivot[1] + dx * sin_a + dy * cos_a)


def _in_order_slots(children: dict[int, tuple[int | None, int | None]], root: int) -> dict[int, int]:
    slots: dict[int, int] = {}
    counter = 0

    def visit(key: int) -> None:
        nonlocal counter
        left, right = children[key]
        if left is not None:
            visit(left)
        slots[key] = counter
        counter += 1
        if right is not None:
            visit(right)

    visit(root)
    return slots


def _depths(children: dict[int, tuple[int | None, int | None]], root: int) -> dict[int, int]:
    out: dict[int, int] = {}

    def visit(key: int, depth: int) -> None:
        out[key] = depth
        left, right = children[key]
        if left is not None:
            visit(left, depth + 1)
        if right is not None:
            visit(right, depth + 1)

    visit(root, 0)
    return out


def _layout_x(children: dict[int, tuple[int | None, int | None]], root: int) -> dict[int, float]:
    """Compact in-order layout of the CURRENT tree: columns sized to fit,
    whole row centered. Rotations preserve in-order order, so only
    insertions ever trigger (smooth) reflow."""
    slots = _in_order_slots(children, root)
    count = len(slots)
    col = min(164.0, (TREE_RIGHT - TREE_LEFT) / max(count - 1, 1))
    x0 = (TREE_LEFT + TREE_RIGHT) / 2.0 - col * (count - 1) / 2.0
    return {key: x0 + slot * col for key, slot in slots.items()}


def _descendants(children: dict[int, tuple[int | None, int | None]], root: int) -> list[int]:
    out: list[int] = []

    def visit(key: int) -> None:
        out.append(key)
        left, right = children[key]
        if left is not None:
            visit(left)
        if right is not None:
            visit(right)

    visit(root)
    return out


class _Node:
    """Point-track actor: every motion is an appended segment; gaps hold.

    Segment kinds: fly (queue -> home), xshift (insertion reflow), y
    (depth change), arc (rotation sweep to an exact post pose), set (pin).
    """

    def __init__(self, key: int) -> None:
        self.key = key
        self.queue_pt = QUEUE_SLOTS[key]
        self.segments: list[tuple[float, float, str, object]] = []
        self.dips: list[tuple[float, float, float, float, float]] = []
        self.cur_pt: Point = self.queue_pt
        self.born_at = math.inf

    def add(self, t0: float, t1: float, kind: str, data: object, new_pt: Point) -> None:
        self.segments.append((t0, t1, kind, data))
        self.cur_pt = new_pt

    def position(self, t: float) -> Point | None:
        if t < self.born_at:
            return None
        x, y = self.cur_pt if not self.segments else self.segments[0][3][0]
        x, y = self.queue_pt
        for t0, t1, kind, data in self.segments:
            if t < t0:
                break
            u = clamp((t - t0) / max(t1 - t0, 1e-6)) if t1 > t0 else 1.0
            if kind == "fly" or kind == "set":
                (x, y) = data[1] if kind == "fly" else data
                if kind == "fly":
                    x, y = _lerp2(data[0], data[1], ease(u))
            elif kind == "xshift":
                x = _lerp_scalar(x, data, ease(u))
            elif kind == "y":
                y = _lerp_scalar(y, data, ease(u))
            elif kind == "arc":
                pivot, angle, post = data
                x, y = _rotate(_seg_start(self.segments, t0), pivot, angle * ease(u))
                if u >= 1.0:
                    x, y = post
        for dip0, dip1, dip2, dip3, amount in self.dips:
            if t < dip0:
                break
            if t < dip1:
                y += amount * ease((t - dip0) / max(dip1 - dip0, 1e-6))
            elif t < dip2:
                y += amount
            else:
                y += amount * (1.0 - ease((t - dip2) / max(dip3 - dip2, 1e-6)))
        return (x, y)


def _seg_start(segments, t0: float) -> Point:
    """Position just before the segment beginning at t0."""
    x, y = QUEUE_SLOTS[1]
    for seg_t0, seg_t1, kind, data in segments:
        if seg_t0 >= t0:
            break
        u = 1.0 if seg_t1 <= seg_t0 else 1.0
        if kind in ("fly", "set"):
            x, y = data[1] if kind == "fly" else data
        elif kind == "xshift":
            x = data
        elif kind == "y":
            y = data
        elif kind == "arc":
            pivot, angle, post = data
            x, y = post
    return (x, y)


def _lerp2(a: Point, b: Point, u: float) -> Point:
    return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)


def _lerp_scalar(a: float, b: float, u: float) -> float:
    return a + (b - a) * u


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class _Edge:
    def __init__(self, a: int, b: int) -> None:
        self.a = a
        self.b = b
        self.fades: list[tuple[float, float, float]] = []

    def alpha(self, t: float) -> float:
        value = 0.0  # edges are born by fading in, never pre-lit
        for t0, t1, target in self.fades:
            if t < t0:
                continue
            span = max(t1 - t0, 1e-6)
            if t >= t1:
                value = target
            else:
                u = (t - t0) / span
                value = value + (target - value) * clamp(u)
        return value


class InsertAnim:
    """Built once from the event list; sampled every frame afterwards."""

    def __init__(self, events: list[dict], final_root: int, final_children: dict) -> None:
        slots = _in_order_slots(final_children, final_root)
        self.nodes: dict[int, _Node] = {}
        for key in _in_order_slots(final_children, final_root):
            self.nodes[key] = _Node(key)
        self.edges: list[_Edge] = []
        self.rings: list[tuple[list[int], float, float, str]] = []
        self.lever_glow: list[tuple[float, float, int, int]] = []
        self._build(events)

    # -- construction ----------------------------------------------------
    def _node(self, key: int) -> _Node:
        return self.nodes[key]

    def _edge(self, a: int, b: int) -> _Edge:
        for item in self.edges:
            if {item.a, item.b} == {a, b}:
                return item
        item = _Edge(a, b)
        self.edges.append(item)
        return item

    def _build(self, events: list[dict]) -> None:
        depth: dict[int, int] = {}
        for event in events:
            kind = event["kind"]
            getattr(self, f"_do_{kind}")(event, depth)

    def _do_fly(self, event: dict, depth: dict[int, int]) -> None:
        key = event["key"]
        parent = event["parent"]
        node = self._node(key)
        node.born_at = event["t0"]
        post_root, post_children = event["post_tree"]
        depth.clear()
        depth.update(_depths(post_children, post_root))
        targets = _layout_x(post_children, post_root)
        landing = (targets[key], TOP_Y + depth[key] * ROW_H)
        node.add(event["t0"], event["t1"], "fly", (node.cur_pt, landing), landing)
        for other_key, other in self.nodes.items():
            if other_key == key or other.born_at > event["t0"]:
                continue
            target_x = targets[other_key]
            if abs(target_x - other.cur_pt[0]) > 0.5:
                other.add(event["t0"], event["t1"], "xshift", target_x,
                          (target_x, other.cur_pt[1]))
        if parent is not None:
            self._edge(parent, key).fades.append((event["t1"] - 0.18, event["t1"] + 0.12, 1.0))

    def _do_check(self, event: dict, depth: dict[int, int]) -> None:
        for key in event["path"]:
            self.rings.append(([key], event["t0"], event["t1"], GLOW_WHITE))

    def _do_scale(self, event: dict, depth: dict[int, int]) -> None:
        upper, lower = event["upper"], event["lower"]
        self.lever_glow.append((event["t0"], event["t1"] + 0.2, upper, lower))
        for group in event["groups"]:
            self.rings.append((list(group), event["t0"], event["t1"], GLOW_ORANGE))

    def _do_rot(self, event: dict, depth: dict[int, int]) -> None:
        upper, lower = event["upper"], event["lower"]
        parent = event["parent"]
        groups = event["groups"]
        t0, t1 = event["t0"], event["t1"]
        w = t1 - t0
        pre_root, pre_children = event["pre_tree"]
        post_root, post_children = event["post_tree"]
        pre_d = _depths(pre_children, pre_root)
        post_d = _depths(post_children, post_root)
        pre_upper = (self._node(upper).cur_pt[0], TOP_Y + pre_d[upper] * ROW_H)
        pre_lower = (self._node(lower).cur_pt[0], TOP_Y + pre_d[lower] * ROW_H)
        post_upper = (self._node(upper).cur_pt[0], TOP_Y + post_d[upper] * ROW_H)
        post_lower = (self._node(lower).cur_pt[0], TOP_Y + post_d[lower] * ROW_H)
        pivot = ((pre_upper[0] + pre_lower[0]) / 2.0, (pre_upper[1] + pre_lower[1]) / 2.0)
        v_pre = (pre_lower[0] - pre_upper[0], pre_lower[1] - pre_upper[1])
        v_post = (post_lower[0] - post_upper[0], post_lower[1] - post_upper[1])
        cross = v_pre[0] * v_post[1] - v_pre[1] * v_post[0]
        dot = v_pre[0] * v_post[0] + v_pre[1] * v_post[1]
        angle = math.atan2(cross, dot)  # minimal sweep: the rising end rises monotonically
        s0, s1 = t0 + SPIN_A * w, t0 + SPIN_B * w
        g0, g1 = t0 + GLIDE_A * w, t0 + GLIDE_B * w
        r0, r1 = t0 + REATTACH_A * w, t0 + REATTACH_B * w

        upper_node, lower_node = self._node(upper), self._node(lower)
        upper_node.add(s0, s1, "arc", (pivot, angle, post_upper), post_upper)
        lower_node.add(s0, s1, "arc", (pivot, angle, post_lower), post_lower)
        # radial settle when |v_pre| != |v_post|: translation only, angle fixed
        if abs(_dist(pre_upper, pre_lower) - _dist(post_upper, post_lower)) > 0.5:
            upper_node.add(s1, g1, "y", post_upper[1], post_upper)
            lower_node.add(s1, g1, "y", post_lower[1], post_lower)

        for group, _root in groups:
            for key in group:
                if key in (upper, lower):
                    continue
                node = self._node(key)
                node.dips.append((t0, t0 + DETACH_END * w, r0, r1, DIP))
                if post_d[key] != pre_d[key]:
                    node.add(r0, r1, "y", TOP_Y + post_d[key] * ROW_H,
                             (node.cur_pt[0], TOP_Y + post_d[key] * ROW_H))

        # All three cargos are removed before the lever turns. This makes the
        # rotation read as "摘下 -> 转动 -> 按新位置挂回", including the two
        # outer cargo groups that keep their relative order.
        pre_parent_edges = (
            (upper, groups[0][1]),
            (lower, groups[1][1]),
            (lower, groups[2][1]),
        )
        for parent_key, child_key in pre_parent_edges:
            if child_key is not None:
                self._edge(parent_key, child_key).fades.append((t0, t0 + DETACH_END * w, 0.0))

        middle_root = groups[1][1]
        post_parent_edges = (
            (upper, groups[0][1]),
            (upper, middle_root),
            (lower, groups[2][1]),
        )
        for parent_key, child_key in post_parent_edges:
            if child_key is not None:
                self._edge(parent_key, child_key).fades.append((r0, r1, 1.0))
        if parent is not None:
            self._edge(parent, upper).fades.append((s0, s0 + 0.3 * (SPIN_B - SPIN_A) * w, 0.0))
            self._edge(parent, lower).fades.append((r0, r1, 1.0))
        self.lever_glow.append((t0 + SPIN_A * w * 0.5, r1 + 0.25, upper, lower))
        depth.clear()
        depth.update(post_d)

    def _do_hold(self, event: dict, depth: dict[int, int]) -> None:
        pass

    # -- sampling --------------------------------------------------------
    def draw_into(self, draw, t: float) -> None:
        positions = {key: node.position(t) for key, node in self.nodes.items()}
        for item in self.edges:
            alpha = item.alpha(t)
            if alpha <= 0.01:
                continue
            pa, pb = positions.get(item.a), positions.get(item.b)
            if pa is None or pb is None:
                continue
            edge(draw, pa, pb, INK, width=7, opacity=alpha, trim=39)
        for t0, t1, upper, lower in self.lever_glow:
            if t0 <= t <= t1:
                pa, pb = positions[upper], positions[lower]
                fade_in = clamp((t - t0) / 0.18)
                fade_out = clamp((t1 - t) / 0.18)
                edge(draw, pa, pb, GLOW_WHITE, width=10, opacity=min(fade_in, fade_out), trim=39)
        for keys, t0, t1, color in self.rings:
            if not (t0 - 0.15 <= t <= t1 + 0.15):
                continue
            points = [positions[key] for key in keys if positions.get(key) is not None]
            if not points:
                continue
            fade = min(clamp((t - (t0 - 0.15)) / 0.15), clamp(((t1 + 0.15) - t) / 0.15))
            if len(points) == 1:
                cx, cy = points[0]
                radius = 52.0
            else:
                cx = sum(p[0] for p in points) / len(points)
                cy = sum(p[1] for p in points) / len(points)
                radius = max(math.hypot(p[0] - cx, p[1] - cy) for p in points) + 50.0
            _outline_round(draw, (cx, cy), radius, color, fade)
        for key, node in self.nodes.items():
            point = positions[key]
            if point is None:
                if t < node.born_at:
                    glow_node(draw, QUEUE_SLOTS[key], str(key), INDIGO, INDIGO_GLOW,
                              radius=25, key_size=24)
                continue
            glow_node(draw, point, str(key), INDIGO, INDIGO_GLOW, radius=46, key_size=34)


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], fade: float) -> tuple[int, int, int]:
    return tuple(int(a[i] * fade + b[i] * (1.0 - fade)) for i in range(3))  # type: ignore[return-value]


def _outline_round(draw, center: Point, radius: float, color: tuple[int, int, int], fade: float) -> None:
    import math as _math

    cx, cy = center
    rx, ry = radius, 46.0 + radius * 0.10
    # soft glow imitation: wide faint pass + crisp pass
    for width, alpha in ((7, 0.30 * fade), (3, 0.95 * fade)):
        mixed = _mix(color, BLACK, 1.0 - alpha)
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), outline=mixed, width=width)


def build(events: list[dict], final_root: int, final_children: dict) -> InsertAnim:
    return InsertAnim(events, final_root, final_children)
