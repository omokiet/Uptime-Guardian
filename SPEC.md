# Uptime Guardian — System Architecture & Technical Specification

> **Status:** Active / Production Design  
> **Document Type:** System Architecture RFC & Engineering Specification  
> **Target System:** Distributed, Fault-Tolerant Uptime & Certificate Monitoring Engine

---

## 1. System Overview & Engineering Objectives

### 1.1 Problem Statement
Real-world web services experience localized network partitions, sudden DNS failures, unexpected SSL certificate expirations, and transient degradation. Standard monitoring tools often suffer from:
1. **Alert Fatigue (Báo động giả):** Single-packet drops triggering panic alerts.
2. **Database Contention:** Polling databases with `SELECT ... WHERE next_run <= NOW()` causing table locks and IOPS exhaustion at scale.
3. **Duplicate Processing & Race Conditions:** Distributed workers picking the same target or sending duplicate alerts when network latency spikes.
4. **Data Bloat:** Unbounded accumulation of raw ping telemetry degrading query performance over time.

### 1.2 Engineering Objectives
Uptime Guardian is architected from the ground up as a **resilient distributed system** focused on:
- **O(log N) Distributed Scheduling:** Utilizing Redis Sorted Sets to schedule millions of periodic checks without database polling locks.
- **Strict Worker Idempotency:** Guaranteed single-execution semantics through distributed tokens (`job_id`) and TTL-based atomic checks.
- **Finite Alert State Machine with Hysteresis:** State-driven transitions (`UP` ⇄ `PENDING_DOWN` ⇄ `DOWN`) with consecutive failure dampening and cooldown throttling.
- **Two-Tier Telemetry Retention (Rollup Engine):** High-resolution raw telemetry retained for 7 days, aggregated into hourly SLA/SLO summaries for multi-month reporting.
- **Defense-in-Depth Security (Anti-SSRF):** Pre-flight DNS resolution and IP verification preventing Server-Side Request Forgery against private/loopback networks.

---

## 2. System Architecture & Component Topology

```
                            ┌────────────────────────┐
                            │    React Dashboard     │
                            │ (Vite + Tailwind / UI) │
                            └───────────┬────────────┘
                                        │ REST (JWT)
                            ┌───────────▼────────────┐
                            │      API Gateway       │ ◄── [Reverse Proxy: Caddy / Nginx]
                            │   (FastAPI / Python)   │     (Automated TLS Termination)
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

## 3. Subsystem Specifications

### 3.1 Distributed Scheduler Subsystem (Redis Sorted Set)
- **Key Structure:** `scheduler:monitors`
- **Member:** `monitor_id` (UUIDv4 string)
- **Score:** `next_check_timestamp` (Unix epoch milliseconds)
- **Atomic Dispatch Algorithm:**
  1. Scheduler executes an atomic Lua script every 1,000ms:
     ```lua
     local key = KEYS[1]
     local max_score = tonumber(ARGV[1])
     local lease_score = tonumber(ARGV[2])
     local limit = tonumber(ARGV[3])

     local members = redis.call('ZRANGEBYSCORE', key, '-inf', max_score, 'LIMIT', 0, limit)
     for _, member in ipairs(members) do
         redis.call('ZADD', key, lease_score, member)
     end
     return members
     ```
  2. The atomic lease prevents race conditions across horizontal scheduler replicas.
  3. For each leased monitor, the scheduler dispatches a message to RabbitMQ `check.jobs` and updates `scheduler:monitors` score to `now + (interval_seconds * 1000)`.

### 3.2 Checker Worker & Network Validation Engine
- **Queue Consumer:** Consumes from RabbitMQ `check.jobs` with configurable prefetch (`QOS = 10`).
- **Network Verification Pipeline:**
  1. **Anti-SSRF Gate:** Pre-resolves target hostname via DNS. If resolved IP belongs to private/loopback/link-local ranges (RFC 1918, RFC 3927, loopback `127.0.0.0/8`, `::1`), immediately reject.
  2. **Asynchronous HTTP Probe:** Executes non-blocking request via `httpx.AsyncClient` with user-defined timeouts (1–120s). Captures status code and round-trip time (RTT in ms).
  3. **SSL Certificate Expiration Check:** Connects via TLS socket to parse `notAfter` metadata and calculate remaining validity days.
  4. **DNS Latency Verification:** Measures resolution latency and flags NXDOMAIN/TIMEOUT errors.

### 3.3 Worker Idempotency & Deduplication
To guarantee at-most-once execution when RabbitMQ redelivers messages during network partitions or worker restarts:
- Worker issues atomic command: `SET check:processed:<job_id> 1 EX 300 NX`
- If key already exists: Immediate `ACK` without re-executing network probes or duplicate DB insertion.
- If key is new: Complete check execution, persist to PostgreSQL `check_results`, and forward event to RabbitMQ `alert.events`.

### 3.4 Alert State Machine (Finite State Machine with Hysteresis)
- **State Storage:** Redis Hash `monitor:state:<monitor_id>`
  - Fields: `status` (`UP`, `PENDING_DOWN`, `DOWN`), `consecutive_fails`, `last_alert_at`, `cooldown_until`.
- **Distributed Concurrency Lock:** `SET lock:alert:<monitor_id> 1 EX 10 NX` ensures atomic transitions across concurrent alerter workers.
- **State Transition Table:**

| Current State | Health Check Result | Condition | Next State | Action |
|---|---|---|---|---|
| `UP` / `UNKNOWN` | FAIL | `consecutive_fails < threshold` | `PENDING_DOWN` | Increment counter; suppress alert |
| `PENDING_DOWN` | FAIL | `consecutive_fails >= threshold` | `DOWN` | Send DOWN Alert; set cooldown window (15m) |
| `DOWN` | FAIL | In Cooldown Window | `DOWN` | Suppress alert spam |
| `DOWN` | FAIL | Cooldown Expired | `DOWN` | Send Reminder Alert; reset cooldown |
| `DOWN` | SUCCESS | `is_success == True` | `UP` | Send RECOVERY Alert; reset failure counter to 0 |
| `PENDING_DOWN` | SUCCESS | `is_success == True` | `UP` | Reset failure counter; suppress alert |

### 3.5 Two-Tier Telemetry Retention & Rollup Engine
- **Tier 1 (Raw Logs - `check_results`):**
  - Stores granular per-check latency, HTTP status, and SSL expiration days.
  - Retention Policy: Purged automatically after 7 days via background retention job.
- **Tier 2 (Aggregated SLA - `hourly_uptime_summary`):**
  - Background worker computes hourly rollups:
    $$\text{Uptime \%} = \left( \frac{\text{success\_checks}}{\text{total\_checks}} \right) \times 100$$
  - Stores average latency and uptime percentage per hour.
  - Retention Policy: Retained for 30–90 days for ultra-fast dashboard graph queries.

---

## 4. Database Schema (PostgreSQL 16)

```sql
-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
);
CREATE INDEX ix_users_email ON users(email);

