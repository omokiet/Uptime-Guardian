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

## 4. [ĐÃ XỬ LÝ] Khả năng mở rộng: Kênh thông báo cảnh báo cứng (Hardcoded Telegram)
- **Vị trí:** `services/alerter/notifiers.py` & `services/alerter/state_machine.py`
- **Trạng thái:** Đã xử lý (Branch `feature/notification-strategy-pattern`).
- **Giải pháp đã triển khai:**
  - Triển khai Strategy Pattern qua `BaseNotifier` interface tại `services/alerter/notifiers.py`.
  - Hỗ trợ đầy đủ các kênh: `TelegramNotifier`, `DiscordNotifier` (HTTP Webhook), `EmailNotifier` (`smtplib` + `EmailMessage` bất đồng bộ qua `asyncio.to_thread`).
  - Đăng ký và điều phối linh hoạt qua `NOTIFIER_REGISTRY` và `get_notifier()`.
  - Cơ chế cách ly lỗi: Lỗi của một kênh không làm ngắt các kênh còn lại; fallback an toàn về `TELEGRAM_DEFAULT_CHAT_ID` khi chưa có kênh nào gửi thành công.
  - Mở rộng cấu hình SMTP trong `services/common/config.py`.

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

## 9. [ĐÃ XỬ LÝ] Đồng bộ phân tán: Thiếu Distributed Lock cho Telemetry Maintenance Loop
- **Vị trí:** `services/scheduler/scheduler.py`
- **Trạng thái:** Đã xử lý (Atomic Redis lock `SET lock:maintenance:rollup:YYYYMMDDHH 1 NX EX 3600` và `SET lock:maintenance:retention:YYYYMMDD 1 NX EX 86400`).

---

## 10. [ĐÃ XỬ LÝ] API Gateway: Thiếu Phân trang (Pagination) & Rate Limiting
- **Vị trí:** `services/api_gateway/routers/monitors.py` (`list_monitors`) & `routers/auth.py`
- **Trạng thái:** Đã xử lý (Branch `fix/auth-rate-limiting`).
- **Giải pháp đã triển khai:**
  - Phân trang: Đã xử lý (`limit` mặc định 50, tối đa 100, `offset` mặc định 0).
  - Rate limiting tầng Auth: Triển khai `AuthRateLimiter` dependency bảo vệ `/login` (10 req/phút) và `/register` (5 req/5 phút). Sử dụng Redis atomic pipeline `INCR` + `EXPIRE NX`. Hỗ trợ trích xuất IP client từ `X-Forwarded-For` / `X-Real-IP`, cơ chế fail-open khi Redis gặp sự cố và trả về `HTTP 429 Too Many Requests` kèm header `Retry-After`.

---

## 11. [ĐÃ XỬ LÝ] Đồng bộ trạng thái: Thiếu cơ chế Reconciliation Loop cho Scheduler
- **Vị trí:** `services/scheduler/scheduler.py` & `services/scheduler/main.py`
- **Trạng thái:** Đã xử lý (Branch `fix/scheduler-reconciliation-loop`).
- **Giải pháp đã triển khai:**
  - Xây dựng hàm `reconcile_monitors_with_redis()`: Truy vấn lightweight chỉ lấy tập ID monitor active (`is_active=True`), đối chiếu tập hợp với member hiện có trong `scheduler:monitors`.
  - Tự động bổ sung monitor bị thiếu qua `pipe.zadd(..., nx=True)` (không ghi đè score đang lease) và loại bỏ orphan data qua `pipe.zrem()`.
  - Triển khai `run_reconciliation_loop(interval_seconds=300)` chạy nền định kỳ mỗi 5 phút với Redis distributed lock `SET lock:scheduler:reconciliation 1 NX EX 290` ngăn chặn xung đột multi-replica.
  - Tích hợp vào `asyncio.gather` trong `services/scheduler/main.py`.
