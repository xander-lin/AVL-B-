<video src="assets/bst-increasing.webm" controls autoplay loop muted playsinline preload="auto" aria-label="递增插入导致二叉搜索树退化"></video>


如你所见,二叉搜索树在插入有序的时候会产生歪脖子树，导致退化。

为什么会这样呢？因为二叉搜索树,谁先插入谁就是根。接下来插入的就当第一层,然后是第二层,以此类推。
层数越靠上，它越起到一个索引的作用，而索引质量正是时间复杂度的关键。但是二叉搜索树的索引那是谁先来谁就是索引,所以一旦脖子歪了，那是一步错，步步错。

我们上一个视频讲的 AVL 树，通过修补树的形状解决了这个问题。但是我们今天要学习的 B 树自下向上生长,越靠上的索引越晚诞生，由各级动态推举产生。

---

## 先来看看B 树的定义

`m` 阶 B 树是需要满足以下条件：

- 所有叶子都处在同一深度
- 每个节点最多有`m − 1` 个关键字 `m` 个孩子
- 每个节点至少有 `⌈m/2⌉ − 1` 个关键字 `⌈m/2⌉` 个孩子( `⌈  ⌉` 是上取整,`⌊  ⌋ `是下取整)
- 特例:非空 B 树的根节点可以是一个关键字；
  叶节点没有孩子。

B树的“阶数”描述的是一个节点的最大分支数.

接下来出场的五阶B树和四阶B树，将会带你了解这一切。

## 4 阶 B 树

### 4阶 B 树的节点

按照定义
4阶B树:一个节点最多有四个孩子，最多有4-1=3个关键字。至少有4/2=2两个孩子、2-1=1个关键字；下图中最右边标红的四个节点就是不符合定义的接下来它需要进行上溢分裂。然后,这30 60 90就属于是关键字。剩下这四坨就是他的四个孩子。
<img src="assets/btree-order-4.svg" alt="分裂前的真实 4 阶 B 树：根节点 30、60、90，下挂两个、两个、两个和四个关键字的四个孩子">
### 再来看一下5阶B树:

5 阶 B 树最多有 4 个关键字。至少有 2 个关键字；下面这棵树的根节点正好有 4 个关键字和 5 个孩子，处在最大容量；下面的每个叶子都有 2 个关键字，处在最低容量,注意所有叶子在同一深度。

<img src="assets/btree-order-5.svg" alt="合法的 5 阶 B 树：根节点 50、100、150、200 有五个孩子，每个叶子有两个关键字，标注最多四个关键字五个孩子，非根节点至少两个关键字三个孩子">
现在先不用管那个B树的定义，你看着看着就知道是咋回事了。

### 4阶B树的查找:
查找还是和二叉搜索树都差不多。

查找 `50` 时，从根节点 `90` 走左边，`[30,60]` 选择中间孩子，最后在 `[40,50]` 中命中；查找 `125` 时，从根节点 `90` 走右边，`[120]` 继续走右边，到达 `[130]` 后确认树中没有 `125`。

<img src="assets/btree-search.svg" alt="分裂后的三层 4 阶 B 树中同时查找 50 和 125：50 从根节点 90 走左边，经内部节点 30、60 的中间孩子后在 40、50 中命中；125 从根节点 90 和内部节点 120 都走右边，到达 130 后未找到">

### 2. 插入

对于插入,我们直接来看例子。

10,20,30,40 发生上溢,这里我统一推举出上中位;

40,50,60,70 发生上溢,推举出60;

40,45,50,55 推举出50;

70,80,90,100 推举出90;

再看上层,30,50,60,90 推举出 60.

//这里配音我忘说这是四阶B树了，所以画面中一定要表现出来。
<video src="assets/btree-insert.webm" controls autoplay loop muted playsinline preload="auto" aria-label="在同一棵四阶 B 树上按 10、20、30、40、50、60、70、45、55、80、90、100 连续插入：四次叶节点或父节点溢出分别推举 30、60、50、90，最后父节点 [30,50,60,90] 溢出并推举 60 成为新根，分裂后的节点保持叶子同深"></video>

