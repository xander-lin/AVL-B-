"""AVL recap segment seg06 (scene s5-insert).

Complete-insertion animation rebuilt around the rewritten narration. Three
manuscript-authored text shots precede the tree sequence; every following
narration unit owns one explicit visual beat (fly, upward check, scale
diagnosis, rotation, hold). The tree sequence has no on-screen text and no
subtitles. Beat windows are provisional weights until the new narration
recording arrives; then they are re-derived from that recording's ASR
boundaries without touching the visuals.
"""
import math

from PIL import Image, ImageDraw

from engine import *  # noqa: F401,F403
import engine as avl_engine


SCENE_ID = "s5-insert"

# These blocks are copied from the manuscript. Blank lines in the manuscript
# define the reveal units; neither their wording nor their order is changed.
TEXT_SHOT_HEIGHT_SETUP = (
    "第一次旋转后是改变了重心，重心变了，左撇子变右撇子了，树高可没变，记住这点，后面要考。",
)
TEXT_SHOT_HEIGHT_CASES = (
    "插入前，假设最大的两颗左右子树是 n 与 n+1，那么树高是 n+2。",
    "插入时临时变成 n 与 n+2，第一次旋转后，或者说第一种旋转后，还是 n 与 n+2。",
    "第二次旋转后，或者说第二种旋转后，一边增加 1，一边减少 1，插入完成后最终，n 变成 n+1，n+2 变成 n+1，树高还是 n+2。",
)
TEXT_SHOT_HEIGHT_RULE = (
    "中间失衡的调整不会引起树高变化。",
    "两边失衡只牵涉第二种旋转，同理也不会引起树高变化。",
    "那么，无论是两边失衡，还是中间失衡，插入前树高是多少，插入后树高就是多少。",
)
TEXT_SHOT_HEIGHT_COUNTEREXAMPLE = (
    "能使 AVL 树树高增长的插入一定是无调整的，也就是凡牵涉调整的插入都不会引起树高变化。",
    "能使 AVL 树树高增长的插入一定是无调整的，但是无调整的插入可不一定使树高增长，",
    "\n比如单单一个 2，左子树是 1，插入 3。",
)
TEXT_SHOT_TWO = (
    "接下来让我们讲从零开始的完整插入。每插入一个数，首先肯定是按二叉搜索树的规则给它找到落点。",
    "然后呢？",
)
TEXT_SHOT_THREE = (
    "然后，首先就是插入后需要从落点沿着来路一直向上判断到根，因为插入这个节点属于很多层子树，我们需要判断它对各级子树的影响。",
    "但是在一直向上判断到根的过程中，我们发现失衡就修复，修复完还需要继续向上检查吗？",
    "我们再来读一读这句话：修复完还需要继续向上检查吗？",
    "是修复完！那说明调整操作已经发生了，可是刚刚我们得到结论，凡牵涉调整的插入都不会引起树高变化。",
    "那调整的这棵树树高没变化，它是在内部进行了修复，对外界来说是不可感的，那外界就不需要进行调整。",
    "因为对外界来说它就相当于没变，所以其实需要且只需要调整一次！",
)


_CLAUSE_RE = None
HEIGHT_ACCENT = (224, 244, 232)


def _clauses(source: str) -> list[str]:
    """Split one manuscript line into clauses that may never be broken."""
    import re

    return re.findall(r"[^，。；、！？：]*[，。；、！？：]|[^，。；、！？：]+", source)


def _wrapped_lines(value: str, size: int, width: float) -> list[str]:
    """Wrap by whole clauses: a sentence fragment is never cut mid-way."""
    lines: list[str] = []
    for source in value.split("\n"):
        if not source:
            lines.append("")
            continue
        current = ""
        for part in _clauses(source):
            if text_w(part, size) > width:
                # single overlong clause: hard-break as a last resort
                if current:
                    lines.append(current)
                    current = ""
                chunk = ""
                for char in part:
                    if chunk and text_w(chunk + char, size) > width:
                        lines.append(chunk)
                        chunk = char
                    else:
                        chunk += char
                current = chunk
                continue
            candidate = current + part
            if current and text_w(candidate, size) > width:
                lines.append(current)
                current = part
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines


