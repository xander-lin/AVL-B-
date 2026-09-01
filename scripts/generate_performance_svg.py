#!/usr/bin/env python3
"""Render the measured AVL benchmark CSV as a self-contained SVG chart."""

from __future__ import annotations

import csv
import math
import sys
from pathlib import Path


WIDTH = 1720
HEIGHT = 900
BACKGROUND = "#000000"
GRID = "#262626"
AXIS = "#F8FAFC"
INK = "#F8FAFC"
MUTED = "#8A8A8A"

# 每族四档：O0 -> O3 由浅到深；Rust 只跑了 O3
FAMILIES = [
    ("c-ours", "我们的 C", "#D9E4FF", "#A3BCF7", "#6E8FE0", "#3B5BA5", "#8FA9E8"),
    ("c-classic", "传统 C", "#FFDFB8", "#FFC48A", "#FFA94D", "#C07B2D", "#FFBE73"),
    ("cpp", "C++（我们的逻辑）", "#E6DEFA", "#C9B8F2", "#A68AE0", "#7159B8", "#C9B8F2"),
]
RUST_FILL, RUST_STROKE = "#EFE3A0", "#F2DC94"


def esc(value: object) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def text(x: float, y: float, value: object, size: int, fill: str = INK,
         anchor: str = "start", weight: str = "400") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" '
            f'font-size="{size}px" font-weight="{weight}" text-anchor="{anchor}" '
            'font-family="Noto Sans CJK SC,system-ui,sans-serif">'
            f"{esc(value)}</text>")


def nice_ticks(low: float, high: float) -> list[float]:
    start = math.floor(math.log10(low))
    end = math.ceil(math.log10(high))
    ticks = []
    for exponent in range(start, end + 1):
        for factor in (1, 2, 5):
            tick = factor * 10 ** exponent
            if low <= tick <= high:
                ticks.append(tick)
    return ticks


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: generate_performance_svg.py RESULTS.csv OUTPUT.svg")

    rows = []
    with Path(sys.argv[1]).open(newline="") as handle:
        for row in csv.DictReader(handle):
            row["milliseconds"] = float(row["milliseconds"])
            row["rotations"] = int(row["rotations"])
            rows.append(row)

    workloads = ["insert", "delete", "search", "ascending", "mixed"]
    levels = ["O0", "O1", "O2", "O3"]
    series = []  # (implementation, optimization, fill, stroke)
    for impl, _, *shades in FAMILIES:
        for opt, fill in zip(levels, shades[:4]):
            series.append((impl, opt, fill, shades[4]))
    series.append(("rust", "O3", RUST_FILL, RUST_STROKE))

    measured = {(row["implementation"], row["optimization"], row["workload"]): row
                for row in rows}
    values = [row["milliseconds"] for row in rows]
    low = min(values) * 0.72
    high = max(values) * 1.35
    ticks = nice_ticks(low, high)

    left, right, top, bottom = 105, 42, 175, 105
    chart_left, chart_right = left, WIDTH - right
    chart_top, chart_bottom = top, HEIGHT - bottom
    chart_height = chart_bottom - chart_top
    group_width = (chart_right - chart_left) / len(workloads)
    bar_width = min(18.0, group_width / 20)
    gap = bar_width * 0.22
    total_width = len(series) * bar_width + (len(series) - 1) * gap

    def y_for(value: float) -> float:
        return chart_bottom - (math.log(value) - math.log(low)) / (math.log(high) - math.log(low)) * chart_height

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{BACKGROUND}"/>',
        text(left, 64, "AVL 性能对比 · Clang 实测", 30, weight="700"),
    ]

    # 图例：一族一段色带，四格即 O0..O3，从浅到深
    def ramp(x: float, y: float, shades: tuple[str, ...], widths: tuple[int, ...]) -> float:
        cx = x
        for shade, w in zip(shades, widths):
            parts.append(f'<rect x="{cx:.1f}" y="{y:.1f}" width="{w}" height="18" fill="{shade}"/>')
            cx += w
        return cx

    lx = left
    ly = 96
    for impl, _, *shades in FAMILIES:
        shades4 = tuple(shades[:4])
        end = ramp(lx, ly, shades4, (18,) * 4)
        label = {"c-ours": "我们的 C", "c-classic": "传统 C",
                 "cpp": "C++（我们的逻辑）"}[impl]
        parts.append(text(end + 12, ly + 15, label, 16))
        lx = end + 12 + (len(label) * 16 if any(ord(c) > 127 for c in label) else len(label) * 9) + 56
    end = ramp(lx, ly, (RUST_FILL,), (18,))
    parts.append(text(end + 12, ly + 15, "Rust（我们的逻辑）", 16))

    parts.append(text(left, ly + 46,
                      "一族四格 = 四档优化，自左向右 O0 → O1 → O2 → O3，颜色由浅到深；"
                      "Rust 仅测了 O3。纵轴为对数刻度，单位毫秒。",
                      14, MUTED))

    for tick in ticks:
        y = y_for(tick)
        parts.append(f'<line x1="{chart_left}" y1="{y:.1f}" x2="{chart_right}" y2="{y:.1f}" '
                     f'stroke="{GRID}" stroke-width="1"/>')
        label = f"{tick:g}"
        parts.append(text(chart_left - 14, y + 5, label, 13, MUTED, "end"))
    parts.append(text(36, chart_top - 18, "ms", 14, MUTED, "middle"))

    for workload_index, workload in enumerate(workloads):
        center = chart_left + group_width * (workload_index + 0.5)
        start = center - total_width / 2
        for series_index, (implementation, optimization, color, stroke) in enumerate(series):
            row = measured[(implementation, optimization, workload)]
            x = start + series_index * (bar_width + gap)
            y = y_for(row["milliseconds"])
            height = chart_bottom - y
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" '
                f'height="{height:.1f}" fill="{color}" stroke="{stroke}" stroke-width="1"/>')
        parts.append(text(center, chart_bottom + 31, workload, 16, INK, "middle", "600"))

    parts.extend([
        f'<line x1="{chart_left}" y1="{chart_bottom}" x2="{chart_right}" y2="{chart_bottom}" '
        f'stroke="{AXIS}" stroke-width="2"/>',
        "</svg>",
    ])

    Path(sys.argv[2]).write_text("\n".join(parts) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
