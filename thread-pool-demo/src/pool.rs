//! 线程池本体：固定工人 + 任务提交 + 优雅 / 超时关闭。

use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::Duration;

use crate::error::PoolError;
use crate::job::Job;
use crate::worker::Worker;

/// 固定大小的线程池。
///
/// 任务经 `execute` / `try_execute` 塞进 mpsc channel；工人线程从共享接收端取任务执行。
/// 丢弃 `ThreadPool` 时优雅关闭：先 drop sender 让工人处理完剩余任务，再逐个 join。
pub struct ThreadPool {
    workers: Vec<Worker>,
    sender: Option<mpsc::Sender<Job>>,
}

impl ThreadPool {
    /// 创建 `size` 个工人线程的池。
    pub fn new(size: usize) -> Self {
        // TODO: 实现线程池构造（核心：channel + Arc<Mutex<Receiver>> + spawn workers）
        // 参考文章「骨架：队列 + 固定工人」：
        //   assert!(size > 0);
        //   let (sender, receiver) = mpsc::channel::<Job>();
        //   let receiver = Arc::new(Mutex::new(receiver));
        //   let workers = (0..size)
        //       .map(|id| Worker::new(id, Arc::clone(&receiver)))
        //       .collect();
        //   Self { workers, sender: Some(sender) }
        // 注意：mpsc::Receiver 不能克隆，多个工人共享同一接收端只能加锁（Arc<Mutex<..>>）。
        todo!()
    }

    /// 提交一个任务；若池已关闭则静默丢弃（快速路径）。
    pub fn execute<F>(&self, f: F)
    where
        F: FnOnce() + Send + 'static,
    {
        // TODO: 实现 execute（快速提交，忽略 send 错误）
        // 参考文章「提交任务：sender 不能先消失」：
        //   let job: Job = Box::new(f);
        //   // 忽略 send 错误：池已关闭，接收端已消失
        //   let _ = self.sender.as_ref().unwrap().send(job);
        todo!()
    }

    /// 提交一个任务；若池已关闭返回 `PoolError::PoolClosed`，不静默丢任务。
    pub fn try_execute<F>(&self, f: F) -> Result<(), PoolError>
    where
        F: FnOnce() + Send + 'static,
    {
        // TODO: 实现 try_execute（明确返回 PoolClosed，不静默丢任务）
        // 参考文章「提交任务：sender 不能先消失」：
        //   let job: Job = Box::new(f);
        //   self.sender
        //       .as_ref()
        //       .ok_or(PoolError::PoolClosed)?
        //       .send(job)
        //       .map_err(|_| PoolError::PoolClosed)
        todo!()
    }

    /// 关闭，最多等 `timeout`；`true` 表示所有工人都按时结束，`false` 表示超时强杀。
    pub fn shutdown_timeout(mut self, timeout: Duration) -> bool {
        // TODO: 实现超时关闭（核心：drop sender + 轮询 is_finished）
        // 参考文章「优雅关闭：最难的部分」中的 shutdown_timeout：
        //   drop(self.sender.take());
        //   let deadline = std::time::Instant::now() + timeout;
        //   let mut all_done = true;
        //   for worker in &mut self.workers {
        //       let handle = worker.handle.take().unwrap();
        //       // 标准库没有 join_timeout，只能轮询 is_finished
        //       while !handle.is_finished() {
        //           if std::time::Instant::now() > deadline {
        //               all_done = false;
        //               break;
        //           }
        //           std::thread::sleep(std::time::Duration::from_millis(5));
        //       }
        //       if handle.is_finished() {
        //           let _ = handle.join();
        //       }
        //   }
        //   all_done
        todo!()
    }
}

impl Drop for ThreadPool {
    fn drop(&mut self) {
        // TODO: 实现优雅关闭（核心：先 drop sender 让 recv 返回 Err，再 join）
        // 参考文章「优雅关闭：最难的部分」：
        //   // 先丢弃 sender，让 recv 返回 Err
        //   drop(self.sender.take());
        //   // 再等所有工人处理完剩余任务并退出
        //   for worker in &mut self.workers {
        //       if let Some(handle) = worker.handle.take() {
        //           handle.join().unwrap();
        //       }
        //   }
        // 顺序很关键：mpsc 是 FIFO，工人在跳出循环前会把队列剩余任务全跑完，
        // 所以这是「排完队再退」，不是「立刻砍」。
        todo!()
    }
}
