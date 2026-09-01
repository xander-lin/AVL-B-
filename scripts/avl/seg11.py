"""AVL recap segment seg11 (s10-code): the silent final code section.

Manuscript text and the C code are shown as still pages — no animation, no
narration (the audio track is padded with silence). Each page's duration is
set by how hard the code is to digest, not by any voice timing.

Code is highlighted by Pygments (real C lexer + the standard Monokai theme),
never by hand-picked colors.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

from PIL import Image, ImageDraw

from engine import *  # noqa: F401,F403

_VENDOR = _Path(__file__).resolve().parents[1] / "vendor"
if str(_VENDOR) not in _sys.path:
    _sys.path.insert(0, str(_VENDOR))

from pygments.lexers import get_lexer_by_name  # noqa: E402
from pygments.styles import get_style_by_name  # noqa: E402


SCENE_ID = "s10-code"

P_DATA = (
    "先看数据结构。和普通二叉搜索树的节点比，AVL 的节点只多了一个整数 height，"
    "记录以它为根的这棵子树有多高，叶子是一层。然后是四个一句话工具。maxInt，取两数里大的那个。"
    "heightOf，问某个位置多高：有节点就报出它的 height，是空位就报零——有了这条约定，后面的代码都不用为空子树单写分支。"
    "balanceFactor，左高减右高，这就是天平的读数：正数左边沉，负数右边沉，绝对值超过一就是失衡。"
    "updateHeight 用在回溯的路上：任何节点的高度永远是一加较高的那个孩子，所以父亲的身高不用专门记着，回头拿两个孩子现算就行。"
    "这些函数都只在这一个文件里使用，所以一律加上 static，把名字关在文件内部，不给别的编译单元添乱。"
).replace("`", "")

P_ROTATE = (
    "旋转只有一个原语：旋转天平。不需要左旋右旋两个名字——朝哪边转，重量自己会说话：沉的那端升起来做新根，轻的那端沉下去。"
    "代码同样不用指明方向，开头称一称两端谁重，方向自然就出来了。接下来就三步。第一步，换天平两端：沉的一端升起当新根，node 沉下去做它的孩子。"
    "第二步，中间货物原路改挂：它从升起那端的内侧摘下来，挂到沉下去那端靠近升起节点的内侧——注意它还挂在左中右的正中间，这正是中序顺序不变的原因。"
    "第三步，自底向上报身高：先沉下去的、再升起来的，顺序不能反，因为升起来那端的新身高要用对方报完之后的数来算。"
    "最后把新根交还给上层。调用方保证进入这个函数时两端必有一边更重，所以开头的方向判断不会落空。"
).replace("`", "")

P_INSERT = (
    "插入是这套思想从头到尾走一遍。递归落下阶段就是二叉搜索树的老路由：小的往左，大的往右，走到空位就新建节点挂上去；"
    "碰到相等的关键字直接原样退回，这棵树不允许重复。真正的戏在回溯阶段：每一层先把身高报上来，再读一次 balanceFactor，然后整个交给同一个 repair 函数收尾。"
    "repair 里只有两问：第一问，读数的绝对值是不是冲到了二？没有，这层没事，原样返回。冲到了，第二问——当前节点和沉下去那一侧的孩子组成天平，称一称中间货物："
    "中间货物更重，就先对孩子转一次，把重心挪回两端；随后不管走没走这一步，都再做一次普通旋转天平。"
    "注意这套判断从头到尾没有看新关键字落在了哪条路，它只看形状——所以这份 repair 插入和删除可以一字不差地共用，这是后面删除代码特别短的原因。"
).replace("`", "")

P_SEARCH = (
    "查询最能说明这棵树骨子里还是二叉搜索树：小了往左，大了往右，相等就是找着了；一路走到空还没遇见，就没有。"
    "没有旋转，没有修复，一个 while 循环走到底，找到返回节点，没找到返回 NULL。"
).replace("`", "")

P_DELETE = (
    "删除分两段。第一段是二叉搜索树的老规矩，先把节点摘下来：沿查找路由往下走，走到空也没见着，返回空，一切照旧；命中了，先数孩子——零个或一个，"
    "把独子，也可能是空，直接接回父亲，这个节点就地释放；两个孩子挡住了单点替换，就请右子树里最小的关键字后继上来顶替：从右孩子出发一路向左走到头就是它，"
    "把关键字抄到自己身上，再到右子树里把这个后继删掉，于是删有两个孩子的节点就化成了删最多一个孩子的后继。第二段更简单：沿回溯路径逐层调用同一个 repair，一字不用改。"
    "这正是只看形状的好处——传统写法里插入靠新关键字认路，删除手里没有新关键字，只好改读孩子的平衡因子，两张判断表各写一份；我们这里压根没有第一张表，"
    "自然也不需要第二张。还有一点和插入不同：删除的修复可能让局部继续变矮，好在递归本来就要走完整条回溯路，天然保证一路检查到根。"
).replace("`", "")

P_PERF = (
    "性能图使用本次已经完成的实测数据，C 和传统 C 均由 Clang 编译，"
    "C++ 使用我们的平衡因子与天平旋转逻辑，Rust 使用我们的逻辑；"
    "三种本地编译实现分别展示 O0 到 O3，Rust 使用 -O3。电脑运行状态瞬息万变，图一乐，电子斗蛐蛐。"
).replace("`", "")

C_DATA = """typedef struct AVLNode {
    int key;
    int height;                     /* 本节点高度，叶子为 1 */
    struct AVLNode *left, *right;
} AVLNode;

