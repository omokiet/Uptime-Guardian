# Uptime Guardian — Đặc Tả Kiến Trúc & Thiết Kế Kỹ Thuật Hệ Thống

[English](SPEC.md) | **Tiếng Việt**

> **Trạng thái:** Active / Thiết Kế Production  
> **Loại tài liệu:** System Architecture RFC & Engineering Specification  
> **Mục tiêu:** Hệ thống giám sát Uptime & Chứng chỉ SSL phân tán, chịu lỗi cao

---

## 1. Tổng Quan Hệ Thống & Mục Tiêu Kỹ Thuật

### 1.1 Bài Toán Thực Tế
Các dịch vụ web trong môi trường thực tế luôn đối mặt với rủi ro: nghẽn mạng cục bộ, sự cố DNS, chứng chỉ SSL hết hạn đột ngột hoặc suy giảm hiệu năng tạm thời. Các công cụ giám sát thông thường thường gặp phải:
1. **Báo Động Rác (Alert Fatigue):** Một vài gói tin rớt tức thời đã kích hoạt cảnh báo gây nhiễu cho đội vận hành.
2. **Nghẽn Khóa Database:** Liên tục quét cơ sở dữ liệu với `SELECT ... WHERE next_run <= NOW()` gây khóa bảng và cạn kiệt IOPS ở quy mô lớn.
3. **Xung Đột Concurrency & Xử Lý Trùng Lặp:** Nhiều worker cùng lúc nhận kiểm tra 1 target hoặc gửi nhiều cảnh báo trùng nhau khi mạng trễ.
4. **Phình Dữ Liệu:** Dữ liệu log ping thô tích lũy không giới hạn làm suy thoái hiệu năng truy vấn của toàn bộ hệ thống.

### 1.2 Mục Tiêu Kỹ Thuật
Uptime Guardian được thiết kế theo tư duy **Engineering-First** với các cam kết kỹ thuật chặt chẽ:
- **Lập Lịch Phân Tán O(log N):** Ứng dụng Redis Sorted Sets để lập lịch hàng triệu tác vụ định kỳ mà không khóa bảng cơ sở dữ liệu.
- **Tính Idempotency Tuyệt Đối Của Worker:** Đảm bảo ngữ nghĩa thực thi duy nhất (single-execution semantics) thông qua token phân tán (`job_id`) và kiểm tra nguyên tử có thời hạn (TTL).
- **Alert State Machine Với Cơ Chế Hysteresis:** Chuyển đổi trạng thái có kiểm soát (`UP` ⇄ `PENDING_DOWN` ⇄ `DOWN`) kết hợp ngưỡng thất bại liên tiếp (dampening) và cửa sổ cooldown 15 phút.
- **Cơ Chế Lưu Trữ Dữ Liệu 2 Tầng (Rollup Engine):** Dữ liệu đo lường chi tiết được giữ trong 7 ngày, tổng hợp định kỳ hàng giờ thành báo cáo SLA/SLO lưu trữ 30–90 ngày.
- **Phòng Thủ Chiều Sâu (Anti-SSRF):** Phân giải DNS trước khi gọi mạng, ngăn chặn các cuộc tấn công Server-Side Request Forgery hướng vào mạng nội bộ hoặc dải loopback.

---

## 2. Kiến Trúc Hệ Thống & Topo Thành Phần

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

## 3. Đặc Tả Chi Tiết Các Hệ Thống Con

### 3.1 Hệ Thống Con Lập Lịch Phân Tán (Redis Sorted Set)
- **Cấu trúc Key:** `scheduler:monitors`
- **Member:** `monitor_id` (chuỗi UUIDv4)
- **Score:** `next_check_timestamp` (Unix epoch mili-giây)
- **Thuật toán Dispatch nguyên tử:**
  1. Scheduler thực thi một Lua script nguyên tử định kỳ mỗi 1,000ms:
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
  2. Kỹ thuật lease này ngăn chặn hoàn toàn race condition giữa các replica scheduler chạy song song.
  3. Với mỗi monitor đến hạn, scheduler gửi job payload vào RabbitMQ queue `check.jobs` và cập nhật điểm số mới `now + (interval_seconds * 1000)`.

### 3.2 Đội Ngũ Checker Worker & Công Cụ Kiểm Tra Mạng
- **Cơ chế tiêu thụ:** Lắng nghe RabbitMQ queue `check.jobs` với prefetch có kiểm soát (`QOS = 10`).
- **Quy trình kiểm tra mạng:**
  1. **Cổng kiểm tra Anti-SSRF:** Phân giải hostname qua DNS. Nếu IP thuộc dải private/loopback/link-local (RFC 1918, RFC 3927, loopback `127.0.0.0/8`, `::1`), lập tức từ chối kết nối.
  2. **Thực thi HTTP bất đồng bộ:** Gửi request non-blocking bằng `httpx.AsyncClient` với timeout tùy biến (1–120s). Đo lường status code và thời gian phản hồi khứ hồi (RTT ms).
  3. **Kiểm tra hạn chứng chỉ SSL:** Thiết lập TLS socket handshake bóc tách trường `notAfter` để tính số ngày hiệu lực còn lại.
  4. **Kiểm tra độ trễ DNS:** Đo thời gian phân giải DNS và phát hiện sớm các lỗi NXDOMAIN hoặc timeout phân giải tên miền.

