# Prediction Market Core Trading Demo - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a prediction market demo with YES/NO order book trading, real-time WebSocket updates, matching engine with mirror matching, and simulated settlement.

**Architecture:** Monorepo with `backend/` (Rust/Axum + SQLite) and `frontend/` (React/Vite/TypeScript). REST API for CRUD operations, WebSocket for real-time order book and trade push. Backend crates: api-server binary, matching-engine lib, event-pool lib, settlement lib.

**Tech Stack:** Rust 1.80+, Axum 0.7, Tokio, sqlx 0.7 (SQLite), serde, React 18, Vite 5, TypeScript 5, React Router 6, Recharts

## Global Constraints

- All prices in cents (u64, 0-100) internally to avoid floating point
- YES + NO price = 100 cents (1.00 USD) always maintained
- User auth mocked: `X-User-Id: 1` header on all requests
- WebSocket messages are JSON with `{ "type": "...", "data": {...} }` envelope
- Startup seeds 5 demo events with categories: sports, crypto, weather, politics, esports
- Each new user gets 100,000 cents (1000.00 USD) demo balance

---

### Task 1: Rust project scaffold and database setup

**Files:**
- Create: `prediction-market/backend/Cargo.toml`
- Create: `prediction-market/backend/src/main.rs`
- Create: `prediction-market/backend/src/db.rs`
- Create: `prediction-market/backend/migrations/001_init.sql`

**Interfaces:**
- Produces: `DbPool` type alias, `run_migrations(pool: &DbPool)` function
- Produces: `AppState { db: DbPool }` struct

- [ ] **Step 1: Create Cargo.toml**

```toml
[package]
name = "prediction-market"
version = "0.1.0"
edition = "2021"

[dependencies]
axum = { version = "0.7", features = ["ws"] }
tokio = { version = "1", features = ["full"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
sqlx = { version = "0.7", features = ["runtime-tokio-rustls", "sqlite", "chrono"] }
chrono = { version = "0.4", features = ["serde"] }
tower-http = { version = "0.5", features = ["cors"] }
tracing = "0.1"
tracing-subscriber = "0.3"
uuid = { version = "1", features = ["v4"] }
```

- [ ] **Step 2: Create database migration**

```sql
-- migrations/001_init.sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    balance INTEGER NOT NULL DEFAULT 100000,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'general',
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','settled')),
    result TEXT CHECK(result IN ('yes','no')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    event_id INTEGER NOT NULL REFERENCES events(id),
    side TEXT NOT NULL CHECK(side IN ('yes','no')),
    order_type TEXT NOT NULL CHECK(order_type IN ('market','limit')),
    price INTEGER NOT NULL CHECK(price >= 0 AND price <= 100),
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    filled_qty INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','partial','filled','canceled')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id),
    buy_user_id INTEGER NOT NULL REFERENCES users(id),
    sell_user_id INTEGER NOT NULL REFERENCES users(id),
    side TEXT NOT NULL CHECK(side IN ('yes','no')),
    price INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    event_id INTEGER NOT NULL REFERENCES events(id),
    side TEXT NOT NULL CHECK(side IN ('yes','no')),
    quantity INTEGER NOT NULL DEFAULT 0,
    avg_price INTEGER NOT NULL DEFAULT 0,
    realized_pnl INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, event_id, side)
);

-- Seed demo user
INSERT OR IGNORE INTO users (id, username, balance) VALUES (1, 'demo', 100000);
```

- [ ] **Step 3: Create db.rs**

```rust
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
```

- [ ] **Step 4: Create main.rs skeleton**

```rust
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
```

- [ ] **Step 5: Verify it compiles and starts**

```bash
cd prediction-market/backend && cargo check
```

Expected: compilation succeeds (warnings about unused modules ok).

- [ ] **Step 6: Commit**

```bash
git add prediction-market/backend/
git commit -m "feat: scaffold Rust backend with SQLite and Axum skeleton"
```

---

### Task 2: Event pool module - models and seed data

**Files:**
- Create: `prediction-market/backend/src/event/mod.rs`
- Create: `prediction-market/backend/src/event/models.rs`
- Create: `prediction-market/backend/src/event/pool.rs`

**Interfaces:**
- Produces: `Event { id, title, description, category, status, result, created_at }` struct
- Produces: `EventPool::list(pool, category, status) -> Vec<Event>`
- Produces: `EventPool::get(pool, id) -> Option<Event>`
- Produces: `EventPool::seed(pool)` - inserts 5 demo events if table is empty

- [ ] **Step 1: Create event models**

```rust
// src/event/models.rs
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct Event {
    pub id: i64,
    pub title: String,
    pub description: String,
    pub category: String,
    pub status: String,
    pub result: Option<String>,
    pub created_at: String,
}

#[derive(Debug, Deserialize)]
pub struct EventFilter {
    pub category: Option<String>,
    pub status: Option<String>,
}
```

- [ ] **Step 2: Create event mod.rs**

```rust
// src/event/mod.rs
pub mod models;
pub mod pool;
```

- [ ] **Step 3: Create event pool with seed data**

```rust
// src/event/pool.rs
use crate::db::DbPool;
use super::models::{Event, EventFilter};

pub struct EventPool;

impl EventPool {
    pub async fn list(pool: &DbPool, filter: EventFilter) -> Vec<Event> {
        let mut query = String::from("SELECT * FROM events WHERE 1=1");
        if filter.category.is_some() {
            query.push_str(" AND category = ?");
        }
        if filter.status.is_some() {
            query.push_str(" AND status = ?");
        }
        query.push_str(" ORDER BY created_at DESC");

        let mut q = sqlx::query_as::<_, Event>(&query);
        if let Some(ref cat) = filter.category {
            q = q.bind(cat);
        }
        if let Some(ref st) = filter.status {
            q = q.bind(st);
        }
        q.fetch_all(pool).await.unwrap_or_default()
    }

    pub async fn get(pool: &DbPool, id: i64) -> Option<Event> {
        sqlx::query_as::<_, Event>("SELECT * FROM events WHERE id = ?")
            .bind(id)
            .fetch_optional(pool)
            .await
            .unwrap_or(None)
    }

    pub async fn seed(pool: &DbPool) {
        let count: (i64,) = sqlx::query_as("SELECT COUNT(*) FROM events")
            .fetch_one(pool)
            .await
            .unwrap_or((0,));
        if count.0 > 0 {
            return;
        }
        let events = vec![
            ("BTC突破100K美元", "比特币在2026年12月31日前是否突破100,000美元？", "crypto"),
            ("湖人队赢得NBA总冠军", "洛杉矶湖人队在2026-27赛季是否赢得NBA总冠军？", "sports"),
            ("明天纽约下雨", "2026年7月7日纽约市是否有可测量的降雨？", "weather"),
            ("美国总统大选结果", "2028年美国总统大选是否由现任政党候选人获胜？", "politics"),
            ("LOL世界赛冠军", "2026年英雄联盟全球总决赛是否由LCK赛区队伍夺冠？", "esports"),
        ];
        for (title, desc, cat) in events {
            sqlx::query("INSERT INTO events (title, description, category) VALUES (?, ?, ?)")
                .bind(title)
                .bind(desc)
                .bind(cat)
                .execute(pool)
                .await
                .ok();
        }
    }

    pub async fn set_result(pool: &DbPool, id: i64, result: &str) {
        sqlx::query("UPDATE events SET result = ?, status = 'settled' WHERE id = ?")
            .bind(result)
            .bind(id)
            .execute(pool)
            .await
            .ok();
    }
}
```