/* 两数取大 */
static int maxInt(int a, int b) { return a > b ? a : b; }

/* 空节点高度记 0，叶子高度为 1 */
static int heightOf(AVLNode *n) { return n ? n->height : 0; }

/* 平衡因子 = 左子树高 - 右子树高，绝对值超过 1 即失衡 */
static int balanceFactor(AVLNode *n) { return heightOf(n->left) - heightOf(n->right); }

/* 插入/删除回溯时，由两个孩子重新算出本节点高度 */
static void updateHeight(AVLNode *n) {
    n->height = 1 + maxInt(heightOf(n->left), heightOf(n->right));
}"""

C_ROTATE = """/* 旋转天平：沉的一端升起当新根，中间货物原路换挂到沉下去的一端 */
static AVLNode *rotate(AVLNode *node) {
    AVLNode *root, *middle;

    if (heightOf(node->right) > heightOf(node->left)) {   /* 右端沉：右端升起 */
        root   = node->right;         /* 升起来的右端 */
        middle = root->left;          /* 中间挂载的货物 */
        root->left  = node;           /* 天平旋转：右端升起成为新根 */
        node->right = middle;         /* 中间货物原路挂回正中间 */
    } else {                          /* 左端沉：左端升起，完全镜像 */
        root   = node->left;
        middle = root->right;
        root->right = node;
        node->left  = middle;
    }

    updateHeight(node);              /* 先更新低下去的，再更新升起来的 */
    updateHeight(root);
    return root;
}"""

C_REPAIR = """/* 哪边沉，哪边就和本节点组成天平；先称货物，再决定转一次还是两次 */
static AVLNode *repair(AVLNode *node) {
    updateHeight(node);
    int bf = balanceFactor(node);

    if (bf > 1) {                            /* 左边沉：杠杆是 node—node->left */
        if (balanceFactor(node->left) < 0)   /* 中间货物更重：先转孩子转移重心 */
            node->left = rotate(node->left);
        return rotate(node);                 /* 旋转天平 */
    }

    if (bf < -1) {                           /* 右边沉：杠杆是 node—node->right */
        if (balanceFactor(node->right) > 0)  /* 中间货物更重 */
            node->right = rotate(node->right);
        return rotate(node);
    }

    return node;                             /* 平衡未被破坏，原样返回 */
}"""

C_INSERT = """static AVLNode *newNode(int key) {
    AVLNode *fresh = malloc(sizeof(AVLNode));
    if (fresh == NULL) exit(1);              /* 内存耗尽：教学代码直接退出，实际项目应向上报告 */
    fresh->key    = key;
    fresh->height = 1;
    fresh->left = fresh->right = NULL;
    return fresh;
}

