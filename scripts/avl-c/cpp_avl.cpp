#include "avl_variants.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <new>

namespace cpp_avl {

struct Node {
    int key;
    int height;
    Node *left;
    Node *right;
};

static_assert(offsetof(Node, key) == 0);
static_assert(offsetof(Node, height) == 4);
static_assert(offsetof(Node, left) == 8);
static_assert(offsetof(Node, right) == 16);

std::uint64_t rotation_count = 0;

inline int height(const Node *node) {
    return node == nullptr ? 0 : node->height;
}

inline int balance_factor(const Node *node) {
    return height(node->left) - height(node->right);
}

inline void update_height(Node *node) {
    node->height = 1 + std::max(height(node->left), height(node->right));
}

Node *rotate(Node *node) {
    Node *root;
    Node *middle;

    if (height(node->right) > height(node->left)) {
        root = node->right;
        middle = root->left;
        root->left = node;
        node->right = middle;
    } else {
        root = node->left;
        middle = root->right;
        root->right = node;
        node->left = middle;
    }

    update_height(node);
    update_height(root);
    ++rotation_count;
    return root;
}

Node *repair(Node *node) {
    update_height(node);
    const int factor = balance_factor(node);

    if (factor > 1) {
        if (balance_factor(node->left) < 0)
            node->left = rotate(node->left);
        return rotate(node);
    }

    if (factor < -1) {
        if (balance_factor(node->right) > 0)
            node->right = rotate(node->right);
        return rotate(node);
    }

    return node;
}

Node *insert(Node *node, int key) {
    if (node == nullptr) {
        Node *fresh = new (std::nothrow) Node{key, 1, nullptr, nullptr};
        if (fresh == nullptr)
            std::abort();
        return fresh;
    }

    if (key < node->key)
        node->left = insert(node->left, key);
    else if (key > node->key)
        node->right = insert(node->right, key);
    else
        return node;

    return repair(node);
}

Node *remove_min(Node *node, int &key) {
    if (node->left == nullptr) {
        key = node->key;
        Node *right = node->right;
        delete node;
        return right;
    }

    node->left = remove_min(node->left, key);
    return repair(node);
}

Node *erase(Node *node, int key) {
    if (node == nullptr)
        return nullptr;

    if (key < node->key) {
        node->left = erase(node->left, key);
    } else if (key > node->key) {
        node->right = erase(node->right, key);
    } else {
        if (node->left == nullptr) {
            Node *right = node->right;
            delete node;
            return right;
        }
        if (node->right == nullptr) {
            Node *left = node->left;
            delete node;
            return left;
        }

        int successor;
        node->right = remove_min(node->right, successor);
        node->key = successor;
    }

    return repair(node);
}

Node *search(Node *node, int key) {
    while (node != nullptr && node->key != key)
        node = key < node->key ? node->left : node->right;
    return node;
}

void free_all(Node *node) {
    if (node == nullptr)
        return;
    free_all(node->left);
    free_all(node->right);
    delete node;
}

} // namespace cpp_avl

extern "C" {

void *cpp_insert(void *root, int key) {
    return cpp_avl::insert(static_cast<cpp_avl::Node *>(root), key);
}

void *cpp_delete(void *root, int key) {
    return cpp_avl::erase(static_cast<cpp_avl::Node *>(root), key);
}

void *cpp_search(void *root, int key) {
    return cpp_avl::search(static_cast<cpp_avl::Node *>(root), key);
}

void cpp_free_all(void *root) {
    cpp_avl::free_all(static_cast<cpp_avl::Node *>(root));
}

void cpp_reset_stats(void) {
    cpp_avl::rotation_count = 0;
}

std::uint64_t cpp_rotations(void) {
    return cpp_avl::rotation_count;
}

}
