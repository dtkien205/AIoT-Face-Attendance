# BTL-new — Điểm danh khuôn mặt AIoT

ESP32-CAM chụp JPEG và gửi về laptop. FastAPI kiểm tra ROI, chất lượng, độ ổn định, PAD và danh tính; React hiển thị kết quả và quản lý lớp. ESP32 không chạy AI hoặc tự quyết định điểm danh.

## Trạng thái thực tế

| Thành phần | Đã triển khai | Còn cần xác minh |
|---|---|---|
| Backend | Auth, CRUD sinh viên/lớp, phiên học, thiết bị/ROI, embedding có consent, điểm danh thủ công, CSV, WebSocket có auth | Tải thực tế nhiều camera |
| Pipeline | Giới hạn ảnh, Haar detector, ROI, nhiều khung hình ổn định, PAD ONNX, dlib embedding, transaction chống trùng/đi muộn | Ngưỡng và độ chính xác trên camera thực |
| PAD | MiniFASNetV2 từ `yakhyo/face-anti-spoofing`; ONNX đã tải và nạp được | APCER/BPCER với ảnh in và video trên ESP32 |
| Frontend | Quản lý sinh viên, lớp/phiên, điểm danh realtime, CSV, thiết bị/ROI, nhật ký | Kiểm thử giao diện bằng trình duyệt thực |
| Firmware | Wi-Fi STA, heartbeat, lấy phiên từ server, gửi multipart JPEG, LED chỉ khi server xác nhận | Biên dịch/nạp board AI Thinker và thử mạng |
| Docker | Multi-stage backend/frontend, Nginx proxy API/WS, volume SQLite, model read-only | Người dùng tự build/chạy theo yêu cầu |

**Không tuyên bố BTL đã đạt kiểm thử phần cứng hoặc chống giả mạo thực tế.** Mặc định `PAD_CALIBRATED=false` và `RECOGNITION_CALIBRATED=false`: vẫn quản lý lớp/điểm danh thủ công được, nhưng không tự chấp nhận khuôn mặt trước khi hiệu chỉnh.

## 1. Chạy bằng Docker Compose

Yêu cầu Docker Engine/Desktop và Compose v2. WSL cần bật Docker Desktop WSL integration.

Chạy từ **thư mục gốc BTL-new**, không phải `backend`:

```bash
# .env đã được tạo riêng trong lần triển khai này.
# Với bản sao mới: cp .env.example .env rồi đặt ADMIN_PASSWORD và DEVICE_TOKEN.
# Không ghi đè .env đang có nếu muốn giữ thông tin đăng nhập.

docker compose config --quiet
docker compose up --build -d
docker compose ps
docker compose logs --tail=100 backend frontend
```

- Dashboard: <http://localhost:8080>
- Swagger: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>
- Đăng nhập: `ADMIN_USERNAME` / `ADMIN_PASSWORD` trong **`.env` ở thư mục gốc**.
- Docker không đọc `backend/.env`; file đó chỉ dành cho chạy Python trực tiếp.
- Model cần có: `models/minifasnet-v2/MiniFASNetV2.onnx`. Compose báo lỗi khi thiếu file thay vì tự tạo thư mục giả.
- Dashboard dùng cùng origin qua Nginx. Từ máy khác trong LAN mở `http://<IP-laptop>:8080`; không cần build lại URL API.
- Backend build mặc định có dlib/face-recognition. Lần đầu cần Internet và có thể lâu do biên dịch C++. Có thể đặt `INSTALL_RECOGNITION=false` nếu chỉ cần quản lý/thủ công; không thể nhận diện tự động ở cấu hình đó.
- Không chạy nhiều Uvicorn workers: WebSocket/tracking/rate-limit hiện dùng bộ nhớ một process.

### Nạp danh sách lớp một lần

```bash
docker compose exec backend python seed.py
```

Seed không ghi điểm danh, không đăng ký khuôn mặt và không tạo ảnh sinh trắc học. Seed idempotent theo mã sinh viên, nhưng chạy lại có thể thêm lại hồ sơ đã xóa. Không bật `SEED_ROSTER=true` thường xuyên nếu muốn tránh hành vi đó.

### Luồng sử dụng

1. Đăng nhập → **Sinh viên** / **Lớp & buổi học** để tạo hoặc chỉnh danh sách.
2. Đăng ký ảnh rõ nét, một khuôn mặt; xác nhận đã có consent và kiểm tra đúng người. Chỉ embedding được lưu vào SQLite, không lưu ảnh thô.
3. Tạo buổi học và mở phiên.
4. Kết nối camera: dùng firmware SoftAP cũ + `camera_bridge.py`, hoặc nạp firmware STA/push; chờ heartbeat xuất hiện trong **Thiết bị & ROI**.
5. Gán thiết bị vào buổi học, hiệu chỉnh ROI 0–1 theo camera.
6. Thu thập và đánh giá ngưỡng PAD/recognition theo [docs/model-evaluation.md](docs/model-evaluation.md). Chỉ bật hai cờ calibrated sau khi có số liệu chấp nhận được.
7. Mở màn **Điểm danh** để xem **Camera điểm danh** ngay đầu trang (ảnh, ROI, kết quả AI lấy mẫu); chọn phiên để nhận WebSocket. Video MJPEG/WebSocket chạy độc lập với AI; cầu nối gửi ảnh xem trước cả khi chưa mở phiên; preview không ghi attendance. Nếu mất WS, bảng vẫn polling mỗi 10 giây.
8. Nếu không xác thực được, giảng viên kiểm tra trực tiếp và dùng **Xác minh thay thế** với lý do; bản ghi ghi rõ `manual:<username>`, không giả là PAD đạt.

