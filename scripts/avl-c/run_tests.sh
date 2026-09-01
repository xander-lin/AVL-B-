#!/bin/sh
# Extracts the ```c blocks from the AVL lesson markdown and runs the full
# correctness suite: invariants + equivalence against classic AVL.
# The markdown file is the single source of truth being tested.
set -e
cd "$(dirname "$0")"
MD="../../AVL树(命名来自他的两个作者).md"
OUT=/tmp/opencode/avl_lesson_blocks.c

awk '/^```c$/{f=1;next} /^```$/{f=0} f' "$MD" > "$OUT"

clang -std=c11 -Wall -Wextra -O1 -fsanitize=address,undefined \
    -I/tmp/opencode test_harness.c -o /tmp/opencode/avl-test
/tmp/opencode/avl-test

clang -std=c11 -Wall -Wextra -O1 -fsanitize=address,undefined \
    -I/tmp/opencode test_equivalence.c -o /tmp/opencode/avl-equiv
/tmp/opencode/avl-equiv

clang -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
    -c test_native_variants.c -o /tmp/opencode/test_native_variants.o
clang++ -std=c++20 -Wall -Wextra -Werror -fsanitize=address,undefined \
    -c cpp_avl.cpp -o /tmp/opencode/cpp_avl-test.o
clang++ -fsanitize=address,undefined \
    /tmp/opencode/test_native_variants.o /tmp/opencode/cpp_avl-test.o \
    -o /tmp/opencode/avl-native-test
/tmp/opencode/avl-native-test

awk '/^```rust$/{f=1;next} /^```$/{f=0} f' "$MD" > /tmp/opencode/avl_lesson.rs
awk '1' test_rust_harness.rs >> /tmp/opencode/avl_lesson.rs
RUSTC=${RUSTC:-rustc}
$RUSTC --edition=2024 -C opt-level=1 -D warnings \
    /tmp/opencode/avl_lesson.rs -o /tmp/opencode/avl-rust-test
/tmp/opencode/avl-rust-test