- [ ] **Step 4: Verify compiles**

```bash
cd prediction-market/backend && cargo check
```

Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add prediction-market/backend/src/event/
git commit -m "feat: add event pool module with models and seed data"
```

---

### Task 3: Matching engine - order book and mirror matching

**Files:**
- Create: `prediction-market/backend/src/matching/mod.rs`
- Create: `prediction-market/backend/src/matching/orderbook.rs`
- Create: `prediction-market/backend/src/matching/engine.rs`
- Create: `prediction-market/backend/src/matching/mirror.rs`

**Interfaces:**
- Produces: `OrderBook { bids: BTreeMap<u64, u64>, asks: BTreeMap<u64, u64> }` - price -> total_qty
- Produces: `MatchingEngine::new(event_id)` struct
- Produces: `MatchingEngine::place_limit(pool, user_id, side, price, qty) -> Vec<Trade>`
- Produces: `MatchingEngine::place_market(pool, user_id, side, qty) -> Vec<Trade>`
- Produces: `MatchingEngine::cancel(pool, order_id, user_id) -> bool`
- Produces: `MatchingEngine::get_orderbook(pool) -> (OrderBook, OrderBook)` - (yes_book, no_book)
- Produces: `mirror::mirror_price(price, side) -> (u64, &str)` - converts YES buy price to NO sell price

- [ ] **Step 1: Create matching mod.rs**

```rust
// src/matching/mod.rs
pub mod orderbook;
pub mod engine;
pub mod mirror;
```

- [ ] **Step 2: Create orderbook.rs**

```rust
// src/matching/orderbook.rs
use serde::Serialize;
use std::collections::BTreeMap;

#[derive(Debug, Clone, Serialize, Default)]
pub struct OrderBook {
    /// price -> total quantity (bids: highest first via rev iteration)
    pub bids: BTreeMap<u64, u64>,
    /// price -> total quantity (asks: lowest first via natural iteration)
    pub asks: BTreeMap<u64, u64>,
}

impl OrderBook {
    pub fn new() -> Self {
        Self { bids: BTreeMap::new(), asks: BTreeMap::new() }
    }

    pub fn add_bid(&mut self, price: u64, qty: u64) {
        *self.bids.entry(price).or_insert(0) += qty;
    }

    pub fn add_ask(&mut self, price: u64, qty: u64) {
        *self.asks.entry(price).or_insert(0) += qty;
    }

    pub fn remove_bid(&mut self, price: u64, qty: u64) {
        if let Some(v) = self.bids.get_mut(&price) {
            if *v <= qty { self.bids.remove(&price); }
            else { *v -= qty; }
        }
    }

    pub fn remove_ask(&mut self, price: u64, qty: u64) {
        if let Some(v) = self.asks.get_mut(&price) {
            if *v <= qty { self.asks.remove(&price); }
            else { *v -= qty; }
        }
    }

    pub fn best_bid(&self) -> Option<u64> {
        self.bids.keys().next_back().copied()
    }

    pub fn best_ask(&self) -> Option<u64> {
        self.asks.keys().next().copied()
    }
}
```

- [ ] **Step 3: Create mirror.rs**

```rust
// src/matching/mirror.rs

/// Convert a YES-side operation to its NO-side equivalent.
/// Buying YES @ 63c = selling NO @ 37c (since YES + NO = 100)
/// Selling YES @ 63c = buying NO @ 37c
pub fn mirror_price(price: u64) -> u64 {
    if price > 100 { 0 } else { 100 - price }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_mirror_buy_yes() {
        // Buy YES @ 63 = Sell NO @ 37
        assert_eq!(mirror_price(63), 37);
    }

    #[test]
    fn test_mirror_at_extremes() {
        assert_eq!(mirror_price(0), 100);
        assert_eq!(mirror_price(100), 0);
    }

    #[test]
    fn test_mirror_above_100_returns_0() {
        assert_eq!(mirror_price(101), 0);
    }
}
```

- [ ] **Step 4: Create matching engine**

```rust
// src/matching/engine.rs
use crate::db::DbPool;
use super::orderbook::OrderBook;
use super::mirror;

#[derive(Debug, Clone)]
pub struct Trade {
    pub buy_user_id: i64,
    pub sell_user_id: i64,
    pub side: String,   // which side was "taken" (the aggressive order's side)
    pub price: u64,
    pub quantity: u64,
}

pub struct MatchingEngine {
    pub event_id: i64,
}

impl MatchingEngine {
    pub fn new(event_id: i64) -> Self {
        Self { event_id }
    }

    /// Build YES order book from open limit orders
    pub async fn get_yes_orderbook(&self, pool: &DbPool) -> OrderBook {
        let mut book = OrderBook::new();
        let rows = sqlx::query_as::<_, OrderRow>(
            "SELECT side, order_type, price, quantity - filled_qty as remaining FROM orders WHERE event_id = ? AND status IN ('open','partial') AND side = 'yes' ORDER BY price"
        )
        .bind(self.event_id)
        .fetch_all(pool).await.unwrap_or_default();

        for r in rows {
            if r.remaining > 0 {
                book.add_ask(r.price, r.remaining);
            }
        }
        book
    }

    /// Build NO order book from open limit orders
    pub async fn get_no_orderbook(&self, pool: &DbPool) -> OrderBook {
        let mut book = OrderBook::new();
        let rows = sqlx::query_as::<_, OrderRow>(
            "SELECT side, order_type, price, quantity - filled_qty as remaining FROM orders WHERE event_id = ? AND status IN ('open','partial') AND side = 'no' ORDER BY price"
        )
        .bind(self.event_id)
        .fetch_all(pool).await.unwrap_or_default();

        for r in rows {
            if r.remaining > 0 {
                book.add_ask(r.price, r.remaining);
            }
        }
        book
    }