def _draw_inverted_line(
    draw: ImageDraw.ImageDraw,
    cx: float,
    y: float,
    text: str,
    size: int,
    phrase: str | None,
) -> None:
    """反选：白底黑字。phrase 为 None 时整行反选，否则只反选该词。"""
    vertical_pad = 5
    horizontal_pad = 6
    if phrase and phrase in text:
        cut = text.index(phrase)
        pre, suf = text[:cut], text[cut + len(phrase):]
        w_pre, w_phrase, w_suf = (text_w(part, size) for part in (pre, phrase, suf))
        x0 = cx - (w_pre + w_phrase + w_suf) / 2.0
        draw.rounded_rectangle(
            (
                x0 + w_pre - horizontal_pad,
                y - size / 2.0 - vertical_pad,
                x0 + w_pre + w_phrase + horizontal_pad,
                y + size / 2.0 + vertical_pad,
            ),
            radius=6,
            fill=INK,
        )
        if pre:
            draw_text(draw, (x0 + w_pre / 2.0, y), pre, size=size, fill=INK, anchor="mm")
        draw_text(draw, (x0 + w_pre + w_phrase / 2.0, y), phrase, size=size,
                  fill=(0, 0, 0), anchor="mm")
        if suf:
            draw_text(draw, (x0 + w_pre + w_phrase + w_suf / 2.0, y), suf,
                      size=size, fill=INK, anchor="mm")
        return
    line_width = text_w(text, size)
    draw.rounded_rectangle(
        (
            cx - line_width / 2.0 - horizontal_pad,
            y - size / 2.0 - vertical_pad,
            cx + line_width / 2.0 + horizontal_pad,
            y + size / 2.0 + vertical_pad,
        ),
        radius=6,
        fill=INK,
    )
    draw_text(draw, (cx, y), text, size=size, fill=(0, 0, 0), anchor="mm")


_HEIGHT_TOKENS = ("n + 1", "n + 2", "n+1", "n+2", "n")


def _draw_height_line(
    draw: ImageDraw.ImageDraw,
    cx: float,
    y: float,
    text: str,
    size: int,
    invert: str | None = None,
) -> None:
    """Paint n, n+1, and n+2 in a mostly-white pale green; `invert` (e.g. 临时)
    keeps its white chip on the same line without disabling the coloring."""
    pieces: list[tuple[str, str]] = []
    cursor = 0
    while cursor < len(text):
        token = next((c for c in _HEIGHT_TOKENS if text.startswith(c, cursor)), None)
        if token is not None:
            pieces.append((token, "height"))
            cursor += len(token)
            continue
        if invert is not None and text.startswith(invert, cursor):
            pieces.append((invert, "invert"))
            cursor += len(invert)
            continue
        start = cursor
        cursor += 1
        while cursor < len(text) and not any(text.startswith(c, cursor) for c in _HEIGHT_TOKENS) and not (invert is not None and text.startswith(invert, cursor)):
            cursor += 1
        pieces.append((text[start:cursor], "ink"))
    widths = [text_w(part, size) for part, _ in pieces]
    x = cx - sum(widths) / 2.0
    for (part, kind), width in zip(pieces, widths):
        if kind == "invert":
            draw.rounded_rectangle(
                (
                    x - 6,
                    y - size / 2.0 - 5,
                    x + width + 6,
                    y + size / 2.0 + 5,
                ),
                radius=6,
                fill=INK,
            )
            draw_text(draw, (x + width / 2.0, y), part, size=size, fill=(0, 0, 0), anchor="mm")
        else:
            color = HEIGHT_ACCENT if kind == "height" else INK
            draw_text(draw, (x + width / 2.0, y), part, size=size, fill=color, anchor="mm")
        x += width


