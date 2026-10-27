//! 调度器（Runner）：receiver / ready / in_flight / scheduled 四状态。

use std::cmp::Ordering;
use std::collections::{BinaryHeap, VecDeque};
use std::sync::Arc;
use std::time::{Duration, Instant};

use futures::FutureExt;
use tokio::sync::{mpsc, Semaphore};
use tokio::task::JoinSet;
use tokio::time::sleep_until;

use crate::client::QueueClient;
use crate::retry::RetryPolicy;
use crate::task::{Task, TaskError, TaskHandler};

/// 队列配置。
#[derive(Clone)]
pub struct QueueConfig {
    /// 队列容量：同时存在的任务总数（含等待、执行、延迟重试）。
    pub capacity: usize,
    /// 并发 Worker 数。
    pub concurrency: usize,
    /// 重试策略。
    pub retry: RetryPolicy,
}

/// 死信：任务 + 失败原因。
pub struct DeadLetter<T> {
    pub task: Task<T>,
    pub reason: String,
}

/// 队列最终报告。
pub struct QueueReport<T> {
    pub accepted: usize,
    pub succeeded: usize,
    pub retries_scheduled: usize,
    pub dead_letters: Vec<DeadLetter<T>>,
}

/// 延迟重试堆元素。
struct Scheduled<T> {
    ready_at: Instant,
    sequence: u64,
    task: Task<T>,
}

impl<T> PartialEq for Scheduled<T> {
    fn eq(&self, other: &Self) -> bool {
        self.sequence == other.sequence
    }
}
impl<T> Eq for Scheduled<T> {}

