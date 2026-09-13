# Uptime Guardian

[English](README.md) | **Tiếng Việt**

> **Hệ thống giám sát Uptime & Chứng chỉ SSL phân tán — Xây dựng theo tư duy chuẩn kỹ thuật (Engineering-First).**

Nền tảng mã nguồn mở tự vận hành (self-hosted), chịu lỗi cao, được thiết kế để giải quyết triệt để các bài toán cốt lõi của hệ thống phân tán: **lập lịch phân tán O(log N), finite state machine, kiểm soát concurrency & race condition, worker idempotency, data rollup và observability chuẩn SRE**.

---

## Kiến Trúc Tổng Quan

```
                            ┌────────────────────────┐
                            │    React Dashboard     │
                            │ (Vite + Tailwind / UI) │
                            └───────────┬────────────┘
                                        │ REST (JWT)
                            ┌───────────▼────────────┐
                            │      API Gateway       │ ◄── [Reverse Proxy: Caddy / Nginx]
                            │   (FastAPI / Python)   │     (Cấp phát SSL HTTPS tự động)
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
│ RabbitMQ: check.jobs │                │ Lưu kết quả                │ Cập nhật state
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

## Các Bài Toán Kỹ Thuật Cốt Lõi Đã Giải Quyết

1. **Lập lịch phân tán với Redis Sorted Set (`ZADD`/`ZPOPMIN`):**
   - Loại bỏ hoàn toàn overhead quét và khóa bảng trong cơ sở dữ liệu.
   - Sắp xếp lịch kiểm tra theo Unix timestamp với độ phức tạp $O(\log N)$.
   - Sử dụng Lua script nguyên tử để chống race condition giữa nhiều scheduler replica.
2. **Alert State Machine & Chống Race Condition:**
   - Quản lý trạng thái chuyển đổi (`UP`, `PENDING_DOWN`, `DOWN`) với ngưỡng thất bại liên tiếp (dampening) và cửa sổ cooldown 15 phút trên Redis hash.
   - Sử dụng khóa phân tán `SETNX` ngăn chặn gửi cảnh báo trùng lặp giữa các worker.
3. **Tính Idempotency của Worker:**
   - Theo dõi mã duy nhất `job_id` (UUIDv4) với Redis `SET EX NX` (300s TTL) chống ghi đè dữ liệu hoặc gửi cảnh báo giả khi RabbitMQ redeliver message.
4. **Data Retention & Hourly Rollup 2 Tầng:**
   - Dữ liệu thô kiểm tra chi tiết được lưu trong 7 ngày.
   - Background cron tổng hợp định kỳ hàng giờ vào bảng `hourly_uptime_summary` để vẽ biểu đồ 30 ngày siêu nhẹ, tránh phình cơ sở dữ liệu PostgreSQL.
5. **Observability Chuẩn SRE:**
   - Xuất telemetry theo chuẩn RED (Rate, Errors, Duration) cho Prometheus và bảng điều khiển Grafana.
   - Đo lường chịu tải bằng k6 với năng lực xử lý >2,000 checks/giây.

---

## Ngăn Xếp Công Nghệ (Tech Stack)

- **Backend:** Python 3.13, FastAPI, SQLAlchemy 2.0 (Async), Alembic, Pydantic v2
- **Message Broker & Cache:** RabbitMQ, Redis 7
- **Database:** PostgreSQL 16
- **Frontend:** React 18, Vite, Tailwind CSS (kèm bản Vanilla UI tích hợp sẵn)
- **Hạ tầng & SRE:** Docker, Docker Compose, Caddy/Nginx, Terraform, Prometheus, Grafana
- **Testing & Chất lượng:** Pytest, pytest-asyncio, k6, Flake8, Bandit SAST

---

## Cấu Trúc Dự Án

```
uptime-guardian/
├── services/
│   ├── api_gateway/       # FastAPI REST API (CRUD monitors, auth, stats)
│   ├── scheduler/         # Redis ZSET distributed scheduler -> RabbitMQ producer
│   ├── checker/           # Async HTTP/SSL/DNS worker với cơ chế Idempotency
│   └── alerter/           # Telegram alert service với state machine & cooldown
├── docker/                # Docker Compose cho dev và production
├── tests/                 # Integration tests, unit tests, và benchmark k6
├── ROADMAP.vi.md          # Lộ trình kỹ thuật 3 mốc release
└── SPEC.vi.md             # Tài liệu đặc tả kiến trúc & kỹ thuật chi tiết
```

---

## Tóm Tắt Lộ Trình Triển Khai

- **Milestone 1 (v0.1.0): Lõi Phân Tán (Đã Hoàn Thành)** — Database schema, FastAPI Gateway, atomic Redis ZSET scheduler, idempotent checker, alert state machine, và dashboard realtime.
- **Milestone 2 (v0.2.0): Vận Hành Production & SRE Observability (Đang Triển Khai)** — Terraform IaC, reverse proxy TLS tự động, Prometheus/Grafana RED metrics, GitHub Actions CI/CD, React Tailwind dashboard, và k6 load test.
- **Milestone 3 (v0.3.0): Mở Rộng Cụm Phân Tán (Kế Hoạch)** — k3s orchestration, HPA auto-scaling theo độ dài hàng đợi RabbitMQ, multi-region quorum check, và live WebSocket telemetry.

Chi tiết kỹ thuật: Xem [ROADMAP.vi.md](./ROADMAP.vi.md) và [SPEC.vi.md](./SPEC.vi.md).
