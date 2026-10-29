# Kiến trúc triển khai

```text
ESP32-CAM / Wi-Fi STA
  ├─ POST heartbeat (token + device ID)
  ├─ GET config (phiên được gán + active)
  └─ POST multipart JPEG theo chu kỳ
       |
       v
Laptop / FastAPI (một process)
  ├─ token thiết bị, assignment và phiên đang mở
  ├─ rate-limit / một ảnh đang xử lý mỗi device
  ├─ giới hạn 5 MiB, JPEG/PNG, 4 MP trước khi decode
  ├─ Haar face detector + một mặt trong ROI + size/sharpness
  ├─ geometric stability IoU qua N frame liên tiếp theo device/session
  ├─ MiniFASNetV2 ONNX / CPU → real softmax index 1
  ├─ dlib embedding 128D → Euclidean distance + ambiguity margin
  ├─ SQLite transaction: recheck phiên/lớp/assignment/enrollment
  ├─ UNIQUE(session_id, student_id), đúng giờ/đi muộn
  └─ audit + WebSocket xác thực
       |
       v
Nginx /api và /ws → React dashboard
```

## Dữ liệu và quyền

- `classes`, `students`: hồ sơ và lớp hiện tại; `attendance_sessions`: draft → open → closed, không mở lại phiên đóng.
- `devices`, `device_configs`: heartbeat và assignment/ROI. Status online/offline tính từ TTL khi đọc API, không mặc định online mãi.
- `face_references`: embedding JSON, consent timestamp, giảng viên đăng ký; không public embedding qua API.
- `attendance`: unique cặp phiên/sinh viên; verification `face+pad:...` hoặc `manual:<username>`.
- `liveness_events`: kết quả/reason/thời gian/mã SV nếu có; endpoint trả tối đa 200 sự kiện mới nhất. Chưa có job tự xóa log; cần chính sách retention ở môi trường triển khai.

Giảng viên dùng bearer HMAC có hạn 8 giờ; secret là ADMIN_PASSWORD, thay secret vô hiệu token cũ. Thiết bị dùng shared DEVICE_TOKEN (prototype, chưa tách token từng camera). WS xác thực ở message đầu, kiểm tra lại khi nhận ping và trước broadcast. CORS không thay thế auth. Giới hạn ảnh và rate-limit nội bộ không thay thế reverse-proxy/network hardening khi public Internet.

## Enrollment và quyết định

Đăng ký khuôn mặt là thao tác giảng viên có consent; cần kiểm tra trực tiếp đúng người. Đúng một mặt và embedding hữu hạn; lưu embedding, không lưu bytes ảnh. Có endpoint thu hồi embedding mà không xóa lịch sử. Không nạp ảnh theo filename từ `data/faces` nữa.

Pipeline dùng cùng bbox đã qua ROI cho PAD và recognition, không tự phát hiện lại một người khác. PAD chỉ được chấp nhận khi model nạp, output đúng 1×3/hữu hạn, class thật đạt threshold và calibrated. Recognition cần dependency, calibrated và embedding trong lớp; best match vượt threshold hoặc gần second-best bị từ chối.

Stability chỉ là liên tục hình học theo IoU và khoảng cách thời gian, không chứng minh cùng danh tính hoặc hướng đi. Một người ngoài ROI không được chọn; nhiều người trong ROI bị reject. Thay camera/độ phân giải/góc lắp phải hiệu chỉnh lại.

## Tính nhất quán

SQLite foreign keys bật, busy timeout 5s. Điểm danh và đổi trạng thái phiên dùng write transaction `BEGIN IMMEDIATE`. Trước insert đọc lại phiên, lớp, assignment và tồn tại enrollment; unique constraint chặn duplicate cả khi request tranh chấp. Duplicate trả created=false, không ghi thêm attendance. Mở/đóng phiên, liveness và attendance phát sự kiện WS; frontend polling phục hồi khi WS mất.

Image inference chạy threadpool để không giữ event loop, mỗi device chỉ xử lý một frame; broadcast có timeout và loại kết nối lỗi. CPU inference không được bảo đảm realtime nếu laptop yếu. Chưa có queue phân tán, TLS server tích hợp, multi-worker/shared tracking hoặc benchmark tải nhiều camera.

## Docker và giới hạn

Backend UID 10001, frontend unprivileged, filesystem read-only + tmpfs. SQLite/embedding ở volume; model mount read-only. Không nhúng secrets/biometric vào image. Xem docker.md để build và backup.

Phần mềm không có đánh giá thực tế đủ để khẳng định chống giả mạo ảnh in/replay, FAR/FRR hoặc latency ESP32. Mặc định calibrated=false. Thiếu/lỗi AI không được ghi tự động; dùng xác minh trực tiếp thủ công có audit và nhãn riêng. SQLite/embedding hiện không mã hóa tại ứng dụng, phải bảo vệ ổ đĩa và backup.
