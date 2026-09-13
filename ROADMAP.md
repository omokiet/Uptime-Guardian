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
  - Real-time dark-mode operational dashboard.
  - Automated test suite with 22/22 unit and integration tests passing.

---

### Milestone 2: Production Hardening & SRE Observability (v0.2.0) — `IN PROGRESS`
> **Focus:** Real-world operations, infrastructure-as-code, continuous deployment, and telemetry.

- [ ] **Infrastructure as Code (Terraform):**
  - Declarative `.tf` configuration for VPS compute instances, cloud firewall rules, and DNS A-records.
- [ ] **Production Reverse Proxy & TLS Automation:**
  - Production Docker Compose configuration with restart policies, container healthchecks, and volume persistence.
  - Caddy / Nginx reverse proxy with automated Let's Encrypt TLS certificate issuance and renewal.
- [ ] **Full-Stack Observability (RED Metrics):**
  - Prometheus metrics exporter for API Gateway (`http_requests_total`, `http_request_duration_seconds`).
  - Worker telemetry exporter (`checks_total`, `check_duration_seconds`, active workers).
  - RabbitMQ queue depth exporter (`rabbitmq_queue_messages_ready`).
  - Curated Grafana operational dashboard monitoring throughput, error budget, and p95/p99 latency.
- [ ] **Continuous Integration & Automated Deployment (GitHub Actions):**
  - Static analysis: Code style linting (Flake8), type validation, and security auditing (Bandit SAST).
  - Automated test execution on each pull request via Pytest.
  - Multi-stage Docker build pipeline publishing production images to GitHub Container Registry (GHCR).
  - Zero-downtime automated deployment to VPS via SSH upon merge to `main`.
- [ ] **Two-Tier Telemetry Rollup & Retention Engine:**
  - Background cron aggregation job: Rolling raw `check_results` into `hourly_uptime_summary` (computing hourly uptime percentage and average RTT).
  - Automatic retention cleanup: Purging raw logs older than 7 days to preserve database disk performance.
- [ ] **Performance Benchmarks (k6):**
  - High-throughput load testing verifying scheduler dispatch and worker processing rates.
  - Baseline documentation in README: Sustained checks/sec capacity, resource utilization, and latency percentiles.
- [ ] **Production React Dashboard (React 18 + Vite + Tailwind CSS):**
  - Dedicated branch: `feature/react-dashboard` branched from `staging`.
  - Visualization: 30-day uptime history timeline (discrete status blocks from `hourly_uptime_summary`), latency chart (p50/p95/p99 RTT over time with Chart.js / Recharts).
  - Modern, responsive architecture with clean state management and Tailwind CSS design tokens.

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
