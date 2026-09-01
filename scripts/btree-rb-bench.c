/*
 * btree-rb-bench.c
 *
 * In-memory comparison of a traditional minimum-degree-2 B tree (a 4-way
 * B tree) and a red-black tree. Every key carries a 32-byte payload. B-tree
 * deletion uses the textbook borrow-before-descend / merge-before-descend
 * algorithm. Both structures receive exactly the same records and query order.
 *
 * Build:
 *   clang -std=c11 -O2 -Wall -Wextra -Wpedantic btree-rb-bench.c -o btree-rb-bench
 * Run:
 *   ./btree-rb-bench 1000000 3
 */
#define _POSIX_C_SOURCE 200809L

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

enum { PAYLOAD_BYTES = 32 };

typedef struct {
    int key;
    unsigned char payload[PAYLOAD_BYTES];
} Record;

_Static_assert(sizeof(((Record *)0)->payload) == 32, "payload must be 32 bytes");

static Record make_record(int key) {
    Record record = { .key = key };
    for (size_t i = 0; i < PAYLOAD_BYTES; ++i)
        record.payload[i] = (unsigned char)((unsigned)key * 31u + (unsigned)i);
    return record;
}

static bool record_payload_is_valid(const Record *record) {
    for (size_t i = 0; i < PAYLOAD_BYTES; ++i) {
        unsigned char expected =
            (unsigned char)((unsigned)record->key * 31u + (unsigned)i);
        if (record->payload[i] != expected)
            return false;
    }
    return true;
}

enum {
    BTREE_MIN_DEGREE = 2,
    BTREE_MAX_KEYS = 2 * BTREE_MIN_DEGREE - 1,
    BTREE_MAX_CHILDREN = BTREE_MAX_KEYS + 1,
};

typedef struct BTreeNode {
    int count;
    Record records[BTREE_MAX_KEYS];
    bool leaf;
    struct BTreeNode *child[BTREE_MAX_CHILDREN];
} BTreeNode;

typedef struct {
    BTreeNode *root;
    size_t live_nodes;
    size_t peak_nodes;
} BTree;

static BTreeNode *btree_new_node(BTree *tree, bool leaf) {
    BTreeNode *node = malloc(sizeof(*node));
    if (node == NULL) {
        fputs("out of memory\n", stderr);
        exit(EXIT_FAILURE);
    }
    node->count = 0;
    node->leaf = leaf;
    for (int i = 0; i < BTREE_MAX_CHILDREN; ++i)
        node->child[i] = NULL;
    ++tree->live_nodes;
    if (tree->live_nodes > tree->peak_nodes)
        tree->peak_nodes = tree->live_nodes;
    return node;
}

static void btree_free_node(BTree *tree, BTreeNode *node) {
    free(node);
    --tree->live_nodes;
}

static int btree_lower_bound(const BTreeNode *node, int key) {
    int index = 0;
    while (index < node->count && node->records[index].key < key)
        ++index;
    return index;
}

static const Record *btree_search(const BTreeNode *node, int key) {
    while (node != NULL) {
        int index = btree_lower_bound(node, key);
        if (index < node->count && node->records[index].key == key)
            return &node->records[index];
        if (node->leaf)
            return NULL;
        node = node->child[index];
    }
    return NULL;
}

static void btree_split_child_in(BTree *tree, BTreeNode *parent, int index) {
    BTreeNode *left = parent->child[index];
    BTreeNode *right = btree_new_node(tree, left->leaf);
    const int middle = BTREE_MIN_DEGREE - 1;
    const int old_count = left->count;

    right->count = old_count - middle - 1;
    for (int i = 0; i < right->count; ++i)
        right->records[i] = left->records[middle + 1 + i];
    if (!left->leaf) {
        for (int i = 0; i <= right->count; ++i)
            right->child[i] = left->child[middle + 1 + i];
        for (int i = middle + 1; i <= old_count; ++i)
            left->child[i] = NULL;
    }
    left->count = middle;

    for (int i = parent->count; i > index; --i)
        parent->records[i] = parent->records[i - 1];
    for (int i = parent->count + 1; i > index + 1; --i)
        parent->child[i] = parent->child[i - 1];
    parent->records[index] = left->records[middle];
    parent->child[index + 1] = right;
    ++parent->count;
}

