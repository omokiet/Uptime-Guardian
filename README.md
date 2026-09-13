#  Uptime Guardian

> **Distributed Uptime & Certificate Monitoring System — Built with an Engineering-First Approach.**

An open-source, resilient, self-hosted distributed uptime monitoring platform engineered to demonstrate core distributed systems principles: **distributed scheduling, state machines, concurrency control, worker idempotency, data rollups, and end-to-end SRE observability**.

---

##  Architecture Overview

```
                            ┌────────────────────────┐
                            │    React Dashboard     │
                            │ (Vite + Tailwind / UI) │
                            └───────────┬────────────┘
                                        │ REST (JWT)
                            ┌───────────▼────────────┐
                            │      API Gateway       │ ◄── [Nginx / Caddy Reverse Proxy]
                            │   (FastAPI / Python)   │     (HTTPS Let's Encrypt)
                            └───────────┬────────────┘
                                        │
           ┌────────────────────────────┼────────────────────────────┐
           │                            │                            │
           ▼                            ▼                            ▼
┌──────────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
│  Distributed Sched.  │     │    PostgreSQL 16     │     │      Redis 7         │
│  (Redis Sorted Set)  │     │ (Monitors, Summaries)│     │(ZSET, State, Locks)  │
└──────────┬───────────┘     └──────────▲───────────┘     └──────────┬───────────┘
           │ Job payload                │                            │
           ▼                            │                            │
┌──────────────────────┐                │                            │
│ RabbitMQ: check.jobs │                │ Save results               │ State updates
└──────────┬───────────┘                │                            │
           │ Consume                    │                            │
           ▼                            │                            │
┌──────────────────────┐                │                            │
│   Checker Workers    ├────────────────┘                            │
│  (httpx, SSL, DNS)   ├──────────────────────────────┐              │
└──────────────────────┘                              │              │
                                                      │ Publish      │
                                                      ▼              ▼
                                           ┌──────────────────────────────┐
                                           │     Alerter Worker Service   │
                                           │  (State Machine + Telegram)  │
                                           └──────────────────────────────┘
```

---

##  Core Engineering Problems Solved

1. **Distributed Scheduling with Redis Sorted Sets (`ZADD`/`ZPOPMIN`):**
   - Avoids database table scanning/locking overhead.
   - Monitors scheduled by Unix timestamp score with O(log N) complexity.
2. **Alert State Machine & Race Condition Prevention:**
   - Tracks `consecutive_fail_count` and `cooldown_until` on Redis hashes.
   - Distributed locking via `SETNX` prevents duplicate alerts across concurrent workers.
3. **Worker Idempotency:**
   - UUIDv4 `job_id` tracking prevents duplicate database writes and false alert triggers during worker retries or network partitions.
4. **Data Retention & Hourly Rollup:**
   - High-frequency raw checks retained for 7 days.
   - Hourly background aggregation into `hourly_uptime_summary` for fast 30-day dashboard rendering without bloating PostgreSQL.
5. **Production SRE Observability:**
   - RED metrics (Rate, Errors, Duration) collected by Prometheus and displayed on Grafana.
   - k6 load tested up to 2,000+ checks/second.

---

##  Technology Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (Async), Alembic, Pydantic v2
- **Message Broker & Cache:** RabbitMQ, Redis 7
- **Database:** PostgreSQL 16
- **Frontend:** React 18, Vite, Tailwind CSS
- **Infrastructure & SRE:** Docker, Docker Compose, Nginx/Caddy, Terraform, Prometheus, Grafana
- **Testing & Quality:** Pytest, pytest-asyncio, k6, Flake8, Bandit SAST

---

##  Project Structure

```
uptime-guardian/
├── services/
│   ├── api_gateway/       # FastAPI REST API (CRUD monitors, auth, stats)
│   ├── scheduler/         # Redis ZSET distributed scheduler -> RabbitMQ producer
│   ├── checker/           # Async HTTP/SSL/DNS worker with idempotency control
│   └── alerter/           # Telegram alert service with state machine & cooldown
├── docker/                # Local development & production Docker Compose configs
├── tests/                 # Integration tests, unit tests, and k6 benchmark scripts
├── ROADMAP.md             # Engineering release roadmap (Milestones 1–3)
└── SPEC.md                # System Architecture & Technical Specification RFC
```

---

##  Roadmap Quick View

- **Milestone 1 (v0.1.0): Core Distributed Engine (Completed)** — Database schema, FastAPI Gateway, atomic Redis ZSET scheduler, idempotent checker, alert state machine, and real-time dashboard.
- **Milestone 2 (v0.2.0): Production Hardening & SRE Observability (In Progress)** — Terraform IaC, production TLS proxy, Prometheus/Grafana RED metrics, GitHub Actions CI/CD, and k6 load benchmarks.
- **Milestone 3 (v0.3.0): Distributed Resilience & Scaling (Planned)** — k3s orchestration, queue-driven HPA auto-scaling, multi-region quorum validation, and live WebSocket telemetry.

For full technical details, refer to [ROADMAP.md](./ROADMAP.md) and [SPEC.md](./SPEC.md).
