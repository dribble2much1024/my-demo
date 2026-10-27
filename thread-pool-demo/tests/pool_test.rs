//! 线程池测试脚手架。
//!
//! 断言留给你补（每个 `todo!` 前有该测什么）。实现完删掉这行 allow 让编译器恢复检查。

#![allow(dead_code, unused_imports, unused_variables, unused_mut)]

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{mpsc, Arc};
use std::time::Duration;

use thread_pool_demo::{BoundedQueue, PoolError, ThreadPool};

#[test]
fn executes_all_jobs() {
    // TODO: 提交 N 个任务，用 AtomicUsize 计数，验证全部执行。
    // 思路：let pool = ThreadPool::new(4);
    //       let counter = Arc::new(AtomicUsize::new(0));
    //       for _ in 0..100 { pool.execute(...counter.fetch_add(1)...) }
    //       drop(pool); assert_eq!(counter.load(...), 100);
    todo!()
}

#[test]
fn try_execute_after_close_returns_error() {
    // TODO: 关闭池后，try_execute 应返回 Err(PoolError::PoolClosed)。
    // 思路：let pool = ThreadPool::new(2); drop(pool);
    //       assert_eq!(pool.try_execute(|| {}), Err(PoolError::PoolClosed));
    todo!()
}

#[test]
fn shutdown_drains_queued_jobs() {
    // TODO: 提交任务后立即 drop 池，验证排队任务仍被优雅关闭跑完。
    // 思路：提交一个通过 channel 通知的任务，drop 池后 recv_timeout 应能收到通知。
    todo!()
}

#[test]
fn bounded_queue_blocks_when_full() {
    // TODO: 填满有界队列后，push 应阻塞；另一线程 pop 后 push 才返回（背压）。
    // 思路：let q = Arc::new(BoundedQueue::new(2)); 主线程 push 两次填满；
    //       再开一个线程延时 pop，主线程第三次 push 应在这之后才返回。
    todo!()
}

#[test]
fn worker_survives_panicking_job() {
    // TODO: 提交一个 panic 任务，再提交正常任务，验证工人没死（panic 被隔离）。
    // 思路：pool.execute(|| panic!("boom")); pool.execute(正常任务计数); drop 后计数 == 1。
    todo!()
}
