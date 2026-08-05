// src/db.rs
use sqlx::sqlite::{SqlitePool, SqlitePoolOptions};
use std::path::Path;

pub type DbPool = SqlitePool;

pub async fn init_pool() -> DbPool {
    let db_path = "data/prediction-market.db";
    if let Some(parent) = Path::new(db_path).parent() {
        std::fs::create_dir_all(parent).ok();
    }
    SqlitePoolOptions::new()
        .max_connections(5)
        .connect(&format!("sqlite:{}?mode=rwc", db_path))
        .await
        .expect("Failed to create DB pool")
}

pub async fn run_migrations(pool: &DbPool) {
    let sql = include_str!("../migrations/001_init.sql");
    sqlx::query(sql)
        .execute(pool)
        .await
        .expect("Failed to run migrations");
}
