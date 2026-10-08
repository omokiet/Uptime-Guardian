# PROBLEMS & ARCHITECTURAL DEBT — Uptime Guardian

Tài liệu ghi nhận các vấn đề kiến trúc, lỗ hổng bảo mật và điểm nghẽn hiệu năng thực chiến trong môi trường Production.

---

## 1. [ĐÃ XỬ LÝ] Bảo mật: Anti-SSRF HTTP Redirect Bypass
- **Vị trí:** `services/checker/checker.py`
- **Trạng thái:** Đã xử lý (Branch `fix/p0-security-performance`).
- **Giải pháp đã triển khai:**
  - Tắt `follow_redirects=False`.
  - Tự bắt mã `301, 302, 303, 307, 308`, chuẩn hóa URL tương đối qua `urljoin`.
  - Kiểm tra vòng lặp chuyển hướng qua `visited_urls`, giới hạn `max_redirects = 5`.
  - Chạy `validate_target_url()` trên từng URL chuyển hướng để chặn dải IP private/loopback.

---

## 2. Bảo mật: DNS Rebinding (TOCTOU)
- **Vị trí:** `services/common/ssrf.py` và `services/checker/checker.py`
- **Vấn đề:** Thời điểm kiểm tra DNS (`validate_target_url`) và thời điểm gửi request thực tế (`httpx.request`) là hai thao tác phân giải DNS độc lập (Time-of-Check to Time-of-Use).
- **Rủi ro:** Kẻ tấn công cấu hình máy chủ DNS trả về IP công cộng ở lần phân giải đầu tiên (TTL = 0), nhưng trả về `127.0.0.1` ở lần phân giải thứ hai của httpx.
- **Giải pháp đề xuất:** 
  - Triển khai Custom Async Transport hoặc hook socket kết nối TCP để kiểm tra IP thực tế ngay trước khi handshake bắt đầu.

---

## 3. Hiệu năng & Lưu trữ: Nguy cơ Table Bloat ở bảng CheckResult
- **Vị trí:** `services/common/models.py` (Bảng `check_results`) và `services/common/rollup.py`
- **Vấn đề:** Toàn bộ log raw của tất cả monitors được ghi dồn vào một bảng đơn. Khi đạt quy mô lớn (> 10 triệu bản ghi), lệnh `DELETE` định kỳ gây table bloat, phân mảnh index và tốn tài nguyên Vacuum của PostgreSQL.
- **Rủi ro:** Suy giảm hiệu năng truy vấn lịch sử và tốn dung lượng đĩa.
- **Giải pháp đề xuất:**
  - Áp dụng PostgreSQL Declarative Table Partitioning theo thời gian (`RANGE (created_at)` theo tuần hoặc theo tháng). Khi hết hạn 7 ngày retention, thực thi `DROP TABLE partition` tức thì ($O(1)$) thay vì `DELETE`.
  - Nghiên cứu chuyển đổi sang TimescaleDB hoặc ClickHouse chuyên dụng cho telemetry time-series data.

---

## 4. Khả năng mở rộng: Kênh thông báo cảnh báo cứng (Hardcoded Telegram)
- **Vị trí:** `services/alerter/state_machine.py`
- **Vấn đề:** Hàm gửi cảnh báo đang gắn chặt với API của Telegram (`send_telegram_alert`), mặc dù bảng `alert_configs` đã có trường `channel`.
- **Rủi ro:** Thiếu hỗ trợ các kênh quan trọng như Discord Webhook, Slack Webhook, Email SMTP / SES.
- **Giải pháp đề xuất:**
  - Áp dụng Strategy Pattern / Adapter Interface: Khai báo interface `NotificationChannel` với các implementation cụ thể (`TelegramNotifier`, `DiscordNotifier`, `EmailNotifier`).
  - Đọc `AlertConfig.channel` để điều phối adapter phù hợp.

---

## 5. Khớp nối kiến trúc: Shared Kernel `services/common`
- **Vị trí:** `services/common/`
- **Vấn đề:** Các microservices độc lập (`api_gateway`, `scheduler`, `checker`, `alerter`) đều phụ thuộc trực tiếp vào chung một thư mục mã nguồn và DB models.
- **Rủi ro:** Vi phạm ranh giới dịch vụ (Service Boundary), thay đổi ở một service dễ gây ảnh hưởng ngoài ý muốn tới service khác.
- **Giải pháp đề xuất:**
  - Chuẩn hóa contracts giữa các service qua schema JSON/Protobuf rõ ràng.
  - Tách `services.common` thành internal Python package có semantic versioning khi mở rộng hệ thống.

---

