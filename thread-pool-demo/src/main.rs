use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use thread_pool_demo::ThreadPool;

fn main() {
    // 4 个工人
    let pool = ThreadPool::new(4);

    let counter = Arc::new(AtomicUsize::new(0));

    // 提交 8 个任务，每个任务让计数器 +1
    for i in 0..8 {
        let counter = Arc::clone(&counter);
        pool.execute(move || {
            let total = counter.fetch_add(1, Ordering::SeqCst) + 1;
            println!("job {i} done, total = {total}");
        });
    }

    // 优雅关闭：先 drop sender，让工人把队列剩余任务跑完再退出
    drop(pool);

    println!("all done, counter = {}", counter.load(Ordering::SeqCst));
}