总之,B 树的插入先沿搜索路径到达叶子。关键字加入后，如果节点没有上溢出，插入结束；如果节点上溢出，就分裂节点，把中间关键字推举到父节点。

父节点也可能因此上溢出，继续向上分裂推举。一直到某一级不再溢出；

### 3. 删除
二叉搜索树 、红黑树、 AVL 树,B树他们对于有两个孩子的节点的删除，都是转化为删除直接前驱或后继。
对于B树,我这里删除有两种方法,两种方法也都需要先转化为删除叶节点。
<img src="assets/btree-delete-cases.svg" alt="删除非叶结点元素最终都转换成删除叶结点元素：第一种叶结点删除按没有下溢和下溢分类，下溢时兄弟够借就借、兄弟不够借就合并；第二种同样转化为叶子结点，直接按首领回家、部落内删除、重新推举首领展开">
第一种就是传统的方法。传统方法先看删除叶节点元素后是否下溢：没有下溢,无需调整；发生下溢时,再分为兄弟够借和兄弟不够借两种情况。
还有一种就是统一的语义,首领回家的版本。

在正式讲解之前。
我先要告诉你一句话，首领回家得到的是一个解的集合,而传统方法则是集合中的最优解。
我必须讲这个解集，因为它对将来的红黑树至关重要,所以也请你耐心听完我们的首领回家的办法。

接下来这些例子都是基于四阶 B 树。

情况一，传统方法中删除后不下溢。
这里我们删除10。
对于传统方法，这个节点删除10并不会下溢出，直接删除就行。
对于我们的方法,把40拉下来,把10删掉,再把一个首领重新推举上去

<video src="assets/btree-case1-traditional.webm" controls autoplay loop muted playsinline preload="auto" aria-label="传统方法删除 10：叶节点没有下溢，直接删除后结束"></video>
<video src="assets/btree-case1-ours.webm" controls autoplay loop muted playsinline preload="auto" aria-label="首领回家法删除 10：并列展示推举 30、40、60 三种合法调整方法"></video>

情况二，传统方法中发生下溢，兄弟够借，向兄弟借关键字并发生旋转。

还是删除10。
传统方法属于下溢出，需要问兄弟借，兄弟够借。发生了旋转。

对于我们的方法,操作不变。把首领拉回家,把10删掉；在合法解集合中,可以重新推举，也可以不重新推举。传统方法保持了层数不变,即便这是一棵更大的树,也不会对上层造成影响。并且调整元素数量最少
而我们的方法中如果采用不重新推举,如果这是一颗更大的树,不重新推举那父节点少了一个元素,可能会导致父节点下溢出,调整的范围更大
<video src="assets/btree-case2-traditional.webm" controls autoplay loop muted playsinline preload="auto" aria-label="传统方法删除 10：根关键字 40 在上方，10 在左叶，50、60 在右叶；发生下溢后借出 50，并将 40 下沉"></video>
<video src="assets/btree-case2-ours.webm" controls autoplay loop muted playsinline preload="auto" aria-label="首领回家法删除 10：根关键字 40 在上方，10 在左叶，50、60 在右叶；并列展示推举 50 与不推举两种合法调整方法"></video>


情况三，传统方法中发生下溢，兄弟不够借，只能合并。这种情况合并之后，父节点那一层就少了一个元素，所以父节点可能会继续下溢出。

传统方法：删除70之后发生下溢，兄弟不够借，就和父节点的关键字合并。父节点因此少了一个元素下溢出,还是不够借,所以父节点继续合并,可以选择50或者80进行合并，这里我们选择50,合并后这次父节点80没有下溢出；四阶 B 树中，节点有零个关键字时也仍然称为下溢出，不说节点没了。然后删除10,合并20与30


对于我们的方法,这里要删除70。首领60回家之后,把70删掉,就剩两个节点了。这个结果无法重新推举；父节点下溢出,在合法解集合中,对于下溢出的父节点,它有两个首领,选择80回家还是50回家都行。50回家了,之后还是可以选择推举或者不推举,当然前提是有的推举才能推举,关键字数量不够就不能推举。这里就不能推举

