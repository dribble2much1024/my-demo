//! 任务、错误分类与业务处理器 trait。

use tokio::sync::OwnedSemaphorePermit;

/// 一个待处理 / 处理中 / 等待重试的任务。
///
/// 字段均为私有，跨模块只能通过访问器读取，`attempt` 的修改由调度器统一完成，
/// 业务 Handler 不负责解释重试次数。
pub struct Task<T> {
    id: String,
    payload: T,
    attempt: u32,
    /// 全生命周期容量配额：任务成功 / 进死信 / 被释放时，drop 该 permit 即归还配额。
    _capacity_permit: OwnedSemaphorePermit,
}

impl<T> Task<T> {
    /// 新建任务。`attempt` 从 1 开始（第一次执行也算在 `max_attempts` 内）。
    pub fn new(id: impl Into<String>, payload: T, permit: OwnedSemaphorePermit) -> Self {
        // todo!("补全 Task::new：构造 Task，attempt 初始为 1")
        Self {
            id: id.into(),
            payload,
            attempt: 1,
            _capacity_permit: permit,
        }
    }

    pub fn id(&self) -> &str {
        &self.id
    }

    pub fn payload(&self) -> &T {
        &self.payload
    }

    pub fn attempt(&self) -> u32 {
        self.attempt
    }

    /// 重试前由调度器调用，执行次数 +1。
    pub fn increment_attempt(&mut self) {
        self.attempt += 1
    }
}

/// Handler 返回的带语义错误：先区分临时失败与永久失败，再决定重试策略。
pub enum TaskError {
    /// 临时失败（连接失败、503、临时限流）→ 延迟后重试。
    Retryable(String),
    /// 永久失败（参数不合法、权限不足）→ 直接进死信。
    Permanent(String),
}

/// 业务处理器通过该 trait 接入队列。队列只关心执行结果，不关心具体业务。
#[async_trait::async_trait]
pub trait TaskHandler<T>: Send + Sync + 'static
where
    T: Send + Sync + 'static,
{
    async fn handle(&self, task: &Task<T>) -> Result<(), TaskError>;
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use tokio::sync::Semaphore;

    #[tokio::test]
    async fn task_holds_id_payload_and_attempt() {
        let sem = Arc::new(Semaphore::new(1));
        let permit = sem.clone().acquire_owned().await.unwrap();

        let mut task = Task::new("welcome-alice", "payload", permit);

        assert_eq!(task.id(), "welcome-alice");
        assert_eq!(task.payload(), &"payload");
        assert_eq!(task.attempt(), 1);

        task.increment_attempt();
        assert_eq!(task.attempt(), 2);
    }
}
