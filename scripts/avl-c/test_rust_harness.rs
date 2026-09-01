use std::collections::BTreeSet;

fn validate_node(node: Option<&Node>, lower: Option<i32>, upper: Option<i32>) -> (i32, usize) {
    let Some(node) = node else {
        return (0, 0);
    };

    if let Some(lower) = lower {
        assert!(lower < node.key);
    }
    if let Some(upper) = upper {
        assert!(node.key < upper);
    }

    let (left_height, left_count) = validate_node(node.left.as_deref(), lower, Some(node.key));
    let (right_height, right_count) =
        validate_node(node.right.as_deref(), Some(node.key), upper);
    let expected_height = 1 + left_height.max(right_height);

    assert_eq!(node.height, expected_height);
    assert!((left_height - right_height).abs() <= 1);
    (expected_height, left_count + right_count + 1)
}

fn validate(tree: &AvlTree, expected: &BTreeSet<i32>) {
    let (_, count) = validate_node(tree.root.as_deref(), None, None);
    assert_eq!(count, expected.len());
    for key in -120..=120 {
        assert_eq!(tree.contains(key), expected.contains(&key));
    }
}

fn next_u32(state: &mut u32) -> u32 {
    *state = state.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
    *state
}

fn main() {
    let lesson = [1, 3, 7, 6, 4, 5, 2, 0, -2, -1, 8, 9, 11, 10, -3, -5, -4, 12, 13, 15, 14];
    let mut tree = AvlTree::default();
    let mut expected = BTreeSet::new();

    for key in lesson {
        tree.insert(key);
        expected.insert(key);
        validate(&tree, &expected);
    }
    for key in lesson.into_iter().rev() {
        tree.delete(key);
        expected.remove(&key);
        validate(&tree, &expected);
    }

    for seed in 0..100 {
        let mut state = seed;
        let mut tree = AvlTree::default();
        let mut expected = BTreeSet::new();
        for _ in 0..3_000 {
            let key = (next_u32(&mut state) % 241) as i32 - 120;
            if next_u32(&mut state) % 10 < 6 {
                tree.insert(key);
                expected.insert(key);
            } else {
                tree.delete(key);
                expected.remove(&key);
            }
            validate(&tree, &expected);
        }
    }

    println!("RUST TESTS PASSED (lesson sequence, 100x3000 mixed operations)");
}
