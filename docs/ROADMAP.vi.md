# Uptime Guardian — Lộ Trình Kỹ Thuật & Các Mốc Phát Hành

[English](ROADMAP.md) | **Tiếng Việt**

> **Tầm nhìn:** Xây dựng một nền tảng giám sát uptime và chứng chỉ số phân tán, tự vận hành, có khả năng chịu lỗi cao nhằm thể hiện các mẫu thiết kế cốt lõi của hệ thống phân tán: lập lịch non-blocking, xử lý idempotent, finite state machine và observability toàn diện chuẩn SRE.

---

## Các Mốc Phát Hành (Release Milestones)

```
  v0.1.0 (Lõi Phân Tán)       ──►  v0.2.0 (Vận Hành SRE)      ──►  v0.3.0 (Scale & Cluster)
  [ĐÃ HOÀN THÀNH]                  [ĐANG TRIỂN KHAI]               [KẾ HOẠCH]
  • FastAPI + SQLAlchemy async    • Terraform dựng VPS           • Kubernetes k3s trên VPS
  • Redis ZSET Scheduler          • Prometheus + Grafana RED     • HPA Scale theo Queue Depth
  • Idempotent Checker Worker     • GitHub Actions CI/CD          • Quorum Check Multi-Region
  • Alert State Machine           • Rollup & Retention Cron       • Live WebSocket Telemetry
  • Phòng thủ Anti-SSRF           • k6 Benchmark (>2k RPS)
```

---

### Milestone 1: Lõi Phân Tán Cốt Lõi (v0.1.0) — `ĐÃ HOÀN THÀNH`
> **Trọng tâm:** Tính đúng đắn, kiểm soát concurrency và chuyển đổi trạng thái tiền định trên hạ tầng container cục bộ.

- [x] **Cơ Sở Dữ Liệu & Migrations:**
  - PostgreSQL 16 schema với toàn bộ timestamp chuẩn UTC (`TIMESTAMPTZ`), khóa ngoại xóa cascade và các index b-tree tối ưu.
  - SQLAlchemy 2.0 ORM bất đồng bộ với Alembic database migrations.
- [x] **API Gateway & Kiểm Soát Truy Cập:**
  - FastAPI service với xác thực phi trạng thái bằng JWT (băm mật khẩu bcrypt).
  - Đầy đủ API CRUD cho monitors và cấu hình các kênh cảnh báo.
  - Cơ chế Anti-SSRF phân giải DNS trước khi gọi mạng, chặn dải mạng RFC 1918, loopback và link-local.
- [x] **Lập Lịch Phân Tán Non-Blocking:**
  - Sử dụng Redis Sorted Set (`scheduler:monitors`) định thời chính xác tới mili-giây.
  - Lua script nguyên tử thực hiện leasing để loại trừ race condition khi chạy nhiều scheduler replica.
  - Đẩy message persistent vào RabbitMQ queue `check.jobs`.
- [x] **Đội Ngũ Checker Worker Idempotent:**
  - Thực thi kiểm tra bất đồng bộ (`httpx`), đo thời gian phản hồi (RTT) và kiểm tra status code.
  - Kiểm tra chứng chỉ TLS/SSL, tính số ngày còn hạn.
  - Cổng deduplication (`SET check:processed:<job_id> 1 EX 300 NX`) chống trùng lặp khi RabbitMQ redeliver.
- [x] **Finite State Machine & Cảnh Báo:**
  - Redis Hash state engine (`monitor:state:<id>`) theo dõi số lần fail liên tiếp và bộ đếm cooldown.
  - Khóa phân tán (`SETNX`) chống race condition cảnh báo giữa các worker node.
  - Tích hợp Telegram Bot gửi cảnh báo sự cố và tự động gửi tin thông báo khi dịch vụ phục hồi (Recovery).
- [x] **Giao Diện & Kiểm Thử Tự Động:**
  - Dashboard quản lý phong cách dark-mode (HTTP polling; live WebSockets trong v0.3.0).
  - Bộ test suite tự động đạt 117/117 unit và integration tests pass.

---

### Milestone 2: Vận Hành Production & SRE Observability (v0.2.0) — `ĐANG TRIỂN KHAI`
> **Trọng tâm:** Triển khai thực tế trên môi trường thật, hạ tầng dưới dạng mã (IaC), CI/CD tự động và giám sát đo lường.

#### Bảng Nghiệm Thu Theo Bằng Chứng Thực Tế (Evidence-Based Verification Matrix)

| Năng lực / Nhiệm vụ | Lệnh kiểm chứng (Evidence Command) | Kết quả mong đợi & Đo lường thực tế | Trạng thái |
| :--- | :--- | :--- | :---: |
| **Reverse Proxy (Caddy TLS)** | `curl -k -i https://localhost/health` | `HTTP/2 200`, `Server: Caddy`, `X-Frame-Options: DENY` | **ĐÃ XÁC MINH (100%)** |
| **RED Metrics (Grafana)** | `http://localhost:3000` (`uptime-guardian-red`) | Rate, 0% Error, Latency p95/p99 hiển thị real-time | **ĐÃ XÁC MINH (Gateway)** |
| **CI/CD Pipeline (GitHub)** | Kiểm tra checks của PR #1 | 3 runner Ubuntu (Backend, Frontend, Compose) hiện tích xanh | **ĐÃ XÁC MINH (PR #1)** |
| **PostgreSQL Partitioning** | `psql -c "\d+ check_results"` | `Partition key: RANGE (created_at)` & các partition tuần | **ĐÃ XÁC MINH (100%)** |
| **k6 Load Benchmark** | `k6 run tests/load/k6_benchmark.js` | Hoàn thành 24.254 iterations; baseline đơn node ~200 RPS | **ĐÃ XÁC MINH (Baseline)** |
| **Hạ tầng dạng mã (IaC)** | `terraform validate` | 0 lỗi cú pháp/cấu hình | **CHƯA TRIỂN KHAI** |

