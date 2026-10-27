//! 队列提交客户端（可 Clone，Semaphore 背压）。

use std::sync::Arc;

use tokio::sync::mpsc;
use tokio::sync::mpsc::error::SendError;
use tokio::sync::Semaphore;

use crate::task::Task;

/// 提交客户端。可 Clone，多个生产者共享同一队列。
pub struct QueueClient<T> {
    capacity: Arc<Semaphore>,
    sender: mpsc::Sender<Task<T>>,
}

impl<T> QueueClient<T> {
    pub(crate) fn new(capacity: Arc<Semaphore>, sender: mpsc::Sender<Task<T>>) -> Self {
        Self { capacity, sender }
    }

    /// 提交任务。先获取容量配额（满载时等待，背压），再发送。
    pub async fn enqueue(
        &self,
        id: impl Into<String>,
        payload: T,
    ) -> Result<(), SendError<Task<T>>>
    where
        T: Send,
    {
        todo!("补全 enqueue：获取 Semaphore 配额 + 构造 Task + 发送")
    }
}

impl<T> Clone for QueueClient<T> {
    fn clone(&self) -> Self {
        Self {
            capacity: Arc::clone(&self.capacity),
            sender: self.sender.clone(),
        }
    }
}