接下来我们删除10,首领20回家,10被删除,还是没什么可推举的。但这次父节点并不下溢出,然后这就结束了。


<video src="assets/btree-case3-traditional.webm" controls autoplay loop muted playsinline preload="auto" aria-label="传统方法先后删除 10 和 90：兄弟不够借，连续与分隔关键字合并并向上修复下溢"></video>
<video src="assets/btree-case3-ours.webm" controls autoplay loop muted playsinline preload="auto" aria-label="首领回家法先后删除 10 和 90：并列展示首领 50 回家和首领 80 回家两种合法调整方法"></video>
我们很容易发现,对于阶数为奇数的B树，只有大于最大容量时能够推举,对于阶数为偶数的B树,大于等于最大容量时能够推举。

<img src="assets/btree-promotion-parity.svg" alt="横向展示推举完成后的三个 B 树状态：四阶三个关键字、四阶四个关键字、五阶五个关键字">

接下来看一个完整的例子,这次我们用的是5阶B树:

<video src="assets/btree-delete-5-slow.webm" controls autoplay loop muted playsinline preload="auto" aria-label="一个四层五阶 B 树按传统方法展示完整删除动作，并按原视频 0.6 倍速播放：删除内部关键字 450 时先与后继 460 交换；直接删除叶节点 450 后发生下溢，右兄弟处于下限不能借，于是与分隔关键字 500 合并；直接删除 410 后下溢，右兄弟可以借，分隔关键字 460 下移、兄弟关键字 480 上移；直接删除 360 后，沿途兄弟均不能借，依次与分隔关键字 380、300、400 合并，最终根变空，合并节点上升成为新根，树从四层缩成三层"></video>
删除450,它不是叶节点，先用后继460替换它。然后直接删除叶节点中的450。节点下溢，右兄弟只有两个关键字不够借，所以和分隔关键字500以及右兄弟合并。父节点没有下溢。

删除410,删除410后节点下溢，右兄弟够借。分隔关键字460下移到左节点，右兄弟最小关键字480上移到父节点，完成一次旋转。

删除360,删除360后节点下溢出，右兄弟不够借，和分隔关键字380合并。父节点因此下溢出，继续检查同层兄弟；兄弟仍不够借，就再和分隔关键字300合并。上层节点也发生下溢出，最后和根关键字400以及右兄弟合并，树从四层缩成三层。

---

## 从 4 阶推广到任意阶


### 阶数决定容量，不改变机制
然后

 每个节点最多有`m − 1` 个关键字 `m` 个孩子
 每个节点至少有 `⌈m/2⌉ − 1` 个关键字 `⌈m/2⌉` 个孩子
 
 最多 m-1 关键字。再插入一个变成 m 个但是上溢出还要推举出一个,又变成m-1个
 分裂时是对 m -1 关键字平分为两半。考虑到奇偶问题。最终可以是 `⌈m/2⌉ − 1`

上溢出之后，分裂完，两个孩子刚好就是"最低"的容量。


高度三层的 m 阶 B 树最多能存等比数列求和为 `m³ − 1` 个关键字，

图片说明：静态图对比同样三层时 4 阶、100 阶、512 阶各自能存的关键字数量级，说明阶数由存储页的大小决定。

<img src="assets/btree-order-scaling.svg" alt="同样三层：4 阶最多 63 个关键字，100 阶约 100 万个，512 阶约 1.34 亿个">

普通外存设备读写速度很慢，但是他们有个特点在一定程度上它们读取一大段数据的时间,与读取一两个字节的时间几乎是一样的,读取一样多的数据,读取次数越少越好。

这正是 B 树被发明出来的场景
磁盘一次寻址读写一整页，把一整页做成一个大节点，树的层数就约等于寻址次数。几百阶的 B 树只要三四层就能覆盖上亿条数据.

还有一点就是 B 树的并发写入改造比较简单

