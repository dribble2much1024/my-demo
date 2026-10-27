/// 调度器全局配置。
#[derive(Debug, Clone, Copy)]
pub struct SchedulerConfig {
    /// 全局并发上限：最多同时运行的执行数。
    pub max_concurrency: usize,
}

impl SchedulerConfig {
    pub fn new(max_concurrency: usize) -> Self {
        Self { max_concurrency }
    }
}
