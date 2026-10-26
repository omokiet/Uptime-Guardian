# K6 Load Testing & Benchmarking — Uptime Guardian

Kịch bản kiểm thử tải thực tế cho toàn bộ hệ sinh thái **Uptime Guardian**, thiết kế đo lường throughput mục tiêu **>2.000 RPS** và độ trễ P95/P99.

---

## 1. Mục tiêu kiểm thử (SLA & Targets)

- **Target Throughput:** Đạt ngưỡng từ 2.000 đến 2.500 requests/giây (RPS).
- **Tỷ lệ lỗi (Error Rate):** `http_req_failed < 1%`.
- **Độ trễ (Latency SLA):**
  - Route Gateway (`/health`): $P_{95} < 50\text{ms}$.
  - Route Nghiệp vụ (`GET /monitors`): $P_{95} < 200\text{ms}$, $P_{99} < 500\text{ms}$.

---

## 2. Kịch bản phân phối tải (Traffic Distribution)

| Tỷ lệ | Endpoint | Mục đích đo lường |
| :--- | :--- | :--- |
| **45%** | `GET /health` | Trần chịu tải tối đa của Reverse Proxy Caddy + FastAPI ASGI |
| **40%** | `GET /api/v1/monitors?limit=20` | Tải truy vấn Database PostgreSQL kèm xác thực JWT & Phân trang |
| **10%** | `GET /api/v1/monitors/{id}` | Tải đọc chi tiết kèm lịch sử 20 lần check gần nhất |
| **5%** | `POST /api/v1/monitors` | Tải ghi nhận DB transaction và ghi ZSET vào Redis |

---

## 3. Cách chạy kịch bản (Execution Guide)

### Cách 1: Chạy trực tiếp bằng Binary K6 (Khuyến nghị)
1. Cài đặt k6 trên Windows:
   ```powershell
   winget install grafana.k6
   # hoặc
   choco install k6
   ```
2. Khởi động hệ thống Uptime Guardian:
   ```powershell
   docker compose -f docker/docker-compose.dev.yml up -d
   ```
3. Chạy benchmark:
   ```powershell
   k6 run tests/load/k6_benchmark.js
   ```

### Cách 2: Chạy qua Docker Container (Không cần cài k6)
```powershell
docker run --rm -i --network=host -v ${PWD}/tests/load:/scripts grafana/k6 run /scripts/k6_benchmark.js
```

### Cách 3: Tùy biến địa chỉ mục tiêu (Target URL)
Mặc định kịch bản nhắm vào `http://localhost:8000`. Khi benchmark qua Caddy Proxy (port 80):
```powershell
k6 run -e BASE_URL=http://localhost tests/load/k6_benchmark.js
```
