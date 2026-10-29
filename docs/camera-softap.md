# Laptop bắt Wi-Fi ESP32 — tương thích firmware BTL-IoT

```text
ESP32-CAM phát Wi-Fi ESP32_DIEM_DANH
    192.168.4.1:81/stream (MJPEG)
             |
Laptop kết nối vào Wi-Fi ESP32
    camera_bridge.py đọc MJPEG liên tục, giữ khung mới nhất
             |
    FastAPI Docker :8000 (token thiết bị)
             |
    Dashboard localhost:8080
```

Không yêu cầu ESP32 tự gửi HTTP, không cần biết IP laptop. Không dùng USB như webcam: USB cấp nguồn/nạp firmware; ảnh truyền qua Wi-Fi. Có thể giữ firmware cũ đang hoạt động, không cần nạp lại.

## Cách khuyến nghị trên Windows: cầu nối chạy trên host

Cách này tránh khác biệt routing Docker/WSL tới mạng SoftAP và **không cần cài thư viện Python**. Cần Python 3.10+ trên Windows. Cầu nối chỉ dùng standard library, tự đọc `.env` gốc để lấy DEVICE_TOKEN.

1. Khi còn Internet, tự build/chạy backend + frontend theo README. Docker image/model phải có sẵn trước khi chuyển sang Wi-Fi ESP32 không có Internet.
2. Cấp nguồn ESP32, laptop kết nối `ESP32_DIEM_DANH` (password theo firmware bạn nạp). Windows báo “No Internet” là bình thường; giữ kết nối.
3. Kiểm tra snapshot trong trình duyệt: <http://192.168.4.1:81/capture>. Phải thấy một ảnh. Đóng mọi tab `/stream` và tắt app BTL-IoT cũ đang đọc stream: server firmware cũ có thể bị stream liên tục chiếm nên `/capture` timeout.
4. Mở PowerShell tại dự án và kiểm tra:

```powershell
cd D:\PTIT\2026-1\IOT\BTL-new
py -3 backend\camera_bridge.py --check
```

`--check` lấy một JPEG, gửi heartbeat và đọc assignment; không upload frame điểm danh. Nếu không có Python launcher `py`, dùng `python` thay `py -3`.

5. Chạy liên tục, giữ cửa sổ này mở:

```powershell
py -3 backend\camera_bridge.py
```

6. Mở <http://localhost:8080> → **Thiết bị & ROI**, chọn `esp32-cam-01`. Tạo/mở buổi học và gán thiết bị vào phiên, lưu ROI. Cầu nối tự lấy lại config mỗi 2 giây, không phải restart.
7. Vào **Điểm danh**, chọn phiên. Sinh viên cần có embedding, đúng lớp và qua đủ ROI/chất lượng/ổn định/PAD/recognition. Khi model chưa calibrated, có kết nối nhưng không điểm danh tự động.

Nhấn Ctrl+C để dừng cầu nối. Dừng không tạo attendance offline. Sau khi mất camera, trạng thái device thành offline theo TTL (mặc định 45s); heartbeat không được gửi nếu camera không trả ảnh.

## Biến cấu hình `.env` gốc

Mặc định tương thích firmware cũ, không bắt buộc thêm nếu dùng địa chỉ mặc định:

```dotenv
CAMERA_CAPTURE_URL=http://192.168.4.1:81/capture
CAMERA_TRANSPORT=mjpeg
CAMERA_STREAM_URL=http://192.168.4.1:81/stream
CAMERA_PREVIEW_FPS=15
PREVIEW_MAX_FPS=20
CAMERA_DEVICE_ID=esp32-cam-01
CAMERA_INTERVAL_SECONDS=0.8
CAMERA_TIMEOUT_SECONDS=5
# Cầu nối host, nếu backend port khác 8000:
BRIDGE_BACKEND_URL=http://127.0.0.1:8000
```

Token dùng `DEVICE_TOKEN` hiện có, không cần ADMIN_PASSWORD. Không gửi token/mật khẩu lên chat. Sau khi sửa `.env`, restart cầu nối. Nếu có sẵn env shell cùng tên, nó ưu tiên hơn file.

## Lựa chọn: cầu nối trong Docker

Compose có profile `camera-ap`, chỉ bật khi muốn container đọc SoftAP:

```bash
# Tự thực hiện build khi còn Internet:
docker compose --profile camera-ap up --build -d
# Xem cầu nối:
docker compose logs -f camera-bridge
# Dừng riêng cầu nối:
docker compose --profile camera-ap stop camera-bridge
```

Profile dùng image `python:3.12-slim-bookworm`, mount script read-only, backend URL nội bộ `http://backend:8000`. Nếu image chưa có, cần pull trước khi vào Wi-Fi ESP32.

Nếu host mở snapshot được nhưng container không đọc được vì Docker Desktop/WSL/VPN routing, dùng **cầu nối PowerShell trên host** thay vì đổi toàn bộ firmware hoặc mở firewall vô điều kiện. Dừng service bridge trước khi chạy bridge host.

**Chỉ chạy một cầu nối cho một camera/device ID.** Không chạy đồng thời profile Docker, bridge PowerShell và app BTL-IoT cũ. Hai nguồn frame có thể gây 429 hoặc phá tính liên tục tracking.

