# AGENTS.md — Uptime Guardian AI Agent Guidelines

Trạm kiểm soát và quy chuẩn cộng tác dành cho các AI Agent (Antigravity / Pair Programming AI) hoạt động trên codebase Uptime Guardian.

---

## 1. Bản Đồ Tài Liệu Dự Án (Documentation Map)

Toàn bộ tài liệu kỹ thuật được gom gọn trong thư mục `docs/`:

- **README**: [README.md](file:///d:/repositary/UptimeGuardian/README.md) & [README.vi.md](file:///d:/repositary/UptimeGuardian/README.vi.md) — Tổng quan kiến trúc, quickstart và chỉ dẫn cài đặt.
- **ROADMAP**: [docs/ROADMAP.md](file:///d:/repositary/UptimeGuardian/docs/ROADMAP.md) & [docs/ROADMAP.vi.md](file:///d:/repositary/UptimeGuardian/docs/ROADMAP.vi.md) — Kế hoạch phát triển các Milestone và ma trận bằng chứng nghiệm thu (Evidence-based Verification).
- **SPEC TỔNG**: [docs/SPEC.md](file:///d:/repositary/UptimeGuardian/docs/SPEC.md) & [docs/SPEC.vi.md](file:///d:/repositary/UptimeGuardian/docs/SPEC.vi.md) — Đặc tả kiến trúc tổng thể, mô hình dữ liệu và các giao thức.
- **FEATURE SPECS (SDD)**: `docs/specs/` — Thư mục chứa đặc tả từng tính năng chi tiết theo tiêu chuẩn Spec-Driven Development.
  - [docs/specs/milestone-3-distributed-resilience.md](file:///d:/repositary/UptimeGuardian/docs/specs/milestone-3-distributed-resilience.md) — Multi-Region Quorum Consensus & WebSocket Telemetry.
- **PROBLEMS & DEBT**: [docs/PROBLEMS.md](file:///d:/repositary/UptimeGuardian/docs/PROBLEMS.md) — Sổ theo dõi nợ kiến trúc, lỗi bảo mật thực chiến và lịch sử xử lý.
- **DEVOPS LAB**: [docs/DEVOPS_GUIDE.md](file:///d:/repositary/UptimeGuardian/docs/DEVOPS_GUIDE.md) — Hướng dẫn thực hành lab SRE, chaos experiments và câu lệnh mẫu.

---

## 2. Quy Tắc Code Bắt Buộc (Strict Coding Rules)

1. **Cấm Local Import**: Tuyệt đối không import thư viện/module trong thân hàm. Mọi import phải đặt ở đầu file (top-level). Nếu bắt buộc vì lý do bất khả kháng, phải hỏi và được user duyệt trước.
2. **Cấm Comment Thừa**: Không comment giải thích "code đang làm gì". Chỉ comment giải thích "TẠI SAO (WHY)" cho các đoạn logic phân tán, thuật toán đặc biệt phức tạp.
3. **Khám Bệnh Trước (Pre-flight Analysis)**: Trước khi sinh code nghiệp vụ, bắt buộc phân tích Edge Cases (Timezone UTC, Race condition, Crash recovery, Orphan data...) và báo cáo giải pháp cho user duyệt "OK".
4. **Kiểm Soát Nhập/Xuất Dependencies**:
   - `requirements.txt`: Chỉ chứa runtime dependencies cho Production containers.
   - `requirements-dev.txt`: Chứa test runners, linters, SAST tools cho CI/Local dev.

---

## 3. Quy Trình Git & DevOps (Mentorship Mode)

- **Quy tắc Git**:
  - Nhánh bảo hộ: `main` (Production) và `staging` (Integration).
  - Tách nhánh con (`feature/*`, `fix/*`, `refactor/*`, `test/*`) từ `staging`.
  - Không tự ý chạy các lệnh Git đụng chạm remote (`commit`, `push`, `merge`, `rebase`, `tag`, `PR...`) khi chưa hỏi và được user duyệt "OK".
  - Khi hoàn thành tính năng và test/lint pass 100%, hỏi duyệt để merge nhánh con về lại `staging`.
- **Vai trò DevOps Mentor**:
  - Không tự ý làm hộ các thao tác terminal nếu nhằm mục đích rèn luyện người dùng.
  - Giải thích bản chất kỹ thuật "TẠI SAO" trước khi đưa câu lệnh mẫu cho user tự gõ.