    /// Place a limit order. Returns list of trades from matching.
    pub async fn place_limit(
        &self, pool: &DbPool, user_id: i64, side: &str,
        price: u64, quantity: u64,
    ) -> Vec<Trade> {
        // Insert the order
        let order_id: i64 = sqlx::query_scalar(
            "INSERT INTO orders (user_id, event_id, side, order_type, price, quantity) VALUES (?, ?, ?, 'limit', ?, ?) RETURNING id"
        )
        .bind(user_id).bind(self.event_id).bind(side).bind(price as i64).bind(quantity as i64)
        .fetch_one(pool).await.unwrap();

        let trades = self.match_order(pool, order_id, user_id, side, price, quantity).await;
        trades
    }

    /// Place a market order — matches immediately at best available prices
    pub async fn place_market(
        &self, pool: &DbPool, user_id: i64, side: &str, quantity: u64,
    ) -> Vec<Trade> {
        // Market buy: use price=100 (worst acceptable), market sell: use price=0
        let price = if side == "yes" { 100u64 } else { 100u64 }; // 100 = buy at any ask
        // Actually for market sell, trigger trades against bids
        let order_id: i64 = sqlx::query_scalar(
            "INSERT INTO orders (user_id, event_id, side, order_type, price, quantity) VALUES (?, ?, ?, 'market', ?, ?) RETURNING id"
        )
        .bind(user_id).bind(self.event_id).bind(side).bind(price as i64).bind(quantity as i64)
        .fetch_one(pool).await.unwrap();

        let trades = self.match_order(pool, order_id, user_id, side, price, quantity).await;
        // Market order: mark any remaining as filled (no liquidity)
        sqlx::query("UPDATE orders SET status = 'filled' WHERE id = ? AND status IN ('open','partial')")
            .bind(order_id).execute(pool).await.ok();
        trades
    }

    /// Core matching: try to cross the aggressive order against the opposite side
    async fn match_order(
        &self, pool: &DbPool, order_id: i64, user_id: i64, side: &str,
        price: u64, mut remaining: u64,
    ) -> Vec<Trade> {
        let mut trades = Vec::new();
        let opp_side = if side == "yes" { "no" } else { "yes" };

        // Get resting orders on opposite side, ordered by price (best first)
        let resting = if opp_side == "no" {
            // Buying YES: match against lowest NO asks (= highest YES price via mirror)
            sqlx::query_as::<_, RestingOrder>(
                "SELECT id, user_id, price, quantity - filled_qty as remaining FROM orders WHERE event_id = ? AND side = 'no' AND status IN ('open','partial') ORDER BY price ASC"
            )
            .bind(self.event_id).fetch_all(pool).await.unwrap_or_default()
        } else {
            // Buying NO: match against lowest YES asks
            sqlx::query_as::<_, RestingOrder>(
                "SELECT id, user_id, price, quantity - filled_qty as remaining FROM orders WHERE event_id = ? AND side = 'yes' AND status IN ('open','partial') ORDER BY price ASC"
            )
            .bind(self.event_id).fetch_all(pool).await.unwrap_or_default()
        };

        for r in resting {
            if remaining == 0 { break; }
            // Cross when aggressive price + resting price >= 100 (mirror relationship)
            if !cross { continue; }

            let trade_price = 100 - r.price; // effective YES price
            let fill_qty = remaining.min(r.remaining);

            // Record trade
            trades.push(Trade {
                buy_user_id: if side == "yes" { user_id } else { r.user_id },
                sell_user_id: if side == "yes" { r.user_id } else { user_id },
                side: side.to_string(),
                price: trade_price,
                quantity: fill_qty,
            });

            // Update resting order
            let new_filled: i64 = sqlx::query_scalar("SELECT filled_qty FROM orders WHERE id = ?")
                .bind(r.id).fetch_one(pool).await.unwrap();
            let total_filled = new_filled as u64 + fill_qty;
            let total_qty: i64 = sqlx::query_scalar("SELECT quantity FROM orders WHERE id = ?")
                .bind(r.id).fetch_one(pool).await.unwrap();
            let new_status = if total_filled >= total_qty as u64 { "filled" } else { "partial" };
            sqlx::query("UPDATE orders SET filled_qty = ?, status = ? WHERE id = ?")
                .bind(total_filled as i64).bind(new_status).bind(r.id)
                .execute(pool).await.ok();

            // Update aggressive order filled quantity
            sqlx::query("UPDATE orders SET filled_qty = filled_qty + ?, status = CASE WHEN filled_qty >= quantity THEN 'filled' ELSE 'partial' END WHERE id = ?")
                .bind(fill_qty as i64).bind(order_id)
                .execute(pool).await.ok();

            // Update positions for both sides
            self.update_position(pool, user_id, side, trade_price, fill_qty, true).await;
            self.update_position(pool, r.user_id, opp_side, trade_price, fill_qty, false).await;

            remaining -= fill_qty;
        }
        trades
    }

    async fn update_position(&self, pool: &DbPool, user_id: i64, side: &str, price: u64, qty: u64, is_buy: bool) {
        // Upsert position
        if is_buy {
            // Buyer gets shares
            sqlx::query(
                "INSERT INTO positions (user_id, event_id, side, quantity, avg_price) VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id, event_id, side) DO UPDATE SET quantity = quantity + ?, avg_price = ((avg_price * quantity) + (? * ?)) / (quantity + ?)"
            )
            .bind(user_id).bind(self.event_id).bind(side).bind(qty as i64).bind(price as i64)
            .bind(qty as i64).bind(price as i64).bind(qty as i64).bind(qty as i64)
            .execute(pool).await.ok();
        } else {
            // Seller reduces shares
            sqlx::query(
                "UPDATE positions SET quantity = quantity - ? WHERE user_id = ? AND event_id = ? AND side = ?"
            )
            .bind(qty as i64).bind(user_id).bind(self.event_id).bind(side)
            .execute(pool).await.ok();
        }

        // Adjust balances for the buy side
        if is_buy {
            sqlx::query("UPDATE users SET balance = balance - ? WHERE id = ?")
                .bind((price * qty) as i64).bind(user_id)
                .execute(pool).await.ok();
        } else {
            sqlx::query("UPDATE users SET balance = balance + ? WHERE id = ?")
                .bind((price * qty) as i64).bind(user_id)
                .execute(pool).await.ok();
        }
    }

