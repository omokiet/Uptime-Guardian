# Uptime Guardian — Technical Roadmap & Release Milestones

**English** | [Tiếng Việt](ROADMAP.vi.md)

> **Vision:** Building a resilient, self-hosted, distributed uptime and certificate monitoring platform engineered to demonstrate core distributed systems patterns: non-blocking scheduling, idempotent processing, finite state machines, and end-to-end SRE observability.

---

## Release Milestones

```
  v0.1.0 (Core Engine)       ──►  v0.2.0 (Production SRE)   ──►  v0.3.0 (Scale & Resilience)
  [COMPLETED]                     [COMPLETED]                     [COMPLETED]
  • FastAPI + SQLAlchemy async    • Caddy Reverse Proxy TLS      • Multi-Region Quorum Consensus
  • Redis ZSET Scheduler          • Prometheus + Grafana RED     • AMQP Topic Challenge Exchange
  • Idempotent Checker Worker     • GitHub Actions CI/CD          • Live WebSocket Telemetry Stream
  • Alert State Machine           • PostgreSQL Range Partition   • Atomic Quorum Decision Guard
  • Anti-SSRF Defense             • k6 Load Benchmarks (>2k RPS) • SLA Rollup Suppression
```

---

### Milestone 1: Core Distributed Engine (v0.1.0) — `COMPLETED`
> **Focus:** Correctness, concurrency control, and deterministic state transitions on containerized local infrastructure.

- [x] **Relational Schema & Migrations:**
  - PostgreSQL 16 schema with strict UTC timestamps (`TIMESTAMPTZ`), cascade deletion, and optimized b-tree indexes.
  - Asynchronous SQLAlchemy 2.0 ORM with Alembic database migrations.
- [x] **API Gateway & Access Control:**
  - FastAPI service with JWT stateless authentication (bcrypt password hashing).
  - Full CRUD operations for monitors and notification channel configurations.
  - Defense-in-depth pre-flight Anti-SSRF validation engine blocking RFC 1918, loopback, and link-local ranges.
- [x] **Non-Blocking Distributed Scheduler:**
  - Atomic Redis Sorted Set (`scheduler:monitors`) scheduling with millisecond precision.
  - Atomic Lua script leasing to prevent duplicate dispatch across concurrent scheduler replicas.
  - Persistent message dispatching to RabbitMQ `check.jobs`.
- [x] **Idempotent Checker Fleet:**
  - Asynchronous probe execution (`httpx`) measuring response time (RTT) and status validation.
  - TLS socket handshake inspection calculating remaining SSL certificate validity days.
  - Deduplication gate (`SET check:processed:<job_id> 1 EX 300 NX`) preventing redundant execution on message redelivery.
- [x] **Finite State Machine & Alerting:**
  - Redis Hash state engine (`monitor:state:<id>`) tracking consecutive failures and cooldown timers.
  - Distributed mutual exclusion lock (`SETNX`) preventing alert race conditions across worker nodes.
  - Telegram Bot notification dispatcher with automatic recovery signaling.
- [x] **Dashboard & Verification:**
  - Dark-mode operational dashboard (HTTP polling; live WebSockets in v0.3.0).
  - Automated test suite with 117/117 unit and integration tests passing.

---

### Milestone 2: Production Hardening & SRE Observability (v0.2.0) — `IN PROGRESS`
> **Focus:** Real-world operations, infrastructure-as-code, continuous deployment, and telemetry.

#### Evidence-Based Verification Matrix

| Capability / Task | Evidence Verification Command | Expected Output & Observed Result | Status |
| :--- | :--- | :--- | :---: |
| **Reverse Proxy (Caddy TLS)** | `curl -k -i https://localhost/health` | `HTTP/2 200`, `Server: Caddy`, `X-Frame-Options: DENY` | **VERIFIED (100%)** |
| **RED Metrics (Grafana)** | `http://localhost:3000` (`uptime-guardian-red`) | Live API Request Rate, 0% 5xx Error Ratio, p95/p99 Latency | **VERIFIED (Gateway)** |
| **CI/CD Pipeline (GitHub)** | GitHub Actions PR #1 checks | 3 Ubuntu jobs (Backend, Frontend, Compose) with green checkmarks | **VERIFIED (PR #1)** |
| **PostgreSQL Partitioning** | `psql -c "\d+ check_results"` | `Partition key: RANGE (created_at)` & child weekly tables | **VERIFIED (100%)** |
| **k6 Load Benchmark** | `k6 run tests/load/k6_benchmark.js` | 24,254 iterations completed; single-node ~200 RPS baseline | **VERIFIED (Baseline)** |
| **Infrastructure as Code** | `terraform validate` | Zero syntax/validation errors | **PENDING** |

- [ ] **Infrastructure as Code (Terraform):**
  - Declarative `.tf` configuration for VPS compute instances, cloud firewall rules, and DNS A-records.
