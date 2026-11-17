# Uptime Guardian

**English** | [Tiếng Việt](README.vi.md)

> **Distributed Uptime & Certificate Monitoring System — Built with an Engineering-First Approach.**

An open-source, resilient, self-hosted distributed uptime monitoring platform engineered to demonstrate core distributed systems principles: **distributed scheduling, state machines, concurrency control, worker idempotency, data rollups, and end-to-end SRE observability**.

---

##  Architecture Overview

```
                            ┌────────────────────────┐
                            │    React Dashboard     │
                            │ (Vite + Tailwind / UI) │
                            └─────┬────────────▲─────┘
                        REST (JWT)│            │ WebSocket (/ws/telemetry)
                            ┌─────▼────────────┴─────┐
                            │      API Gateway       │ ◄── [Caddy Reverse Proxy]
                            │   (FastAPI / Python)   │     (HTTPS Let's Encrypt / TLS)
                            └───────────┬────────────┘
                                        │
           ┌────────────────────────────┼────────────────────────────┐
           │                            │                            │
           ▼                            ▼                            ▼
┌──────────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
│  Distributed Sched.  │     │    PostgreSQL 16     │     │      Redis 7         │
│  (Redis Sorted Set)  │     │ (Monitors, Partition)│     │(ZSET, State, Quorum, │
└──────────┬───────────┘     └──────────▲───────────┘     │ Pub/Sub Telemetry)   │
           │ Job payload                │                 └──────────┬───────────┘
           ▼                            │                            │
┌──────────────────────┐                │                            │
│ RabbitMQ: check.jobs │                │ Save results               │ State & Quorum
└──────────┬───────────┘                │                            │
           │ Consume                    │                            │
           ▼                            │                            │
┌───────────────────────────────────────┴────────────────────────┐   │
│                   Regional Checker Workers                     │   │
│   (vn-han, sg-sin, us-iad — httpx, Anti-SSRF, DNS, Quorum)     │   │
└──────────┬────────────────────────────┬────────────────────────┘   │
           │ Challenge exchange         │ Publish                    │
           ▼                            ▼                            ▼
┌──────────────────────┐     ┌───────────────────────────────────────────┐
│  quorum.exchange     │     │          Alerter Worker Service           │
│ (AMQP Topic Exchange)│     │   (Consensus Engine + State Machine)      │
└──────────────────────┘     └───────────────────────────────────────────┘
```

---

##  Core Engineering Problems Solved

1. **Distributed Scheduling with Redis Sorted Sets (`ZADD`/`ZPOPMIN`):**
   - Avoids database table scanning/locking overhead.
   - Monitors scheduled by Unix timestamp score with O(log N) complexity.
   - Atomic Lua leasing script prevents duplicate execution across scheduler replicas.
2. **Alert State Machine & Race Condition Prevention:**
   - Tracks `consecutive_fail_count` and `cooldown_until` on Redis hashes.
   - Distributed locking via `SETNX` prevents duplicate alerts across concurrent workers.
3. **Worker Idempotency:**
   - UUIDv4 `job_id` tracking prevents duplicate database writes and false alert triggers during worker retries or network partitions.
4. **Data Retention & Hourly Rollup:**
   - High-frequency raw checks retained for 7 days with PostgreSQL table range partitioning.
   - Hourly background aggregation into `hourly_uptime_summary` for fast 30-day dashboard rendering without bloating PostgreSQL.
5. **Production SRE Observability:**
   - RED metrics (Rate, Errors, Duration) collected by Prometheus and displayed on Grafana.
   - Target capacity designed for >2,000 checks/second (single-node baseline benchmark: ~200 RPS via k6).
6. **Multi-Region Quorum Consensus (Resilience to Localized Peering Disruptions):**
   - Out-of-band challenge verification across geographic nodes (`vn-han`, `sg-sin`, `us-iad`) via RabbitMQ `quorum.exchange`.
   - Redis voting sessions (`quorum:session:<challenge_id>`) with atomic `HSETNX` decision guards.
   - Fast-tracks genuine outages to `DOWN` while suppressing localized transit failures (`is_suppressed=True`), preserving 100% user SLA.
7. **Real-time Live WebSocket Telemetry:**
   - Real-time streaming of `check_result` and `status_change` events over `/ws/telemetry` via Redis Pub/Sub multiplexing.
   - Bounded per-socket buffer queues (`asyncio.Queue(maxsize=100)`) with `drop_oldest` policy to prevent memory bloat on slow connections.
   - Automatic exponential backoff reconnection on the React dashboard.

---

##  Technology Stack

- **Backend:** Python 3.13, FastAPI, SQLAlchemy 2.0 (Async), Alembic, Pydantic v2
- **Message Broker & Cache:** RabbitMQ, Redis 7
- **Database:** PostgreSQL 16 (Range Partitioned by Week)
- **Frontend:** React 18, Vite, Tailwind CSS, Recharts
- **Infrastructure & SRE:** Docker, Docker Compose, Caddy Reverse Proxy, Prometheus, Grafana
- **Testing & Quality:** Pytest, pytest-asyncio (168 tests), k6, Flake8, Bandit SAST

---

##  Project Structure

```
uptime-guardian/
├── services/
│   ├── api_gateway/       # FastAPI REST & WebSocket Gateway (/ws/telemetry, auth, monitors)
│   ├── scheduler/         # Redis ZSET distributed scheduler -> RabbitMQ producer
│   ├── checker/           # Multi-region probe workers (HTTP, SSL, Anti-SSRF, Quorum consumer)
│   ├── alerter/           # Quorum consensus engine + State machine notification service
│   ├── common/            # Shared ORM models, dual-dialect schemas, Redis, and Anti-SSRF
│   └── dashboard/         # React + Vite + Tailwind CSS monitoring dashboard
├── docker/                # Local development & production Docker Compose configs
├── tests/                 # 168+ unit, integration, and k6 benchmark test suites
└── docs/                  # Architecture specs, roadmaps, debt tracking, & guides
```

---

##  Roadmap Quick View

- **Milestone 1 (v0.1.0): Core Distributed Engine (Completed)** — Database schema, FastAPI Gateway, atomic Redis ZSET scheduler, idempotent checker, alert state machine, and initial dashboard.
- **Milestone 2 (v0.2.0): Production Hardening & SRE Observability (Completed)** — Caddy TLS proxy, Prometheus/Grafana RED metrics, GitHub Actions CI/CD, PostgreSQL range partitioning, and k6 benchmarks.
- **Milestone 3 (v0.3.0): Distributed Resilience & Live Telemetry (Completed)** — Multi-region quorum consensus verification, AMQP challenge topic exchange, Redis quorum voting aggregator, and live WebSocket telemetry stream.

For full technical details, refer to [ROADMAP.md](docs/ROADMAP.md) and [SPEC.md](docs/SPEC.md).