def _draw_text_shot(
    draw: ImageDraw.ImageDraw,
    blocks: tuple[str, ...],
    shown: int,
    highlights: tuple = (),
    t: float = 0.0,
    *,
    height_tokens: bool = False,
) -> None:
    """Center manuscript blocks in final positions and reveal cumulatively."""
    visible = blocks[:shown]
    center_x = WIDTH / 2.0
    all_lines = [_wrapped_lines(block, 39, 1740.0) for block in blocks]
    line_height = 58.0
    block_gap = 32.0
    all_height = sum(len(lines) * line_height for lines in all_lines) + block_gap * (len(all_lines) - 1)
    y = (HEIGHT - all_height) / 2.0 + line_height / 2.0
    active = [
        (block_index, phrase)
        for start, end, block_index, phrase in highlights
        if start <= t < end
    ]
    for index, lines in enumerate(all_lines):
        if index < len(visible):
            for line_text in lines:
                hits = [phrase for b_index, phrase in active if b_index == index and (phrase is None or phrase in line_text)]
                if height_tokens:
                    _draw_height_line(
                        draw,
                        center_x,
                        y,
                        line_text,
                        39,
                        invert=hits[0] if hits else None,
                    )
                elif hits:
                    _draw_inverted_line(draw, center_x, y, line_text, 39, hits[0])
                else:
                    draw_text(draw, (center_x, y), line_text, size=39, anchor="mm")
                y += line_height
        else:
            y += len(lines) * line_height
        if index != len(all_lines) - 1:
            y += block_gap


def _collect_ops() -> tuple[list[Step], list[Step]]:
    flies: list[Step] = []
    rots: list[Step] = []
    for beat in avl_engine.INSERT_BEATS:
        for step in beat.steps:
            (flies if step.kind == "fly" else rots).append(step)
    return flies, rots


_OPS: tuple[list[Step], list[Step]] | None = None


def _ops() -> tuple[list[Step], list[Step]]:
    global _OPS
    if _OPS is None:
        _OPS = _collect_ops()
    return _OPS


_BEAT_TABLE: "list[tuple[float, float, str, object]] | None" = None


def _beats(tl: Timeline) -> "list[tuple[float, float, str, object]]":
    """One beat per narration sentence, anchored to ASR windows. A beat may
    lead its sentence slightly, but the on-screen state always matches what
    is being spoken (text pages while conclusions are narrated, each fly /
    check / scale / rot inside its own spoken sentence)."""
    global _BEAT_TABLE
    if _BEAT_TABLE is not None:
        return _BEAT_TABLE

    flies, rots = _ops()
    def cue(si: int) -> tuple[float, float]:
        return tl.win(19, si)

    first_start, first_end = cue(42)
    first_third = (first_end - first_start) / 3.0
    B: "list[tuple[float, float, str, object]]" = [
        (cue(0)[0], cue(3)[0], "height_text", (TEXT_SHOT_HEIGHT_SETUP, ((cue(0)[0], 1),), ())),
        (cue(3)[0], cue(10)[0], "height_text", (TEXT_SHOT_HEIGHT_CASES, ((cue(4)[0], 1), (cue(5)[0], 2), (cue(7)[0], 3)), ())),
        (cue(10)[0], cue(14)[0], "text", (TEXT_SHOT_HEIGHT_RULE, ((cue(10)[0], 1), (cue(11)[0], 2), (cue(13)[0], 3)), ())),
         (cue(14)[0], cue(19)[0], "text", (TEXT_SHOT_HEIGHT_COUNTEREXAMPLE, ((cue(14)[0], 1), (cue(16)[0], 2), (cue(18)[0], 3)), ((cue(14)[0], cue(19)[0], 0, None),))),
        (cue(19)[0], cue(23)[0], "text", (TEXT_SHOT_TWO, ((cue(19)[0], 1), (cue(22)[0], 2)), ())),
        (cue(23)[0], cue(24)[0], "walk", None),
        (cue(24)[0], cue(37)[0], "text", (TEXT_SHOT_THREE, ((cue(24)[0], 2), (cue(25)[0], 3), (cue(27)[0], 4), (cue(30)[0], 5), (cue(35)[0], 6)), ())),
        (cue(37)[0], cue(41)[0], "rule", None),
        (cue(41)[0], first_start, "intro", None),
        (first_start, first_start + first_third, "fly", flies[0]),
        (first_start + first_third, first_start + first_third * 2, "fly", flies[1]),
        (first_start + first_third * 2, first_end, "fly", flies[2]),
        (cue(43)[0], cue(46)[0], "check", (flies[2].post, [3, 1])),
        (cue(46)[0], cue(48)[0], "scale", (1, 3, "left")),
        (cue(48)[0], cue(49)[0], "rot", rots[0]),
        (cue(49)[0], cue(50)[0], "show_tree", rots[0].post),
        (cue(50)[0], cue(51)[0], "fly", flies[3]),
        (cue(51)[0], cue(53)[0], "fly", flies[4]),
        (cue(53)[0], cue(54)[0], "scale", (7, 6, "right")),
        (cue(54)[0], cue(55)[0], "rot", rots[1]),
        (cue(55)[0], cue(56)[0], "show_tree", rots[1].post),
        (cue(56)[0], cue(57)[0], "fly", flies[5]),
        (cue(57)[0], cue(58)[0], "scale", (3, 6, "left")),
        (cue(58)[0], (cue(58)[0] + cue(58)[1]) / 2, "rot", rots[2]),
        ((cue(58)[0] + cue(58)[1]) / 2, cue(59)[0], "rot", rots[3]),
        (cue(59)[0], cue(60)[0], "fly", flies[6]),
        (cue(60)[0], cue(62)[0], "scale", (3, 1, "right")),
        (cue(62)[0], cue(63)[0], "rot", rots[4]),
        (cue(63)[0], cue(64)[0], "rot", rots[5]),
        (cue(64)[0], cue(65)[0], "show_tree", rots[5].post),
        (cue(65)[0], cue(66)[0], "fly", flies[7]),
        (cue(66)[0], cue(68)[0], "fly", flies[8]),
        (cue(68)[0], cue(69)[0], "scale", (1, 0, "right")),
        (cue(69)[0], cue(71)[0], "rot", rots[6]),
        (cue(71)[0], cue(72)[0], "show_tree", rots[6].post),
        (cue(72)[0], cue(74)[0], "fly", flies[9]),
        (cue(74)[0], cue(78)[0], "scale", (2, 0, "right")),
        (cue(78)[0], tl.gs(20, 0), "rot", rots[7]),
    ]
    _BEAT_TABLE = B
    return B