    /// Cancel an open order
    pub async fn cancel(&self, pool: &DbPool, order_id: i64, user_id: i64) -> bool {
        let result = sqlx::query("UPDATE orders SET status = 'canceled' WHERE id = ? AND user_id = ? AND status IN ('open','partial')")
            .bind(order_id).bind(user_id)
            .execute(pool).await;
        result.map(|r| r.rows_affected() > 0).unwrap_or(false)
    }
}

#[derive(sqlx::FromRow)]
struct OrderRow {
    #[allow(dead_code)]
    side: String,
    #[allow(dead_code)]
    order_type: String,
    price: i64,
    remaining: i64,
}

#[derive(sqlx::FromRow)]
struct RestingOrder {
    id: i64,
    user_id: i64,
    price: i64,
    remaining: i64,
}
```

- [ ] **Step 5: Verify compiles**

```bash
cd prediction-market/backend && cargo check
```

Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add prediction-market/backend/src/matching/
git commit -m "feat: add matching engine with order book and mirror matching"
```

---

### Task 4: Settlement engine

**Files:**
- Create: `prediction-market/backend/src/settlement/mod.rs`
- Create: `prediction-market/backend/src/settlement/engine.rs`

**Interfaces:**
- Produces: `SettlementEngine::settle(pool, event_id, result) -> SettlementResult { total_payout, winners_count }`

- [ ] **Step 1: Create settlement mod.rs**

```rust
// src/settlement/mod.rs
pub mod engine;
```

- [ ] **Step 2: Create settlement engine**

```rust
// src/settlement/engine.rs
use crate::db::DbPool;
use crate::event::pool::EventPool;

pub struct SettlementResult {
    pub total_payout: u64,
    pub winners_count: usize,
}

pub struct SettlementEngine;

impl SettlementEngine {
    pub async fn settle(pool: &DbPool, event_id: i64, result: &str) -> SettlementResult {
        EventPool::set_result(pool, event_id, result).await;

        let winning_side = result;
        let losing_side = if result == "yes" { "no" } else { "yes" };

        // Find winning positions
        let winners: Vec<(i64, i64)> = sqlx::query_as(
            "SELECT user_id, quantity FROM positions WHERE event_id = ? AND side = ? AND quantity > 0"
        )
        .bind(event_id).bind(winning_side)
        .fetch_all(pool).await.unwrap_or_default();

        let total_payout: u64 = winners.iter().map(|(_, q)| *q as u64 * 100).sum();
        let winners_count = winners.len();

        // Payout winners: 100 cents per share
        for (user_id, qty) in &winners {
            sqlx::query("UPDATE users SET balance = balance + ? WHERE id = ?")
                .bind((qty * 100) as i64).bind(user_id)
                .execute(pool).await.ok();
        }

        // Zero out winning positions (they got paid)
        sqlx::query("UPDATE positions SET quantity = 0, realized_pnl = realized_pnl + quantity * 100 WHERE event_id = ? AND side = ?")
            .bind(event_id).bind(winning_side)
            .execute(pool).await.ok();

        // Zero out losing positions
        sqlx::query("UPDATE positions SET quantity = 0 WHERE event_id = ? AND side = ?")
            .bind(event_id).bind(losing_side)
            .execute(pool).await.ok();

        SettlementResult { total_payout, winners_count }
    }
}
```

- [ ] **Step 3: Verify compiles**

```bash
cd prediction-market/backend && cargo check
```

Expected: OK.

- [ ] **Step 4: Commit**

```bash
git add prediction-market/backend/src/settlement/
git commit -m "feat: add settlement engine"
```

---

### Task 5: API routes - REST endpoints

**Files:**
- Create: `prediction-market/backend/src/api/mod.rs`
- Create: `prediction-market/backend/src/api/routes.rs`
- Create: `prediction-market/backend/src/api/ws.rs`
- Create: `prediction-market/backend/src/auth.rs`

**Interfaces:**
- Consumes: `AppState`, `MatchingEngine`, `EventPool`, `SettlementEngine`
- Produces: `router() -> Router<AppState>` with all REST + WS routes

- [ ] **Step 1: Create auth.rs**

```rust
// src/auth.rs
use axum::{http::HeaderMap, extract};

/// Extract user_id from X-User-Id header, default to 1 (demo user)
pub fn get_user_id(headers: &HeaderMap) -> i64 {
    headers
        .get("X-User-Id")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.parse::<i64>().ok())
        .unwrap_or(1)
}
```

- [ ] **Step 2: Create api/mod.rs**

```rust
// src/api/mod.rs
pub mod routes;
pub mod ws;
```

- [ ] **Step 3: Create routes.rs with all REST endpoints**

