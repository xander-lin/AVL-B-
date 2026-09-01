/* perf_bench.c — one workload harness for C, C++, and Rust AVL trees.
 * Every native implementation is exposed through the same small C ABI. */
#define _POSIX_C_SOURCE 199309L
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "avl_variants.h"

#ifndef AVL_BENCH_OPERATIONS
#define AVL_BENCH_OPERATIONS (2 * 1000 * 1000)
#endif

long g_rotOurs = 0, g_rotClassic = 0;
volatile uintptr_t g_sink = 0;

#include "avl_instr.c"   /* lesson C code; rotate() is instrumented below */

/* ===== classic C implementation ===== */
static AVLNode *rotateLeft_c(AVLNode *node) {
    g_rotClassic++;
    AVLNode *root = node->right;
    AVLNode *middle = root->left;
    root->left = node;
    node->right = middle;
    updateHeight(node);
    updateHeight(root);
    return root;
}

static AVLNode *rotateRight_c(AVLNode *node) {
    g_rotClassic++;
    AVLNode *root = node->left;
    AVLNode *middle = root->right;
    root->right = node;
    node->left = middle;
    updateHeight(node);
    updateHeight(root);
    return root;
}

static AVLNode *insert_c(AVLNode *node, int key) {
    if (!node) return newNode(key);
    if (key == node->key) return node;
    if (key < node->key) node->left = insert_c(node->left, key);
    else                 node->right = insert_c(node->right, key);
    updateHeight(node);
    int bf = balanceFactor(node);
    if (bf > 1 && key < node->left->key) return rotateRight_c(node);
    if (bf > 1) {
        node->left = rotateLeft_c(node->left);
        return rotateRight_c(node);
    }
    if (bf < -1 && key > node->right->key) return rotateLeft_c(node);
    if (bf < -1) {
        node->right = rotateRight_c(node->right);
        return rotateLeft_c(node);
    }
    return node;
}

static AVLNode *deleteKey_c(AVLNode *node, int key) {
    if (!node) return NULL;
    if (key < node->key) node->left = deleteKey_c(node->left, key);
    else if (key > node->key) node->right = deleteKey_c(node->right, key);
    else {
        if (!node->left || !node->right) {
            AVLNode *child = node->left ? node->left : node->right;
            free(node);
            return child;
        }
        AVLNode *pred = node->left;
        while (pred->right) pred = pred->right;
        node->key = pred->key;
        node->left = deleteKey_c(node->left, pred->key);
    }
    updateHeight(node);
    int bf = balanceFactor(node);
    if (bf > 1 && balanceFactor(node->left) >= 0) return rotateRight_c(node);
    if (bf > 1) {
        node->left = rotateLeft_c(node->left);
        return rotateRight_c(node);
    }
    if (bf < -1 && balanceFactor(node->right) <= 0) return rotateLeft_c(node);
    if (bf < -1) {
        node->right = rotateRight_c(node->right);
        return rotateLeft_c(node);
    }
    return node;
}

static void freeAll(AVLNode *node) {
    if (!node) return;
    freeAll(node->left);
    freeAll(node->right);
    free(node);
}

/* ===== common harness ===== */
typedef void *(*InsertFn)(void *, int);
typedef void *(*DeleteFn)(void *, int);
typedef void *(*SearchFn)(void *, int);
typedef void (*FreeFn)(void *);
typedef void (*ResetFn)(void);
typedef uint64_t (*RotationsFn)(void);

typedef struct {
    const char *name;
    InsertFn insert;
    DeleteFn delete_key;
    SearchFn search;
    FreeFn free_all;
    ResetFn reset_stats;
    RotationsFn rotations;
} Variant;

static void *ours_insert(void *root, int key) { return insert(root, key); }
static void *ours_delete(void *root, int key) { return deleteKey(root, key); }
static void *ours_search(void *root, int key) { return search(root, key); }
static void ours_free_all(void *root) { freeAll(root); }
static void ours_reset_stats(void) { g_rotOurs = 0; }
static uint64_t ours_rotations(void) { return (uint64_t)g_rotOurs; }

static void *classic_insert(void *root, int key) { return insert_c(root, key); }
static void *classic_delete(void *root, int key) { return deleteKey_c(root, key); }
static void *classic_search(void *root, int key) { return search(root, key); }
static void classic_free_all(void *root) { freeAll(root); }
static void classic_reset_stats(void) { g_rotClassic = 0; }
static uint64_t classic_rotations(void) { return (uint64_t)g_rotClassic; }

static void *cpp_variant_insert(void *root, int key) { return cpp_insert(root, key); }
static void *cpp_variant_delete(void *root, int key) { return cpp_delete(root, key); }
static void *cpp_variant_search(void *root, int key) { return cpp_search(root, key); }
static void cpp_variant_free_all(void *root) { cpp_free_all(root); }

static double now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

static uint32_t next_u32(uint32_t *state) {
    *state = *state * 1664525u + 1013904223u;
    return *state;
}

static double median5(double values[5]) {
    double sorted[5];
    memcpy(sorted, values, sizeof sorted);
    for (int i = 1; i < 5; i++) {
        double value = sorted[i];
        int j = i;
        while (j > 0 && sorted[j - 1] > value) {
            sorted[j] = sorted[j - 1];
            j--;
        }
        sorted[j] = value;
    }
    return sorted[2];
}