def _locate(t: float, tl: Timeline) -> tuple[str, object, float, int]:
    beats = _beats(tl)
    index = len(beats) - 1
    for i, (start, _end, _kind, _payload) in enumerate(beats):
        if t < start:
            index = i - 1
            break
    index = max(index, 0)
    start, end, kind, payload = beats[index]
    progress = clamp((t - start) / max(end - start, 1e-6))
    flies_done = sum(1 for beat in beats[:index] if beat[2] == "fly")
    return kind, payload, progress, flies_done


_ANIM = None


def _anim(tl: Timeline):
    """Build the whole second-half animation once; sample per frame.

    Positions are keyframed from the ASR-anchored beat table; x slots come
    from the final tree's in-order layout and never change, so the tree can
    never reflow or jump. The rotation angle is solved from the exact
    pre/post geometry of the lever pair (never a fixed 90 degrees).
    """
    global _ANIM
    if _ANIM is not None:
        return _ANIM
    import insert_anim as ia

    events: list[dict] = []
    rot_events: list[dict] = []
    current_children: dict | None = None

    def descendants(children: dict, root: int | None) -> list[int]:
        out: list[int] = []

        def visit(key: int) -> None:
            out.append(key)
            left, right = children[key]
            if left is not None:
                visit(left)
            if right is not None:
                visit(right)

        if root is not None:
            visit(root)
        return out

    for t0, t1, kind, payload in _beats(tl):
        if kind == "fly":
            key = payload.params[0]
            post_children = payload.post[1]
            parent = next((k for k, ch in post_children.items() if key in ch), None)
            events.append({
                "kind": "fly", "t0": t0, "t1": t1, "key": key, "parent": parent,
                "post_tree": payload.post,
            })
            current_children = post_children
        elif kind in ("check", "show_check"):
            events.append({"kind": "check", "t0": t0, "t1": t1, "path": list(payload[1])})
        elif kind in ("scale", "show_scale"):
            upper, direction = payload[0], payload[2]
            upper_left, upper_right = current_children[upper]
            if direction == "left":
                lower = upper_right
                groups = [
                    descendants(current_children, upper_left),
                    descendants(current_children, current_children[lower][0]),
                    descendants(current_children, current_children[lower][1]),
                ]
            else:
                lower = upper_left
                groups = [
                    descendants(current_children, upper_right),
                    descendants(current_children, current_children[lower][0]),
                    descendants(current_children, current_children[lower][1]),
                ]
            events.append({
                "kind": "scale", "t0": t0, "t1": t1,
                "upper": upper, "lower": lower, "groups": groups,
            })
        elif kind == "rot":
            upper, direction = payload.params
            pre_children = payload.pre[1]
            upper_left, upper_right = pre_children[upper]
            if direction == "left":
                lower = upper_right
                middle_root = pre_children[lower][0]
                stay_upper, stay_lower = upper_left, pre_children[lower][1]
            else:
                lower = upper_left
                middle_root = pre_children[lower][1]
                stay_upper, stay_lower = upper_right, pre_children[lower][0]
            parent = next((k for k, ch in pre_children.items() if upper in ch), None)
            event = {
                "kind": "rot", "t0": t0, "t1": t1,
                "upper": upper, "lower": lower, "parent": parent,
                "groups": [
                    (descendants(pre_children, stay_upper), stay_upper),
                    (descendants(pre_children, middle_root), middle_root),
                    (descendants(pre_children, stay_lower), stay_lower),
                ],
                "pre_tree": payload.pre, "post_tree": payload.post,
            }
            events.append(event)
            current_children = payload.post[1]
    _, rots = _ops()
    final_root, final_children = rots[-1].post[0], rots[-1].post[1]
    _ANIM = ia.build(events, final_root, final_children)
    return _ANIM


