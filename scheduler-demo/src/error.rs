use thiserror::Error;

/// 创建调度器 / 注册任务时的配置校验错误。
///
/// 这些错误在启动时就应被捕获，避免运行后才出现忙等或重复 ID 覆盖已有任务。
#[derive(Debug, Error, PartialEq, Eq)]
pub enum SchedulerError {
    #[error("job id 不能为空")]
    EmptyJobId,

    #[error("job id 重复: {0}")]
    DuplicateJobId(String),

    #[error("周期必须大于 0")]
    ZeroInterval,

    #[error("max_concurrency 必须大于 0")]
    ZeroMaxConcurrency,

    #[error("CatchUp.max_runs 必须大于 0")]
    ZeroCatchUpRuns,
}
