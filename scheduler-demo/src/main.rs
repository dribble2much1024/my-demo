use std::time::Duration;

use tracing::info;
use tracing_subscriber::EnvFilter;

use scheduler_demo::config::SchedulerConfig;
use scheduler_demo::definition::JobDefinition;
use scheduler_demo::jobs::{CleanupJob, PrewarmJob};
use scheduler_demo::policy::{MisfirePolicy, OverlapPolicy};
use scheduler_demo::schedule::Schedule;
use scheduler_demo::Scheduler;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .init();

    let mut scheduler = Scheduler::new(SchedulerConfig::new(4)).expect("无效配置");

    // 启动 1 秒后预热一次缓存
    scheduler
        .add(JobDefinition::new(
            "prewarm-cache",
            Schedule::once(Duration::from_secs(1)),
            PrewarmJob,
        ))
        .expect("注册预热任务失败");

    // 每 5 秒清理一次 Session
    scheduler
        .add(
            JobDefinition::new(
                "cleanup-sessions",
                Schedule::every(Duration::from_secs(5)),
                CleanupJob,
            )
            .misfire_policy(MisfirePolicy::Skip)
            .overlap_policy(OverlapPolicy::SkipIfRunning),
        )
        .expect("注册清理任务失败");

    info!("调度器启动，按 Ctrl-C 停止");

    let report = scheduler
        .run_until(async {
            if let Err(error) = tokio::signal::ctrl_c().await {
                tracing::error!(%error, "failed to listen for Ctrl-C");
            }
        })
        .await;

    info!(
        started = report.started,
        succeeded = report.succeeded,
        failed = report.failed,
        panicked = report.panicked,
        skipped_misfires = report.skipped_misfires,
        skipped_overlaps = report.skipped_overlaps,
        discarded_on_shutdown = report.discarded_on_shutdown,
        "调度器已停止"
    );
}
