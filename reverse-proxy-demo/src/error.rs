//! 代理错误类型，以及向 Axum 响应的转换。

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};

/// 代理处理过程中可能出现的错误。
#[derive(Debug, thiserror::Error)]
pub enum ProxyError {
    /// 选择候选节点前，已经没有任何健康节点可用。对应 503。
    #[error("no healthy backend available")]
    NoHealthyBackend,

    /// 存在候选节点，但实际访问上游全部失败。对应 502。
    #[error("upstream request failed: {0}")]
    Upstream(#[from] reqwest::Error),

    /// 请求体超过配置上限。对应 413。
    #[error("request body too large")]
    PayloadTooLarge,

    /// 目标 URL 无法合成（后端基础地址 + path/query 拼接失败）。对应 502。
    #[error("failed to build target url: {0}")]
    BadTarget(String),
}

impl IntoResponse for ProxyError {
    fn into_response(self) -> Response {
        let status = match &self {
            ProxyError::NoHealthyBackend => StatusCode::SERVICE_UNAVAILABLE, // 503
            ProxyError::PayloadTooLarge => StatusCode::PAYLOAD_TOO_LARGE,    // 413
            ProxyError::Upstream(_) | ProxyError::BadTarget(_) => {
                StatusCode::BAD_GATEWAY // 502
            }
        };
        (status, self.to_string()).into_response()
    }
}