## 6. Thiết kế mã nguồn: Thiếu phân tầng Clean Architecture ở API Gateway
- **Vị trí:** `services/api_gateway/routers/monitors.py`
- **Vấn đề:** Logic định tuyến (HTTP Router), logic nghiệp vụ và truy vấn cơ sở dữ liệu SQLAlchemy đang nằm chung trong một tệp.
- **Giải pháp đề xuất:**
  - Phân tách cấu trúc thành các tầng: `routers/` (HTTP controller) -> `services/` (Business logic) -> `repositories/` (Database access).

---

## 7. [ĐÃ XỬ LÝ] Hiệu năng: Tạo mới `httpx.AsyncClient` trên mỗi Job (Socket Exhaustion)
- **Vị trí:** `services/checker/checker.py` & `services/checker/main.py`
- **Trạng thái:** Đã xử lý (Branch `fix/p0-security-performance`).
- **Giải pháp đã triển khai:**
  - Khởi tạo client dùng chung `get_httpx_client()` với `Limits(max_connections=200, max_keepalive_connections=50, keepalive_expiry=30.0)`.
  - Tái sử dụng HTTP connection pool, giải quyết triệt để nguy cơ `TIME_WAIT` socket exhaustion.
  - Tự động đóng client an toàn với `close_httpx_client()` khi worker shutdown.

---

## 8. [ĐÃ XỬ LÝ] Độ tin cậy Message Queue: Nuốt lỗi âm thầm & Thiếu Dead Letter Queue (DLQ)
- **Vị trí:** `services/checker/main.py` & `services/alerter/main.py`
- **Trạng thái:** Đã xử lý (Branch `fix/p0-security-performance`).
- **Giải pháp đã triển khai:**
  - Loại bỏ hoàn toàn `except: pass`.
  - Ghi nhận `logger.error("...", exc_info=True)` đầy đủ traceback khi gặp lỗi không mong muốn.
  - Tăng Prometheus counter `CHECKER_PROCESSING_ERRORS_TOTAL.inc()` để phục vụ cảnh báo SRE.

---

## 9. Đồng bộ phân tán: Thiếu Distributed Lock cho Telemetry Maintenance Loop
- **Vị trí:** `services/scheduler/scheduler.py` (dòng 118-135)
- **Vấn đề:** Vòng lặp `run_telemetry_maintenance_loop()` chạy Rollup và Purge dựa vào thời gian đồng hồ cục bộ (`now.minute >= 5` và `now.hour == 3`).
- **Rủi ro:** Khi scale chạy 2-3 replicas của Scheduler để đảm bảo High Availability (HA), tất cả các replica sẽ đồng thời thực thi `aggregate_hourly_uptime()` và `purge_old_check_results()` cùng một lúc, gây lock bảng DB và trùng lặp tính toán.
- **Giải pháp đề xuất:** Sử dụng Redis Distributed Lock (`SET lock:maintenance:rollup 1 EX 300 NX`) để chỉ 1 replica duy nhất được thực hiện maintenance job trong mỗi chu kỳ.

---

## 10. API Gateway: Thiếu Phân trang (Pagination) & Rate Limiting
- **Vị trí:** `services/api_gateway/routers/monitors.py` (`list_monitors`) & `routers/auth.py`
- **Vấn đề:** Endpoint `GET /monitors` không có tham số `limit` và `offset`, trả về toàn bộ monitor của user. Endpoints `POST /login`, `POST /register` không có rate limit.
- **Rủi ro:** User sở hữu hàng ngàn monitor sẽ khiến API Gateway bị nghẽn RAM khi serialize dữ liệu (Memory Spike / OOM). Attacker có thể brute-force mật khẩu mà không bị chặn.
- **Giải pháp đề xuất:** Áp dụng Pagination bắt buộc (`limit` tối đa 100) và triển khai Redis Token Bucket rate limiting middleware cho tầng Auth.

---

## 11. Đồng bộ trạng thái: Thiếu cơ chế Reconciliation Loop cho Scheduler
- **Vị trí:** `services/scheduler/scheduler.py` (dòng 108)
- **Vấn đề:** Hàm `sync_active_monitors_to_redis()` chỉ được gọi duy nhất 1 lần khi tiến trình khởi động.
- **Rủi ro:** Nếu Redis bị khởi động lại (restart/failover) hoặc dữ liệu trong Redis ZSET bị xóa/evict trong khi scheduler đang chạy, danh sách monitor cần chạy sẽ bị mất hoàn toàn và hệ thống ngừng giám sát mà không tự hồi phục.
- **Giải pháp đề xuất:** Chạy một chu kỳ đối soát (Reconciliation loop) định kỳ mỗi 5–10 phút để quét lại các monitor `is_active=True` từ DB và bổ sung lại vào Redis ZSET nếu bị thiếu.
