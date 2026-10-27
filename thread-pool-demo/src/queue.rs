//! 有界 FIFO 队列：满时阻塞生产者，空时阻塞消费者 —— 即背压。

use std::collections::VecDeque;
use std::sync::{Condvar, Mutex};

/// 一个有容量上限的队列。
///
/// `push` 在队列满时阻塞（`not_full.wait`）；`pop` 在队列空时阻塞（`not_empty.wait`）。
/// 两个条件变量分别协调生产者和消费者，避免无界增长导致的 OOM。
pub struct BoundedQueue<T> {
    inner: Mutex<VecDeque<T>>,
    not_empty: Condvar,
    not_full: Condvar,
    capacity: usize,
}

impl<T> BoundedQueue<T> {
    pub fn new(capacity: usize) -> Self {
        assert!(capacity > 0, "capacity must be positive");
        Self {
            inner: Mutex::new(VecDeque::with_capacity(capacity)),
            not_empty: Condvar::new(),
            not_full: Condvar::new(),
            capacity,
        }
    }

    pub fn capacity(&self) -> usize {
        self.capacity
    }

    pub fn len(&self) -> usize {
        self.inner.lock().unwrap().len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// 入队；队列满时阻塞调用方，直到有空位（背压核心）。
    pub fn push(&self, item: T) {
        // TODO: 实现有界队列的 push（背压核心）
        // 参考文章「队列必须有界」一节：
        //   let mut q = self.inner.lock().unwrap();
        //   while q.len() == self.capacity {
        //       q = self.not_full.wait(q).unwrap(); // 队列满，阻塞生产者
        //   }
        //   q.push_back(item);
        //   self.not_empty.notify_one();
        // 注意用 while 而非 if，防止虚假唤醒（spurious wakeup）后继续越界入队。
        todo!()
    }

    /// 出队；队列空时阻塞调用方，直到有元素。
    pub fn pop(&self) -> T {
        // TODO: 实现有界队列的 pop
        // 参考文章「队列必须有界」一节：
        //   let mut q = self.inner.lock().unwrap();
        //   while q.is_empty() {
        //       q = self.not_empty.wait(q).unwrap(); // 队列空，阻塞消费者
        //   }
        //   let item = q.pop_front().unwrap();
        //   self.not_full.notify_one();
        //   item
        todo!()
    }
}
