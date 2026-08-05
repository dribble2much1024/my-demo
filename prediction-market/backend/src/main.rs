// src/main.rs
mod api;
mod db;
mod event;
mod matching;
mod settlement;

use axum::Router;
use std::net::SocketAddr;
use tower_http::cors::{Any, CorsLayer};

#[derive(Clone)]
pub struct AppState {
    pub db: db::DbPool,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::init();

    let pool = db::init_pool().await;
    db::run_migrations(&pool).await;

    let state = AppState { db: pool };

    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    let app = Router::new()
        .merge(api::routes::router())
        .layer(cors)
        .with_state(state);

    let addr = SocketAddr::from(([127, 0, 0, 1], 3000));
    tracing::info!("listening on {}", addr);
    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
