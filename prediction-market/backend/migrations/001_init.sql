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
