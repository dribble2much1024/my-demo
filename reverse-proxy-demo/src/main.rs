//! 反向代理入口：解析参数、初始化日志、启动服务并优雅关闭。

use reverse_proxy_demo::{build_router, config::Config, health, state::ProxyState};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // 初始化日志：可通过 RUST_LOG 环境变量控制级别。
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    let args: Vec<String> = std::env::args().skip(1).collect();
    let config = Config::from_args(args)?;
    let state = ProxyState::new(&config)?;

    // 启动主动健康检查后台任务（服务退出后 abort，避免残留）。
    let health_task = health::spawn_health_check(state.clone());
    let app = build_router(state.clone());

    let listener = tokio::net::TcpListener::bind(&config.listen).await?;
    tracing::info!("proxy listening on {}", config.listen);

    // 优雅关闭：收到 Ctrl-C 后停止 accept，让已有连接完成请求。
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await?;

    health_task.abort();
    Ok(())
}

async fn shutdown_signal() {
    let _ = tokio::signal::ctrl_c().await;
    tracing::info!("shutdown signal received, draining connections...");
}