```rust
// src/api/routes.rs
use axum::{
    extract::{Path, Query, State},
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    routing::{delete, get, post},
    Json, Router,
};
use serde::{Deserialize, Serialize};
use crate::{
    api::ws,
    auth, db::DbPool,
    event::{
        models::EventFilter,
        pool::EventPool,
    },
    matching::engine::MatchingEngine,
    settlement::engine::SettlementEngine,
    AppState,
};

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/api/events", get(list_events))
        .route("/api/events/:id", get(get_event))
        .route("/api/events/:id/orderbook", get(get_orderbook))
        .route("/api/orders", post(place_order))
        .route("/api/orders/:id", delete(cancel_order))
        .route("/api/positions", get(get_positions))
        .route("/api/trades", get(get_trades))
        .route("/api/whoami", get(whoami))
        .route("/api/settle/:id", post(settle_event))
        .route("/ws/orderbook/:event_id", get(ws::ws_handler))
}

// --- Request/Response types ---

#[derive(Deserialize)]
struct PlaceOrderReq {
    event_id: i64,
    side: String,
    #[serde(default)]
    order_type: String, // "limit" or "market"
    price: Option<u64>,
    quantity: u64,
}

#[derive(Serialize, sqlx::FromRow)]
struct PositionRow {
    id: i64,
    user_id: i64,
    event_id: i64,
    side: String,
    quantity: i64,
    avg_price: i64,
    realized_pnl: i64,
    created_at: String,
    #[sqlx(default)]
    event_title: Option<String>,
}

#[derive(Serialize, sqlx::FromRow)]
struct TradeRow {
    id: i64,
    event_id: i64,
    buy_user_id: i64,
    sell_user_id: i64,
    side: String,
    price: i64,
    quantity: i64,
    created_at: String,
}

#[derive(Serialize, sqlx::FromRow)]
struct UserRow {
    id: i64,
    username: String,
    balance: i64,
    created_at: String,
}

// --- Handlers ---

async fn list_events(
    State(state): State<AppState>,
    Query(filter): Query<EventFilter>,
) -> impl IntoResponse {
    let events = EventPool::list(&state.db, filter).await;
    Json(events)
}

async fn get_event(
    State(state): State<AppState>,
    Path(id): Path<i64>,
) -> impl IntoResponse {
    match EventPool::get(&state.db, id).await {
        Some(event) => Json(serde_json::json!({ "event": event })).into_response(),
        None => (StatusCode::NOT_FOUND, "not found").into_response(),
    }
}

async fn get_orderbook(
    State(state): State<AppState>,
    Path(id): Path<i64>,
) -> impl IntoResponse {
    let engine = MatchingEngine::new(id);
    let yes_book = engine.get_yes_orderbook(&state.db).await;
    let no_book = engine.get_no_orderbook(&state.db).await;
    Json(serde_json::json!({
        "yes": { "bids": yes_book.bids, "asks": yes_book.asks },
        "no": { "bids": no_book.bids, "asks": no_book.asks }
    }))
}

async fn place_order(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<PlaceOrderReq>,
) -> impl IntoResponse {
    let user_id = auth::get_user_id(&headers);
    let engine = MatchingEngine::new(req.event_id);

    let trades = match req.order_type.as_str() {
        "market" => engine.place_market(&state.db, user_id, &req.side, req.quantity).await,
        _ => {
            let price = req.price.unwrap_or(50);
            engine.place_limit(&state.db, user_id, &req.side, price, req.quantity).await
        }
    };

    // Persist trades to DB
    for t in &trades {
        sqlx::query("INSERT INTO trades (event_id, buy_user_id, sell_user_id, side, price, quantity) VALUES (?, ?, ?, ?, ?, ?)")
            .bind(req.event_id).bind(t.buy_user_id).bind(t.sell_user_id).bind(&t.side).bind(t.price as i64).bind(t.quantity as i64)
            .execute(&state.db).await.ok();
    }

    Json(serde_json::json!({
        "trades": trades.iter().map(|t| serde_json::json!({
            "price": t.price,
            "quantity": t.quantity,
            "side": t.side,
        })).collect::<Vec<_>>()
    }))
}

async fn cancel_order(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(id): Path<i64>,
) -> impl IntoResponse {
    let user_id = auth::get_user_id(&headers);
    // We need event_id for the engine, so fetch it
    let event_id: Option<(i64,)> = sqlx::query_as("SELECT event_id FROM orders WHERE id = ?")
        .bind(id).fetch_optional(&state.db).await.unwrap_or(None);
    if let Some((event_id,)) = event_id {
        let engine = MatchingEngine::new(event_id);
        let ok = engine.cancel(&state.db, id, user_id).await;
        if ok {
            return (StatusCode::OK, "canceled").into_response();
        }
    }
    (StatusCode::NOT_FOUND, "not found or not yours").into_response()
}

async fn get_positions(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> impl IntoResponse {
    let user_id = auth::get_user_id(&headers);
    let positions = sqlx::query_as::<_, PositionRow>(
        "SELECT p.*, e.title as event_title FROM positions p LEFT JOIN events e ON p.event_id = e.id WHERE p.user_id = ? AND p.quantity > 0"
    )
    .bind(user_id)
    .fetch_all(&state.db).await.unwrap_or_default();
    Json(positions)
}

async fn get_trades(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> impl IntoResponse {
    let user_id = auth::get_user_id(&headers);
    let trades = sqlx::query_as::<_, TradeRow>(
        "SELECT * FROM trades WHERE buy_user_id = ? OR sell_user_id = ? ORDER BY created_at DESC LIMIT 50"
    )
    .bind(user_id).bind(user_id)
    .fetch_all(&state.db).await.unwrap_or_default();
    Json(trades)
}

async fn whoami(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> impl IntoResponse {
    let user_id = auth::get_user_id(&headers);
    let user = sqlx::query_as::<_, UserRow>("SELECT * FROM users WHERE id = ?")
        .bind(user_id)
        .fetch_one(&state.db).await;
    match user {
        Ok(u) => Json(u).into_response(),
        Err(_) => (StatusCode::NOT_FOUND, "user not found").into_response(),
    }
}

async fn settle_event(
    State(state): State<AppState>,
    Path(id): Path<i64>,
    Json(body): Json<serde_json::Value>,
) -> impl IntoResponse {
    let result = body.get("result").and_then(|v| v.as_str()).unwrap_or("yes");
    let settlement = SettlementEngine::settle(&state.db, id, result).await;
    Json(serde_json::json!({
        "total_payout": settlement.total_payout,
        "winners_count": settlement.winners_count,
        "result": result,
    }))
}
```

- [ ] **Step 4: Verify compiles**

```bash
cd prediction-market/backend && cargo check
```

