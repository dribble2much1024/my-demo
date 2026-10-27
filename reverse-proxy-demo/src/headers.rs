//! HTTP 语义处理：逐跳 Header 过滤，以及 X-Forwarded-* 注入。

use http::{HeaderMap, HeaderName, HeaderValue};

/// 标准逐跳 Header（RFC 7230 §6.1）。这些字段只描述当前这一跳连接，
/// 不能原样转发给上游。
pub const HOP_BY_HOP_HEADERS: &[&str] = &[
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
];

/// 从 HeaderMap 中删除所有逐跳 Header。
///
/// 除了标准列表，`Connection` 的值里还可以用逗号分隔声明额外的逐跳字段
/// （例如 `Connection: X-Internal`），这些字段名也需要一并删除。
pub fn strip_hop_by_hop(headers: &mut HeaderMap) {
    // 先收集 Connection 声明出的自定义逐跳字段名，再统一删除。
    let mut extra: Vec<HeaderName> = Vec::new();
    if let Some(connection) = headers.get("connection") {
        if let Ok(value) = connection.to_str() {
            for name in value.split(',') {
                let name = name.trim();
                if !name.is_empty() {
                    // 名字可能是非法 HeaderName，忽略解析失败的项。
                    if let Ok(header_name) = HeaderName::from_bytes(name.as_bytes()) {
                        extra.push(header_name);
                    }
                }
            }
        }
    }

    // 删除标准逐跳字段。
    for name in HOP_BY_HOP_HEADERS {
        headers.remove(*name);
    }
    // 删除 Connection 里声明的自定义逐跳字段。
    for name in extra {
        headers.remove(name);
    }
}

/// 注入转发相关 Header，让后端仍能得知原始外部请求信息。
///
/// - `X-Forwarded-Host`: 客户端原始 Host（即代理地址）
/// - `X-Forwarded-Proto`: 外部请求协议（本 demo 恒为 `http`）
pub fn inject_forwarded_headers(headers: &mut HeaderMap, original_host: Option<&str>) {
    if let Some(host) = original_host {
        if let Ok(value) = HeaderValue::from_str(host) {
            headers.insert("x-forwarded-host", value);
        }
    }
    headers.insert("x-forwarded-proto", HeaderValue::from_static("http"));
}
