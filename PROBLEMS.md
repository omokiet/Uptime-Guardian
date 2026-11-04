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

## 2. [ĐÃ XỬ LÝ] Bảo mật: DNS Rebinding (TOCTOU)
- **Vị trí:** `services/common/ssrf.py`, `services/common/transport.py` và `services/checker/checker.py`
- **Trạng thái:** Đã xử lý (Branch `feature/anti-dns-rebinding`).
- **Giải pháp đã triển khai:**
  - Tách hàm `is_ip_allowed` và `resolve_safe_ip` tại `services/common/ssrf.py`, kiểm tra toàn bộ các bản ghi IP được phân giải (IPv4/IPv6). Nếu bất kỳ bản ghi nào thuộc dải private/loopback/link-local/multicast/reserved thì từ chối ngay.
  - Xây dựng `AntiRebindingNetworkBackend` kế thừa `httpcore._backends.auto.AutoBackend`: phân giải DNS và xác thực IP trực tiếp ngay trước khi kết nối TCP, pin socket kết nối thẳng tới `safe_ip` đã được xác thực, ngăn chặn triệt để TOCTOU giữa bước check và bước connect.
  - Xây dựng `AntiRebindingTransport` kế thừa `httpx.AsyncHTTPTransport`, tích hợp vào `get_httpx_client()`.
  - Cập nhật `check_ssl_days` ghim IP kết nối trực tiếp tới `safe_ip` đồng thời giữ nguyên `server_hostname` để xác thực TLS certificate và SNI chuẩn xác.

---

## 3. [ĐÃ XỬ LÝ] Hiệu năng & Lưu trữ: Nguy cơ Table Bloat ở bảng CheckResult
- **Vị trí:** `services/common/partitions.py`, `services/common/rollup.py`, `alembic/versions/002_partition_check_results.py`
- **Trạng thái:** Đã xử lý (Branch `feature/table-partitioning`).
- **Giải pháp đã triển khai:**
  - Áp dụng PostgreSQL Declarative Table Partitioning theo thời gian (`RANGE (created_at)` theo tuần với default partition fail-safe).
  - Tự động tạo trước 4 tuần partition và default partition qua `ensure_future_partitions()`.
  - Cơ chế retention 7 ngày: Thực thi `drop_expired_partitions()` xóa partition cũ tức thì ($O(1)$) thay vì chạy lệnh `DELETE` gây table bloat và WAL write amplification. Fallback an toàn về batch `DELETE` khi chạy trên SQLite.
  - Tích hợp bảo trì tự động vào cron 03:00 UTC hàng ngày của Scheduler.

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

## 6. [ĐÃ XỬ LÝ] Thiết kế mã nguồn: Thiếu phân tầng Clean Architecture ở API Gateway
- **Vị trí:** `services/api_gateway/routers/monitors.py`, `alerts.py`, `services/`, `repositories/`
- **Trạng thái:** Đã xử lý (Branch `refactor/api-gateway-layers`).
- **Giải pháp đã triển khai:**
  - Tách tầng Repository: `MonitorRepository`, `CheckResultRepository`, `AlertConfigRepository`, `HourlySummaryRepository` phụ trách truy vấn SQLAlchemy thuần túy, không commit transaction trong repo.
  - Tách tầng Service: `MonitorService`, `AlertService` phụ trách nghiệp vụ, phân quyền ownership theo `current_user`, điều phối Redis (`zadd`/`zrem`/`delete`) kèm error handling fail-safe, quản lý transaction commit.
  - Tầng Router: `monitors.py`, `alerts.py` trở thành thin controller, chỉ tiếp nhận HTTP request, dependency injection, gọi service và trả về schema DTO.

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

---