static void btree_insert_nonfull(BTree *tree, BTreeNode *node, Record record) {
    for (;;) {
        int index;
        if (node->leaf) {
            index = node->count - 1;
            while (index >= 0 && node->records[index].key > record.key) {
                node->records[index + 1] = node->records[index];
                --index;
            }
            node->records[index + 1] = record;
            ++node->count;
            return;
        }

        index = btree_lower_bound(node, record.key);
        if (node->child[index]->count == BTREE_MAX_KEYS) {
            btree_split_child_in(tree, node, index);
            if (record.key > node->records[index].key)
                ++index;
        }
        node = node->child[index];
    }
}

static void btree_insert(BTree *tree, Record record) {
    if (tree->root == NULL) {
        tree->root = btree_new_node(tree, true);
        tree->root->records[0] = record;
        tree->root->count = 1;
        return;
    }

    if (btree_search(tree->root, record.key) != NULL)
        return;

    if (tree->root->count == BTREE_MAX_KEYS) {
        BTreeNode *old_root = tree->root;
        BTreeNode *new_root = btree_new_node(tree, false);
        new_root->child[0] = old_root;
        tree->root = new_root;
        btree_split_child_in(tree, new_root, 0);
    }
    btree_insert_nonfull(tree, tree->root, record);
}

static Record btree_predecessor(const BTreeNode *node) {
    while (!node->leaf)
        node = node->child[node->count];
    return node->records[node->count - 1];
}

static Record btree_successor(const BTreeNode *node) {
    while (!node->leaf)
        node = node->child[0];
    return node->records[0];
}

static void btree_remove_from_leaf(BTreeNode *node, int index) {
    for (int i = index + 1; i < node->count; ++i)
        node->records[i - 1] = node->records[i];
    --node->count;
}

static void btree_borrow_from_previous(BTreeNode *parent, int index) {
    BTreeNode *child = parent->child[index];
    BTreeNode *sibling = parent->child[index - 1];

    for (int i = child->count; i > 0; --i)
        child->records[i] = child->records[i - 1];
    if (!child->leaf) {
        for (int i = child->count + 1; i > 0; --i)
            child->child[i] = child->child[i - 1];
        child->child[0] = sibling->child[sibling->count];
    }
    child->records[0] = parent->records[index - 1];
    parent->records[index - 1] = sibling->records[sibling->count - 1];
    --sibling->count;
    ++child->count;
}

static void btree_borrow_from_next(BTreeNode *parent, int index) {
    BTreeNode *child = parent->child[index];
    BTreeNode *sibling = parent->child[index + 1];

    child->records[child->count] = parent->records[index];
    if (!child->leaf)
        child->child[child->count + 1] = sibling->child[0];
    parent->records[index] = sibling->records[0];
    for (int i = 1; i < sibling->count; ++i)
        sibling->records[i - 1] = sibling->records[i];
    if (!sibling->leaf) {
        for (int i = 1; i <= sibling->count; ++i)
            sibling->child[i - 1] = sibling->child[i];
    }
    --sibling->count;
    ++child->count;
}

/* Merge child[index], parent->records[index], and child[index + 1]. */
static void btree_merge_children(BTree *tree, BTreeNode *parent, int index) {
    BTreeNode *left = parent->child[index];
    BTreeNode *right = parent->child[index + 1];
    const int left_count = left->count;

    left->records[left_count] = parent->records[index];
    for (int i = 0; i < right->count; ++i)
        left->records[left_count + 1 + i] = right->records[i];
    if (!left->leaf) {
        for (int i = 0; i <= right->count; ++i)
            left->child[left_count + 1 + i] = right->child[i];
    }
    left->count = left_count + 1 + right->count;

    for (int i = index + 1; i < parent->count; ++i)
        parent->records[i - 1] = parent->records[i];
    for (int i = index + 2; i <= parent->count; ++i)
        parent->child[i - 1] = parent->child[i];
    parent->child[parent->count] = NULL;
    --parent->count;
    btree_free_node(tree, right);
}

