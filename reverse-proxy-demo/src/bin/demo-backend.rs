//! 演示后端：返回自身名字与收到的 path/query，用于观察轮询与故障转移。
//!
//! 用法: demo-backend <监听地址> <名字>
//! 例如: demo-backend 127.0.0.1:3001 one

use axum::extract::State;
use axum::http::{StatusCode, Uri};
use axum::routing::get;
use axum::Router;

#[derive(Clone)]
struct BackendInfo {
    name: String,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() < 2 {
        anyhow::bail!("用法: demo-backend <监听地址> <名字>");
    }
    let addr = args[0].clone();
    let name = args[1].clone();

    let state = BackendInfo { name: name.clone() };

    let app = Router::new()
        .route("/health", get(health))
        .fallback(echo)
        .with_state(state);

    let listener = tokio::net::TcpListener::bind(&addr).await?;
    println!("backend [{name}] listening on {addr}");
    axum::serve(listener, app).await?;
    Ok(())
}

async fn health() -> StatusCode {
    StatusCode::OK
}

async fn echo(State(info): State<BackendInfo>, uri: Uri) -> String {
    let path = uri.path_and_query().map(|p| p.as_str()).unwrap_or("/");
    format!("backend={} path={}\n", info.name, path)
}