那么古尔丹代价是什么呢？

B 树的代价，首先是空间利用率,B 树每个节点内部都是一个数组。插入,分裂、删除和合并之后，节点并不一定能恰好装满，所以一页里可能会留下一部分空槽。

其次，节点变大以后，节点内部的工作也变多了。

这B树确实不错。
可对于内存几乎没有页代价,有没有性能更强空间还不浪费的数据结构呢？
有的

## 完

### 编程

下面的代码固定演示四阶 B 树(递归版)：每个节点最多三个关键字，非根节点至少一个关键字。插入时，关键字沿搜索路径落到叶子；发生上溢，就把上中位关键字作为首领推举到父节点，父节点也可能继续上溢并向上推举。删除时采用前文的统一语义：沿目标路径先把父节点的首领带回家，与相邻节点合并；然后在合并后的节点中删除关键字。如果删完仍然上溢，就把中间首领重新推举回父节点；如果没有上溢，父节点少了一个关键字，继续检查父节点是否下溢。删除内部节点的关键字时，先用右子树最小关键字后继顶替，再去删除后继所在的叶节点。

```c
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>

enum {
    ORDER = 4,
    MAX_KEYS = ORDER - 1,
    MIN_KEYS = (ORDER + 1) / 2 - 1,

    /* 首领回家后，两个节点和一个父分隔关键字暂时放在一起。 */
    TEMP_MAX_KEYS = 2 * MAX_KEYS + 1,
    TEMP_MAX_CHILDREN = TEMP_MAX_KEYS + 1
};

typedef struct BTreeNode {
    int key_count;
    int keys[TEMP_MAX_KEYS];
    bool leaf;
    struct BTreeNode *children[TEMP_MAX_CHILDREN];
} BTreeNode;

typedef struct {
    BTreeNode *root;
} BTree;

typedef struct {
    bool happened;
    int leader;
    BTreeNode *right;
} Split;

static void *checked_malloc(size_t size) {
    void *memory = malloc(size);
    if (memory == NULL) {
        fprintf(stderr, "out of memory\n");
        exit(EXIT_FAILURE);
    }
    return memory;
}

static BTreeNode *new_node(bool leaf) {
    BTreeNode *node = checked_malloc(sizeof(*node));
    node->key_count = 0;
    node->leaf = leaf;
    for (int i = 0; i < TEMP_MAX_CHILDREN; ++i)
        node->children[i] = NULL;
    return node;
}
```

#### 节点查找与插入

```c

static int lower_bound(const BTreeNode *node, int key) {
    int position = 0;
    while (position < node->key_count && node->keys[position] < key)
        ++position;
    return position;
}

static bool contains(const BTreeNode *node, int key) {
    while (node != NULL) {
        int position = lower_bound(node, key);
        if (position < node->key_count && node->keys[position] == key)
            return true;
        if (node->leaf)
            return false;
        node = node->children[position];
    }
    return false;
}

/*
 * 节点上溢时取上中位：四个关键字 [10,20,30,40] 推举 30，
 * 左边留下 [10,20]，右边留下 [40]。
 */
static Split split_node(BTreeNode *node) {
    Split result = { true, 0, NULL };
    int total = node->key_count;
    int middle = total / 2;
    BTreeNode *right = new_node(node->leaf);

    result.leader = node->keys[middle];
    result.right = right;
    right->key_count = total - middle - 1;
    for (int i = 0; i < right->key_count; ++i)
        right->keys[i] = node->keys[middle + 1 + i];

    if (!node->leaf) {
        for (int i = 0; i <= right->key_count; ++i) {
            right->children[i] = node->children[middle + 1 + i];
            node->children[middle + 1 + i] = NULL;
        }
    }
    node->key_count = middle;
    return result;
}

static void put_split_into_parent(BTreeNode *parent, int child_index,
                                  Split split) {
    for (int i = parent->key_count; i > child_index; --i)
        parent->keys[i] = parent->keys[i - 1];
    for (int i = parent->key_count + 1; i > child_index + 1; --i)
        parent->children[i] = parent->children[i - 1];

    parent->keys[child_index] = split.leader;
    parent->children[child_index + 1] = split.right;
    ++parent->key_count;
}

/*
 * 插入的上溢沿递归回溯：子节点先分裂并推举首领，
 * 父节点接过首领后如果也溢出，再把自己的首领继续向上交给父亲。
 */
static Split insert_recursive(BTreeNode *node, int key) {
    if (node->leaf) {
        int position = lower_bound(node, key);
        for (int i = node->key_count; i > position; --i)
            node->keys[i] = node->keys[i - 1];
        node->keys[position] = key;
        ++node->key_count;
    } else {
        int child_index = lower_bound(node, key);
        Split split = insert_recursive(node->children[child_index], key);
        if (split.happened)
            put_split_into_parent(node, child_index, split);
    }

    if (node->key_count > MAX_KEYS)
        return split_node(node);
    return (Split){ false, 0, NULL };
}

static void insert(BTree *tree, int key) {
    if (contains(tree->root, key))
        return;                         /* 这份示例不保存重复关键字 */

    if (tree->root == NULL) {
        tree->root = new_node(true);
        tree->root->keys[0] = key;
        tree->root->key_count = 1;
        return;
    }

    Split split = insert_recursive(tree->root, key);
    if (split.happened) {
        BTreeNode *new_root = new_node(false);
        new_root->keys[0] = split.leader;
        new_root->key_count = 1;
        new_root->children[0] = tree->root;
        new_root->children[1] = split.right;
        tree->root = new_root;
    }
}
```