/* Ensure child[index] has at least the minimum number of keys before descent. */
static void btree_fill(BTree *tree, BTreeNode *parent, int index) {
    if (index > 0 && parent->child[index - 1]->count >= BTREE_MIN_DEGREE)
        btree_borrow_from_previous(parent, index);
    else if (index < parent->count
             && parent->child[index + 1]->count >= BTREE_MIN_DEGREE)
        btree_borrow_from_next(parent, index);
    else if (index < parent->count)
        btree_merge_children(tree, parent, index);
    else
        btree_merge_children(tree, parent, index - 1);
}

static void btree_delete_iterative(BTree *tree, BTreeNode *node, int key) {
    for (;;) {
        int index = btree_lower_bound(node, key);
        if (index < node->count && node->records[index].key == key) {
        if (node->leaf) {
            btree_remove_from_leaf(node, index);
            return;
        }

        if (node->child[index]->count >= BTREE_MIN_DEGREE) {
            Record predecessor = btree_predecessor(node->child[index]);
            node->records[index] = predecessor;
            key = predecessor.key;
            node = node->child[index];
        } else if (node->child[index + 1]->count >= BTREE_MIN_DEGREE) {
            Record successor = btree_successor(node->child[index + 1]);
            node->records[index] = successor;
            key = successor.key;
            node = node->child[index + 1];
        } else {
            btree_merge_children(tree, node, index);
            node = node->child[index];
        }
            continue;
        }

        if (node->leaf)
            return;

        const bool was_last_child = index == node->count;
        if (node->child[index]->count < BTREE_MIN_DEGREE)
            btree_fill(tree, node, index);
        if (was_last_child && index > node->count)
            --index;
        node = node->child[index];
    }
}

static bool btree_delete(BTree *tree, int key) {
    if (tree->root == NULL || btree_search(tree->root, key) == NULL)
        return false;
    btree_delete_iterative(tree, tree->root, key);
    if (tree->root->count == 0) {
        BTreeNode *old_root = tree->root;
        tree->root = old_root->leaf ? NULL : old_root->child[0];
        btree_free_node(tree, old_root);
    }
    return true;
}

static void btree_destroy(BTree *tree, BTreeNode *node) {
    if (node == NULL)
        return;

    size_t stack_count = 1;
    size_t stack_capacity = 64;
    BTreeNode **stack = malloc(stack_capacity * sizeof(*stack));
    if (stack == NULL)
        exit(EXIT_FAILURE);
    stack[0] = node;
    while (stack_count != 0) {
        node = stack[--stack_count];
        if (!node->leaf) {
            for (int i = 0; i <= node->count; ++i) {
                if (stack_count == stack_capacity) {
                    stack_capacity *= 2;
                    BTreeNode **grown = realloc(
                        stack, stack_capacity * sizeof(*stack));
                    if (grown == NULL) {
                        free(stack);
                        exit(EXIT_FAILURE);
                    }
                    stack = grown;
                }
                stack[stack_count++] = node->child[i];
            }
        }
        btree_free_node(tree, node);
    }
    free(stack);
}

typedef enum { RB_RED, RB_BLACK } RBColor;

typedef struct RBNode {
    Record record;
    RBColor color;
    struct RBNode *left;
    struct RBNode *right;
    struct RBNode *parent;
} RBNode;

typedef struct {
    RBNode *root;
    RBNode *nil;
    size_t live_nodes;
    size_t peak_nodes;
} RBTree;

static RBTree *rb_new_tree(void) {
    RBTree *tree = malloc(sizeof(*tree));
    if (tree == NULL)
        exit(EXIT_FAILURE);
    tree->nil = malloc(sizeof(*tree->nil));
    if (tree->nil == NULL)
        exit(EXIT_FAILURE);
    tree->nil->color = RB_BLACK;
    tree->nil->left = tree->nil;
    tree->nil->right = tree->nil;
    tree->nil->parent = tree->nil;
    tree->root = tree->nil;
    tree->live_nodes = 0;
    tree->peak_nodes = 0;
    return tree;
}