def _draw_insert(image: Image.Image, t: float, tl: Timeline) -> None:
    draw = ImageDraw.Draw(image)
    kind, payload, _progress, _flies_done = _locate(t, tl)
    walk_start, walk_end = tl.win(19, 23)
    if walk_start <= t < walk_end:
        # The multi-level check gets its own diagram so the spoken explanation
        # is anchored to the four actual ancestor subtrees.
        draw_source_media(
            image,
            "avl-walk-up-four.svg",
            t,
            walk_start,
            loop=False,
            max_width=1480,
            max_height=870,
            x_center=1020,
            y_center=565,
        )
        return
    if kind in ("text", "height_text"):
        blocks, reveals, highlights = payload
        shown = 1
        for reveal_time, count in reveals:
            if t >= reveal_time:
                shown = count
        _draw_text_shot(draw, blocks, shown, highlights, t, height_tokens=kind == "height_text")
        if blocks is TEXT_SHOT_HEIGHT_COUNTEREXAMPLE and shown >= 3:
            # Keep the example diagram inline with the separate "比如..."
            # sentence rather than parking it in the lower-right corner.
            draw_source_media(
                image,
                "avl-insert-three-node.svg",
                t,
                0.0,
                loop=False,
                max_width=450,
                max_height=230,
                x_center=1575,
                y_center=672,
            )
    elif kind == "walk":
        draw_source_media(
            image,
            "avl-walk-up-four.svg",
            t,
            walk_start,
            loop=False,
            max_width=1480,
            max_height=870,
            x_center=1020,
            y_center=565,
        )
    elif kind == "rule":
        draw_text(draw, (960, 380), "按二叉搜索树的规则给它找到落点", size=44, fill=INK)
        draw_text(draw, (960, 480), "插入后一直向上判断到根", size=44, fill=INK)
        draw_text(draw, (960, 580), "一旦遇到失衡，调整一次就提前结束", size=44, fill=INK)
    else:
        # intro / fly / check / scale / rot / show_* / holds: one continuous
        # keyframed scene, sampled per frame — no per-beat state machines.
        _anim(tl).draw_into(draw, t)


def draw(image: Image.Image, t: float, tl: Timeline) -> None:
    _draw_insert(image, t, tl)


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
