# Uptime Guardian — Technical Roadmap & Release Milestones

**English** | [Tiếng Việt](ROADMAP.vi.md)

> **Vision:** Building a resilient, self-hosted, distributed uptime and certificate monitoring platform engineered to demonstrate core distributed systems patterns: non-blocking scheduling, idempotent processing, finite state machines, and end-to-end SRE observability.

---

## Release Milestones

```
  v0.1.0 (Core Engine)       ──►  v0.2.0 (Production SRE)   ──►  v0.3.0 (Scale & Cluster)
  [COMPLETED]                     [IN PROGRESS]                   [PLANNED]
  • FastAPI + SQLAlchemy async    • Terraform VPS Provisioning   • k3s Kubernetes Deploy
  • Redis ZSET Scheduler          • Prometheus + Grafana RED     • HPA Queue-Depth Scaling
  • Idempotent Checker Worker     • GitHub Actions CI/CD          • Multi-Region Quorum Check
  • Alert State Machine           • Data Rollup & Retention Cron • Live WebSocket Telemetry
  • Anti-SSRF Defense             • k6 Load Benchmarks (>2k RPS)
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

### Milestone 3: Distributed Resilience & Scaling (v0.3.0) — `PLANNED`
> **Focus:** Cluster orchestration, auto-scaling, and geo-distributed consensus.

- [ ] **Kubernetes Manifests & Helm Packaging:**
  - Production deployment manifests configured for lightweight Kubernetes (`k3s`).
  - Declarative Helm chart with configurable replica counts and resource quotas.
- [ ] **Event-Driven Auto-Scaling (KEDA / HPA):**
  - Horizontal Pod Autoscaler for Checker Workers dynamically scaling up/down based on RabbitMQ queue backlog.
- [ ] **Multi-Region Quorum Verification:**
  - Distributed workers running across distinct geographic zones to cross-verify failures and eliminate false alarms caused by localized peering issues.
- [ ] **WebSocket Live Telemetry Feed:**
  - Real-time event streaming push notifications to connected dashboard clients without polling.
