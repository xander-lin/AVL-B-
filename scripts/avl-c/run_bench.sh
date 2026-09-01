#!/bin/sh
# Compiles C/C++ with clang and the Rust lesson implementation, then writes
# measured data and regenerates the chart.
set -eu

SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR"
MD="../../AVL树(命名来自他的两个作者).md"
TMP=/tmp/opencode
RESULTS=avl-performance.csv
OPERATIONS=${AVL_OPERATIONS:-2000000}

awk '/^```c$/{f=1;next} /^```$/{f=0} f' "$MD" > "$TMP/avl_lesson_blocks.c"
awk '/^```rust$/{f=1;next} /^```$/{f=0} f' "$MD" > "$TMP/avl_lesson.rs"
awk '/^static AVLNode \*rotate\(AVLNode \*node\) \{/{print; print "    g_rotOurs++;"; next} {print}' \
    "$TMP/avl_lesson_blocks.c" > "$TMP/avl_instr.c"

RUSTC=${RUSTC:-rustc}
printf '%s\n' 'implementation,optimization,workload,selection,milliseconds,rotations' > "$RESULTS"

for optimization in O0 O1 O2 O3; do
    clang -std=c11 -Wall -Wextra -"$optimization" -DAVL_BENCH_OPERATIONS="$OPERATIONS" \
        -I"$TMP" -c perf_bench.c -o "$TMP/perf_bench-$optimization.o"
    clang++ -std=c++20 -Wall -Wextra -"$optimization" -c cpp_avl.cpp \
        -o "$TMP/cpp_avl-$optimization.o"
    clang++ "$TMP/perf_bench-$optimization.o" "$TMP/cpp_avl-$optimization.o" \
        -o "$TMP/avl-bench-$optimization"
    "$TMP/avl-bench-$optimization" --csv "$optimization" >> "$RESULTS"
done

awk '1' rust_bench_harness.rs >> "$TMP/avl_lesson.rs"
"$RUSTC" --edition=2024 -C opt-level=3 -C debuginfo=0 \
    -C target-cpu=native -C lto=fat -C codegen-units=1 -C panic=abort \
    "$TMP/avl_lesson.rs" -o "$TMP/avl-bench-rust"
"$TMP/avl-bench-rust" "$OPERATIONS" >> "$RESULTS"

python3 ../generate_performance_svg.py "$RESULTS" ../../assets/avl-performance.svg
printf 'Wrote %s and ../../assets/avl-performance.svg\n' "$RESULTS"
