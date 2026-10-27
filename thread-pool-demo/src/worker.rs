//! 工人线程：从共享接收端循环取任务执行。

use std::sync::{mpsc, Arc, Mutex};
use std::thread;

use crate::job::Job;

/// 一个工人线程，`id` 用于标识，`handle` 用于关闭时 join。
pub struct Worker {
    pub(crate) id: usize,
    pub(crate) handle: Option<thread::JoinHandle<()>>,
}

impl Worker {
    /// 起一个线程：`recv` 一个任务 → 执行 → 重复，直到发送端被丢弃。
    ///
    /// 循环必须做到三件事：
    ///  1. **毒锁恢复**：`receiver.lock()` 可能返回 `Err`（持锁期间发生 panic 会把 Mutex
    ///     "毒化"）。用 `poisoned.into_inner()` 恢复继续用，而不是 `.unwrap()` 直接炸。
    ///  2. **退出信号**：`recv()` 返回 `Err` 表示所有 `Sender` 已丢弃，`break` 退出。
    ///  3. **panic 隔离**：`job()` 若 panic，用 `catch_unwind` 接住，保住工人线程——
    ///     否则每 panic 一次就静默减员一个工人，池越来越小。
    pub fn new(id: usize, receiver: Arc<Mutex<mpsc::Receiver<Job>>>) -> Self {
        // TODO: 实现工人线程主循环（核心：recv 循环 + panic 隔离 + 毒锁恢复）
        // 参考文章「工人线程：循环取任务」与「那些真正让线程池崩掉的细节」：
        //   let handle = thread::spawn(move || loop {
        //       // 1) 恢复毒化锁，而不是 unwrap() 直接炸
        //       let guard = match receiver.lock() {
        //           Ok(g) => g,
        //           Err(poisoned) => poisoned.into_inner(),
        //       };
        //       // 2) recv 阻塞，直到有任务或所有 sender 被丢弃
        //       match guard.recv() {
        //           Ok(job) => {
        //               // 3) catch_unwind 保住工人
        //               if std::panic::catch_unwind(std::panic::AssertUnwindSafe(job)).is_err() {
        //                   eprintln!("worker task panicked, keeping worker alive");
        //               }
        //           }
        //           Err(_) => break, // 发送端已关闭，退出循环
        //       }
        //   });
        //   Self { id, handle: Some(handle) }
        todo!()
    }
}