- [ ] **Hạ Tầng Dạng Mã (Terraform):**
  - Cấu hình `.tf` khai báo máy chủ VPS, tường lửa cloud firewall và bản ghi DNS A-record.
- [x] **Reverse Proxy & Tự Động Hóa TLS:**
  - Docker Compose production với restart policies, container healthcheck và volume lưu trữ bền vững.
  - Reverse proxy Caddy tự động quản lý TLS (internal TLS cho môi trường local/staging, sẵn sàng Let's Encrypt).
  - *Bằng chứng:* Lệnh `curl -k -i https://localhost/health` xác nhận trả về HTTP 200 kèm các HTTP security headers do Caddy gắn.
- [x] **Hệ Thống Giám Sát Đo Lường (RED Metrics):**
  - Prometheus metrics exporter cho API Gateway (`api_http_requests_total`, `api_http_request_duration_seconds`).
  - Dashboard Grafana giám sát lưu lượng throughput, tỷ lệ lỗi và độ trễ p95/p99.
  - *Bằng chứng:* Dashboard Grafana (`http://localhost:3000`) hiển thị đường cong phân vị p95/p99, throughput và tỷ lệ 5xx 0%.
  - [ ] Cấu hình scrape exporter riêng cho Worker & độ sâu hàng đợi RabbitMQ.
- [x] **Tích Hợp & Triển Khai Tự Động (GitHub Actions CI/CD):**
  - Kiểm tra tĩnh: Linter (Flake8), type validation và quét bảo mật SAST (Bandit).
  - Tự động chạy Pytest trên mỗi Pull Request (117 tests pass).
  - Multi-stage Docker build, tự động đẩy container image lên GitHub Container Registry (GHCR).
  - *Bằng chứng:* PR #1 (`feature/devops-lab-fixes` -> `staging`) vượt qua toàn bộ 3 job trên GitHub Actions runner.
  - [ ] Tự động SSH vào VPS, pull image mới và restart zero-downtime khi merge vào nhánh `main`.
  - [ ] Nâng cấp CI runner sử dụng Service Containers thật (PostgreSQL 16, Redis 7, RabbitMQ) thay vì mock.
- [x] **Động Cơ Rollup & Lưu Trữ Dữ Liệu 2 Tầng:**
  - Background cron gom nhóm dữ liệu thô `check_results` theo từng giờ vào bảng `hourly_uptime_summary` hỗ trợ backfill tự động.
  - Cơ chế tự động dọn dẹp (retention): Declarative PostgreSQL table partitioning tự động drop partition cũ hơn 7 ngày.
  - *Bằng chứng:* Migration `002_partition_check_results.py` phân vùng bảng thành công, tự động tạo trước 4 partition tuần qua `ensure_future_partitions()`.
- [x] **Benchmark Chịu Tải (k6):**
  - Kịch bản k6 kiểm thử tải toàn diện (`tests/load/k6_benchmark.js`).
  - *Bằng chứng:* Chạy k6 hoàn tất 24.254 iterations trong 4m50s, đo đạc được năng lực baseline ~200 RPS đơn node.
- [x] **Giao Diện Production React Dashboard (React 18 + Vite + Tailwind CSS):**
  - Nhánh riêng: `feature/UI` tách từ `staging`.
  - Thiết kế SaaS tối giản: Bảng màu Dark Zinc thanh lịch, đồng bộ 100% tiếng Anh chuẩn quốc tế và vi tương tác tinh tế.
  - Trực quan hóa: Biểu đồ độ trễ Recharts, theo dõi hạn chứng chỉ SSL, live status chips và form CRUD quản trị.
  - Xác thực biên dịch: TypeScript strict mode 0 lỗi, bundle tối ưu (612 kB).

---

### Milestone 3: Mở Rộng Cụm Phân Tán (v0.3.0) — `KẾ HOẠCH`
> **Trọng tâm:** Điều phối cụm container, tự động mở rộng theo tải và kiểm tra chéo đa khu vực.

- [ ] **Kubernetes Manifests & Đóng Gói Helm:**
  - Manifests triển khai chuẩn cho Kubernetes siêu nhẹ (`k3s`).
  - Helm chart khai báo số replica và hạn mức tài nguyên (resource quotas).
- [ ] **Tự Động Mở Rộng Theo Hàng Đợi (KEDA / HPA):**
  - Horizontal Pod Autoscaler tự động tăng/giảm số lượng Checker Worker dựa trên độ sâu hàng đợi RabbitMQ `check.jobs`.
- [ ] **Kiểm Tra Chéo Đa Khu Vực (Multi-Region Quorum):**
  - Triển khai worker tại nhiều vùng địa lý khác nhau để kiểm tra chéo, loại bỏ cảnh báo giả do nghẽn mạng cục bộ.
- [ ] **Luồng Dữ Liệu Realtime WebSocket:**
  - Stream dữ liệu trực tiếp đến dashboard client qua WebSocket mà không cần polling định kỳ.
