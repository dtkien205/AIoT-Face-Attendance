# SoftAP — dùng giống BTL-IoT/Firmware_ESP32

## Nếu board đang chạy firmware cũ

**Không cần nạp lại.** Firmware tham chiếu `BTL-IoT/Firmware_ESP32/code_esp32_cam.ino` phát Wi-Fi `ESP32_DIEM_DANH`, IP `192.168.4.1`, snapshot `http://192.168.4.1:81/capture`. Chạy cầu nối laptop theo [docs/camera-softap.md](../../docs/camera-softap.md).

## Nếu muốn nạp firmware từ BTL-new

Sketch `esp32_cam_softap.ino` giữ SoftAP/IP/snapshot tương thích, nhưng khởi tạo camera an toàn hơn (zero-init, PSRAM fallback), không tắt brownout và không báo LED điểm danh chỉ vì có ảnh.

1. Arduino IDE, Espressif ESP32 board package 3.x, board AI Thinker ESP32-CAM.
2. Copy `config.example.h` thành `config.h` trong cùng thư mục; đặt SSID/password riêng (password ít nhất 8 ký tự).
3. Mở `esp32_cam_softap.ino`, upload theo kết nối USB-UART/board hiện có. Cấp nguồn 5V ổn định, logic UART 3.3V. Nếu nối GPIO0-GND để nạp, bỏ nối rồi reset khi chạy.
4. Serial Monitor 115200. Kết nối laptop vào SSID đã cấu hình.
5. Snapshot vẫn `http://192.168.4.1:81/capture`. Preview chuyển sang **`http://192.168.4.1:82/stream`**, tách server để không khóa snapshot. Không nên mở preview khi đo latency/điểm danh.

Không cần ArduinoJson cho sketch SoftAP. Không cần IP laptop, router hoặc DEVICE_TOKEN trong firmware này: token chỉ nằm ở cầu nối và backend. WPA2/password Wi-Fi là lớp bảo vệ camera; HTTP camera không có auth riêng, chỉ dùng mạng thử nghiệm tin cậy. Không chia sẻ password mặc định của firmware cũ khi triển khai thật.

Hai sketch là **hai lựa chọn thay thế**, không nạp cả hai: `esp32_cam` dùng Wi-Fi router/push JPEG; `esp32_cam_softap` dùng ESP32 phát Wi-Fi/laptop pull JPEG. Firmware mới chưa được biên dịch/nạp board trong phiên này. Firmware cũ đã có trên board của bạn vẫn dùng được với cầu nối.