-- Monitors table
CREATE TABLE monitors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
    name VARCHAR(100) NOT NULL,
    url TEXT NOT NULL,
    method VARCHAR(10) DEFAULT 'GET' NOT NULL,
    interval_seconds INT DEFAULT 60 NOT NULL,
    timeout_seconds INT DEFAULT 10 NOT NULL,
    expected_status_code INT DEFAULT 200 NOT NULL,
    consecutive_threshold INT DEFAULT 3 NOT NULL,
    current_status VARCHAR(20) DEFAULT 'UNKNOWN' NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
);
CREATE INDEX ix_monitors_user_id ON monitors(user_id);

-- Check results table (Raw Data - Retention: 7 Days)
CREATE TABLE check_results (
    id BIGSERIAL PRIMARY KEY,
    monitor_id UUID REFERENCES monitors(id) ON DELETE CASCADE NOT NULL,
    job_id UUID NOT NULL,
    status_code INT,
    response_time_ms INT,
    is_success BOOLEAN NOT NULL,
    error_message TEXT,
    ssl_days_remaining INT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
);
CREATE INDEX idx_check_results_monitor_created ON check_results(monitor_id, created_at DESC);

-- Hourly uptime summary table (Hourly Rollup - Retention: 90 Days)
CREATE TABLE hourly_uptime_summary (
    id BIGSERIAL PRIMARY KEY,
    monitor_id UUID REFERENCES monitors(id) ON DELETE CASCADE NOT NULL,
    hour_timestamp TIMESTAMPTZ NOT NULL,
    total_checks INT NOT NULL,
    success_checks INT NOT NULL,
    avg_response_time_ms INT NOT NULL,
    uptime_percentage NUMERIC(5,2) NOT NULL,
    UNIQUE (monitor_id, hour_timestamp)
);
CREATE INDEX idx_hourly_summary_monitor_time ON hourly_uptime_summary(monitor_id, hour_timestamp DESC);

-- Alert configurations table
CREATE TABLE alert_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    monitor_id UUID REFERENCES monitors(id) ON DELETE CASCADE NOT NULL,
    channel VARCHAR(20) NOT NULL, -- 'telegram', 'webhook', 'email'
    destination TEXT NOT NULL,
    is_enabled BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
);
```

---

## 5. Security & Isolation Architecture

1. **Anti-SSRF Protection:**
   - Hostname resolution enforces strict prohibition against RFC 1918 (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), RFC 3927 link-local (`169.254.0.0/16`), loopback (`127.0.0.0/8`, `::1`), and multicast addresses.
2. **Authentication & Authorization:**
   - Stateless JWT authentication signed with HMAC-SHA256.
   - Passwords hashed with salted bcrypt (`cost factor = 12`).
   - Tenant isolation enforced at database query level using `user_id` filtering.
3. **Container Hardening:**
   - Non-root user execution inside Docker containers.
   - Strict resource limits (CPU quotas, memory caps) preventing noisy neighbor starvation.

---

## 6. Observability & Telemetry (RED Metrics)

The system exposes Prometheus telemetry scraped on `/metrics`:

| Metric Name | Type | Description |
|---|---|---|
| `http_requests_total{handler, status}` | Counter | Inbound API Gateway throughput and HTTP response codes |
| `http_request_duration_seconds` | Histogram | Latency distribution of API Gateway requests |
| `checks_total{status}` | Counter | Total volume of probes executed by worker fleet |
| `check_duration_seconds` | Histogram | Network RTT and probe latency percentiles (p50, p95, p99) |
| `alert_events_total{channel, status}` | Counter | Outbound alert dispatch volume and notification success rate |
| `rabbitmq_queue_messages_ready` | Gauge | Queue depth of `check.jobs` (primary scaling trigger) |