## Chẩn đoán

- Không vào được `192.168.4.1:81/capture`: kiểm tra đang kết nối đúng Wi-Fi, board có nguồn ổn định, firmware có `/capture`, tắt VPN/proxy cho mạng camera nếu cần. Cầu nối bỏ qua HTTP proxy hệ thống cho traffic cục bộ.
- Capture timeout khi `/stream` mở: đóng stream; firmware cũ dùng chung HTTP server. Sketch SoftAP mới trong BTL-new tách stream sang port 82.
- `HTTP 401`: DEVICE_TOKEN cầu nối và backend không trùng. Docker đọc `.env` gốc, không đọc `backend/.env`.
- `HTTP 409`: assignment/phiên vừa thay đổi hoặc phiên đóng; cầu nối reload config và không mặc định thành công.
- `HTTP 429`: có nguồn frame thứ hai hoặc chu kỳ quá nhanh; dừng nguồn thừa/điều chỉnh interval.
- Log `idle`: camera/backend đã kết nối; còn chờ gán **buổi học đang mở** trên dashboard.
- Log `waiting`: xem reason và Nhật ký xác thực; có thể mặt ngoài ROI, chờ ổn định, PAD reject hoặc chưa đăng ký danh tính.
- Log `accepted`: backend xác nhận; nếu duplicate có `created=false`, unique constraint vẫn không tạo điểm danh thứ hai.

Không xác minh kết nối hardware trong phiên này vì camera ở máy khác. Đã có unit tests cho idle/active, binary multipart, failure không heartbeat và config refresh.

## Màn hình camera trong dashboard

Vào **Điểm danh**: panel **Camera điểm danh** nằm đầu trang. Chọn camera, xem video/ROI/kết quả AI lấy mẫu, có Phóng to và Tạm dừng. Cầu nối phiên bản mới gửi ảnh preview ngay cả khi chưa gán phiên; chỉ pipeline phiên mở mới có quyền tạo attendance. Không mở thêm `/stream`.

Sau khi cập nhật code, người dùng tự build lại backend/frontend và khởi động lại cầu nối PowerShell (Ctrl+C rồi chạy lại). Ảnh chỉ giữ RAM TTL 5 giây, tối đa 8 camera; endpoint xem ảnh yêu cầu bearer giảng viên và no-store. Khi mất nguồn ảnh, UI bỏ ảnh cũ thay vì giả camera còn live. Tạm dừng preview không dừng cầu nối/điểm danh; muốn dừng điểm danh hãy đóng phiên.


## Tối ưu độ trễ: video độc lập với AI

Mặc định bridge đọc **một kết nối MJPEG** tới `/stream`, không đồng thời gọi `/capture` trên firmware cũ. `--check` vẫn dùng snapshot: dừng bridge trước khi chạy check. Không mở `/stream` bằng tab/app khác.

Ba worker trên laptop: đọc camera liên tục → bộ đệm một khung mới nhất; preview gửi qua HTTP keep-alive riêng; AI lấy mẫu theo CAMERA_INTERVAL_SECONDS trên kết nối riêng. AI timeout/chậm không giữ khóa luồng preview. Khi mạng chậm bỏ khung cũ, không phát lại hàng đợi. Khung quá 2 giây không được lấy mới để upload/phân tích.

Backend không ghi SQLite mỗi frame preview, kiểm tra ảnh trong threadpool, giới hạn PREVIEW_MAX_FPS riêng với frame AI. Frontend nhận JPEG binary qua WebSocket và ACK sau decode/display; chỉ một ảnh in-flight để viewer chậm không tích latency. Metadata/result polling độc lập 800ms. Khung mặt AI không vẽ lên video mới vì tọa độ đó thuộc khung lấy mẫu trước, có thể sai vị trí. ROI vẫn hiển thị theo config.

`CAMERA_PREVIEW_FPS=15` là mục tiêu, **chưa phải FPS đo thực tế**. Có thể thử 20 nếu Wi-Fi/CPU ổn và PREVIEW_MAX_FPS >= CAMERA_PREVIEW_FPS; nếu mạng không ổn, giảm 10–12. Không tăng FPS AI theo FPS video: giữ sampling .8s hoặc đo lại latency/stability. Không khắc phục được lỗi `No route to host` bằng cách tăng FPS.

Firmware BTL-IoT cũ dùng stream port **81**. Sketch SoftAP mới của BTL-new dùng port **82**: đặt CAMERA_STREAM_URL tương ứng. Firmware chỉ chụp/nén JPEG/phát Wi-Fi; toàn bộ FE/BE/PAD/recognition chạy trên máy tính. Không cần nạp lại board hiện tại để dùng tối ưu bridge này.

Nếu firmware không có stream, đặt CAMERA_TRANSPORT=snapshot để fallback; preview/AI vẫn tách nhưng tốc độ bị giới hạn bởi HTTP capture. Không tự fallback song song khi stream lỗi, tránh khóa server ESP32 cũ.

Sau cập nhật: tự build backend/frontend; Ctrl+C dừng **mọi bridge cũ**, rồi chạy một bridge mới và Ctrl+F5 dashboard. Không chạy đồng thời PowerShell/WSL/Docker bridge. Khuyến nghị Windows host khi WSL báo No route to host mà Windows mở camera được.