static RBNode *rb_new_node(RBTree *tree, int key) {
    RBNode *node = malloc(sizeof(*node));
    if (node == NULL) {
        fputs("out of memory\n", stderr);
        exit(EXIT_FAILURE);
    }
    node->record = make_record(key);
    node->color = RB_RED;
    node->left = tree->nil;
    node->right = tree->nil;
    node->parent = tree->nil;
    ++tree->live_nodes;
    if (tree->live_nodes > tree->peak_nodes)
        tree->peak_nodes = tree->live_nodes;
    return node;
}

static void rb_left_rotate(RBTree *tree, RBNode *node) {
    RBNode *pivot = node->right;
    node->right = pivot->left;
    if (pivot->left != tree->nil)
        pivot->left->parent = node;
    pivot->parent = node->parent;
    if (node->parent == tree->nil)
        tree->root = pivot;
    else if (node == node->parent->left)
        node->parent->left = pivot;
    else
        node->parent->right = pivot;
    pivot->left = node;
    node->parent = pivot;
}

static void rb_right_rotate(RBTree *tree, RBNode *node) {
    RBNode *pivot = node->left;
    node->left = pivot->right;
    if (pivot->right != tree->nil)
        pivot->right->parent = node;
    pivot->parent = node->parent;
    if (node->parent == tree->nil)
        tree->root = pivot;
    else if (node == node->parent->right)
        node->parent->right = pivot;
    else
        node->parent->left = pivot;
    pivot->right = node;
    node->parent = pivot;
}

static void rb_insert_fixup(RBTree *tree, RBNode *node) {
    while (node->parent->color == RB_RED) {
        if (node->parent == node->parent->parent->left) {
            RBNode *uncle = node->parent->parent->right;
            if (uncle->color == RB_RED) {
                node->parent->color = RB_BLACK;
                uncle->color = RB_BLACK;
                node->parent->parent->color = RB_RED;
                node = node->parent->parent;
            } else {
                if (node == node->parent->right) {
                    node = node->parent;
                    rb_left_rotate(tree, node);
                }
                node->parent->color = RB_BLACK;
                node->parent->parent->color = RB_RED;
                rb_right_rotate(tree, node->parent->parent);
            }
        } else {
            RBNode *uncle = node->parent->parent->left;
            if (uncle->color == RB_RED) {
                node->parent->color = RB_BLACK;
                uncle->color = RB_BLACK;
                node->parent->parent->color = RB_RED;
                node = node->parent->parent;
            } else {
                if (node == node->parent->left) {
                    node = node->parent;
                    rb_right_rotate(tree, node);
                }
                node->parent->color = RB_BLACK;
                node->parent->parent->color = RB_RED;
                rb_left_rotate(tree, node->parent->parent);
            }
        }
    }
    tree->root->color = RB_BLACK;
}

static RBNode *rb_search(const RBTree *tree, int key) {
    RBNode *node = tree->root;
    while (node != tree->nil && node->record.key != key)
        node = key < node->record.key ? node->left : node->right;
    return node;
}

static void rb_insert(RBTree *tree, int key) {
    RBNode *parent = tree->nil;
    RBNode *node = tree->root;
    while (node != tree->nil) {
        parent = node;
        if (key == node->record.key)
            return;
        node = key < node->record.key ? node->left : node->right;
    }

    node = rb_new_node(tree, key);
    node->parent = parent;
    if (parent == tree->nil)
        tree->root = node;
    else if (key < parent->record.key)
        parent->left = node;
    else
        parent->right = node;
    rb_insert_fixup(tree, node);
}

static RBNode *rb_minimum(const RBTree *tree, RBNode *node) {
    while (node->left != tree->nil)
        node = node->left;
    return node;
}

static void rb_transplant(RBTree *tree, RBNode *old_node, RBNode *new_node) {
    if (old_node->parent == tree->nil)
        tree->root = new_node;
    else if (old_node == old_node->parent->left)
        old_node->parent->left = new_node;
    else
        old_node->parent->right = new_node;
    new_node->parent = old_node->parent;
}

