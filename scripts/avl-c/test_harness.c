/* test_harness.c — includes the C blocks extracted from the AVL lesson and
 * stresses the lever-semantics implementation: structure invariants, set
 * semantics against a model, deterministic shape assertions, big trees. */
#include <stdio.h>
#include <stdlib.h>
#include <limits.h>
#include <assert.h>

#include "avl_lesson_blocks.c"

static long violations = 0;

static int subtree_ok(AVLNode *n, long lo, long hi) {
    if (!n) return 0;
    if (!(lo < n->key && n->key < hi)) violations++;
    int hl = subtree_ok(n->left, lo, n->key);
    int hr = subtree_ok(n->right, n->key, hi);
    if (n->height != 1 + (hl > hr ? hl : hr)) violations++;
    if (hl - hr > 1 || hr - hl > 1) violations++;
    return 1 + (hl > hr ? hl : hr);
}

static void validate(AVLNode *root) {
    subtree_ok(root, LONG_MIN, LONG_MAX);
}

static int collected[200001], collected_n = 0;
static void inorder(AVLNode *n) {
    if (!n) return;
    inorder(n->left);
    collected[collected_n++] = n->key;
    inorder(n->right);
}

static int height_bound_violation(AVLNode *root, int n) {
    int h = heightOf(root), lg = 0;
    while ((1LL << (lg + 1)) <= (long long)n + 2) lg++;
    return h > (int)(1.4405 * (lg + 1)) + 2;
}

#define OFF 50
static unsigned char model[101];

static void drain(AVLNode **t, int lo, int hi, int seed_tag) {
    for (int k = lo; k <= hi; k++) {
        assert((search(*t, k) != NULL) == (model[k + OFF] != 0));
        if (model[k + OFF]) {
            *t = deleteKey(*t, k);
            model[k + OFF] = 0;
        }
        assert((search(*t, k) != NULL) == 0);
    }
    validate(*t);
    if (*t != NULL) { printf("seed %d: tree not empty after drain\n", seed_tag); exit(1); }
}

static void run_mixed(int seed, int ops) {
    srand(seed);
    for (int k = 0; k < 101; k++) model[k] = 0;
    AVLNode *t = NULL;
    for (int i = 0; i < ops; i++) {
        int k = rand() % 101 - OFF;
        int r = rand() % 10;
        if (r < 6)      { t = insert(t, k);   model[k + OFF] = 1; }
        else if (r < 9) { t = deleteKey(t, k); model[k + OFF] = 0; }
        else {
            if (model[k + OFF]) { t = deleteKey(t, k); model[k + OFF] = 0; }
            else                { t = insert(t, k);   model[k + OFF] = 1; }
        }
        validate(t);
        assert((search(t, k) != NULL) == (model[k + OFF] != 0));
    }
    drain(&t, -OFF, OFF, seed);
}

static void expect_shape1(AVLNode *t, int root, int l, int r, const char *tag) {
    if (!t || t->key != root
        || !t->left || t->left->key != l || t->left->left || t->left->right
        || !t->right || t->right->key != r || t->right->left || t->right->right) {
        printf("FAIL shape (%s)\n", tag); exit(1);
    }
}

int main(void) {
    /* four classic triggers must all land on the same balanced shape */
    int seqs[4][3] = {{1,2,3},{3,2,1},{1,3,2},{3,1,2}};
    const char *names[4] = {"RR","LL","LR(middle-heavy)","RL(middle-heavy)"};
    for (int i = 0; i < 4; i++) {
        AVLNode *t = NULL;
        for (int j = 0; j < 3; j++) t = insert(t, seqs[i][j]);
        validate(t);
        expect_shape1(t, 2, 1, 3, names[i]);
        free(t->left); free(t->right); free(t);
    }

    /* deletion with heavy-child balance factor 0: must take the plain
     * single rotation (no straightening step). */
    AVLNode *t = NULL;
    int build[] = {2,1,4,3,5};
    for (int i = 0; i < 5; i++) t = insert(t, build[i]);
    t = deleteKey(t, 1);
    validate(t);
    if (!t || t->key != 4
        || !t->left || t->left->key != 2 || t->left->left || !(t->left->right && t->left->right->key == 3)
        || !(t->right && t->right->key == 5)) {
        printf("FAIL zero-bf-child delete case: expected single rotation root 4\n");
        return 1;
    }
    free(t->left->right); free(t->left); free(t->right); free(t);

    /* the lesson's own insertion sequence */
    int lesson[] = {1,3,7,6,4,5,2,0,-2,-1,8,9,11,10,-3,-5,-4,12,13,15,14};
    t = NULL;
    for (int i = 0; i < 21; i++) t = insert(t, lesson[i]);
    validate(t);
    collected_n = 0; inorder(t);
    for (int i = 0; i < 21; i++)
        if (collected_n != 21 || collected[i] != i - 5) { printf("FAIL lesson inorder\n"); return 1; }
    for (int i = 20; i >= 0; i--) t = deleteKey(t, lesson[i]);
    validate(t);
    if (t) { printf("FAIL lesson drain\n"); return 1; }

    /* randomized mixed insert/delete vs model */
    for (int s = 0; s < 300; s++) run_mixed(s, 3000);

    /* big sequential trees */
    t = NULL;
    for (int i = 1; i <= 50000; i++) t = insert(t, i);
    validate(t);
    if (height_bound_violation(t, 50000)) { printf("FAIL ascending height bound\n"); return 1; }
    collected_n = 0; inorder(t);
    if (collected_n != 50000) { printf("FAIL ascending count\n"); return 1; }
    for (int i = 1; i <= 50000; i += 2) t = deleteKey(t, i);
    validate(t);
    for (int i = 2; i <= 50000; i += 2)
        if (!search(t, i)) { printf("FAIL evens kept\n"); return 1; }
    for (int i = 50000; i >= 2; i -= 2) t = deleteKey(t, i);
    validate(t);
    if (t) { printf("FAIL ascending drain\n"); return 1; }

    t = NULL;
    for (int i = 50000; i >= 1; i--) t = insert(t, i);
    validate(t);
    if (height_bound_violation(t, 50000)) { printf("FAIL descending height bound\n"); return 1; }
    while (t) t = deleteKey(t, t->key);
    if (t) { printf("FAIL descending drain\n"); return 1; }

    if (violations) { printf("FAIL: %ld invariant violations\n", violations); return 1; }
    printf("ALL TESTS PASSED (4 shapes, zero-bf-child delete, lesson sequence, "
           "300x3000 random ops, 100k sequential inserts/deletes)\n");
    return 0;
}
