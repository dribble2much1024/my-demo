//! 提交任务可能失败的显式错误类型。

use std::fmt;

/// 向线程池提交任务时的失败原因。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PoolError {
    /// 池已关闭（所有 sender 都已被丢弃 / 接收端已消失），无法再提交。
    PoolClosed,
}

impl fmt::Display for PoolError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            PoolError::PoolClosed => write!(f, "thread pool is closed"),
        }
    }
}

impl std::error::Error for PoolError {}
