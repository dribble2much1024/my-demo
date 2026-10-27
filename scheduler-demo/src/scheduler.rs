use std::collections::{BinaryHeap, HashMap, VecDeque};
use std::future::Future;

use tokio::task::{JoinError, JoinSet};
use tokio::time::Instant;

use crate::config::SchedulerConfig;
use crate::deadline::Deadline;
use crate::definition::JobDefinition;
use crate::error::SchedulerError;
use crate::report::{RunOutcome, SchedulerReport};

/// 一个待运行（或正在运行）的执行单元，对应文章里的 *occurrence*。
#[derive(Debug, Clone)]
pub struct Occurrence {
    pub job_id: String,
    /// 本次执行锚定的计划槽位（fixed-rate 的 scheduled_at）。
    pub scheduled_at: Instant,
    /// 用于日志 / 幂等键，与 `Deadline::sequence` 同源。
    pub sequence: u64,
}

/// 一次执行结束后的回传结果（由 `JoinSet` 产出）。
#[derive(Debug)]
struct FinishedRun {
    job_id: String,
    outcome: RunOutcome,
}

/// 每个已注册 Job 的可变运行状态。
struct JobState {
    definition: JobDefinition,
    /// 当前正在运行的次数，用于 overlap 判断。
    running: usize,
}

/// 进程内任务调度器。
///
/// 核心状态：
/// - `jobs`：Job ID -> 定义 + 运行计数；
/// - `heap`：待到期 deadline 的最小堆（调度层）；
/// - `ready`：已到期、等待执行的 occurrence 队列（执行层的入口）；
/// - `in_flight`：正在运行的 Tokio task（`JoinSet`）。
pub struct Scheduler {
    config: SchedulerConfig,
    jobs: HashMap<String, JobState>,
    heap: BinaryHeap<Deadline>,
    ready: VecDeque<Occurrence>,
    in_flight: JoinSet<FinishedRun>,
    /// 单调递增的序号，用于打破相同 deadline 的平局。
    sequence: u64,
    report: SchedulerReport,
}

impl Scheduler {
    pub fn new(config: SchedulerConfig) -> Result<Self, SchedulerError> {
        // TODO(你来实现): 创建调度器。
        // 1. 校验 config.max_concurrency > 0，否则返回 SchedulerError::ZeroMaxConcurrency。
        // 2. 初始化各字段（jobs / heap / ready / in_flight / sequence / report 均为空或默认值）。
        todo!("校验配置并构造 Scheduler")
    }

    pub fn add(&mut self, definition: JobDefinition) -> Result<(), SchedulerError> {
        // TODO(你来实现): 注册任务。
        // 1. 校验：
        //    - id 非空（SchedulerError::EmptyJobId）；
        //    - id 不重复（SchedulerError::DuplicateJobId）；
        //    - 周期 > 0（SchedulerError::ZeroInterval）；
        //    - CatchUp { max_runs } > 0（SchedulerError::ZeroCatchUpRuns）。
        // 2. 计算 first_due = Instant::now() + schedule.first_delay()。
        // 3. 分配一个递增 sequence，把 Deadline::new(first_due, sequence, id) 压入 heap。
        // 4. 把 JobState { definition, running: 0 } 存入 jobs。
        todo!("注册任务到调度器")
    }

    pub async fn run_until<F>(mut self, shutdown: F) -> SchedulerReport
    where
        F: Future<Output = ()>,
    {
        tokio::pin!(shutdown);

        // TODO(你来实现): 主循环，结构如下（把这段注释翻译成代码）——
        //
        // loop {
        //     // 下一次到期的 deadline；堆空则为 None
        //     let next_due = self.heap.peek().map(|d| d.due_at);
        //
        //     tokio::select! {
        //         // 1) 收到关闭信号
        //         _ = &mut shutdown => {
        //             self.discard_ready();      // 丢弃尚未启动的 occurrence
        //             break;
        //         }
        //         // 2) 有正在运行的任务结束
        //         completed = self.in_flight.join_next(), if !self.in_flight.is_empty() => {
        //             self.handle_completion(completed);
        //         }
        //         // 3) 最近的 deadline 到期
        //         _ = tokio::time::sleep_until(next_due), if next_due.is_some() => {
        //             self.dispatch_due(Instant::now());
        //         }
        //     }
        //
        //     // 每轮结束都尝试在并发上限内启动 ready 队列里的任务
        //     self.start_ready();
        // }
        //
        // // 关闭后：等待 in_flight 里已经启动的任务全部结束
        // self.drain_in_flight().await;
        //
        // self.report
        todo!("实现主循环与优雅关闭")
    }