Expected: OK (ws_handler not yet defined — that's fine, Task 6 adds it).

- [ ] **Step 5: Commit**

```bash
git add prediction-market/backend/src/api/ prediction-market/backend/src/auth.rs prediction-market/backend/src/main.rs
git commit -m "feat: add REST API routes for events, orders, positions, settlement"
```

---

### Task 6: WebSocket handler

**Files:**
- Create: `prediction-market/backend/src/api/ws.rs`

**Interfaces:**
- Consumes: `AppState`, `MatchingEngine`
- Produces: `ws_handler(ws: WebSocketUpgrade, State, Path) -> Response`

- [ ] **Step 1: Create ws.rs**

```rust
// src/api/ws.rs
use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        Path, State,
    },
    response::IntoResponse,
};
use futures::{sink::SinkExt, stream::StreamExt};
use std::time::Duration;
use crate::{matching::engine::MatchingEngine, AppState};

pub async fn ws_handler(
    ws: WebSocketUpgrade,
    State(state): State<AppState>,
    Path(event_id): Path<i64>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_socket(socket, state, event_id))
}

async fn handle_socket(socket: WebSocket, state: AppState, event_id: i64) {
    let (mut sender, mut receiver) = socket.split();
    let engine = MatchingEngine::new(event_id);

    // Send full snapshot on connect
    let yes_book = engine.get_yes_orderbook(&state.db).await;
    let no_book = engine.get_no_orderbook(&state.db).await;
    let snapshot = serde_json::json!({
        "type": "snapshot",
        "data": {
            "yes": { "bids": yes_book.bids, "asks": yes_book.asks },
            "no": { "bids": no_book.bids, "asks": no_book.asks }
        }
    });
    let _ = sender.send(Message::Text(snapshot.to_string().into())).await;

    // Push updates every 1 second (polling from DB for simplicity)
    let mut interval = tokio::time::interval(Duration::from_secs(1));
    let send_task = tokio::spawn(async move {
        loop {
            interval.tick().await;
            let yes_book = engine.get_yes_orderbook(&state.db).await;
            let no_book = engine.get_no_orderbook(&state.db).await;
            let update = serde_json::json!({
                "type": "update",
                "data": {
                    "yes": { "bids": yes_book.bids, "asks": yes_book.asks },
                    "no": { "bids": no_book.bids, "asks": no_book.asks },
                    "yes_best_bid": yes_book.best_bid(),
                    "yes_best_ask": yes_book.best_ask(),
                    "no_best_bid": no_book.best_bid(),
                    "no_best_ask": no_book.best_ask(),
                }
            });
            if sender.send(Message::Text(update.to_string().into())).await.is_err() {
                break;
            }
        }
    });

    // Keep connection alive, handle incoming pongs
    while let Some(Ok(msg)) = receiver.next().await {
        match msg {
            Message::Close(_) => break,
            _ => {}
        }
    }
    send_task.abort();
}
```

- [ ] **Step 2: Add futures dependency to Cargo.toml**

In `Cargo.toml`, add `futures = "0.3"` to dependencies.

- [ ] **Step 3: Verify compiles**

```bash
cd prediction-market/backend && cargo check
```

Expected: OK.

- [ ] **Step 4: Commit**

```bash
git add prediction-market/backend/src/api/ws.rs prediction-market/backend/Cargo.toml
git commit -m "feat: add WebSocket handler for real-time order book"
```

---

### Task 7: Frontend project scaffold

**Files:**
- Create: `prediction-market/frontend/package.json`
- Create: `prediction-market/frontend/tsconfig.json`
- Create: `prediction-market/frontend/vite.config.ts`
- Create: `prediction-market/frontend/index.html`
- Create: `prediction-market/frontend/src/main.tsx`
- Create: `prediction-market/frontend/src/App.tsx`
- Create: `prediction-market/frontend/src/types/index.ts`
- Create: `prediction-market/frontend/src/api/client.ts`

**Interfaces:**
- Produces: `Event`, `OrderBook`, `Position`, `Trade` TypeScript types
- Produces: `api.get<T>(path)` and `api.post<T>(path, body)` functions

- [ ] **Step 1: Create package.json**

```json
{
  "name": "prediction-market-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0",
    "recharts": "^2.12.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.3",
    "vite": "^5.4.0"
  }
}
```

- [ ] **Step 2: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": false,
    "noUnusedParameters": false,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"]
}
```

- [ ] **Step 3: Create vite.config.ts**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:3000',
      '/ws': { target: 'ws://127.0.0.1:3000', ws: true },
    },
  },
})
```

- [ ] **Step 4: Create index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>预测市场 - Prediction Market</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Create types/index.ts**

```typescript
export interface Event {
  id: number;
  title: string;
  description: string;
  category: string;
  status: string;
  result: string | null;
  created_at: string;
}

export interface OrderBookLevel {
  bids: Record<number, number>;
  asks: Record<number, number>;
}

export interface OrderBookData {
  yes: OrderBookLevel;
  no: OrderBookLevel;
  yes_best_bid?: number;
  yes_best_ask?: number;
  no_best_bid?: number;
  no_best_ask?: number;
}

export interface Position {
  id: number;
  user_id: number;
  event_id: number;
  side: string;
  quantity: number;
  avg_price: number;
  realized_pnl: number;
  created_at: string;
  event_title?: string;
}

export interface Trade {
  id: number;
  event_id: number;
  buy_user_id: number;
  sell_user_id: number;
  side: string;
  price: number;
  quantity: number;
  created_at: string;
}

export interface User {
  id: number;
  username: string;
  balance: number;
  created_at: string;
}

export interface WsMessage {
  type: 'snapshot' | 'update';
  data: OrderBookData;
}
```

- [ ] **Step 6: Create api/client.ts**

```typescript
const BASE = '';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', 'X-User-Id': '1' },
    ...options,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
  del: <T>(path: string) =>
    request<T>(path, { method: 'DELETE' }),
};
```

- [ ] **Step 7: Create main.tsx**

```tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
)
```

- [ ] **Step 8: Create App.tsx skeleton**

```tsx
import { Routes, Route, Link } from 'react-router-dom'
import EventList from './pages/EventList'
import EventDetail from './pages/EventDetail'
import Positions from './pages/Positions'
import Settlement from './pages/Settlement'

export default function App() {
  return (
    <div className="app">
      <nav className="nav">
        <Link to="/">事件列表</Link>
        <Link to="/positions">我的仓位</Link>
        <Link to="/settlement">结算记录</Link>
      </nav>
      <main className="main">
        <Routes>
          <Route path="/" element={<EventList />} />
          <Route path="/event/:id" element={<EventDetail />} />
          <Route path="/positions" element={<Positions />} />
          <Route path="/settlement" element={<Settlement />} />
        </Routes>
      </main>
    </div>
  )
}
```

- [ ] **Step 9: Install dependencies and verify it starts**

```bash
cd prediction-market/frontend && npm install && npm run dev
```

Expected: Dev server starts on port 5173.

- [ ] **Step 10: Commit**

```bash
git add prediction-market/frontend/
git commit -m "feat: scaffold React frontend with Vite, types, and API client"
```

---

### Task 8: Frontend pages - EventList, EventDetail, Positions, Settlement

**Files:**
- Create: `prediction-market/frontend/src/pages/EventList.tsx`
- Create: `prediction-market/frontend/src/pages/EventDetail.tsx`
- Create: `prediction-market/frontend/src/pages/Positions.tsx`
- Create: `prediction-market/frontend/src/pages/Settlement.tsx`
- Create: `prediction-market/frontend/src/index.css`

**Interfaces:**
- Consumes: `api`, types from Task 7
- Produces: 4 page components rendered by App.tsx router

- [ ] **Step 1: Create index.css with base styles**

```css
:root { --bg: #0f0f0f; --surface: #1a1a1a; --border: #2a2a2a; --text: #e0e0e0; --muted: #888; --green: #4ade80; --red: #f87171; --accent: #60a5fa; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); }
.app { max-width: 960px; margin: 0 auto; padding: 0 16px; }
.nav { display: flex; gap: 24px; padding: 16px 0; border-bottom: 1px solid var(--border); margin-bottom: 24px; }
.nav a { color: var(--accent); text-decoration: none; font-weight: 500; }
.nav a:hover { text-decoration: underline; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 12px; }
.card h3 { margin-bottom: 8px; }
.btn { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 500; }
.btn-primary { background: var(--accent); color: #fff; }
.btn-danger { background: var(--red); color: #fff; }
.btn-green { background: var(--green); color: #000; }
.flex { display: flex; gap: 12px; align-items: center; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.input { background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; color: var(--text); width: 100%; }
.select { background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; color: var(--text); }
.muted { color: var(--muted); font-size: 14px; }
.green { color: var(--green); }
.red { color: var(--red); }
.price-bar { display: flex; justify-content: space-between; padding: 4px 8px; border-radius: 4px; margin: 2px 0; cursor: pointer; }
.price-bar:hover { opacity: 0.8; }
.bid-bar { background: rgba(74, 222, 128, 0.15); }
.ask-bar { background: rgba(248, 113, 113, 0.15); }
```