### 3.3 Tính Idempotency Của Worker & Chống Trùng Lặp
Để đảm bảo ngữ nghĩa xử lý "tối đa 1 lần" khi RabbitMQ gửi lại message (redelivery) do mạng rớt hoặc container worker khởi động lại:
- Worker chạy lệnh nguyên tử: `SET check:processed:<job_id> 1 EX 300 NX`
- Nếu key đã tồn tại: Lập tức `ACK` bỏ qua, không kiểm tra mạng lại và không ghi đè dữ liệu vào database.
- Nếu key chưa tồn tại: Thực thi toàn bộ quy trình kiểm tra, lưu vào PostgreSQL `check_results`, và gửi sự kiện vào RabbitMQ `alert.events`.

### 3.4 Alert State Machine (Finite State Machine với Hysteresis)
- **Lưu trữ State:** Redis Hash `monitor:state:<monitor_id>`
  - Các trường: `status` (`UP`, `PENDING_DOWN`, `DOWN`), `consecutive_fails`, `last_alert_at`, `cooldown_until`.
- **Khóa Concurrency Phân Tán:** `SET lock:alert:<monitor_id> 1 EX 10 NX` đảm bảo quá trình chuyển đổi trạng thái luôn nguyên tử giữa các alerter worker song song.
- **Bảng Ma Trận Chuyển Đổi Trạng Thái:**

| Trạng thái hiện tại | Kết quả kiểm tra | Điều kiện | Trạng thái mới | Hành động |
|---|---|---|---|---|
| `UP` / `UNKNOWN` | THẤT BẠI | `consecutive_fails < threshold` | `PENDING_DOWN` | Tăng bộ đếm; chặn gửi alert |
| `PENDING_DOWN` | THẤT BẠI | `consecutive_fails >= threshold` | `DOWN` | Gửi DOWN Alert; kích hoạt cooldown 15m |
| `DOWN` | THẤT BẠI | Đang trong cửa sổ cooldown | `DOWN` | Chặn spam tin nhắn |
| `DOWN` | THẤT BẠI | Cooldown đã hết hạn | `DOWN` | Gửi tin Reminder Alert; gia hạn cooldown |
| `DOWN` | THÀNH CÔNG | `is_success == True` | `UP` | Gửi tin RECOVERY Alert; reset bộ đếm về 0 |
| `PENDING_DOWN` | THÀNH CÔNG | `is_success == True` | `UP` | Reset bộ đếm thất bại; không gửi alert |

### 3.5 Cơ Chế Lưu Trữ Dữ Liệu 2 Tầng (Rollup Engine)
- **Tầng 1 (Dữ liệu thô - `check_results`):**
  - Lưu chi tiết độ trễ, HTTP status, số ngày hạn SSL của từng lượt kiểm tra.
  - Chính sách lưu trữ: Tự động xóa sau 7 ngày qua cron dọn dẹp nền.
- **Tầng 2 (Dữ liệu tổng hợp SLA - `hourly_uptime_summary`):**
  - Worker tính toán định kỳ hàng giờ:
    $$\text{Tỷ lệ Uptime \%} = \left( \frac{\text{số\_lượt\_thành\_công}}{\text{tổng\_số\_lượt\_kiểm\_tra}} \right) \times 100$$
  - Lưu độ trễ trung bình và tỷ lệ uptime theo từng giờ.
  - Chính sách lưu trữ: Giữ lại 30–90 ngày phục vụ render biểu đồ dashboard siêu tốc.

---

## 4. Lược Đồ Cơ Sở Dữ Liệu (PostgreSQL 16 Schema)

```sql
-- Bảng người dùng
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
);
CREATE INDEX ix_users_email ON users(email);

-- Bảng Monitor
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

-- Bảng kết quả check thô (Retention: 7 Ngày)
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

-- Bảng tổng hợp theo giờ (Hourly Rollup - Retention: 90 Ngày)
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

-- Bảng cấu hình kênh cảnh báo
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

## 5. Kiến Trúc Bảo Mật & Cô Lập Môi Trường

1. **Phòng vệ Anti-SSRF:**
   - Cơ chế phân giải tên miền nghiêm ngặt chặn toàn bộ dải IP riêng RFC 1918 (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), RFC 3927 link-local (`169.254.0.0/16`), loopback (`127.0.0.0/8`, `::1`) và multicast.
2. **Xác thực & Ủy quyền:**
   - Stateless JWT authentication ký bằng thuật toán HMAC-SHA256.
   - Mật khẩu người dùng được băm bằng bcrypt có salt ngẫu nhiên (`cost factor = 12`).
   - Phân tách tenant tuyệt đối ở tầng truy vấn SQL thông qua trường `user_id`.
3. **Hardening Container:**
   - Container chạy dưới quyền non-root.
   - Áp dụng quota CPU và Memory cap chặt chẽ chống hiện tượng noisy neighbor.

---

## 6. Giám Sát Đo Lường (Chuẩn RED Metrics)

Hệ thống xuất telemetry cho Prometheus thu thập tại endpoint `/metrics`:

| Tên Metric | Kiểu | Mô tả |
|---|---|---|
| `http_requests_total{handler, status}` | Counter | Lưu lượng request và mã phản hồi HTTP của API Gateway |
| `http_request_duration_seconds` | Histogram | Phân phối độ trễ xử lý của API Gateway |
| `checks_total{status}` | Counter | Tổng số lượt probe được worker fleet thực hiện |
| `check_duration_seconds` | Histogram | Độ trễ RTT và các phân vị latency (p50, p95, p99) |
| `alert_events_total{channel, status}` | Counter | Số lượng thông báo cảnh báo đã phát đi và tỷ lệ thành công |
| `rabbitmq_queue_messages_ready` | Gauge | Độ sâu hàng đợi `check.jobs` (trigger chính để scale worker) |