    /// 关闭时：丢弃 ready 队列里尚未启动的 occurrence，并计入 `discarded_on_shutdown`。
    fn discard_ready(&mut self) {
        // TODO: self.ready.drain(..)，把数量累加到 self.report.discarded_on_shutdown。
        todo!()
    }

    /// 处理一个刚完成的执行：取出 job_id + outcome，running 减一，记入 report。
    fn handle_completion(&mut self, completed: Option<Result<FinishedRun, JoinError>>) {
        // TODO:
        // 1. 从 completed 里取出 FinishedRun（若 JoinError，可当作 Panicked 或记日志）。
        // 2. self.jobs.get_mut(&job_id).running 减一（注意下限）。
        // 3. 按 outcome 更新 self.report.succeeded / failed / panicked。
        todo!()
    }

    /// 到期派发：弹出堆中所有已到期的 deadline，按 misfire 策略决定执行哪些。
    fn dispatch_due(&mut self, now: Instant) {
        // TODO:
        // 1. 循环：只要 heap.peek().due_at <= now 就弹出。
        // 2. 对每个 deadline 找到它的 Job（schedule / misfire / overlap 策略）。
        // 3. 一次性任务：只生成一个 Occurrence（scheduled_at = due_at）。
        // 4. 周期任务：计算漏掉了几次——
        //        additional = (now - due_at).as_secs() / interval.as_secs()   // 用整数运算，勿用 Duration 直接除
        //        total_due = additional + 1
        //        next_due = due_at + total_due * interval
        //    按 MisfirePolicy：
        //        - Skip：只保留最近一个槽位（scheduled_at = due_at + additional * interval）；
        //        - CatchUp { max_runs }：保留最近 max_runs 个槽位；
        //    每个保留的槽位生成一个 Occurrence 推入 ready；被丢弃的计入 skipped_misfires。
        // 5. 周期任务把 next_due 作为新的 Deadline 压回 heap（sequence 重新分配）。
        //    注意：next_due 仍从原 due_at 往后推（fixed-rate），补跑不改变原周期。
        todo!()
    }

    /// 在并发上限内，从 ready 队列启动任务。
    fn start_ready(&mut self) {
        // TODO:
        // 1. while self.in_flight.len() < self.config.max_concurrency：
        //    从 self.ready.pop_front() 取出一个 occurrence，没了就 break。
        // 2. 查该 job 的 overlap 策略：
        //    - SkipIfRunning 且 job.running > 0 => 跳过，skipped_overlaps += 1，continue；
        // 3. 否则 job.running += 1，self.report.started += 1。
        // 4. spawn 到 self.in_flight：
        //    - 构造 JobContext { scheduled_at: occurrence.scheduled_at, started_at: Instant::now() }；
        //    - 用 AssertUnwindSafe(handler.run(context)).catch_unwind().await 捕获 panic；
        //    - 把 Ok/Err/panic 映射成 RunOutcome，返回 FinishedRun { job_id, outcome }。
        //
        // 参考文章里的 panic 隔离写法：
        //   let outcome = AssertUnwindSafe(handler.run(context))
        //       .catch_unwind()
        //       .await
        //       .map(|result| match result {
        //           Ok(()) => RunOutcome::Succeeded,
        //           Err(error) => RunOutcome::Failed(error),
        //       })
        //       .unwrap_or(RunOutcome::Panicked);
        todo!()
    }

    /// 关闭后：等待 in_flight 中的任务全部结束。
    async fn drain_in_flight(&mut self) {
        // TODO: while let Some(completed) = self.in_flight.join_next().await {
        //     self.handle_completion(completed);
        // }
        todo!()
    }
}