## 12. [ĐÃ XỬ LÝ] Bảo mật & Hợp đồng API: SSRF qua Notifier Webhook & Bất nhất Schema AlertConfig
- **Vị trí:** `services/alerter/notifiers.py`, `services/common/schemas.py`
- **Trạng thái:** Đã xử lý (Branch `feature/anti-dns-rebinding` & `fix/p0-security-performance`).
- **Giải pháp đã triển khai:**
  - Áp dụng `AntiRebindingTransport(verify=True)` bảo vệ các outbound request trong `DiscordNotifier` và `WebhookNotifier`.
  - Cập nhật regex schema `AlertConfigCreate` sang `^(telegram|email|discord|webhook)$` và bổ sung field validator `check_destination_safety` gọi `validate_target_url` phòng thủ anti-SSRF.

---

## 13. [ĐÃ XỬ LÝ] Hiệu năng & Scale: AMQP Channel Churn & Re-declare Queue trên mỗi tin nhắn
- **Vị trí:** `services/common/rabbitmq.py`
- **Trạng thái:** Đã xử lý (Branch `fix/p0-security-performance`).
- **Giải pháp đã triển khai:**
  - Tái sử dụng channel dùng chung qua `get_publish_channel()`, loại bỏ thao tác open/close channel liên tục trên mỗi message.
  - Cache tập hợp `_declared_queues` trong memory để chỉ khai báo queue 1 lần duy nhất lúc khởi động service.
  - `publish_message` phát hành trực tiếp qua `channel.default_exchange.publish` với chế độ persistent delivery.

---

## 14. [ĐÃ XỬ LÝ] Độ tin cậy & Dữ liệu: Alerter Lock Contention làm nuốt mất Alert Event vĩnh viễn
- **Vị trí:** `services/alerter/state_machine.py`, `services/alerter/main.py`
- **Trạng thái:** Đã xử lý (Branch `fix/p0-security-performance`).
- **Giải pháp đã triển khai:**
  - Tăng số lần thử lấy distributed lock lên 4 lần trong `handle_alert_event`, ném `TimeoutError` nếu không thành công sau backoff.
  - Alerter consumer bọc trong `message.process(requeue=True)` để tự động reject và đẩy lại message vào hàng đợi RabbitMQ thay vì nuốt mất message.

---

