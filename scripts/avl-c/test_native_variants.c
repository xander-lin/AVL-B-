#include "avl_variants.h"

#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct AVLNode {
    int key;
    int height;
    struct AVLNode *left;
    struct AVLNode *right;
} AVLNode;

static int validate(const AVLNode *node, long lower, long upper) {
    if (node == NULL) return 0;
    assert(lower < node->key && node->key < upper);
    int left = validate(node->left, lower, node->key);
    int right = validate(node->right, node->key, upper);
    assert(node->height == 1 + (left > right ? left : right));
    assert(abs(left - right) <= 1);
    return node->height;
}

static int same_shape(const AVLNode *left, const AVLNode *right) {
    if (left == NULL || right == NULL) return left == right;
    return left->key == right->key
        && left->height == right->height
        && same_shape(left->left, right->left)
        && same_shape(left->right, right->right);
}

static void exercise(const char *name,
                     void *(*insert_fn)(void *, int),
                     void *(*delete_fn)(void *, int),
                     void *(*search_fn)(void *, int),
                     void (*free_fn)(void *)) {
    static const int lesson[] = {
        1, 3, 7, 6, 4, 5, 2, 0, -2, -1,
        8, 9, 11, 10, -3, -5, -4, 12, 13, 15, 14,
    };
    AVLNode *reference = NULL;
    AVLNode *tree = NULL;

    for (size_t i = 0; i < sizeof lesson / sizeof lesson[0]; i++) {
        reference = (AVLNode *)cpp_insert(reference, lesson[i]);
        tree = (AVLNode *)insert_fn(tree, lesson[i]);
        validate(tree, LONG_MIN, LONG_MAX);
        assert(search_fn(tree, lesson[i]) != NULL);
    }
    validate(tree, LONG_MIN, LONG_MAX);
    validate(reference, LONG_MIN, LONG_MAX);
    assert(same_shape(reference, tree));
    cpp_free_all(reference);
    free_fn(tree);

    for (int seed = 0; seed < 100; seed++) {
        unsigned state = (unsigned)seed;
        unsigned char model[241] = {0};
        tree = NULL;
        for (int op = 0; op < 3000; op++) {
            state = state * 1664525u + 1013904223u;
            int key = (int)(state % 241u) - 120;
            state = state * 1664525u + 1013904223u;
            if (state % 10u < 6u) {
                tree = (AVLNode *)insert_fn(tree, key);
                model[key + 120] = 1;
            } else {
                tree = (AVLNode *)delete_fn(tree, key);
                model[key + 120] = 0;
            }
            validate(tree, LONG_MIN, LONG_MAX);
            for (int check_key = -120; check_key <= 120; check_key++)
                assert((search_fn(tree, check_key) != NULL)
                       == (model[check_key + 120] != 0));
        }
        free_fn(tree);
    }

    printf("%s native AVL tests passed\n", name);
}

int main(void) {
    exercise("C++", cpp_insert, cpp_delete, cpp_search, cpp_free_all);
    return 0;
}
