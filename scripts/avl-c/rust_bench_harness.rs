#[derive(Clone, Copy)]
enum Workload {
    Insert,
    Delete,
    Search,
    Ascending,
    Mixed,
}

fn next_u32(state: &mut u32) -> u32 {
    *state = state.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
    *state
}

fn median5(mut values: [f64; 5]) -> f64 {
    for i in 1..values.len() {
        let value = values[i];
        let mut j = i;
        while j > 0 && values[j - 1] > value {
            values[j] = values[j - 1];
            j -= 1;
        }
        values[j] = value;
    }
    values[2]
}

fn best5(values: [f64; 5]) -> f64 {
    values.into_iter().fold(f64::INFINITY, f64::min)
}

fn run_workload(workload: Workload, n: usize, seed: u32) -> (f64, u64) {
    let mut tree = AvlTree::default();
    let mut started = std::time::Instant::now();

    match workload {
        Workload::Insert => {
            let mut state = seed;
            for _ in 0..n {
                tree.insert((next_u32(&mut state) % 5_000_000) as i32);
            }
        }
        Workload::Delete => {
            let mut state = seed;
            let mut keys: Vec<i32> = (0..n as i32).collect();
            for i in (1..n).rev() {
                let j = (next_u32(&mut state) % (i as u32 + 1)) as usize;
                keys.swap(i, j);
            }
            for &key in &keys {
                tree.insert(key);
            }
            tree.rotations = 0;
            started = std::time::Instant::now();
            for key in keys {
                tree.delete(key);
            }
        }
        Workload::Search => {
            let mut state = seed;
            let mut keys: Vec<i32> = (0..n as i32).collect();
            for i in (1..n).rev() {
                let j = (next_u32(&mut state) % (i as u32 + 1)) as usize;
                keys.swap(i, j);
            }
            for key in keys {
                tree.insert(key);
            }
            let mut hits = 0u64;
            for j in 0..300_000u32 {
                let key = ((j * 7_919) % (n as u32 * 2)) as i32 - n as i32 / 3;
                hits += u64::from(tree.contains(key));
            }
            std::hint::black_box(hits);
        }
        Workload::Ascending => {
            for key in 0..n {
                tree.insert(key as i32);
            }
        }
        Workload::Mixed => {
            let mut state = seed;
            for _ in 0..n {
                let key = (next_u32(&mut state) % 150_000) as i32;
                if next_u32(&mut state) % 10 < 6 {
                    tree.insert(key);
                } else {
                    tree.delete(key);
                }
            }
        }
    }

    let milliseconds = started.elapsed().as_secs_f64() * 1_000.0;
    let rotations = tree.rotations;
    std::hint::black_box(tree);
    (milliseconds, rotations)
}

fn bench(name: &str, workload: Workload, n: usize, seed: u32) {
    let mut times = [0.0; 5];
    let mut rotations = 0;
    for round in 0..5 {
        let (milliseconds, count) = run_workload(workload, n, seed + round);
        times[round as usize] = milliseconds;
        if round == 0 {
            rotations = count;
        }
    }
    let selection = match workload {
        Workload::Insert | Workload::Delete | Workload::Search => "best",
        Workload::Ascending | Workload::Mixed => "median",
    };
    let milliseconds = match workload {
        Workload::Insert | Workload::Delete | Workload::Search => best5(times),
        Workload::Ascending | Workload::Mixed => median5(times),
    };
    println!("rust,O3,{name},{selection},{milliseconds:.6},{rotations}");
}

fn main() {
    let operations = std::env::args()
        .nth(1)
        .and_then(|value| value.parse().ok())
        .unwrap_or(2_000_000);
    bench("insert", Workload::Insert, operations, 1);
    bench("delete", Workload::Delete, operations, 2);
    bench("search", Workload::Search, operations, 3);
    bench("ascending", Workload::Ascending, operations, 4);
    bench("mixed", Workload::Mixed, operations, 5);
}
