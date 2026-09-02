# Tree Media Sources

`generate_tree_media.py` generates the SVG and motion media used by the tree notes:

- `二叉搜索树.md`
- `AVL树.md`
- `B树.md`
- `红黑树.md`

Run it from the project root:

```sh
python3 scripts/generate_tree_media.py
```

Requirements:

- `python3`
- `rsvg-convert`
- `ffmpeg`
- ImageMagick `magick` or `convert`

## Frame inspection sheets

`check_video_frames.py` creates compressed contact sheets for visual inspection
of a rendered video. The default protocol is for the course's 24 fps output:
one source frame every 8 frames, nine sampled frames per 3x3 sheet, followed by
JPEG compression at quality 50. Each sheet includes source frame numbers and
timestamps, and `manifest.json` records the exact mapping back to the video.

Run it from the project root:

```sh
python3 scripts/check_video_frames.py \
  outputs/avl-video/avl-recap.mp4 \
  outputs/avl-video/frame-check
```

The input FPS is checked by default. For a 30 fps source asset, pass its real
rate explicitly:

```sh
python3 scripts/check_video_frames.py \
  assets/avl-right-left.webm \
  /tmp/avl-right-left-frame-check \
  --fps 30
```

Useful options include `--start-frame`, `--end-frame`, `--quality`,
`--max-width`, `--group-size`, and `--columns`. A final incomplete group is
kept so the end of the video is still inspected.

The script defines each tree state directly. Static SVGs use transparent backgrounds and sky-blue `#38BDF8` marks. All process animations are rendered as transparent WebM files with continuous frame-by-frame motion. The three B-tree animations (`btree-insert`, `btree-borrow`, `btree-merge`) are built on a cell-based scene engine with NO outer node frames: a B-tree node is drawn as an array of tightly touching cell boxes, multiway structure is implied by adjacency, and every edge hangs from a gap boundary under the parent row (row-left + slot * CELL_W). Every visible change is cell motion — keys fall in inside their cells, slide aside as siblings land, travel between nodes during splits, borrowing, and merging, and fade out quickly when deleted. The BST degeneration animation keeps the waiting keys in a top queue, moves each key directly into its final tree position, and crops all transparent margins across the full animation. The AVL single-left animation levels the original balance, restores its original tilt and cargo position, then rotates to the opposite side while the cargo slides across. The general right-rotation animation detaches all three mounted subtrees to waiting spots, rotates the bare two-node lever, then reattaches the subtrees in left, middle, right order with their edges fading back in. The middle-imbalance rotation follows the judgment order of the lesson: captions first read the shape (the right side stands taller), then locate the lever z—y from the heavy side, and only then weigh the three cargos to identify the heavier middle cargo X as the middle imbalance. A red outline marks the heavier cargo and a bold stroke marks the current lever. It first rotates the subtree containing X to move the center of gravity to the right, then treats the lever as the reshaped z—X and repeats the detach, spin, and reattach cycle as a second ordinary rotation. Every caption stays on screen for a full two seconds. The full AVL insertion animation simulates `1, 3, 7, 6, 4, 5, 2, 0, -2, -1`: every value falls into its search position; each ordinary rotation first detaches the local subtree from its parent, pauses, detaches the three mounted cargo groups, pauses, turns the bare lever, pauses, reattaches the cargo groups in left, middle, right order, pauses, and reconnects the rotated subtree. Double rotations perform that complete sequence twice. The AVL deletion animation removes `1`, pauses on the unbalanced tree, then uses the same staged left-rotation process. The lesson-example rotation animation selects the `5—9` lever in the example-one tree, detaches the three cargos `3`, `6`, and `14→17` to waiting spots, spins the bare lever through a continuous quarter turn, then reattaches every cargo to its own side. The B-tree insertion animation inserts `10..130` one by one inside their own cells, promoting the upper median on every overflow. Each upward split keeps the original parent-child line alive — its anchor stays glued to the parent key's right boundary and its far end follows the left half of the torn array; the promoted key rises vertically to the parent row's height directly above its leaf position, pauses there as an independent bare node flanked by two edges anchored at its own cell boundaries, then slides sideways along the row into its slot — where its left tether lands exactly on top of the original line (the coincidence test) and its right tether lands on the row's right boundary. The cascade ends the film: `120` merges into the already-full root [30,60,90], which splits with `90` rising as a brand-new root, and the tree grows its third level. The B-tree borrow animation pulls the parent separator down between both children into one contiguous six-key row, strikes and removes the target, then re-promotes the middle key — the same separator — because five survivors exceed order-4 capacity. The unified lend animation (`btree-lend`) runs the same recipe against a bare left leaf and a full right sibling: after the delete only four keys remain, so the promoted upper median is the sibling's `60`, not the old separator. The three traditional-method animations mirror the same order-4 cases: `btree-classic-plain` strikes and removes `10` inside a full leaf and nothing else moves; `btree-classic-lend` marks the emptied leaf with a dashed ghost cell, pulses a ring on the rich sibling, raises `50` into the parent, then sinks `40` into the empty seat; `btree-classic-merge` pulses the ring on the minimum sibling, pulls `40` down between the struck `10` and `60` into one contiguous row, removes `10`, and raises `[40,60]` as the new root. The B-tree merge animation (`btree-merge`) drops the separator cell onto the leaf row, then slides the sibling key across; when the two cells touch they simply are one contiguous array node — nothing is pre-drawn, the node exists because its cells stand together. The merge animation then raises that node to take the root's place one level higher. `btree-delete-5basic` and `btree-delete-5cascade` share one parameterized builder (`btree_delete_complex_frames(order, tree_spec, ops, width, height, leaf_gap)`): the pull-down language has the separator descending with two unbroken lines to its children, a gray thick-dashed ghost in the vacated slot, no line to the old node, promotion rises with the same two lines to its future children, and any node below minimum keys gains a red rim. The basic video covers swap, plain merge, and promotion on a three-level order-5 tree; the cascade video uses a four-level order-5 tree where a leaf merge underflows level three, an internal merge underflows level two, and the root merge empties the root so the whole merged subtree settles upward one level (three-level shrink). Underflow red rims, four-level layout depths, and the settle-from-current-positions rework live inside the builder. The three compare animations (`btree-case1-compare`, `btree-case2-compare`, `btree-case3-compare`) replay each deletion case on one 1100x660 canvas: a centered glowing title card reads 我们的方法 before the silent unified segment, then a 传统方法 card introduces the traditional segment, where bottom-center captions narrate the traditional judgment chain (删 10 → 下溢了吗 → 兄弟够借吗 → 借或合) in sync with each phase; both segments of one case share the same tree geometry so the shape never jumps between methods. The six single-method scenes are thin wrappers over parameterized `*_frames` builders so the compare scenes reuse the exact same choreography. The search static routes a real lookup for `90` through the three-level order-4 tree with the comparison path highlighted, and the order-scaling static compares how many keys three levels hold at orders 4, 100, and 512. The red-black encoding animation morphs one 2-3-4 tree into its binary encoding while edges follow the traveling keys. The red-black insertion animation drops nodes `10`, `20`, `30` in one by one — each arrives as a red square node and the first is painted black as the root; it holds on the red-red violation, rotates with the `20—10` link crossfading dashed to solid, then recolors into the black-root encoding. The red-black color-flip animation lands `5`, holds on the uncle-red violation, then crossfades the flip without rotation. The red-black deletion animation fades `10` into a double-black NIL marker, then repairs by rotation. Red-black binary nodes are drawn as squares to match the B-tree box language. Red-black figures use the literal two colors: red members are red-filled squares joined by red links; black members are dark-filled squares with a visible rim joined by slate-gray links. The encoding animation stays sky-blue while the multiway structure morphs into binary form and only takes on the red-black colors once the conversion completes.
The B-tree static SVGs are consecutive stages of one real tree: `btree-order-4.svg` shows the pre-split tree with a four-cell overflow leaf, and `btree-search.svg` shows the resulting three-level tree and lookup route. Both use the AVL neon square-cell visual language.