impl<T> PartialOrd for Scheduled<T> {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl<T> Ord for Scheduled<T> {
    fn cmp(&self, other: &Self) -> Ordering {
        // BinaryHeap 是最大堆，反转 ready_at 让最早到期的在堆顶；
        // sequence 用于稳定排序，避免 T 需要实现 Ord。
        other
            .ready_at
            .cmp(&self.ready_at)
            .then_with(|| other.sequence.cmp(&self.sequence))
    }
}

/// 调度器：消费 channel 任务，调度执行、重试、死信。
pub struct Runner<T, H> {
    receiver: mpsc::Receiver<Task<T>>,
    handler: Arc<H>,
    retry: RetryPolicy,
    concurrency: usize,
    ready: VecDeque<Task<T>>,
    scheduled: BinaryHeap<Scheduled<T>>,
    sequence: u64,
    accepted: usize,
    succeeded: usize,
    retries_scheduled: usize,
    dead_letters: Vec<DeadLetter<T>>,
}

/// 构建队列，返回提交客户端与调度器。
pub fn build<T, H>(config: QueueConfig, handler: H) -> (QueueClient<T>, Runner<T, H>)
where
    T: Send + Sync + 'static,
    H: TaskHandler<T>,
{
    let capacity = Arc::new(Semaphore::new(config.capacity));
    let (sender, receiver) = mpsc::channel(config.capacity);
    let client = QueueClient::new(Arc::clone(&capacity), sender);
    let runner = Runner {
        receiver,
        handler: Arc::new(handler),
        retry: config.retry,
        concurrency: config.concurrency,
        ready: VecDeque::new(),
        scheduled: BinaryHeap::new(),
        sequence: 0,
        accepted: 0,
        succeeded: 0,
        retries_scheduled: 0,
        dead_letters: Vec::new(),
    };
    (client, runner)
}

impl<T, H> Runner<T, H>
where
    T: Send + Sync + 'static,
    H: TaskHandler<T>,
{
    /// 运行调度循环，直到所有发送端关闭且任务排空。
    pub async fn run(mut self) -> QueueReport<T> {
        // 提示：用 JoinSet 管理在飞任务，用 select! 调度，catch_unwind 隔离 panic。
        //
        // 1. let mut in_flight = JoinSet::new(); let mut receiver_open = true;
        // 2. 循环体：
        //    a. fill：while in_flight.len() < self.concurrency {
        //         let Some(task) = self.ready.pop_front() else { break };
        //         let handler = Arc::clone(&self.handler);
        //         in_flight.spawn(async move {
        //             let result = handler.handle(&task).catch_unwind().await;
        //             (task, result)
        //         });
        //       }
        //    b. let next_deadline = self.scheduled.peek().map(|s| s.ready_at);
        //    c. 退出条件（排空）：
        //       if !receiver_open && self.ready.is_empty()
        //           && self.scheduled.is_empty() && in_flight.is_empty() { break; }
        //    d. tokio::select! {
        //         submission = self.receiver.recv() => {
        //           match submission {
        //             Some(task) => { self.accepted += 1; self.ready.push_back(task); }
        //             None => receiver_open = false,
        //           }
        //         }
        //         completion = in_flight.join_next(), if !in_flight.is_empty() => {
        //           if let Some(Ok((task, result))) = completion {
        //             self.handle_result(task, result);
        //           }
        //         }
        //         _ = sleep_until(next_deadline.unwrap_or_else(Instant::now)),
        //             if next_deadline.is_some() => {
        //           self.drain_due();
        //         }
        //       }
        // 3. 返回 QueueReport { accepted, succeeded, retries_scheduled, dead_letters }
        todo!("补全 run：主调度循环")
    }

    /// 处理一个执行完成的任务：成功 / 重试调度 / 进死信（含 panic）。
    ///
    /// `result` 外层是 catch_unwind 的结果：`Err(_)` 表示 handler panic。
    fn handle_result(
        &mut self,
        mut task: Task<T>,
        result: Result<Result<(), TaskError>, Box<dyn std::any::Any + Send>>,
    ) {
        // 提示：
        // - Ok(Ok(()))                     -> succeeded += 1（task drop，配额归还）
        // - Ok(Err(Permanent(reason)))     -> 进死信
        // - Ok(Err(Retryable(reason)))     -> 若 attempt >= max_attempts 进死信；
        //                                     否则 increment_attempt + 计算 delay + push 进 scheduled
        // - Err(_)（panic）                -> 进死信，reason 说明 panic
        todo!("补全 handle_result：成功 / 重试 / 死信分类")
    }

    /// 把 scheduled 中已到期的任务移到 ready。
    fn drain_due(&mut self) {
        // 提示：while 堆顶 ready_at <= now，pop 出来 push 进 self.ready；否则 break。
        todo!("补全 drain_due：到期任务 scheduled -> ready")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Mutex;
    use tokio::time::timeout;

    #[derive(Clone, Debug)]
    struct TestPayload {
        /// 前 retry_times 次返回 Retryable，之后成功。
        retry_times: u32,
        /// 是否永久失败。
        permanent: bool,
        /// 是否 panic。
        panic: bool,
    }

    #[derive(Clone)]
    struct TestHandler {
        /// 执行顺序 (task_id, attempt)。
        log: Arc<Mutex<Vec<(String, u32)>>>,
        /// 当前并发计数。
        concurrent: Arc<AtomicUsize>,
        /// 并发峰值。
        peak: Arc<AtomicUsize>,
    }

    impl TestHandler {
        fn new() -> Self {
            Self {
                log: Arc::new(Mutex::new(Vec::new())),
                concurrent: Arc::new(AtomicUsize::new(0)),
                peak: Arc::new(AtomicUsize::new(0)),
            }
        }
    }

    #[async_trait::async_trait]
    impl TaskHandler<TestPayload> for TestHandler {
        async fn handle(&self, task: &Task<TestPayload>) -> Result<(), TaskError> {
            let cur = self.concurrent.fetch_add(1, Ordering::SeqCst) + 1;
            self.peak.fetch_max(cur, Ordering::SeqCst);
            self.log
                .lock()
                .unwrap()
                .push((task.id().to_string(), task.attempt()));

            // 少量耗时，让并发窗口可观察。
            tokio::time::sleep(Duration::from_millis(5)).await;

            let p = task.payload();
            let result = if p.panic {
                panic!("handler panicked");
            } else if p.permanent {
                Err(TaskError::Permanent("permanent".into()))
            } else if task.attempt() <= p.retry_times {
                Err(TaskError::Retryable("retryable".into()))
            } else {
                Ok(())
            };

            self.concurrent.fetch_sub(1, Ordering::SeqCst);
            result
        }
    }

    fn config(capacity: usize, concurrency: usize, max_attempts: u32) -> QueueConfig {
        QueueConfig {
            capacity,
            concurrency,
            retry: RetryPolicy::new(
                Duration::from_millis(10),
                Duration::from_millis(100),
                max_attempts,
            ),
        }
    }

    async fn run_queue(
        payloads: Vec<(String, TestPayload)>,
        cfg: QueueConfig,
    ) -> (QueueReport<TestPayload>, TestHandler) {
        let handler = TestHandler::new();
        let (client, runner) = build(cfg, handler.clone());
        for (id, p) in payloads {
            client.enqueue(id, p).await.unwrap();
        }
        drop(client); // 关闭发送端，触发排空
        let report = runner.run().await;
        (report, handler)
    }

    #[tokio::test]
    async fn retryable_failure_succeeds_after_retries() {
        let (report, handler) = run_queue(
            vec![(
                "welcome-alice".into(),
                TestPayload { retry_times: 2, permanent: false, panic: false },
            )],
            config(10, 1, 4),
        )
        .await;

        assert_eq!(report.succeeded, 1);
        assert_eq!(report.retries_scheduled, 2);
        assert_eq!(report.dead_letters.len(), 0);
        // 执行了 3 次（attempt 1, 2, 3）
        assert_eq!(handler.log.lock().unwrap().len(), 3);
    }

    #[tokio::test]
    async fn permanent_failure_does_not_retry() {
        let (report, _) = run_queue(
            vec![(
                "welcome-bob".into(),
                TestPayload { retry_times: 0, permanent: true, panic: false },
            )],
            config(10, 1, 4),
        )
        .await;

        assert_eq!(report.succeeded, 0);
        assert_eq!(report.retries_scheduled, 0);
        assert_eq!(report.dead_letters.len(), 1);
    }

    #[tokio::test]
    async fn max_attempts_exhausted_goes_to_dead_letter() {
        let (report, _) = run_queue(
            vec![(
                "t".into(),
                TestPayload { retry_times: 100, permanent: false, panic: false },
            )],
            config(10, 1, 3),
        )
        .await;

        assert_eq!(report.succeeded, 0);
        assert_eq!(report.retries_scheduled, 2);
        assert_eq!(report.dead_letters.len(), 1);
    }

    #[tokio::test]
    async fn delayed_retry_does_not_hold_worker() {
        let handler = TestHandler::new();
        let (client, runner) = build(config(10, 1, 4), handler.clone());
        client
            .enqueue("a", TestPayload { retry_times: 1, permanent: false, panic: false })
            .await
            .unwrap();
        client
            .enqueue("b", TestPayload { retry_times: 0, permanent: false, panic: false })
            .await
            .unwrap();
        drop(client);
        let report = runner.run().await;

        assert_eq!(report.succeeded, 2);
        let ids: Vec<String> = handler.log.lock().unwrap().iter().map(|(id, _)| id.clone()).collect();
        // a 第一次失败后不占 Worker，b 先执行，然后 a 重试
        assert_eq!(ids, vec!["a".to_string(), "b".to_string(), "a".to_string()]);
    }

    #[tokio::test]
    async fn concurrency_does_not_exceed_limit() {
        let n = 8;
        let handler = TestHandler::new();
        let (client, runner) = build(config(10, 2, 4), handler.clone());
        for i in 0..n {
            client
                .enqueue(
                    format!("t{i}"),
                    TestPayload { retry_times: 0, permanent: false, panic: false },
                )
                .await
                .unwrap();
        }
        drop(client);
        let report = runner.run().await;

        assert_eq!(report.succeeded, n);
        assert!(handler.peak.load(Ordering::SeqCst) <= 2);
    }

    #[tokio::test]
    async fn handler_panic_is_isolated_as_dead_letter() {
        let (report, _) = run_queue(
            vec![(
                "p".into(),
                TestPayload { retry_times: 0, permanent: false, panic: true },
            )],
            config(10, 1, 4),
        )
        .await;

        assert_eq!(report.dead_letters.len(), 1);
        assert_eq!(report.succeeded, 0);
    }

    #[tokio::test]
    async fn capacity_covers_scheduled_retry() {
        // capacity=1：一个任务进入延迟重试期间，配额仍被占用，
        // 第 2 个 enqueue 应被背压阻塞，直到前者完成释放配额。
        let handler = TestHandler::new();
        let cfg = QueueConfig {
            capacity: 1,
            concurrency: 1,
            retry: RetryPolicy::new(Duration::from_millis(200), Duration::from_millis(200), 4),
        };
        let (client, runner) = build(cfg, handler.clone());

        client
            .enqueue("a", TestPayload { retry_times: 1, permanent: false, panic: false })
            .await
            .unwrap();

        let runner_task = tokio::spawn(async move { runner.run().await });

        // 等 a 第一次执行失败进入 scheduled（配额仍被占用）
        tokio::time::sleep(Duration::from_millis(20)).await;

        // 第 2 个 enqueue 应被背压阻塞
        let mut second = Box::pin(client.enqueue(
            "b",
            TestPayload { retry_times: 0, permanent: false, panic: false },
        ));
        let blocked = timeout(Duration::from_millis(40), &mut second).await.is_err();
        assert!(blocked, "第 2 个 enqueue 应被容量背压阻塞（scheduled 任务仍占配额）");

        let _ = second.await;
        let report = runner_task.await.unwrap();
        assert_eq!(report.succeeded, 2);
    }
}
