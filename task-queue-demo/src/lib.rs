//! 进程内后台任务队列：背压、并发 Worker、错误分类、指数退避、死信、优雅排空。
//!
//! 只讨论调度语义，任务全在内存中，进程崩溃会丢失。

pub mod task;
pub mod retry;
pub mod queue;
pub mod client;

pub use client::QueueClient;
pub use queue::{build, DeadLetter, QueueConfig, QueueReport, Runner};
pub use retry::RetryPolicy;
pub use task::{Task, TaskError, TaskHandler};