static double selected_time(const char *name, double values[5]) {
    if (strcmp(name, "insert") == 0 || strcmp(name, "delete") == 0
        || strcmp(name, "search") == 0) {
        double best = values[0];
        for (int i = 1; i < 5; i++)
            if (values[i] < best) best = values[i];
        return best;
    }
    return median5(values);
}

enum { W_INSERT, W_ASC, W_MIX, W_DELETE, W_SEARCH };

static double run_workload(int kind, const Variant *variant, int n,
                           unsigned seed, uint64_t *rotations) {
    void *tree = NULL;
    int *delete_keys = NULL;
    variant->reset_stats();
    double started = now();

    switch (kind) {
    case W_INSERT: {
        uint32_t state = seed;
        for (int i = 0; i < n; i++)
            tree = variant->insert(tree, (int)(next_u32(&state) % 5000000u));
        break;
    }
    case W_ASC:
        for (int i = 0; i < n; i++) tree = variant->insert(tree, i);
        break;
    case W_MIX: {
        uint32_t state = seed;
        for (int i = 0; i < n; i++) {
            int key = (int)(next_u32(&state) % 150000u);
            if (next_u32(&state) % 10u < 6u)
                tree = variant->insert(tree, key);
            else
                tree = variant->delete_key(tree, key);
        }
        break;
    }
    case W_DELETE: {
        delete_keys = malloc((size_t)n * sizeof(*delete_keys));
        if (!delete_keys) exit(1);
        uint32_t state = seed;
        for (int i = 0; i < n; i++) delete_keys[i] = i;
        for (int i = n - 1; i > 0; i--) {
            int j = (int)(next_u32(&state) % (uint32_t)(i + 1));
            int tmp = delete_keys[i];
            delete_keys[i] = delete_keys[j];
            delete_keys[j] = tmp;
        }
        for (int i = 0; i < n; i++) tree = variant->insert(tree, delete_keys[i]);
        variant->reset_stats();
        started = now();
        for (int i = 0; i < n; i++) tree = variant->delete_key(tree, delete_keys[i]);
        break;
    }
    case W_SEARCH: {
        uint32_t state = seed;
        int *keys = malloc((size_t)n * sizeof(*keys));
        if (!keys) exit(1);
        for (int i = 0; i < n; i++) keys[i] = i;
        for (int i = n - 1; i > 0; i--) {
            int j = (int)(next_u32(&state) % (uint32_t)(i + 1));
            int tmp = keys[i];
            keys[i] = keys[j];
            keys[j] = tmp;
        }
        for (int i = 0; i < n; i++) tree = variant->insert(tree, keys[i]);
        free(keys);
        break;
    }
    }

    double elapsed = now() - started;
    free(delete_keys);

    if (kind == W_SEARCH) {
        started = now();
        uintptr_t hits = 0;
        for (unsigned i = 0; i < 300000u; i++) {
            int key = (int)((i * 7919u) % (unsigned)(n * 2)) - n / 3;
            hits += variant->search(tree, key) != NULL;
        }
        elapsed += now() - started;
        g_sink += hits;
    }

    *rotations = variant->rotations();
    g_sink ^= (uintptr_t)tree;
    variant->free_all(tree);
    return elapsed;
}

static void bench(const Variant *variant, const char *name, int kind, int n,
                  unsigned seed, int csv, const char *optimization) {
    double times[5];
    uint64_t rotations[5];
    for (int round = 0; round < 5; round++)
        times[round] = run_workload(kind, variant, n, seed + (unsigned)round,
                                    &rotations[round]);

    double measured = selected_time(name, times);
    if (csv) {
        const char *selection = (strcmp(name, "insert") == 0
                              || strcmp(name, "delete") == 0
                              || strcmp(name, "search") == 0) ? "best" : "median";
        printf("%s,%s,%s,%s,%.6f,%llu\n", variant->name, optimization, name,
               selection, measured * 1e3, (unsigned long long)rotations[0]);
    } else {
        printf("%-8s %-10s %8.1f ms (%llu rot)\n", variant->name, name,
               measured * 1e3, (unsigned long long)rotations[0]);
    }
}

int main(int argc, char **argv) {
    int csv = argc > 1 && strcmp(argv[1], "--csv") == 0;
    const char *optimization = argc > 2 ? argv[2] : "O2";
    const Variant variants[] = {
        {"c-ours", ours_insert, ours_delete, ours_search, ours_free_all,
         ours_reset_stats, ours_rotations},
        {"c-classic", classic_insert, classic_delete, classic_search,
         classic_free_all, classic_reset_stats, classic_rotations},
        {"cpp", cpp_variant_insert, cpp_variant_delete, cpp_variant_search,
         cpp_variant_free_all, cpp_reset_stats, cpp_rotations},
    };
    const char *names[] = {"insert", "delete", "search", "ascending", "mixed"};
    const int kinds[] = {W_INSERT, W_DELETE, W_SEARCH, W_ASC, W_MIX};
    const unsigned seeds[] = {1, 2, 3, 4, 5};
    const int workload_count = (int)(sizeof names / sizeof names[0]);
    const int operations = AVL_BENCH_OPERATIONS;

    setvbuf(stdout, NULL, _IOLBF, 0);
    for (size_t v = 0; v < sizeof variants / sizeof variants[0]; v++)
        for (int i = 0; i < workload_count; i++)
            bench(&variants[v], names[i], kinds[i], operations, seeds[i],
                  csv, optimization);
    return 0;
}