static void rb_delete_fixup(RBTree *tree, RBNode *node) {
    while (node != tree->root && node->color == RB_BLACK) {
        if (node == node->parent->left) {
            RBNode *sibling = node->parent->right;
            if (sibling->color == RB_RED) {
                sibling->color = RB_BLACK;
                node->parent->color = RB_RED;
                rb_left_rotate(tree, node->parent);
                sibling = node->parent->right;
            }
            if (sibling->left->color == RB_BLACK
                && sibling->right->color == RB_BLACK) {
                sibling->color = RB_RED;
                node = node->parent;
            } else {
                if (sibling->right->color == RB_BLACK) {
                    sibling->left->color = RB_BLACK;
                    sibling->color = RB_RED;
                    rb_right_rotate(tree, sibling);
                    sibling = node->parent->right;
                }
                sibling->color = node->parent->color;
                node->parent->color = RB_BLACK;
                sibling->right->color = RB_BLACK;
                rb_left_rotate(tree, node->parent);
                node = tree->root;
            }
        } else {
            RBNode *sibling = node->parent->left;
            if (sibling->color == RB_RED) {
                sibling->color = RB_BLACK;
                node->parent->color = RB_RED;
                rb_right_rotate(tree, node->parent);
                sibling = node->parent->left;
            }
            if (sibling->right->color == RB_BLACK
                && sibling->left->color == RB_BLACK) {
                sibling->color = RB_RED;
                node = node->parent;
            } else {
                if (sibling->left->color == RB_BLACK) {
                    sibling->right->color = RB_BLACK;
                    sibling->color = RB_RED;
                    rb_left_rotate(tree, sibling);
                    sibling = node->parent->left;
                }
                sibling->color = node->parent->color;
                node->parent->color = RB_BLACK;
                sibling->left->color = RB_BLACK;
                rb_right_rotate(tree, node->parent);
                node = tree->root;
            }
        }
    }
    node->color = RB_BLACK;
}

static bool rb_delete(RBTree *tree, int key) {
    RBNode *removed = rb_search(tree, key);
    if (removed == tree->nil)
        return false;

    RBNode *fix_node;
    RBColor removed_color = removed->color;
    if (removed->left == tree->nil) {
        fix_node = removed->right;
        rb_transplant(tree, removed, removed->right);
    } else if (removed->right == tree->nil) {
        fix_node = removed->left;
        rb_transplant(tree, removed, removed->left);
    } else {
        RBNode *successor = rb_minimum(tree, removed->right);
        removed_color = successor->color;
        fix_node = successor->right;
        if (successor->parent == removed) {
            fix_node->parent = successor;
        } else {
            rb_transplant(tree, successor, successor->right);
            successor->right = removed->right;
            successor->right->parent = successor;
        }
        rb_transplant(tree, removed, successor);
        successor->left = removed->left;
        successor->left->parent = successor;
        successor->color = removed->color;
    }
    free(removed);
    --tree->live_nodes;
    if (removed_color == RB_BLACK)
        rb_delete_fixup(tree, fix_node);
    return true;
}

static void rb_destroy(RBTree *tree) {
    size_t stack_count = 0;
    size_t stack_capacity = 64;
    RBNode **stack = malloc(stack_capacity * sizeof(*stack));
    if (stack == NULL)
        exit(EXIT_FAILURE);
    if (tree->root != tree->nil)
        stack[stack_count++] = tree->root;
    while (stack_count != 0) {
        RBNode *node = stack[--stack_count];
        if (node->left != tree->nil) {
            if (stack_count == stack_capacity) {
                stack_capacity *= 2;
                RBNode **grown = realloc(
                    stack, stack_capacity * sizeof(*stack));
                if (grown == NULL) {
                    free(stack);
                    exit(EXIT_FAILURE);
                }
                stack = grown;
            }
            stack[stack_count++] = node->left;
        }
        if (node->right != tree->nil) {
            if (stack_count == stack_capacity) {
                stack_capacity *= 2;
                RBNode **grown = realloc(
                    stack, stack_capacity * sizeof(*stack));
                if (grown == NULL) {
                    free(stack);
                    exit(EXIT_FAILURE);
                }
                stack = grown;
            }
            stack[stack_count++] = node->right;
        }
        free(node);
        --tree->live_nodes;
    }
    free(stack);
    free(tree->nil);
    free(tree);
}

static double seconds(void) {
    struct timespec time_value;
    clock_gettime(CLOCK_MONOTONIC, &time_value);
    return (double)time_value.tv_sec + (double)time_value.tv_nsec * 1e-9;
}

