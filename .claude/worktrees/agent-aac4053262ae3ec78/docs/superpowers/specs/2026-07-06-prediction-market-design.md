# Prediction Market Core Trading Demo - Design Spec

> Date: 2026-07-06
> Source: The Web3 预测市场基础课程文章
> Scope: 核心交易 Demo

## Overview

A prediction market demo where users trade YES/NO outcome shares on real-world events.
The platform acts as an exchange (not a house), providing matching, trading, and settlement.

## Tech Stack

- **Frontend**: React 18 + Vite + TypeScript
- **Backend**: Rust (Axum + Tokio) + SQLite (sqlx)
- **Realtime**: REST API + WebSocket (order book + trade push)

## Architecture

```
React SPA (Vite)          Rust (Axum)
+-----------------+       +--------------------------+
|  Event List     |  REST |  /api/events             |
|  Event Detail   |<----->|  /api/orders             |
|  Order Book     |       |  /api/positions           |
|  Trade History  |  WS   |  /api/settle              |
|                 |<----->|  /ws/orderbook/:event_id  |
+-----------------+       +----------+---------------+
                                     |
                              +------v--------+
                              |  SQLite       |
                              |  (sqlx)       |
                              +---------------+
```

## Modules

### Backend (Rust/Axum)

| Module | Crate | Responsibilities |
|--------|-------|-----------------|
| `api-server` | Server binary | HTTP routes, WebSocket, state, auth mock |
| `matching-engine` | Library | Order book, price-time priority, YES/NO mirror matching |
| `event-pool` | Library | Event CRUD, seed data, result arbitration |
| `settlement` | Library | Position snapshot, payout calculation, cleanup |

### Frontend (React)

| Page | Route | Content |
|------|-------|---------|
| Event List | `/` | Category filter, probability cards, search |
| Event Detail | `/event/:id` | YES/NO order book, price chart, order form |
| My Positions | `/positions` | Active holdings, P&L, trade history |
| Settlement | `/settlement` | Settled events, payout details |

## Key Design Decisions

### YES/NO Mirror Matching
Buying YES at $0.63 is equivalent to buying NO at $0.37 (since YES + NO = $1.00).
The matching engine normalizes orders internally, enabling cross-side matching:
a YES buy can match against a NO sell when prices align.

### Order Types
- Market orders: execute immediately at best available price
- Limit orders: post to order book, match if possible, remain until filled/canceled

### Simulated Funds
Each user gets 1,000 USDC demo balance on registration. No real wallet integration.

### Settlement
Admin manually confirms event outcome. Settlement engine snapshots positions,
pays winning holders $1.00 per share, destroys losing shares.

### WebSocket Protocol
- Client subscribes to `ws://host/ws/orderbook/:event_id`
- Server pushes: order book snapshot, incremental updates, last trade price
- Messages are JSON

## Data Model

```
users: id, username, balance, created_at
events: id, title, description, category, status(active|paused|settled), result(yes|no|null), created_at
orders: id, user_id, event_id, side(yes|no), type(market|limit), price, quantity, filled_qty, status(open|partial|filled|canceled), created_at
trades: id, event_id, buyer_id, seller_id, side, price, quantity, created_at
positions: id, user_id, event_id, side, quantity, avg_price, realized_pnl, created_at
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/events` | List events (filterable by category, status) |
| GET | `/api/events/:id` | Event detail + current YES/NO prices |
| GET | `/api/events/:id/orderbook` | Full order book snapshot |
| POST | `/api/orders` | Place order (market or limit) |
| DELETE | `/api/orders/:id` | Cancel order |
| GET | `/api/positions` | User positions |
| GET | `/api/trades` | Trade history |
| POST | `/api/settle/:event_id` | Trigger settlement (admin) |
| WS | `/ws/orderbook/:event_id` | Real-time order book stream |

## Project Structure

```
my-tool/
  prediction-market/
    backend/
      Cargo.toml
      src/
        main.rs
        api/
          routes.rs
          ws.rs
        matching/
          engine.rs
          orderbook.rs
          mirror.rs
        event/
          pool.rs
          models.rs
        settlement/
          engine.rs
        db.rs
        auth.rs
      migrations/
    frontend/
      package.json
      vite.config.ts
      src/
        App.tsx
        pages/
        components/
        hooks/
        api/
        types/
```
