# Firmware ESP32-CAM — AI Thinker

Firmware hiện dùng **Wi-Fi STA + gửi JPEG**, không còn SoftAP/stream demo cũ. Không chạy AI trên ESP32 và không tự ghi điểm danh.

## Cài/nạp

1. Arduino IDE 2.x, board package **esp32 by Espressif Systems 3.x**.
2. Library Manager: **ArduinoJson 7.x**.
3. Chọn board **AI Thinker ESP32-CAM**, bật PSRAM nếu tùy chọn xuất hiện; cấp nguồn 5V ổn định.
4. Arduino yêu cầu tên thư mục khớp sketch: tạo thư mục sketch `code_esp32_cam`, sao chép `code_esp32_cam.ino` và `config.example.h` vào đó. Đổi file cấu hình thành `config.h` trong thư mục sketch (không đổi file ví dụ gốc).
5. Điền `WIFI_SSID`, `WIFI_PASSWORD`, `SERVER_URL`, `DEVICE_ID`, `DEVICE_TOKEN`.
6. Dùng USB-UART mức logic 3.3V; nối GPIO0-GND khi upload, bỏ nối rồi reset để chạy. Serial 115200.

```cpp
#define SERVER_URL "http://192.168.1.10:8000"
#define DEVICE_ID "esp32-cam-01"
#define DEVICE_TOKEN "gia-tri-DEVICE_TOKEN-trong-env"
```

ESP32 và laptop cùng LAN. IP trên là ví dụ, phải thay IP thực tế. Không dùng `localhost`/`127.0.0.1` trên ESP32. File `config.h` chứa secret đã được ignore, không chia sẻ công khai.

## Luồng

- Heartbeat mỗi 10 giây: `POST /api/devices/heartbeat`, header `X-Device-ID`, `X-Device-Token`.
- Sau heartbeat: `GET /api/devices/config` để nhận phiên được giảng viên gán.
- Chỉ khi config `active=true`: chụp VGA JPEG và gửi multipart `image` đến `/api/devices/{id}/frames?session_id=...` theo `FRAME_INTERVAL_MS`.
- Server yêu cầu mặc định 3 frame ổn định; chu kỳ phải ngắn hơn `STABLE_GAP_SECONDS`. Nếu laptop chậm, đo latency và hiệu chỉnh phù hợp.
- LED đỏ GPIO33 active-low chỉ nháy khi HTTP 202 và JSON `accepted=true`; không nháy thành công chỉ vì upload thành công.
- Mất mạng/lỗi heartbeat/config: bỏ phiên cục bộ; không báo thành công. HTTP 409 dừng gửi ảnh cho tới lần lấy config tiếp theo.

## Sau khi nạp

Đợi camera xuất hiện ở dashboard → Thiết bị & ROI → gán buổi học đang mở → lưu ROI. Nếu PAD/recognition chưa calibrated, frame vẫn bị từ chối an toàn.

Firmware chưa được biên dịch bằng Arduino CLI hoặc nạp board trong phiên triển khai này. Cần kiểm tra nguồn, pinout, phiên bản board package, bộ nhớ upload và kết nối thực. HTTP không bảo vệ token khỏi nghe lén: chỉ dùng LAN thử nghiệm tin cậy; muốn triển khai ngoài mạng đó phải bổ sung TLS và kiểm tra chứng chỉ, không tắt verification.