static uint32_t next_random(uint32_t *state) {
    *state = *state * 1664525u + 1013904223u;
    return *state;
}

static void shuffle(int *keys, size_t count, uint32_t *state) {
    for (size_t i = count; i > 1; --i) {
        size_t j = next_random(state) % (uint32_t)i;
        int temporary = keys[i - 1];
        keys[i - 1] = keys[j];
        keys[j] = temporary;
    }
}

static int *make_permutation(size_t count, uint32_t seed) {
    int *keys = malloc(count * sizeof(*keys));
    if (keys == NULL)
        exit(EXIT_FAILURE);
    for (size_t i = 0; i < count; ++i)
        keys[i] = (int)i;
    shuffle(keys, count, &seed);
    return keys;
}

static int *make_queries(size_t count) {
    int *queries = malloc(count * sizeof(*queries));
    if (queries == NULL)
        exit(EXIT_FAILURE);
    for (size_t i = 0; i < count; ++i) {
        uint64_t value = (uint64_t)i * 2654435761ULL;
        queries[i] = (int)(value % (count * 2 + 1)) - (int)(count / 2);
    }
    return queries;
}

static volatile uint64_t sink;

static double benchmark_btree_insert(const int *keys, size_t count,
                                     size_t *peak_nodes) {
    BTree tree = { NULL, 0, 0 };
    double started = seconds();
    for (size_t i = 0; i < count; ++i)
        btree_insert(&tree, make_record(keys[i]));
    double elapsed = seconds() - started;
    *peak_nodes = tree.peak_nodes;
    sink ^= tree.live_nodes;
    btree_destroy(&tree, tree.root);
    return elapsed;
}

static double benchmark_btree_search(const int *keys, const int *queries,
                                     size_t count, size_t query_count,
                                     size_t *peak_nodes) {
    BTree tree = { NULL, 0, 0 };
    for (size_t i = 0; i < count; ++i)
        btree_insert(&tree, make_record(keys[i]));
    double started = seconds();
    uint64_t hits = 0;
    for (size_t i = 0; i < query_count; ++i) {
        const Record *record = btree_search(tree.root, queries[i]);
        hits += record != NULL && record_payload_is_valid(record);
    }
    double elapsed = seconds() - started;
    *peak_nodes = tree.peak_nodes;
    sink ^= hits;
    btree_destroy(&tree, tree.root);
    return elapsed;
}

static double benchmark_btree_delete(const int *keys, size_t count,
                                     size_t *peak_nodes) {
    BTree tree = { NULL, 0, 0 };
    for (size_t i = 0; i < count; ++i)
        btree_insert(&tree, make_record(keys[i]));
    double started = seconds();
    for (size_t i = 0; i < count; ++i)
        if (!btree_delete(&tree, keys[i]))
            abort();
    double elapsed = seconds() - started;
    *peak_nodes = tree.peak_nodes;
    sink ^= tree.live_nodes;
    btree_destroy(&tree, tree.root);
    return elapsed;
}

static double benchmark_rb_insert(const int *keys, size_t count,
                                  size_t *peak_nodes) {
    RBTree *tree = rb_new_tree();
    double started = seconds();
    for (size_t i = 0; i < count; ++i)
        rb_insert(tree, keys[i]);
    double elapsed = seconds() - started;
    *peak_nodes = tree->peak_nodes;
    sink ^= tree->live_nodes;
    rb_destroy(tree);
    return elapsed;
}

static double benchmark_rb_search(const int *keys, const int *queries,
                                  size_t count, size_t query_count,
                                  size_t *peak_nodes) {
    RBTree *tree = rb_new_tree();
    for (size_t i = 0; i < count; ++i)
        rb_insert(tree, keys[i]);
    double started = seconds();
    uint64_t hits = 0;
    for (size_t i = 0; i < query_count; ++i) {
        RBNode *record = rb_search(tree, queries[i]);
        hits += record != tree->nil && record_payload_is_valid(&record->record);
    }
    double elapsed = seconds() - started;
    *peak_nodes = tree->peak_nodes;
    sink ^= hits;
    rb_destroy(tree);
    return elapsed;
}

