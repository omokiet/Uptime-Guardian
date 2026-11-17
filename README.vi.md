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
                            └─────┬────────────▲─────┘
                        REST (JWT)│            │ WebSocket (/ws/telemetry)
                            ┌─────▼────────────┴─────┐
                            │      API Gateway       │ ◄── [Reverse Proxy: Caddy]
                            │   (FastAPI / Python)   │     (Cấp phát SSL HTTPS tự động)
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
│ RabbitMQ: check.jobs │                │ Lưu kết quả                │ State & Quorum
└──────────┬───────────┘                │                            │
           │ Consume                    │                            │
           ▼                            │                            │
┌───────────────────────────────────────┴────────────────────────┐   │
│                 Hạm Đội Regional Checker Workers               │   │
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
   - Dữ liệu thô kiểm tra chi tiết được lưu trong 7 ngày trên bảng PostgreSQL range partition theo tuần.
   - Background cron tổng hợp định kỳ hàng giờ vào bảng `hourly_uptime_summary` để vẽ biểu đồ 30 ngày siêu nhẹ, tránh phình cơ sở dữ liệu PostgreSQL.
5. **Observability Chuẩn SRE:**
   - Xuất telemetry theo chuẩn RED (Rate, Errors, Duration) cho Prometheus và bảng điều khiển Grafana.
   - Mục tiêu chịu tải thiết kế >2,000 checks/giây (số đo baseline đơn node hiện tại: ~200 RPS qua k6).
6. **Kiểm Định Đồng Thuận Đa Vùng (Multi-Region Quorum Consensus):**
   - Xác thực chéo out-of-band qua các vùng địa lý (`vn-han`, `sg-sin`, `us-iad`) sử dụng topic exchange `quorum.exchange`.
   - Quản lý phiên bỏ phiếu Redis (`quorum:session:<challenge_id>`) kèm atomic lock `HSETNX` trên quyết định, ngăn chặn bão cảnh báo giả do sự cố peering mạng cục bộ.
   - Fast-track chuyển ngay sang `DOWN` khi đa số vùng xác nhận hỏng, đồng thời tự động đánh dấu `is_suppressed=True` cho sự cố quá cảnh cục bộ để bảo vệ trọn vẹn 100% SLA khách hàng.
7. **Truyền Dữ Liệu Thời Gian Thực Qua Live WebSocket Gateway:**
   - Đẩy trực tiếp các sự kiện `check_result` và `status_change` lên Dashboard qua `/ws/telemetry` thông qua cơ chế multiplexing Redis Pub/Sub theo từng `user_id`.
   - Cơ chế buffer bounded queue (`asyncio.Queue(maxsize=100)`) với chiến lược `drop_oldest` triệt tiêu nguy cơ tràn RAM khi gặp client kết nối chậm (Slow Consumer).
   - Client React tự động phục hồi kết nối bằng thuật toán Exponential Backoff (1s, 2s, 4s, tối đa 10s).

---

## Ngăn Xếp Công Nghệ (Tech Stack)

- **Backend:** Python 3.13, FastAPI, SQLAlchemy 2.0 (Async), Alembic, Pydantic v2
- **Message Broker & Cache:** RabbitMQ, Redis 7
- **Database:** PostgreSQL 16 (Phân vùng theo tuần - Range Partitioning)
- **Frontend:** React 18, Vite, Tailwind CSS, Recharts
- **Hạ tầng & SRE:** Docker, Docker Compose, Caddy Reverse Proxy, Prometheus, Grafana
- **Testing & Chất lượng:** Pytest, pytest-asyncio (168 tests), k6, Flake8, Bandit SAST

---

## Cấu Trúc Dự Án

```
uptime-guardian/
├── services/
│   ├── api_gateway/       # FastAPI REST & WebSocket Gateway (/ws/telemetry, auth, monitors)
│   ├── scheduler/         # Redis ZSET distributed scheduler -> RabbitMQ producer
│   ├── checker/           # Multi-region probe workers (HTTP, SSL, Anti-SSRF, Quorum consumer)
│   ├── alerter/           # Quorum consensus engine + State machine notification service
│   ├── common/            # Module dùng chung (ORM models, dual-dialect schemas, Anti-SSRF)
│   └── dashboard/         # Giao diện dashboard React + Vite + Tailwind CSS
├── docker/                # Docker Compose cho dev và production
├── tests/                 # 168+ unit tests, integration tests, và benchmark k6
└── docs/                  # Tài liệu đặc tả kỹ thuật, roadmap, debt tracking & hướng dẫn
```

---

## Tóm Tắt Lộ Trình Triển Khai

- **Milestone 1 (v0.1.0): Lõi Phân Tán (Đã Hoàn Thành)** — Database schema, FastAPI Gateway, atomic Redis ZSET scheduler, idempotent checker, alert state machine, và dashboard cơ bản.
- **Milestone 2 (v0.2.0): Vận Hành Production & SRE Observability (Đã Hoàn Thành)** — Caddy TLS proxy, Prometheus/Grafana RED metrics, GitHub Actions CI/CD, phân vùng PostgreSQL range partitioning, và k6 load test.
- **Milestone 3 (v0.3.0): Khả Năng Chịu Lỗi Phân Tán & Live Telemetry (Đã Hoàn Thành)** — Multi-region quorum consensus verification, AMQP challenge topic exchange, Redis quorum voting aggregator, và live WebSocket telemetry stream.

Chi tiết kỹ thuật: Xem [ROADMAP.vi.md](docs/ROADMAP.vi.md) và [SPEC.vi.md](docs/SPEC.vi.md).