#### 删除辅助函数

```c

static int minimum_key(const BTreeNode *node) {
    while (!node->leaf)
        node = node->children[0];
    return node->keys[0];
}

/*
 * 首领回家：把 parent 的一个分隔关键字拉到两个孩子之间，
 * 合并成一个暂时节点，并从 parent 删除这个分隔关键字。
 * 暂时节点允许超过三个关键字，删除完成后再由 finish_child 推举。
 *
 * 优先和右兄弟合并；如果目标已经是最右孩子，就和左兄弟合并。
 * 返回合并后目标子树所在的下标。
 */
static int bring_leader_home(BTreeNode *parent, int child_index) {
    int separator_index;
    int left_index;
    int right_index;

    if (child_index < parent->key_count) {
        separator_index = child_index;
        left_index = child_index;
        right_index = child_index + 1;
    } else {
        separator_index = child_index - 1;
        left_index = child_index - 1;
        right_index = child_index;
    }

    BTreeNode *left = parent->children[left_index];
    BTreeNode *right = parent->children[right_index];
    int old_left_keys = left->key_count;
    int old_right_keys = right->key_count;

    left->keys[old_left_keys] = parent->keys[separator_index];
    for (int i = 0; i < old_right_keys; ++i)
        left->keys[old_left_keys + 1 + i] = right->keys[i];

    if (!left->leaf) {
        for (int i = 0; i <= old_right_keys; ++i)
            left->children[old_left_keys + 1 + i] = right->children[i];
    }
    left->key_count = old_left_keys + 1 + old_right_keys;

    for (int i = separator_index; i < parent->key_count - 1; ++i)
        parent->keys[i] = parent->keys[i + 1];
    for (int i = right_index; i < parent->key_count; ++i)
        parent->children[i] = parent->children[i + 1];
    parent->children[parent->key_count] = NULL;
    --parent->key_count;

    free(right);
    return left_index;
}

/* 合并后的节点若上溢，就把新的中间首领推举回 parent。 */
static void finish_child(BTreeNode *parent, int child_index) {
    BTreeNode *child = parent->children[child_index];
    if (child->key_count > MAX_KEYS) {
        Split split = split_node(child);
        put_split_into_parent(parent, child_index, split);
    }
}

static void remove_leaf_key(BTreeNode *leaf, int position) {
    for (int i = position; i < leaf->key_count - 1; ++i)
        leaf->keys[i] = leaf->keys[i + 1];
    --leaf->key_count;
}

/*
 * 删除最小关键字，供“内部关键字先由后继顶替”使用。
 * 后继真正从叶子删掉以后，才允许外层把分隔首领带回家，
 * 因而不会把同一个后继同时留在父子两层。
 */
static bool delete_minimum(BTreeNode *node, bool is_root) {
    if (node->leaf) {
        remove_leaf_key(node, 0);
        return !is_root && node->key_count < MIN_KEYS;
    }

    int child_index = bring_leader_home(node, 0);
    bool underflow = delete_minimum(node->children[child_index], false);
    if (underflow)
        child_index = bring_leader_home(node, child_index);
    finish_child(node, child_index);
    return !is_root && node->key_count < MIN_KEYS;
}
```

