#ifndef AVL_VARIANTS_H
#define AVL_VARIANTS_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void *cpp_insert(void *root, int key);
void *cpp_delete(void *root, int key);
void *cpp_search(void *root, int key);
void cpp_free_all(void *root);
void cpp_reset_stats(void);
uint64_t cpp_rotations(void);

#ifdef __cplusplus
}
#endif

#endif
