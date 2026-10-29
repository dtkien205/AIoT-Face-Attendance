# Kết quả kiểm thử phần mềm — 2026-10-29

## Đã thực hiện

- `python -m unittest discover -s tests -v`: **41 tests PASS** trong môi trường Python kiểm thử Linux ngoài Docker.
- `python -m compileall`: mã Python app/tests/seed/evaluate_pad/camera_bridge qua kiểm tra cú pháp.
- Frontend `tsc -b && vite build`: PASS trong bản sao kiểm thử trên filesystem Linux (dependency trên /mnt/d từng bị hỏng).
- `docker compose --profile camera-ap config --quiet`: PASS; chỉ kiểm tra cấu hình, **không build/chạy container** theo yêu cầu người dùng.
- MiniFASNetV2 ONNX thật đã nạp được, input `batch_size × 3 × 80 × 80`. Chưa đo độ chính xác thực tế.

| Nhóm | Kiểm thử đã có |
|---|---|
| API/auth | Bearer bắt buộc, sai mật khẩu/token thiết bị, WebSocket không auth bị đóng |
| CRUD | Mã SV trùng/normalize, lớp không tồn tại, sửa hồ sơ, không xóa lớp/hồ sơ có lịch sử |
| Enrollment | Consent bắt buộc, lưu/thu hồi embedding, không lưu ảnh thô (encode được mock) |
| Attendance | Đúng lớp, phiên mở/đóng, chống trùng, đi muộn, manual có audit, CSV |
| AI pipeline | Chờ nhiều frame, PAD reject/lỗi fail-closed, output NaN/label thật/calibrated, preprocessing BGR đúng |
| WebSocket | Auth hợp lệ, nhận liveness/attendance và session close |
| Device/ROI | ROI trái/phải không hợp lệ, TTL offline, image format/dimensions |
| SoftAP bridge | Camera failure không heartbeat; idle/active; multipart giữ JPEG binary; chỉ tin accepted của backend; reload config |
| Camera latency | MJPEG chia chunk, bộ đệm latest-only/stale, AI không kéo lùi video, WebSocket binary/ACK bỏ backlog, auth camera socket |
| Camera preview | Auth bắt buộc, preview không attendance, ảnh không cache, thiếu ảnh/TTL/capacity và không ghi đè kết quả frame mới bằng frame cũ |
| Domain/report | ROI, normalize dấu, roster duplicate, filename ambiguous, CSV formula neutralization, APCER/BPCER arithmetic |

Trong bài kiểm thử lỗi AI cố ý, server log `RuntimeError: model failed` là mock có chủ đích; assertion xác nhận không ghi attendance và test PASS. Các ca AI accepted/embedding đều mock, **không chứng minh mô hình nhận đúng người/chống ảnh giả**.

## Chưa thực hiện / cần ghi số liệu khi chạy thực

| Kịch bản thực tế | Kết quả mong đợi | Trạng thái |
|---|---|---|
| Firmware AI Thinker mới biên dịch/nạp | SoftAP hoặc STA đúng chế độ | Chưa có board/Arduino CLI trong phiên |
| Laptop nối Wi-Fi ESP32, /capture | JPEG ổn định, bridge forward | Camera đang ở máy khác; chưa kiểm tra mạng thực |
| Docker images/runtime | Build/chạy healthy, WS proxy, volume persist | Người dùng tự build/chạy |
| Người thật đã đăng ký | Nhận đúng khi đủ điều kiện | Chưa có dữ liệu consent để đo |
| Người ngoài ROI/nhiều mặt/thoáng qua/mờ | Không ghi | Logic có; chưa đo camera thật |
| Ảnh in/video phát điện thoại | PAD reject với tỷ lệ đo được | Chưa đo APCER/BPCER |
| Người chưa đăng ký/giống nhau | Reject với FAR/FRR đo được | Chưa đo |
| Mất camera/mạng | Offline sau TTL, không success giả | Unit test có; chưa thử phần cứng |
| Tốc độ laptop/ESP32 | Latency phù hợp interval/tracking gap | Chưa benchmark |

Thu thập calibration và held-out test độc lập theo model-evaluation.md. Ghi camera, ánh sáng, attack type, số mẫu, threshold, APCER/BPCER, FAR/FRR và latency. Không tuyên bố chống giả mạo tuyệt đối hoặc biến kết quả unit test thành kết quả đo AI.