#### 删除主流程

```c

/*
 * 删除普通关键字：进入下一层之前先首领回家；
 * 删除完成后，合并节点若上溢就首领推举，父节点若下溢则向上返回。
 */
static bool delete_recursive(BTreeNode *node, int key, bool is_root) {
    if (node->leaf) {
        int position = lower_bound(node, key);
        if (position < node->key_count && node->keys[position] == key)
            remove_leaf_key(node, position);
        return !is_root && node->key_count < MIN_KEYS;
    }

    int position = lower_bound(node, key);
    int child_index;
    int key_to_delete = key;

    if (position < node->key_count && node->keys[position] == key) {
        /* 内部节点删除转化为删除右子树中的后继。 */
        key_to_delete = minimum_key(node->children[position + 1]);
        node->keys[position] = key_to_delete;
        child_index = position + 1;

        bool underflow = delete_minimum(node->children[child_index], false);
        if (underflow)
            child_index = bring_leader_home(node, child_index);
    } else {
        child_index = bring_leader_home(node, position);
        bool underflow = delete_recursive(
            node->children[child_index], key_to_delete, false);
        if (underflow)
            child_index = bring_leader_home(node, child_index);
    }

    finish_child(node, child_index);
    return !is_root && node->key_count < MIN_KEYS;
}

static bool erase(BTree *tree, int key) {
    if (!contains(tree->root, key))
        return false;

    delete_recursive(tree->root, key, true);

    if (tree->root->key_count == 0) {
        BTreeNode *old_root = tree->root;
        if (old_root->leaf)
            tree->root = NULL;
        else
            tree->root = old_root->children[0];
        free(old_root);
    }
    return true;
}
```

#### 输出与示例

```c

static void print_tree(const BTreeNode *node, int depth) {
    if (node == NULL)
        return;
    for (int i = 0; i < depth; ++i)
        printf("  ");
    printf("[");
    for (int i = 0; i < node->key_count; ++i)
        printf("%s%d", i == 0 ? "" : ",", node->keys[i]);
    printf("]\n");
    if (!node->leaf)
        for (int i = 0; i <= node->key_count; ++i)
            print_tree(node->children[i], depth + 1);
}

static void destroy(BTreeNode *node) {
    if (node == NULL)
        return;
    if (!node->leaf)
        for (int i = 0; i <= node->key_count; ++i)
            destroy(node->children[i]);
    free(node);
}

int main(void) {
    BTree tree = { NULL };
    const int inserted[] = {
        10, 20, 30, 40, 50, 60, 70, 45, 55, 80, 90, 100
    };
    const int removed[] = { 10, 45, 60, 90 };

    for (size_t i = 0; i < sizeof(inserted) / sizeof(inserted[0]); ++i)
        insert(&tree, inserted[i]);
    for (size_t i = 0; i < sizeof(inserted) / sizeof(inserted[0]); ++i)
        assert(contains(tree.root, inserted[i]));

    printf("after insertion:\n");
    print_tree(tree.root, 0);

    for (size_t i = 0; i < sizeof(removed) / sizeof(removed[0]); ++i) {
        assert(erase(&tree, removed[i]));
        assert(!contains(tree.root, removed[i]));
    }

    printf("after leader-home deletion:\n");
    print_tree(tree.root, 0);
    destroy(tree.root);
    return 0;
}
```