- [ ] **Step 2: Create EventList.tsx**

```tsx
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { Event } from '../types'

export default function EventList() {
  const [events, setEvents] = useState<Event[]>([])
  const [category, setCategory] = useState('')

  useEffect(() => {
    const params = category ? `?category=${category}` : ''
    api.get<Event[]>(`/api/events${params}`).then(setEvents)
  }, [category])

  return (
    <div>
      <div className="flex" style={{ marginBottom: 16 }}>
        <h2>事件列表</h2>
        <select className="select" value={category} onChange={e => setCategory(e.target.value)}>
          <option value="">全部分类</option>
          <option value="sports">体育</option>
          <option value="crypto">加密货币</option>
          <option value="weather">天气</option>
          <option value="politics">政治</option>
          <option value="esports">电竞</option>
        </select>
      </div>
      {events.map(e => (
        <Link key={e.id} to={`/event/${e.id}`} style={{ textDecoration: 'none', color: 'inherit' }}>
          <div className="card">
            <div className="flex" style={{ justifyContent: 'space-between' }}>
              <h3>{e.title}</h3>
              <span className={`muted ${e.status === 'settled' ? (e.result === 'yes' ? 'green' : 'red') : ''}`}>
                {e.status === 'active' ? '进行中' : e.status === 'settled' ? `已结算: ${e.result?.toUpperCase()}` : '暂停'}
              </span>
            </div>
            <p className="muted">{e.description}</p>
            <span className="muted">{e.category}</span>
          </div>
        </Link>
      ))}
    </div>
  )
}
```

- [ ] **Step 3: Create EventDetail.tsx with order book, price chart, order form**

```tsx
import { useEffect, useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { api } from '../api/client'
import { useOrderBook } from '../hooks/useOrderBook'
import type { Event, OrderBookData } from '../types'

export default function EventDetail() {
  const { id } = useParams<{ id: string }>()
  const eventId = Number(id)
  const [event, setEvent] = useState<Event | null>(null)
  const [side, setSide] = useState<'yes' | 'no'>('yes')
  const [orderType, setOrderType] = useState<'market' | 'limit'>('limit')
  const [price, setPrice] = useState(50)
  const [quantity, setQuantity] = useState(10)
  const [msg, setMsg] = useState('')
  const orderBook = useOrderBook(eventId)
  const [priceHistory, setPriceHistory] = useState<{ time: number; price: number }[]>([])

  useEffect(() => {
    api.get<{ event: Event }>(`/api/events/${eventId}`).then(d => setEvent(d.event))
  }, [eventId])

  useEffect(() => {
    if (orderBook) {
      const bestBid = orderBook.yes_best_bid ?? orderBook.no_best_bid
      const bestAsk = orderBook.yes_best_ask ?? orderBook.no_best_ask
      const mid = bestBid && bestAsk ? (bestBid + bestAsk) / 2 : (bestBid ?? bestAsk ?? 50)
      setPriceHistory(prev => [...prev.slice(-50), { time: Date.now(), price: mid }])
    }
  }, [orderBook])

  const placeOrder = useCallback(async () => {
    try {
      const res = await api.post<{ trades: unknown[] }>('/api/orders', {
        event_id: eventId, side, order_type: orderType, price, quantity,
      })
      setMsg(`成交 ${res.trades.length} 笔`)
    } catch {
      setMsg('下单失败')
    }
  }, [eventId, side, orderType, price, quantity])

  if (!event) return <div className="card">加载中...</div>

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>{event.title}</h2>
      <p className="muted" style={{ marginBottom: 16 }}>{event.description}</p>

      {msg && <div className="card" style={{ textAlign: 'center', fontWeight: 500 }}>{msg}</div>}

      <div className="grid-2" style={{ marginBottom: 24 }}>
        <OrderBookPanel title="YES 订单簿" book={orderBook?.yes ?? null} />
        <OrderBookPanel title="NO 订单簿" book={orderBook?.no ?? null} />
      </div>

      <div className="card" style={{ marginBottom: 16, height: 200 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={priceHistory}>
            <XAxis dataKey="time" hide />
            <YAxis domain={[0, 100]} tickFormatter={v => `${v}c`} />
            <Tooltip formatter={(v: number) => [`${v}c`, 'Price']} />
            <Line type="monotone" dataKey="price" stroke="#60a5fa" dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <h3 style={{ marginBottom: 12 }}>下单</h3>
        <div className="flex" style={{ marginBottom: 12 }}>
          <button className={`btn ${side === 'yes' ? 'btn-green' : ''}`} onClick={() => setSide('yes')}>买 YES</button>
          <button className={`btn ${side === 'no' ? 'btn-danger' : ''}`} onClick={() => setSide('no')}>买 NO</button>
        </div>
        <div className="flex" style={{ marginBottom: 12 }}>
          <select className="select" value={orderType} onChange={e => setOrderType(e.target.value as 'market' | 'limit')}>
            <option value="limit">限价单</option>
            <option value="market">市价单</option>
          </select>
        </div>
        {orderType === 'limit' && (
          <div className="flex" style={{ marginBottom: 12 }}>
            <label>价格 (cents):</label>
            <input type="number" className="input" value={price} min={0} max={100} onChange={e => setPrice(Number(e.target.value))} />
          </div>
        )}
        <div className="flex" style={{ marginBottom: 12 }}>
          <label>数量:</label>
          <input type="number" className="input" value={quantity} min={1} onChange={e => setQuantity(Number(e.target.value))} />
        </div>
        <button className="btn btn-primary" onClick={placeOrder}>提交订单</button>
      </div>
    </div>
  )
}

function OrderBookPanel({ title, book }: { title: string; book: OrderBookData['yes'] | null }) {
  if (!book) return <div className="card"><h4>{title}</h4><p className="muted">加载中...</p></div>
  const asks = Object.entries(book.asks).sort(([a], [b]) => Number(b) - Number(a)).slice(-8)
  const bids = Object.entries(book.bids).sort(([a], [b]) => Number(b) - Number(a)).slice(0, 8)
  return (
    <div className="card">
      <h4 style={{ marginBottom: 8 }}>{title}</h4>
      <div style={{ marginBottom: 8 }}>
        {asks.map(([p, q]) => (
          <div key={p} className="price-bar ask-bar">
            <span className="red">{p}c</span>
            <span>{q}</span>
          </div>
        ))}
      </div>
      <div style={{ borderTop: '1px solid var(--border)', paddingTop: 4 }}>
        {bids.map(([p, q]) => (
          <div key={p} className="price-bar bid-bar">
            <span className="green">{p}c</span>
            <span>{q}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Create Positions.tsx**

```tsx
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Position } from '../types'

