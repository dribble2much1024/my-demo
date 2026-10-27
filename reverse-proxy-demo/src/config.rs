//! 命令行配置解析。
//!
//! 代理用法：
//!   reverse-proxy-demo <监听地址> <后端1> [后端2 ...]
//!   reverse-proxy-demo 127.0.0.1:8080 http://127.0.0.1:3001 http://127.0.0.1:3002

use std::time::Duration;

use url::Url;

/// 代理运行配置。
#[derive(Debug, Clone)]
pub struct Config {
    /// 监听地址，如 `127.0.0.1:8080`。
    pub listen: String,
    /// 上游后端 URL 列表（顺序即初始轮询顺序）。
    pub backends: Vec<Url>,
    /// 单次请求体上限（字节），超过返回 413。默认 16 MiB。
    pub max_request_body: usize,
    /// 上游连接/请求超时。
    pub upstream_timeout: Duration,
    /// 主动健康检查间隔。
    pub health_interval: Duration,
    /// 主动健康检查单次超时。
    pub health_timeout: Duration,
    /// 健康检查路径。
    pub health_path: String,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            listen: String::new(),
            backends: Vec::new(),
            max_request_body: 16 * 1024 * 1024,
            upstream_timeout: Duration::from_secs(10),
            health_interval: Duration::from_secs(5),
            health_timeout: Duration::from_secs(2),
            health_path: "/health".to_string(),
        }
    }
}

impl Config {
    /// 从命令行参数解析配置。
    ///
    /// 位置参数：`<监听地址> <后端1> [后端2 ...]`，后端必须能解析为 `Url`。
    pub fn from_args(args: Vec<String>) -> anyhow::Result<Self> {
        let mut config = Config::default();

        if args.len() < 2 {
            anyhow::bail!("用法: reverse-proxy-demo <监听地址> <后端1> [后端2 ...]");
        }

        config.listen = args[0].clone();

        for raw in &args[1..] {
            let url = Url::parse(raw).map_err(|e| anyhow::anyhow!("无效的后端地址 `{raw}`: {e}"))?;
            config.backends.push(url);
        }

        Ok(config)
    }
}
