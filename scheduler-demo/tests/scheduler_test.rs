//! 调度器测试。
//!
//! 所有测试都用 `#[tokio::test(start_paused = true)]` 启动暂停时钟，
//! 调度器里的 sleep 会由测试 runtime 推进，不需要真实等待。
//! 用 `tokio::time::advance(Duration)` 显式推进时间。
//!
//! 测试断言尚未实现（脚手架已备好），补完各 `todo!()` 后可删除下面这行 allow。
#![allow(dead_code, unused_imports, unused_variables)]

use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;

use async_trait::async_trait;

use scheduler_demo::config::SchedulerConfig;
use scheduler_demo::context::JobContext;
use scheduler_demo::definition::JobDefinition;
use scheduler_demo::handler::JobHandler;
use scheduler_demo::policy::{MisfirePolicy, OverlapPolicy};
use scheduler_demo::report::SchedulerReport;
use scheduler_demo::schedule::Schedule;
use scheduler_demo::Scheduler;

/// 一个会记录运行次数的测试 Handler。
#[derive(Clone)]
struct CountingJob {
    runs: Arc<AtomicUsize>,
}

impl CountingJob {
    fn new() -> (Self, Arc<AtomicUsize>) {
        let runs = Arc::new(AtomicUsize::new(0));
        (Self { runs: runs.clone() }, runs)
    }
}

#[async_trait]
impl JobHandler for CountingJob {
    async fn run(&self, _context: JobContext) -> Result<(), String> {
        self.runs.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}

/// 一个会 panic 的测试 Handler，用于验证 panic 隔离。
struct PanicJob;

#[async_trait]
impl JobHandler for PanicJob {
    async fn run(&self, _context: JobContext) -> Result<(), String> {
        panic!("boom");
    }
}

/// 测试脚手架：把调度器丢到后台 task 跑，返回 shutdown 发送端和报告句柄。
///
/// ```ignore
/// let (tx, handle) = spawn_scheduler(scheduler);
/// tokio::time::advance(Duration::from_secs(6)).await;
/// tx.send(()).unwrap();
/// let report = handle.await.unwrap();
/// ```
fn spawn_scheduler(
    scheduler: Scheduler,
) -> (
    tokio::sync::oneshot::Sender<()>,
    tokio::task::JoinHandle<SchedulerReport>,
) {
    let (tx, rx) = tokio::sync::oneshot::channel();
    let handle = tokio::spawn(async move {
        scheduler
            .run_until(async {
                let _ = rx.await;
            })
            .await
    });
    (tx, handle)
}

#[tokio::test(start_paused = true)]
async fn one_shot_runs_once() {
    // TODO: 注册 Schedule::once(5s) 的 CountingJob。
    // 在后台跑调度器，advance 到 6s，触发 shutdown，等待报告。
    // 断言：runs == 1（一次性任务只运行一次，而不是每 5s 循环）。
    //        report.started == 1, report.succeeded == 1。
    todo!()
}

#[tokio::test(start_paused = true)]
async fn periodic_skip_misfired_slots() {
    // TODO: 注册 Schedule::every(10s) + MisfirePolicy::Skip 的 CountingJob。
    // 直接 advance 到 35s（原 deadline 00s，已到期槽位 00/10/20/30）。
    // 断言：Skip 只保留最近一次，runs == 1。
    //        report.skipped_misfires == 3（00/10/20 被跳过）。
    todo!()
}

#[tokio::test(start_paused = true)]
async fn catchup_limits_runs() {
    // TODO: 注册 Schedule::every(10s) + MisfirePolicy::CatchUp { max_runs: 2 }。
    // advance 到 35s。断言：只补最近两次（20s、30s），runs == 2。
    todo!()
}

#[tokio::test(start_paused = true)]
async fn skip_if_running_prevents_overlap() {
    // TODO: 注册一个执行耗时超过周期的 Job（如周期 1s、执行 3s），
    // overlap = SkipIfRunning。推进时间验证同一 Job 不会重叠，
    // report.skipped_overlaps 正确累计。
    todo!()
}

#[tokio::test(start_paused = true)]
async fn shutdown_waits_for_inflight() {
    // TODO: 注册一个执行中立刻触发 shutdown 的场景。
    // 断言：已启动的任务在 run_until 返回前全部结束
    // （报告里的 started 都能对应到 succeeded/failed/panicked）。
    todo!()
}

#[tokio::test(start_paused = true)]
async fn handler_panic_is_isolated() {
    // TODO: 注册 PanicJob（周期任务）。
    // 断言：panic 被隔离捕获，report.panicked 增加，调度器没有崩、
    // 后续周期还能继续运行（可用一个 CountingJob 同时注册来验证）。
    todo!()
}

// 说明：测试里 `start_paused = true` 需要 tokio 的 `test-util` feature（Cargo.toml 已加）。
// 时间用 `tokio::time::advance` 推进；`Instant` 必须用 `tokio::time::Instant`（而非 std），
// 否则拿不到被暂停的时钟。