## 15. [ĐÃ XỬ LÝ] Bảo mật: Bypass Auth Rate Limiting bằng giả mạo Header IP `X-Forwarded-For`
- **Vị trí:** `services/api_gateway/rate_limiter.py` (`get_client_ip`)
- **Trạng thái:** Đã xử lý (Branch `fix/remaining-problems-and-ui`).
- **Giải pháp đã triển khai:**
  - Định nghĩa dải CIDR tin cậy `TRUSTED_PROXIES` ở cấp module (`127.0.0.0/8`, `::1/128`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`).
  - Hàm `get_client_ip` chỉ tin tưởng và bóc tách IP từ `X-Forwarded-For` / `X-Real-IP` khi `settings.TRUST_PROXY=True` VÀ IP kết nối trực tiếp (`request.client.host`) thuộc danh sách trusted reverse proxy.
  - Xác thực cú pháp IP qua `ipaddress.ip_address` để triệt tiêu injection vào Redis keys, fallback an toàn về `request.client.host`.

---

## 16. [ĐÃ XỬ LÝ] Độ ổn định: Race Condition khi Register User gây 500 Unhandled IntegrityError
- **Vị trí:** `services/api_gateway/routers/auth.py`
- **Trạng thái:** Đã xử lý (Branch `staging`).
- **Giải pháp đã triển khai:**
  - Bọc khối `await db.commit()` trong `try...except IntegrityError`, tự động `await db.rollback()`.
  - Ném `HTTPException(status_code=400, detail="Email đã được đăng ký")` an toàn, ngăn chặn phát sinh lỗi HTTP 500 unhandled.

---

## 17. [ĐÃ XỬ LÝ] Toàn vẹn Dữ liệu: Thiếu cơ chế Backfill Rollup khi Scheduler Downtime
- **Vị trí:** `services/common/rollup.py` & `services/scheduler/scheduler.py`
- **Trạng thái:** Đã xử lý (Branch `feature/table-partitioning`).
- **Giải pháp đã triển khai:**
  - Bổ sung hàm `backfill_missing_hourly_summaries(session, hours=24)`: Duyệt 24 giờ gần nhất, tìm các mốc giờ có `CheckResult` nhưng chưa có `HourlyUptimeSummary`.
  - Tự động gọi `aggregate_hourly_uptime` tổng hợp bù dữ liệu vào DB.
  - Tích hợp chạy tự động 1 lần lúc Scheduler khởi động và lặp lại định kỳ trong maintenance loop hàng giờ.

---

## 18. [ĐÃ XỬ LÝ] Độ tin cậy: Idempotency Lock đặt trước khiến Check Job bị bỏ rơi khi Worker Crash
- **Vị trí:** `services/checker/checker.py` (`process_check_job`)
- **Trạng thái:** Đã xử lý (Branch `fix/remaining-problems-and-ui`).
- **Giải pháp đã triển khai:**
  - Áp dụng mô hình khóa 2 pha (Two-phase idempotency lease):
    1. Pha in-flight: Đặt khóa ngắn hạn `lock:check:{job_id}` (TTL 30s) bằng `SET NX`. Nếu worker crash giữa chừng, sau 30s khóa tự hết hạn để RabbitMQ redelivery có thể thực thi lại.
    2. Pha hoàn tất: Chỉ ghi nhận khóa idempotency dài hạn `check:processed:{job_id}` (TTL 300s) sau khi DB transaction commit và alert event publish thành công.
  - Giải phóng `lock:check:{job_id}` trong khối `finally`.

---

## 19. [ĐÃ XỬ LÝ] Chức năng API: Thiếu chỉ số thống kê 24h trong `MonitorDetailResponse`
- **Vị trí:** `services/api_gateway/services/monitor_service.py` (`get_monitor_detail`)
- **Trạng thái:** Đã xử lý (Branch `fix/remaining-problems-and-ui`).
- **Giải pháp đã triển khai:**
  - Tích hợp `hourly_summary_repo.get_by_monitor_id(monitor.id, hours=24)` vào `get_monitor_detail`.
  - Tính toán tỷ lệ `uptime_percentage_24h` và độ trễ phản hồi trung bình gia quyền `avg_response_time_24h` theo số lượng checks từng giờ.
  - Bổ sung fallback tự động tính toán từ `recent_checks` cho monitor mới tạo trong 1 giờ đầu tiên.

---

## 20. [ĐÃ XỬ LÝ] Tài nguyên hệ thống: Rò rỉ Socket File Descriptor trong `check_ssl_days` khi Timeout
- **Vị trí:** `services/checker/checker.py` (`check_ssl_days`)
- **Trạng thái:** Đã xử lý (Branch `fix/remaining-problems-and-ui`).
- **Giải pháp đã triển khai:**
  - Bọc việc đóng `writer.close()` và `await writer.wait_closed()` trong khối `finally` với `try...except Exception: pass`.
  - Triệt tiêu hoàn toàn rò rỉ socket file descriptor và cảnh báo `ResourceWarning: unclosed <socket.socket>` khi handshake timeout.

---

## 21. [ĐÃ XỬ LÝ] Trải nghiệm người dùng (UX): Biểu đồ và danh sách Dashboard không tự refresh (Clunky tracking)
- **Vị trí:** `services/dashboard/src/App.tsx`, `services/dashboard/src/components/MonitorDetailModal.tsx`
- **Trạng thái:** Đã xử lý (Branch `fix/remaining-problems-and-ui`).
- **Giải pháp đã triển khai:**
  - Thêm bộ chọn Auto-Refresh kiểu Grafana (`Off`, `5s`, `10s`, `15s`, `30s`, `1m`) trên Toolbar của trang chủ Dashboard và Header của Monitor Detail Modal.
  - Tự động gọi ngầm `fetchDetail()` và `fetchMonitors()` định kỳ mà không gây giật lag giao diện hay reset vị trí cuộn.