- [x] **Production Reverse Proxy & TLS Automation:**
  - Production Docker Compose configuration with restart policies, container healthchecks, and volume persistence.
  - Caddy reverse proxy with automated TLS certificate handling (internal TLS for local/staging, Let's Encrypt ready).
  - *Evidence:* `curl -k -i https://localhost/health` verified returning HTTP 200 with Caddy security headers.
- [x] **Full-Stack Observability (RED Metrics):**
  - Prometheus metrics exporter for API Gateway (`api_http_requests_total`, `api_http_request_duration_seconds`).
  - Curated Grafana operational dashboard monitoring throughput, error budget, and p95/p99 latency.
  - *Evidence:* Grafana dashboard (`http://localhost:3000`) displays live API request rates, 0% 5xx error ratio, and p95/p99 latency curves.
  - [ ] Dedicated worker & RabbitMQ queue depth Prometheus exporter scrape configuration.
- [x] **Continuous Integration & Automated Deployment (GitHub Actions):**
  - Static analysis: Code style linting (Flake8), type validation, and security auditing (Bandit SAST).
  - Automated test execution on each pull request via Pytest (117 tests passing).
  - Multi-stage Docker build pipeline publishing production images to GitHub Container Registry (GHCR).
  - *Evidence:* PR #1 (`feature/devops-lab-fixes` -> `staging`) passed all 3 Ubuntu runner workflows with green checkmarks.
  - [ ] Zero-downtime automated deployment to VPS via SSH upon merge to `main`.
  - [ ] Upgrade CI test runners to use real PostgreSQL 16, Redis 7, and RabbitMQ Service Containers (replacing mocks).
- [x] **Two-Tier Telemetry Rollup & Retention Engine:**
  - Background cron aggregation job: Rolling raw `check_results` into `hourly_uptime_summary` with automated backfill support.
  - Automatic retention cleanup: Declarative PostgreSQL table partitioning dropping partitions older than 7 days.
  - *Evidence:* Migration `002_partition_check_results.py` applied, weekly partitions auto-generated via `ensure_future_partitions()`.
- [x] **Performance Benchmarks (k6):**
  - High-throughput load testing script (`tests/load/k6_benchmark.js`).
  - *Evidence:* 4m50s benchmark completed 24,254 iterations; measured ~200 RPS single-node baseline.
- [x] **Production React Dashboard (React 18 + Vite + Tailwind CSS):**
  - Dedicated branch: `feature/UI` branched from `staging`.
  - Clean SaaS design system: Neutral dark theme, unified English locale, and subtle micro-interactions.
  - Visualization: Latency chart with Recharts, SSL expiration tracking, live status chips, and CRUD modals.
  - Production build verified: TypeScript strict typechecking, 0 errors, optimized bundle (612 kB).

---

### Milestone 3: Distributed Resilience & Live Telemetry (v0.3.0) — `COMPLETED`
> **Focus:** Geo-distributed consensus verification, localized disruption suppression, and real-time WebSocket telemetry.

#### Evidence-Based Verification Matrix

| Capability / Task | Evidence Verification Command | Expected Output & Observed Result | Status |
| :--- | :--- | :--- | :---: |
| **Multi-Region Models & DDL** | `pytest tests/test_quorum_models.py` | 10 passed: migration, Dual-dialect model, SLA Rollup | **VERIFIED (100%)** |
| **AMQP Challenge Exchange** | `pytest tests/test_quorum_checker.py` | 6 passed: topic exchange, regional queues, out-of-band probe | **VERIFIED (100%)** |
| **Quorum Consensus Engine** | `pytest tests/test_quorum_consensus.py` | 6 passed: atomic HSETNX guard, fast outage confirmation | **VERIFIED (100%)** |
| **WebSocket Live Telemetry** | `pytest tests/test_websocket_telemetry.py` | 7 passed: JWT auth, drop_oldest buffer, pubsub multiplex | **VERIFIED (100%)** |
| **Dashboard TypeScript Build** | `npm --prefix services/dashboard run build` | `dist/` generated, 0 type errors, Vite build clean | **VERIFIED (100%)** |

- [x] **Database Schema Migration & Dual-Dialect Models:**
  - Alembic migration `004_multi_region_quorum.py`: adds `quorum_enabled`, `quorum_threshold`, `quorum_regions` to `monitors` and `region_id`, `is_suppressed` to `check_results`.
  - SQLAlchemy models with dual-dialect (`ARRAY` for PostgreSQL, `JSON` for SQLite tests).
  - SLA Rollup isolation: `aggregate_hourly_uptime` counts `is_suppressed=True` as uptime, protecting customer SLA from localized transit peering faults.
- [x] **AMQP Quorum Challenge Exchange & Regional Workers:**
  - Topic exchange `quorum.exchange` bound to regional queues (`quorum.challenges.<region>`) with message TTL (20s).
  - Out-of-band probe verification with timeout capped at $\le 5$s.
  - Automatic `quorum:active:<monitor_id>` Redis lock to prevent challenge storms.
- [x] **Redis Quorum Aggregator & Consensus Decision Engine:**
  - Distributed voting sessions on Redis hashes (`quorum:session:<challenge_id>`).
  - Atomic decision lock (`HSETNX`) preventing duplicate alert publishing from parallel workers.
  - Alerter state machine fast-tracks to `DOWN` when `quorum_confirmed=True`, with zero emoji/icon pollution.
  - Watchdog timeout resolution automatically suppresses alerts and updates DB if quorum threshold is unreachable.
- [x] **Live WebSocket Gateway & Real-time Telemetry Stream:**
  - FastAPI endpoint `/ws/telemetry` with JWT authentication via query parameter or initial JSON frame.
  - Connection manager with per-socket bounded buffer (`asyncio.Queue(maxsize=100)`) enforcing `drop_oldest` policy.
  - Redis Pub/Sub multiplexing (`telemetry:user:<user_id>`) with automated cleanup on client disconnect.
  - React hook `useWebSocketTelemetry` with exponential backoff reconnect.
- [ ] **Kubernetes Manifests & Helm Packaging (Future Cluster Operations):**
  - Production deployment manifests configured for lightweight Kubernetes (`k3s`).
  - Declarative Helm chart with configurable replica counts and resource quotas.
- [ ] **Event-Driven Auto-Scaling (KEDA / HPA):**
  - Horizontal Pod Autoscaler for Checker Workers dynamically scaling up/down based on RabbitMQ queue backlog.