static double benchmark_rb_delete(const int *keys, size_t count,
                                  size_t *peak_nodes) {
    RBTree *tree = rb_new_tree();
    for (size_t i = 0; i < count; ++i)
        rb_insert(tree, keys[i]);
    double started = seconds();
    for (size_t i = 0; i < count; ++i)
        if (!rb_delete(tree, keys[i]))
            abort();
    double elapsed = seconds() - started;
    *peak_nodes = tree->peak_nodes;
    sink ^= tree->live_nodes;
    rb_destroy(tree);
    return elapsed;
}

static double median(double *values, int count) {
    double sorted[7];
    if (count > (int)(sizeof(sorted) / sizeof(sorted[0])))
        abort();
    memcpy(sorted, values, (size_t)count * sizeof(*values));
    for (int i = 1; i < count; ++i) {
        double value = sorted[i];
        int j = i;
        while (j > 0 && sorted[j - 1] > value) {
            sorted[j] = sorted[j - 1];
            --j;
        }
        sorted[j] = value;
    }
    return sorted[count / 2];
}

static void run_one(const char *name, size_t count, int rounds,
                    const int *keys, const int *queries) {
    double insert_times[7];
    double search_times[7];
    double delete_times[7];
    size_t btree_nodes = 0;
    size_t rb_nodes = 0;
    size_t btree_search_nodes = 0;
    size_t rb_search_nodes = 0;
    size_t btree_delete_nodes = 0;
    size_t rb_delete_nodes = 0;

    for (int round = 0; round < rounds; ++round) {
        if (strcmp(name, "B-tree") == 0) {
            insert_times[round] = benchmark_btree_insert(keys, count, &btree_nodes);
            search_times[round] = benchmark_btree_search(keys, queries, count,
                                                         count * 2, &btree_search_nodes);
            delete_times[round] = benchmark_btree_delete(keys, count,
                                                         &btree_delete_nodes);
        } else {
            insert_times[round] = benchmark_rb_insert(keys, count, &rb_nodes);
            search_times[round] = benchmark_rb_search(keys, queries, count,
                                                      count * 2, &rb_search_nodes);
            delete_times[round] = benchmark_rb_delete(keys, count, &rb_delete_nodes);
        }
    }

    size_t nodes = strcmp(name, "B-tree") == 0 ? btree_nodes : rb_nodes;
    size_t search_nodes = strcmp(name, "B-tree") == 0
                        ? btree_search_nodes : rb_search_nodes;
    size_t delete_nodes = strcmp(name, "B-tree") == 0
                        ? btree_delete_nodes : rb_delete_nodes;
    size_t node_size = strcmp(name, "B-tree") == 0
                     ? sizeof(BTreeNode) : sizeof(RBNode);
    printf("%s,%zu,insert,%.3f,%zu,%d,%zu\n", name, count,
           median(insert_times, rounds) * 1000.0, nodes, PAYLOAD_BYTES, node_size);
    printf("%s,%zu,search,%.3f,%zu,%d,%zu\n", name, count,
           median(search_times, rounds) * 1000.0, search_nodes, PAYLOAD_BYTES, node_size);
    printf("%s,%zu,delete,%.3f,%zu,%d,%zu\n", name, count,
           median(delete_times, rounds) * 1000.0, delete_nodes, PAYLOAD_BYTES, node_size);
}

int main(int argc, char **argv) {
    size_t count = argc > 1 ? (size_t)strtoull(argv[1], NULL, 10) : 1000000;
    int rounds = argc > 2 ? atoi(argv[2]) : 3;
    if (count < 2 || rounds < 1 || rounds > 7) {
        fputs("usage: btree-rb-bench [keys >= 2] [rounds 1..7]\n", stderr);
        return EXIT_FAILURE;
    }

    int *keys = make_permutation(count, 0x12345678u);
    int *queries = make_queries(count * 2);
    puts("structure,keys,operation,median_ms,peak_nodes,payload_bytes,node_size_bytes");
    run_one("B-tree", count, rounds, keys, queries);
    run_one("red-black", count, rounds, keys, queries);
    fprintf(stderr, "sink=%llu\n", (unsigned long long)sink);
    free(queries);
    free(keys);
    return EXIT_SUCCESS;
}