### Thay đổi cấu hình và dừng

```bash
# Sau khi sửa .env: recreate container để nạp env mới; restart không nạp lại env.
docker compose up -d
# Sau khi sửa code/dependencies: tự build lại.
docker compose up --build -d
# Dừng nhưng giữ dữ liệu:
docker compose down
```

**Không dùng `docker compose down -v` nếu cần giữ dữ liệu:** thao tác đó xóa named volume chứa SQLite/embedding. Xem [docs/docker.md](docs/docker.md) để sao lưu và chuyển máy.

## 2. ESP32-CAM

### Laptop bắt Wi-Fi ESP32 (giống BTL-IoT, phù hợp board hiện tại)

**Giữ nguyên firmware cũ, không cần nạp lại.** Laptop kết nối `ESP32_DIEM_DANH`, đóng mọi tab `/stream`, kiểm tra ảnh ở `http://192.168.4.1:81/capture`. Sau khi backend/dashboard chạy, mở PowerShell:

```powershell
cd D:\PTIT\2026-1\IOT\BTL-new
py -3 backend\camera_bridge.py --check
py -3 backend\camera_bridge.py
```

Cầu nối không cần pip, đọc DEVICE_TOKEN từ `.env` gốc, lấy JPEG từ ESP32 rồi chuyển cho backend; không tự quyết định điểm danh. Vào Thiết bị & ROI để gán camera vào buổi đang mở. Chi tiết và lựa chọn Docker profile `camera-ap`: [docs/camera-softap.md](docs/camera-softap.md).

Muốn nạp sketch SoftAP từ BTL-new: [firmware/esp32_cam_softap/README.md](firmware/esp32_cam_softap/README.md).

### ESP32 và laptop cùng router (lựa chọn khác)

Xem [firmware/esp32_cam/README.md](firmware/esp32_cam/README.md). Đặt Wi-Fi/router, `SERVER_URL=http://<IP-LAN-laptop>:8000` và DEVICE_TOKEN trong `config.h`, nạp sketch push JPEG. Không chạy cầu nối SoftAP cùng lúc.

Cả hai cách hiện dùng HTTP, chỉ dùng mạng thử nghiệm tin cậy/cô lập; qua mạng không tin cậy cần TLS đúng cách.

## 3. Chạy trực tiếp không Docker

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
# Cần CMake/C++ compiler nếu cài recognition:
pip install -r requirements-recognition.txt
# Với bản sao mới, cp .env.example .env rồi đặt secret và PAD_MODEL_PATH.
python seed.py
./run.sh
```

```bash
cd frontend
npm ci
npm run dev
```

Có thể dùng Node 20/22 LTS. `VITE_API_URL` mặc định `http://127.0.0.1:8000` cho Vite dev. Với WSL, nếu dependency dưới `/mnt/d` bị hỏng sau giải nén, chuyển bản working copy/dependencies sang filesystem Linux và cài lại; không sửa tay file trong `node_modules`.

## 4. Kiểm thử phần mềm (không Docker)

```bash
cd backend
python -m unittest discover -s tests -v
python -m compileall -q app tests seed.py evaluate_pad.py
cd ../frontend
npm run build
```

41 kiểm thử tự động đã qua trong môi trường kiểm thử Linux. AI acceptance/embedding trong API tests được mock, **không phải chứng cứ độ chính xác PAD/recognition**. Model ONNX thật đã xác minh nạp được; frontend đã build thành công ngoài Docker. Docker chưa được xác minh build/chạy vì người dùng tự thực hiện.

## 5. Tài liệu

- [AGENT.md](AGENT.md): đặc tả và checklist trạng thái.
- [docs/architecture.md](docs/architecture.md): kiến trúc, data flow, giới hạn.
- [docs/docker.md](docs/docker.md): Docker, kiểm tra, sao lưu, khắc phục lỗi.
- [docs/model-evaluation.md](docs/model-evaluation.md): nguồn model, preprocessing và hiệu chỉnh.
- [docs/test-report.md](docs/test-report.md): kết quả phần mềm và kế hoạch kiểm thử thực tế.

## Quyền riêng tư và giới hạn

Embedding vẫn là dữ liệu sinh trắc học nhạy cảm, hiện lưu trong SQLite **chưa mã hóa tại ứng dụng**. Bảo vệ ổ đĩa/volume/backups bằng quyền truy cập và mã hóa máy chủ; chỉ đăng ký khi có consent, thu hồi embedding qua dashboard khi không còn cần. `.env`, cấu hình firmware có secret, ảnh và DB không được commit hoặc đưa vào Docker image.

PAD không bảo đảm chống giả mạo tuyệt đối. Haar detector, tracking IoU và dlib chịu ảnh hưởng ánh sáng, góc mặt, JPEG nén và domain shift. ROI/ổn định hình học không chứng minh hướng di chuyển hoặc liên tục cùng một danh tính. Dùng thay thế thủ công và đo APCER/BPCER/FAR/FRR trên điều kiện thực.