`btree-delete-5` is the traditional deletion walkthrough: one four-level order-5 tree shows successor replacement, direct leaf removal, sibling inspection, borrowing by rotation when possible, merging when borrowing is impossible, and a leaf-to-root underflow cascade. `btree-delete-5-slow.webm` is regenerated from that asset at 0.6x playback speed for detailed viewing. `btree-insert` plays one continuous order-4 tree: the first two splits merge the promoted key beside existing parent keys (rise, hover, then slide), then inserting `45,55` overflows the middle child, the parent tears open between `30` and `60`, and the upper median `50` is pushed straight into the opened middle slot without hovering or sliding. It supersedes the separate `btree-delete-5basic` and `btree-delete-5cascade` assets.

The five `rb-delete-case*.webm` assets show the local repairs after deleting a lone black leaf: a black sibling with two red children, a black sibling with one red child, a black sibling with no red child and a black parent, the same empty-sibling case with a red parent, and a red sibling. The renderer keeps the deleted node visible while it fades out, shows the double-black debt with the deleted key, then separates rotation/reparenting from recoloring; in the upward-promotion case the black leader travels upward before turning red, and the return phase turns it black while its two children turn red.

## B-tree course video

The narrated B-tree course video is built shot by shot under `scripts/btree/`.
`prepare_audio.py` transcribes `audio/B/*.wav` into `outputs/btree-prep/b-asr.json`
(word-level timestamps, same faster-whisper settings as the AVL prep); pass
`--only N` to transcribe one recording index. `shot01.py` renders the opening
shot (BST degeneration → layer/index reading → AVL shape repair → a four-key
order-4 B-tree growing bottom-up with the promoted 30) as one pure
`draw_frame(t)` state function timed by word stamps, then encodes
`outputs/btree-video/shot01-intro.mp4` (1920x1080@60 H.264 + AAC) with a
sidecar SRT. `--preview --at t1,t2` writes checkpoint frames without encoding.

## Red-black bridge

`rb/shot17.py` builds the existing narrated bridge from a four-order B-tree to
its red-black binary encoding. It maps the full `rb-encoding.webm` morph into
the available 6.34-second bridge narration and holds the completed encoding to
the end of the recording. Run it from the project root:

```sh
python3 scripts/rb/shot17.py
```

## B-tree deletion course shots

`btree/deletion_shots.py` renders the newly recorded deletion chapter one
shot at a time. Its outputs are intentionally separate from the completed
pre-deletion and post-deletion B-tree sections under `outputs/btree-video/`.

```sh
python3 scripts/btree/deletion_shots.py --shot 1
```

The first shot uses the new recording `3` to introduce the traditional
deletion branches and the separate `首领回家` semantic path. Use preview mode
before encoding a new shot:

```sh
python3 scripts/btree/deletion_shots.py --shot 1 --preview --at 1,8,12,16,19
```
