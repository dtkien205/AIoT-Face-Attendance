# Docker: build, chạy và quản lý dữ liệu

## Cấu trúc

- `backend/Dockerfile`: stage wheels biên dịch dlib (mặc định), runtime không chứa compiler, chạy UID/GID 10001; stage `test` riêng.
- `frontend/Dockerfile`: Node 22 build React, Nginx unprivileged cổng 8080.
- `docker-compose.yml`: hai service, volume `attendance_db`, mount model/roster read-only, root filesystem read-only + tmpfs, bỏ Linux capabilities, log rotation.
- `.dockerignore`: loại `.env`, DB, ảnh, vendor repos, node_modules/venv khỏi build context.
- `.env` gốc dùng cho Compose, `backend/.env` cho Python native. **Không cần hai file giống nhau khi chỉ chạy Docker.** Không copy secrets vào image.

Docker build và container runtime **chưa được xác minh trong lần bàn giao**: người dùng tự build/chạy. `docker compose config --quiet` đã qua. Model ONNX nạp được ngoài Docker, unit/API tests và frontend build đã qua.

## Trước khi build

1. Kiểm tra Docker Desktop WSL integration hoặc Docker Engine và Compose v2.
2. Chạy từ `BTL-new`.
3. `.env` cần có `ADMIN_PASSWORD`, `DEVICE_TOKEN` không rỗng (đã tạo riêng trong triển khai này). Với bản sao mới, copy `.env.example` và tự tạo secret; không giữ giá trị mẫu.
4. File model `models/minifasnet-v2/MiniFASNetV2.onnx` và `data/class_roster.json` phải tồn tại; source bind dùng `create_host_path:false` để tránh tạo thư mục thay file.
5. `INSTALL_RECOGNITION=true` biên dịch dlib, cần Internet/RAM/thời gian. `false` giảm build nhưng API đăng ký/nhận diện sẽ báo unavailable, chỉ dùng quản lý/thủ công.
6. HTTP bind mặc định mọi interface để ESP32 truy cập. Dùng firewall chỉ cho mạng tin cậy. Có thể đặt `BACKEND_BIND=127.0.0.1`, `FRONTEND_BIND=127.0.0.1` nếu chỉ thao tác laptop.

```bash
docker compose config --quiet
docker compose up --build -d
docker compose ps
docker compose logs --tail=100 backend frontend
```

Không in `docker compose config` đầy đủ vào báo cáo công khai vì nội dung có secret đã interpolate.

## Kiểm tra sau build

```bash
curl --fail http://localhost:8000/health
curl --fail -I http://localhost:8080/
docker compose exec backend python -c 'from app.services.antispoof import AntiSpoofAdapter; p=AntiSpoofAdapter(); print("loaded:", p.session is not None, "reason:", p.reason)'
docker compose exec backend python -c 'import face_recognition; print("recognition dependency imported")'
```

Health chỉ chứng minh process HTTP hoạt động, **không chứng minh AI đã calibrated**. Đăng nhập dashboard xem trạng thái model. Mật khẩu lấy từ `.env` gốc, không có mật khẩu dự phòng. Có thể nạp danh sách:

```bash
docker compose exec backend python seed.py
```

Dashboard và API cùng origin qua Nginx; WS chuyển tiếp Upgrade. Ảnh giới hạn ở Nginx 6 MiB request body, API 5 MiB image + 4 MP. Cổng backend 8000 dành ESP32/Swagger, dashboard 8080.

## Chạy test trong image (tùy chọn, người dùng tự build)

```bash
docker build --target test --build-arg INSTALL_RECOGNITION=false -f backend/Dockerfile -t btl-new-backend-tests .
docker run --rm btl-new-backend-tests
```

Test API dùng SQLite tạm và mock AI, không yêu cầu camera/model thật. Stage test không dùng làm runtime production. Chỉ một Uvicorn worker vì registry WebSocket/tracking/rate-limit nằm trong process.

## Sao lưu SQLite nhất quán

Embedding, consent, hồ sơ và điểm danh đều nằm trong DB của named volume. Dùng SQLite backup API, không `cp` DB đang bị ghi. Ví dụ dưới đây dành cho terminal Linux/WSL, chạy từ gốc dự án:

```bash
mkdir -p backups
backup="backups/attendance-$(date +%Y%m%d-%H%M%S).db"
# -T không tạo TTY; stdout chỉ chứa bytes của bản backup.
docker compose exec -T backend python -c 'import os,sqlite3,tempfile,sys; fd,p=tempfile.mkstemp(suffix=".db"); os.close(fd); src=sqlite3.connect("/app/var/attendance.db"); dst=sqlite3.connect(p); src.backup(dst); dst.close(); src.close(); sys.stdout.buffer.write(open(p,"rb").read()); os.unlink(p)' > "$backup"
chmod 600 "$backup"
```

Kiểm tra backup có dung lượng hợp lệ và `PRAGMA integrity_check` trước khi cần khôi phục. Backup chứa sinh trắc học/PII: mã hóa nơi lưu, không commit, kiểm soát quyền và thời hạn giữ. Lưu `.env` riêng an toàn nếu cần giữ mật khẩu/token khi chuyển máy.

Khôi phục là thao tác ghi đè dữ liệu: dừng backend trước, sao lưu DB hiện có, xác minh đúng volume/backup và quyền UID 10001 rồi mới thay DB. Không chạy lệnh reset/xóa volume nếu chưa có backup đã kiểm tra.

## Các thao tác thường dùng

```bash
docker compose up -d          # nạp lại thay đổi .env bằng recreate khi cần
docker compose restart       # chỉ restart; không nạp lại env đã đổi
docker compose down          # dừng, giữ volume
docker compose logs -f       # xem log
```

`down -v` xóa dữ liệu, không dùng để khắc phục lỗi thông thường. Restart không được coi là xóa lịch sử hoặc reset hệ thống. Seed mặc định false để không tạo lại hồ sơ đã xóa mỗi lần khởi động.

## Khắc phục lỗi

- **Trùng cổng:** đổi `BACKEND_PORT` / `FRONTEND_PORT` trong `.env`, cập nhật `SERVER_URL` firmware theo cổng backend mới.
- **Thiếu model:** tải đúng release ONNX được ghi ở model-evaluation.md, không đổi tên `.pth` thành `.onnx`.
- **dlib build lỗi/OOM:** xem log builder, tăng RAM Docker hoặc giảm `CMAKE_BUILD_PARALLEL_LEVEL` trong Dockerfile. Muốn thử dashboard trước có thể build `INSTALL_RECOGNITION=false`, nhưng phải build lại true để nhận diện.
- **API 401:** dùng tài khoản `.env` gốc; token hết hạn thì đăng nhập lại. ESP32 phải dùng đúng DEVICE_TOKEN.
- **API 409 khi gửi ảnh:** heartbeat, gán thiết bị vào phiên đang mở. Phiên đã đóng không mở lại.
- **PAD/recognition chưa ready:** không bật cờ bừa; xem hướng dẫn calibration và dependency.
- **Camera mất mạng:** dashboard báo offline sau TTL, hệ thống không báo thành công giả. Sự kiện offline hiện suy ra từ heartbeat, không có background job tự lưu log chuyển offline.
- **Không truy cập được từ ESP32 trong WSL:** kiểm tra IP Windows/LAN, publish port Docker Desktop, firewall và mạng Wi-Fi; không dùng IP private của container.
- **Nginx lỗi upstream sau khi thay riêng backend:** recreate cả hai bằng `docker compose up -d --force-recreate` khi cần để Nginx resolve lại service. Lệnh này không xóa volume.
