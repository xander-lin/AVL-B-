/* test_equivalence.c — lever-semantics code (extracted from the lesson) vs the
 * classic textbook four-case AVL. Runs identical operation sequences through
 * both trees and asserts the FULL SHAPES are identical after EVERY operation,
 * including all height fields. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>

#include "avl_lesson_blocks.c"

/* ===== classic implementation: two rotation primitives + four-case dispatch,
 * exactly the code the lesson used before the rewrite ===== */

static AVLNode *rotateLeft_c(AVLNode *node) {
    AVLNode *root   = node->right;
    AVLNode *middle = root->left;
    root->left  = node;
    node->right = middle;
    updateHeight(node);
    updateHeight(root);
    return root;
}

static AVLNode *rotateRight_c(AVLNode *node) {
    AVLNode *root   = node->left;
    AVLNode *middle = root->right;
    root->right = node;
    node->left  = middle;
    updateHeight(node);
    updateHeight(root);
    return root;
}

static AVLNode *insert_c(AVLNode *node, int key) {
    if (node == NULL) return newNode(key);
    if (key == node->key) return node;

    if (key < node->key) node->left  = insert_c(node->left,  key);
    else                 node->right = insert_c(node->right, key);

    updateHeight(node);
    int bf = balanceFactor(node);

    if (bf > 1 && key < node->left->key)         return rotateRight_c(node);
    if (bf > 1 && key > node->left->key) {
        node->left = rotateLeft_c(node->left);
        return rotateRight_c(node);
    }
    if (bf < -1 && key > node->right->key)       return rotateLeft_c(node);
    if (bf < -1 && key < node->right->key) {
        node->right = rotateRight_c(node->right);
        return rotateLeft_c(node);
    }
    return node;
}

static AVLNode *deleteKey_c(AVLNode *node, int key) {
    if (node == NULL) return NULL;

    if (key < node->key)      node->left  = deleteKey_c(node->left,  key);
    else if (key > node->key) node->right = deleteKey_c(node->right, key);
    else {
        if (node->left == NULL || node->right == NULL) {
            AVLNode *child = node->left ? node->left : node->right;
            free(node);
            return child;
        }
        AVLNode *succ = node->right;
        while (succ->left) succ = succ->left;
        node->key  = succ->key;
        node->right = deleteKey_c(node->right, succ->key);
    }

    updateHeight(node);
    int bf = balanceFactor(node);

    if (bf > 1 && balanceFactor(node->left) >= 0)  return rotateRight_c(node);
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

static int same_shape(AVLNode *a, AVLNode *b) {
    if (!a || !b) return a == b;
    return a->key == b->key && a->height == b->height
        && same_shape(a->left, b->left)
        && same_shape(a->right, b->right);
}

static void freeAll(AVLNode *n) {
    if (!n) return;
    freeAll(n->left);
    freeAll(n->right);
    free(n);
}

#define OFF 100
static unsigned char model[201];

static int diverged = 0;

static void check(AVLNode *a, AVLNode *b, int seed, int op) {
    if (!same_shape(a, b)) {
        printf("DIVERGENCE at seed %d op %d\n", seed, op);
        diverged = 1;
    }
}

int main(void) {
    /* lesson sequence, compared after every single insert and delete */
    int seq[] = {1,3,7,6,4,5,2,0,-2,-1,8,9,11,10,-3,-5,-4,12,13,15,14};
    AVLNode *a = NULL, *b = NULL;
    for (int i = 0; i < 21; i++) {
        a = insert(a, seq[i]);
        b = insert_c(b, seq[i]);
        check(a, b, -1, i);
    }
    for (int i = 20; i >= 0; i--) {
        a = deleteKey(a, seq[i]);
        b = deleteKey_c(b, seq[i]);
        check(a, b, -1, 100 + i);
    }
    if (a || b) { printf("FAIL lesson drain\n"); return 1; }

    /* dense keyspace: heavy collisions, lots of deletions */
    for (int s = 0; s < 200 && !diverged; s++) {
        srand(s);
        memset(model, 0, sizeof model);
        a = b = NULL;
        for (int i = 0; i < 5000 && !diverged; i++) {
            int k = rand() % 201 - OFF;
            int r = rand() % 10;
            if (r < 6)      { a = insert(a, k);    b = insert_c(b, k);    model[k+OFF] = 1; }
            else if (r < 9) { a = deleteKey(a, k); b = deleteKey_c(b, k); model[k+OFF] = 0; }
            else if (model[k+OFF]) { a = deleteKey(a, k); b = deleteKey_c(b, k); model[k+OFF] = 0; }
            else                   { a = insert(a, k);    b = insert_c(b, k);    model[k+OFF] = 1; }
            check(a, b, s, i);
            assert((search(a, k) != NULL) == (model[k+OFF] != 0));
        }
        for (int k = -OFF; k <= OFF && !diverged; k++)
            if (model[k+OFF]) {
                a = deleteKey(a, k);
                b = deleteKey_c(b, k);
                check(a, b, s, 90000 + k);
            }
        if (a || b) { printf("FAIL dense drain seed %d\n", s); return 1; }
    }

    /* wide keyspace: deep trees, rare collisions */
    for (int s = 0; s < 40 && !diverged; s++) {
        srand(1000 + s);
        a = b = NULL;
        for (int i = 0; i < 6000 && !diverged; i++) {
            int k = rand() % 250000;
            int r = rand() % 10;
            if (r < 7)      { a = insert(a, k);    b = insert_c(b, k); }
            else            { a = deleteKey(a, k); b = deleteKey_c(b, k); }
            check(a, b, 1000 + s, i);
        }
        freeAll(a); freeAll(b);   /* defined below */
    }

    if (diverged) return 1;
    printf("EQUIVALENT: shapes (keys + heights) identical after every operation\n"
           "  lesson 21-key sequence, 200 dense seeds x 5000 ops, 40 wide seeds x 6000 ops\n");
    return 0;
}