function centsToUsd(c: number) { return (c / 100).toFixed(2) }

export default function Positions() {
  const [positions, setPositions] = useState<Position[]>([])
  const [balance, setBalance] = useState(0)

  useEffect(() => {
    api.get<Position[]>('/api/positions').then(setPositions)
    api.get<{ balance: number }>('/api/whoami').then(u => setBalance(u.balance))
  }, [])

  return (
    <div>
      <div className="card flex" style={{ justifyContent: 'space-between' }}>
        <h3>账户余额: ${centsToUsd(balance)}</h3>
      </div>
      <h2 style={{ margin: '16px 0' }}>我的仓位</h2>
      {positions.length === 0 && <p className="muted">暂无持仓</p>}
      {positions.map(p => (
        <div key={p.id} className="card">
          <div className="flex" style={{ justifyContent: 'space-between' }}>
            <h3>{p.event_title ?? `Event #${p.event_id}`}</h3>
            <span className={p.side === 'yes' ? 'green' : 'red'}>{p.side.toUpperCase()}</span>
          </div>
          <div className="flex">
            <span>数量: {p.quantity}</span>
            <span>均价: {p.avg_price}c</span>
            <span>市值: {centsToUsd(p.quantity * p.avg_price)} USD</span>
          </div>
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 5: Create Settlement.tsx**

```tsx
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Event } from '../types'

export default function Settlement() {
  const [events, setEvents] = useState<Event[]>([])
  const [msg, setMsg] = useState('')

  useEffect(() => {
    api.get<Event[]>('/api/events?status=active').then(setEvents)
  }, [])

  const settle = async (id: number, result: string) => {
    const res = await api.post<{ total_payout: number; winners_count: number }>(`/api/settle/${id}`, { result })
    setMsg(`事件 #${id} 已结算: ${result.toUpperCase()}, 赔付 ${(res.total_payout / 100).toFixed(2)} USD, ${res.winners_count} 人获胜`)
    setEvents(prev => prev.filter(e => e.id !== id))
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>结算管理</h2>
      {msg && <div className="card" style={{ textAlign: 'center' }}>{msg}</div>}
      <p className="muted" style={{ marginBottom: 16 }}>选择一个进行中的事件并确认结果进行结算</p>
      {events.map(e => (
        <div key={e.id} className="card">
          <h3>{e.title}</h3>
          <p className="muted">{e.category}</p>
          <div className="flex" style={{ marginTop: 12 }}>
            <button className="btn btn-green" onClick={() => settle(e.id, 'yes')}>结算为 YES</button>
            <button className="btn btn-danger" onClick={() => settle(e.id, 'no')}>结算为 NO</button>
          </div>
        </div>
      ))}
      {events.length === 0 && <p className="muted">没有可结算的事件</p>}
    </div>
  )
}
```

- [ ] **Step 6: Create useOrderBook hook**

```typescript
// src/hooks/useOrderBook.ts
import { useEffect, useState } from 'react'
import type { OrderBookData, WsMessage } from '../types'

export function useOrderBook(eventId: number): OrderBookData | null {
  const [data, setData] = useState<OrderBookData | null>(null)

  useEffect(() => {
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${protocol}://${location.host}/ws/orderbook/${eventId}`)

    ws.onmessage = (e) => {
      const msg: WsMessage = JSON.parse(e.data)
      setData(msg.data)
    }

    ws.onerror = () => console.warn('WebSocket error')
    return () => ws.close()
  }, [eventId])

  return data
}
```

- [ ] **Step 7: Verify frontend compiles**

```bash
cd prediction-market/frontend && npx tsc --noEmit
```

Expected: No errors (may have unused variable warnings — those are fine).

- [ ] **Step 8: Commit**

```bash
git add prediction-market/frontend/src/pages/ prediction-market/frontend/src/index.css prediction-market/frontend/src/hooks/
git commit -m "feat: add frontend pages and WebSocket hook"
```

---

### Task 9: Integration test - start backend and verify end-to-end

- [ ] **Step 1: Start backend with seed data**

```bash
cd prediction-market/backend && cargo run
```

Expected: Server starts on port 3000, migrations run, seed data inserted.

- [ ] **Step 2: Test REST API with curl**

```bash
curl http://127.0.0.1:3000/api/events
```

Expected: Returns JSON array of 5 events.

```bash
curl http://127.0.0.1:3000/api/events/1/orderbook
```

Expected: Returns `{"yes":{"bids":{},"asks":{}},"no":{"bids":{},"asks":{}}}` (empty initially).

```bash
curl -X POST http://127.0.0.1:3000/api/orders \
  -H 'Content-Type: application/json' \
  -d '{"event_id":1,"side":"yes","order_type":"limit","price":60,"quantity":10}'
```

Expected: Returns `{"trades":[]}` (no matching orders yet, but order is placed).

```bash
curl http://127.0.0.1:3000/api/positions
```

Expected: Returns empty array `[]` (nothing matched yet).

```bash
curl http://127.0.0.1:3000/api/events/1/orderbook
```

Expected: Now shows YES asks at price 60 with quantity 10.

- [ ] **Step 3: Test opposite order matching**

```bash
curl -X POST http://127.0.0.1:3000/api/orders \
  -H 'Content-Type: application/json' \
  -d '{"event_id":1,"side":"no","order_type":"limit","price":40,"quantity":5}'
```

Expected: YES @ 60 + NO @ 40 → "price crosses" since YES_bid(60) + NO_ask(40) = 100 → mirror price of NO_ask is YES=60 which matches YES bid @ 60. Check that trades are returned.

```bash
curl -X POST http://127.0.0.1:3000/api/settle/1 \
  -H 'Content-Type: application/json' \
  -d '{"result":"yes"}'
```

Expected: Returns settlement result with total_payout and winners_count.

```bash
curl http://127.0.0.1:3000/api/whoami
```

Expected: Returns demo user with balance.

- [ ] **Step 5: Commit final state**

```bash
git status
git add -A
git commit -m "feat: complete prediction market demo backend"
```