static AVLNode *insert(AVLNode *node, int key) {
    if (node == NULL) return newNode(key);
    if (key == node->key) return node;           /* 不允许重复关键字 */

    if (key < node->key) node->left  = insert(node->left,  key);
    else                 node->right = insert(node->right, key);

    return repair(node);                     /* 回溯路上每层都称一次 */
}"""

C_SEARCH = """/* 找到返回该节点，没找到返回 NULL */
static AVLNode *search(AVLNode *node, int key) {
    while (node != NULL && key != node->key)
        node = key < node->key ? node->left : node->right;
    return node;
}"""

C_DELETE = """static AVLNode *deleteKey(AVLNode *node, int key) {
    if (node == NULL) return NULL;                 /* 走到空也没见着：树里没有它 */

    if (key < node->key)      node->left  = deleteKey(node->left,  key);
    else if (key > node->key) node->right = deleteKey(node->right, key);
    else {
        if (node->left == NULL || node->right == NULL) {
            AVLNode *child = node->left ? node->left : node->right;
            free(node);
            return child;                          /* 独子（或空）直接接回父亲 */
        }
        AVLNode *succ = node->right;               /* 右子树最小关键字：一路向左 */
        while (succ->left) succ = succ->left;
        node->key  = succ->key;                    /* 后继顶替自己 */
        node->right = deleteKey(node->right, succ->key);   /* 再去右子树删掉后继 */
    }

    return repair(node);                           /* 和插入共用同一份修复 */
}"""

# (header, paragraph, code, seconds, media) — 时长按代码理解难度分配，纯静默；
# media 非空时该页展示 assets/ 下的图片（手稿里对应的插图），不展示代码
SLIDES = (
    ("", "", "", 2.5, ""),                                    # 标题页
    ("实测性能对比", P_PERF, "", 7.0, "avl-performance.svg"),  # 手稿：先对比图，后详细代码
    ("数据结构与四个一句话工具", P_DATA, C_DATA, 8.0, ""),
    ("旋转天平：唯一的旋转原语", P_ROTATE, C_ROTATE, 9.0, ""),
    ("repair：只看形状的修复，插入删除共用", P_INSERT, C_REPAIR, 12.0, ""),
    ("插入：newNode / insert", "", C_INSERT, 6.0, ""),
    ("查询", P_SEARCH, C_SEARCH, 5.0, ""),
    ("删除：deleteKey", P_DELETE, C_DELETE, 12.0, ""),
)
CODE_DURATION = sum(slide[3] for slide in SLIDES)


def total_duration() -> float:
    return CODE_DURATION


def _slide_at(t: float) -> tuple:
    cursor = 0.0
    for slide in SLIDES:
        if t < cursor + slide[3]:
            return slide
        cursor += slide[3]
    return SLIDES[-1]


_STYLE = get_style_by_name("monokai")
_LEXER = get_lexer_by_name("c", stripnl=False)


def _token_color(token) -> tuple[int, int, int]:
    info = _STYLE.style_for_token(token)
    color = info.get("color") or ""
    if len(color) != 6:
        return INK
    return (int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))


def _token_lines(code: str) -> list[list[tuple[object, str]]]:
    lines: list[list[tuple[object, str]]] = [[]]
    for token, text in _LEXER.get_tokens(code):
        parts = text.split("\n")
        for index, part in enumerate(parts):
            if index > 0:
                lines.append([])
            if part:
                lines[-1].append((token, part))
    return lines


def _draw_code(draw: ImageDraw.ImageDraw, code: str, y: float) -> None:
    size = 22
    line_height = 29.0
    for line_tokens in _token_lines(code):
        x = 140.0
        for token, part in line_tokens:
            family = "sans" if any("\u4e00" <= ch <= "\u9fff" for ch in part) else "mono"
            draw_text(draw, (x, y), part, size=size, family=family,
                      fill=_token_color(token), anchor="lm")
            x += text_w(part, size, family)
        y += line_height


def _wrap_clauses(value: str, size: int, width: float) -> list[str]:
    """Greedy clause packing: break only where needed, never mid-clause."""
    import re

    lines: list[str] = []
    for source in value.split("\n"):
        current = ""
        for part in re.findall(r"[^，。；、！？：]*[，。；、！？：]|[^，。；、！？：]+", source):
            if current and text_w(current + part, size) > width:
                lines.append(current)
                current = part
            else:
                current += part
        if current:
            lines.append(current)
    return lines


def draw(image: Image.Image, t: float, tl: Timeline) -> None:
    header, paragraph, code, _seconds, media = _slide_at(t - tl.total)
    draw = ImageDraw.Draw(image)
    if not paragraph and not code and not media:
        draw_mixed(draw, 960, 470, [("我们的 ", INK), ("C 语言代码", ORANGE)], size=64)
        draw_text(draw, (960, 590), "图文对照 · 可暂停细看", size=30, fill=SOFT)
        return
    draw_text(draw, (140, 92), header, size=30, fill=ORANGE, anchor="lm")
    y = 150.0
    if paragraph:
        for line_text in _wrap_clauses(paragraph, 26, 1680):
            draw_text(draw, (140, y), line_text, size=26, fill=INK, anchor="lm")
            y += 38.0
        y += 14.0
    if media:
        draw_source_media(
            image,
            media,
            t,
            0.0,
            loop=False,
            max_width=1500,
            max_height=int(1060 - y - 30),
            x_center=960,
            y_center=int((y + 1060) / 2.0),
        )
        return
    _draw_code(draw, code, y)


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import engine

    tl = engine.prepare()
    engine.register(SCENE_ID, draw)
    out_dir = engine.OUTPUT_DIR / "preview" / SCENE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    cursor = 0.0
    marks = []
    for slide in SLIDES:
        marks.append(cursor + slide[3] / 2.0)
        cursor += slide[3]
    for i, when in enumerate(marks):
        engine.render_frame(tl.total + when).save(out_dir / f"{i}.png")
    print(f"{SCENE_ID}: {len(marks)} previews, duration {CODE_DURATION}s -> {out_dir}")
