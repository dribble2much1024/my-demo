//! 从零实现一个线程池（标准库 `thread` + `mpsc` + `Arc<Mutex<Condvar>>`，不引入 tokio）。
//!
//! 骨架已搭好：类型、签名、demo、测试全部就位，核心逻辑留给你实现（搜 `todo!`）。
//!
//! 核心不在任务队列，而在三件事：有界队列（背压）、panic 隔离 / 毒锁恢复、关闭语义。
//! 实现完对照 `GUIDE.md` 的清单逐项检查，并删掉下面这行 allow 让编译器恢复检查。

#![allow(dead_code, unused_variables, unused_mut, unused_imports)]

mod error;
mod job;
mod pool;
mod queue;
mod worker;

pub use error::PoolError;
pub use job::Job;
pub use pool::ThreadPool;
pub use queue::BoundedQueue;
