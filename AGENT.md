# Hệ thống điểm danh khuôn mặt chống giả mạo

> BTL IoT: ESP32-CAM chỉ chụp và gửi ảnh; laptop chạy backend, AI chống giả mạo, nhận diện khuôn mặt và quản lý điểm danh.

## 1. Mục tiêu

Xây dựng hệ thống điểm danh gồm:

- **ESP32-CAM:** chụp ảnh JPEG và gửi ảnh đến server qua Wi-Fi.
- **Backend:** Python + FastAPI tiếp nhận ảnh, điều phối các bước xử lý và lưu kết quả.
- **ROI (Region of Interest):** chỉ xử lý khuôn mặt nằm trong vùng điểm danh được cấu hình, hạn chế nhận diện người đi ngang ngoài hành lang.
- **Face Anti-Spoofing (PAD):** đánh giá ảnh/khuôn mặt có dấu hiệu giả mạo hay không.
- **Face Recognition:** xác định sinh viên đã đăng ký.
- **Database:** lưu sinh viên, lớp học, buổi học, điểm danh và log.
- **Frontend:** dashboard cho giảng viên theo dõi điểm danh và thống kê trực tiếp.

Mô hình PAD được chọn để **đánh giá thử nghiệm ban đầu** là Paired-Sampling Contrastive trong repo [fas6_iccvw2025](https://github.com/anvarganiev/fas6_iccvw2025). Không coi kết quả benchmark của tác giả là bảo đảm hiệu năng trên camera ESP32-CAM; cần tự kiểm thử trong điều kiện thực tế.

## 2. Kiến trúc

```text
ESP32-CAM
  └── Chụp JPEG, gửi ảnh qua Wi-Fi
           |
           v
Laptop / FastAPI
  ├── Kiểm tra request và chất lượng ảnh
  ├── Lọc vùng quan tâm (ROI) trước cửa điểm danh
  ├── Kiểm tra khuôn mặt ổn định qua nhiều khung hình
  ├── Phát hiện/căn chỉnh khuôn mặt
  ├── PAD: đánh giá thật/giả
  ├── Face Recognition: đối chiếu danh tính
  ├── Attendance Service: kiểm tra phiên và chống ghi trùng
  └── SQLite
           |
           └── REST API + WebSocket
                    |
                    v
              React Dashboard
```

**ESP32-CAM không chạy mô hình AI và không lưu database.** Laptop/server xử lý ảnh và quyết định điểm danh.

## 3. Công nghệ dự kiến

| Thành phần | Công nghệ |
|---|---|
| Firmware | Arduino IDE, C++ |
| Camera | ESP32-CAM, ảnh JPEG |
| API | Python, FastAPI |
| Xử lý ảnh | OpenCV |
| PAD | Repo Paired-Sampling Contrastive; phụ thuộc và cách inference theo README của repo |
| Nhận diện | Face embedding + so khớp cosine, chọn thư viện phù hợp |
| Database | SQLite + SQLAlchemy |
| Frontend | React + Vite + TypeScript |
| Cập nhật trực tiếp | WebSocket |
| Xuất báo cáo | CSV |

## 4. Chức năng

### 4.1. ESP32-CAM

- Kết nối Wi-Fi.
- Chụp JPEG khi server yêu cầu hoặc theo chu kỳ cấu hình.
- Gửi ảnh và mã thiết bị đến API.
- Có thể nhận phản hồi để điều khiển LED/buzzer; chức năng này là tùy chọn.
- Khi không liên lạc được với server, không tự báo điểm danh thành công.

### 4.2. Lọc vùng quan tâm (ROI) và chống bắt nhầm người đi ngang

ROI (Region of Interest) là vùng ảnh được chọn làm khu vực điểm danh, ví dụ vùng ngay trước cửa phòng học nơi sinh viên dừng lại nhìn camera.

- Cấu hình vùng ROI theo tọa độ trên ảnh camera; chỉ tiếp tục xử lý khi khuôn mặt nằm trong hoặc đủ tỷ lệ nằm trong vùng này.
- Bỏ qua khuôn mặt ở ngoài ROI, chẳng hạn người đi ngang ở hành lang.
- Yêu cầu khuôn mặt đủ lớn, rõ nét và xuất hiện ổn định qua nhiều khung hình liên tiếp trước khi chạy PAD và nhận diện. Số khung hình/ngưỡng phải được cấu hình và kiểm thử, không xem đây là bảo đảm tuyệt đối.
- Nếu chỉ gửi từng ảnh rời rạc, backend không thể suy ra chắc chắn hướng di chuyển. Muốn chỉ kích hoạt khi người đi vào, cần chuỗi khung hình có thứ tự để theo dõi quỹ đạo, hoặc bổ sung cảm biến/nút kích hoạt.
- ROI cần được hiệu chỉnh theo vị trí lắp đặt, góc camera và độ phân giải; thay đổi vị trí camera có thể khiến vùng cấu hình không còn chính xác.

ROI giảm xử lý ngoài khu vực điểm danh nhưng không thay thế PAD, nhận diện danh tính hoặc kiểm tra phiên học.

### 4.3. Chống giả mạo (PAD)

- Nhận vùng khuôn mặt đã phát hiện/căn chỉnh.
- Chạy mô hình PAD và đọc output theo đúng cách triển khai của tác giả.
- Áp dụng ngưỡng được hiệu chỉnh trên tập kiểm thử của dự án.
- Nếu ảnh không đủ chất lượng, kết quả không chắc chắn hoặc mô hình lỗi: yêu cầu thử lại/từ chối an toàn, không mặc định là người thật.
- Ghi lại kết quả kiểm thử mà không lưu ảnh thô lâu hơn mức cần thiết.

Repo mô hình:
- [Paired-Sampling Contrastive — GitHub](https://github.com/anvarganiev/fas6_iccvw2025)
- Đọc README, license, yêu cầu môi trường, hướng dẫn tải checkpoint và lệnh inference trước khi tích hợp.
- Không giả định repo có API tương thích trực tiếp với FastAPI. Nên viết adapter riêng trong `backend/app/services/antispoof.py`.

### 4.4. Nhận diện khuôn mặt

- Đăng ký sinh viên với sự đồng ý phù hợp.
- Tạo embedding tham chiếu.
- So khớp khuôn mặt mới với sinh viên đã đăng ký.
- Hiệu chỉnh ngưỡng trên dữ liệu kiểm thử; không dùng ngưỡng tùy ý mà chưa đánh giá.

### 4.5. Điểm danh

- Quản lý sinh viên, lớp và buổi học.
- Chỉ ghi điểm danh khi buổi học đang mở, PAD đạt và danh tính được nhận diện đủ tin cậy.
- Chống ghi trùng theo cặp `(session_id, student_id)`.
- Ghi thời gian, trạng thái đúng giờ/đi muộn và thiết bị.
- Có log cho trường hợp bị từ chối, ảnh kém, mô hình lỗi hoặc thiết bị offline.

### 4.6. Frontend

- Đăng nhập giảng viên.
- Dashboard tổng quan.
- Quản lý sinh viên và lớp học.
- Mở/đóng buổi điểm danh.
- Bảng điểm danh cập nhật trực tiếp.
- Thống kê và xuất CSV.
- Nhật ký sự kiện PAD và trạng thái thiết bị.

## 5. Cấu trúc thư mục dự kiến

```text
face-attendance/
├── firmware/
│   └── esp32_cam/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   │   ├── face_detector.py
│   │   │   ├── antispoof.py
│   │   │   ├── face_recognition.py
│   │   │   └── attendance_service.py
│   │   ├── database.py
│   │   ├── websocket.py
│   │   └── main.py
│   ├── tests/
│   ├── requirements.txt
│   └── .env.example
├── frontend/
├── docs/
│   ├── architecture.md
│   └── test-report.md
└── README.md
```

Đây là cấu trúc mục tiêu; các file sẽ được tạo dần trong quá trình triển khai.

## 6. API dự kiến

| Endpoint | Method | Mục đích |
|---|---|---|
| `/api/auth/login` | POST | Đăng nhập |
| `/api/students` | GET/POST | Liệt kê/thêm sinh viên |
| `/api/classes` | GET/POST | Quản lý lớp |
| `/api/sessions` | GET/POST | Quản lý buổi học |
| `/api/sessions/{id}/start` | POST | Mở phiên điểm danh |
| `/api/sessions/{id}/close` | POST | Đóng phiên điểm danh |
| `/api/devices/heartbeat` | POST | Cập nhật trạng thái thiết bị |
| `/api/devices/{id}/frames` | POST | Nhận ảnh từ ESP32-CAM |
| `/api/attendance` | GET | Lấy danh sách điểm danh |
| `/api/attendance/export` | GET | Xuất CSV |
| `/api/liveness-events` | GET | Xem log PAD |
| `/ws/sessions/{id}` | WebSocket | Cập nhật dashboard |

Các endpoint trên là thiết kế đề xuất, chưa có nghĩa chúng đã được triển khai.

## 7. Quy tắc điểm danh

1. Xác thực thiết bị và kiểm tra phiên điểm danh.
2. Kiểm tra ảnh có đủ chất lượng.
3. Phát hiện khuôn mặt và kiểm tra khuôn mặt có nằm trong ROI hay không; ngoài ROI thì bỏ qua.
4. Nếu có chuỗi khung hình, kiểm tra khuôn mặt đủ rõ và ổn định trước khi tiếp tục.
5. Chạy PAD.
6. Nếu PAD đạt, chạy nhận diện danh tính.
7. Kiểm tra sinh viên thuộc lớp/buổi học tương ứng và chưa được ghi nhận trong phiên.
8. Ghi điểm danh trong transaction, với unique constraint `(session_id, student_id)`.
9. Phát sự kiện cập nhật dashboard.

**Không ghi điểm danh nếu PAD hoặc nhận diện thất bại.** Nếu mô hình lỗi hoặc kết quả không chắc chắn, yêu cầu thử lại hoặc chuyển sang quy trình xác minh thủ công.

## 8. Kế hoạch triển khai

- [ ] Bước 1: Khởi tạo FastAPI và SQLite; tạo CRUD sinh viên/lớp/buổi học.
- [ ] Bước 2: Clone và chạy demo PAD độc lập theo README của repo.
- [ ] Bước 3: Tạo bộ kiểm thử người thật, ảnh in và video điện thoại.
- [ ] Bước 4: Tích hợp PAD vào `antispoof.py`.
- [ ] Bước 5: Tích hợp face recognition và hiệu chỉnh ngưỡng.
- [ ] Bước 6: Hoàn thiện logic điểm danh và chống ghi trùng.
- [ ] Bước 7: Xây dựng React dashboard và WebSocket.
- [ ] Bước 8: Kết nối ESP32-CAM, kiểm tra mạng và phản hồi thiết bị.
- [ ] Bước 9: Đo hiệu năng, viết báo cáo và chuẩn bị demo.

## 9. Kế hoạch kiểm thử

| Tình huống | Kết quả mong đợi |
|---|---|
| Sinh viên thật, đã đăng ký | Có thể được điểm danh khi PAD và nhận diện đạt |
| Người đi ngang ngoài ROI | Bỏ qua, không chạy quy trình điểm danh |
| Khuôn mặt chỉ xuất hiện thoáng qua/ảnh mờ | Không điểm danh; chờ khung hình đạt điều kiện hoặc yêu cầu thử lại |
| Người chưa đăng ký | Không ghi điểm danh |
| Ảnh in | PAD từ chối nếu mô hình phát hiện được |
| Video phát trên điện thoại | PAD từ chối nếu mô hình phát hiện được |
| Điểm danh lần hai | Không tạo bản ghi trùng |
| Buổi học đã đóng | Không ghi điểm danh |
| Mất kết nối camera | Hiển thị offline; không báo thành công giả |
| Mô hình lỗi/ảnh kém | Thử lại hoặc từ chối an toàn |

Báo cáo cần thống kê tỷ lệ chấp nhận nhầm tấn công, tỷ lệ từ chối nhầm người thật và thời gian xử lý. Không tuyên bố chống giả mạo tuyệt đối; hiệu năng phải được xác minh trên camera, ánh sáng và loại tấn công thực tế.

## 10. Bảo mật và quyền riêng tư

- Chỉ thu thập dữ liệu khuôn mặt khi có sự đồng ý và mục đích rõ ràng.
- Hạn chế lưu ảnh thô; bảo vệ embedding vì đây vẫn là dữ liệu sinh trắc học nhạy cảm.
- Không để token thiết bị hoặc mật khẩu trong mã nguồn công khai.
- Giới hạn kích thước ảnh, tốc độ request và quyền truy cập API.
- Dùng HTTPS khi triển khai qua mạng không tin cậy.
- Có cách điểm danh thay thế khi nhận diện sai hoặc hệ thống gặp sự cố.

## 11. Chạy server trong mạng nội bộ

Sau khi backend được tạo, có thể chạy FastAPI bằng lệnh tương tự:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Lệnh trên giả định chạy từ thư mục `backend` và `app/main.py` đã tồn tại. Xem Swagger tại `http://127.0.0.1:8000/docs` trên laptop. Để ESP32-CAM truy cập, dùng địa chỉ IPv4 LAN của laptop, ví dụ `http://192.168.1.10:8000`, và cấu hình firewall cho phép kết nối. Không dùng `127.0.0.1` trong firmware vì địa chỉ đó trỏ về chính ESP32-CAM.

## 12. Tiêu chí hoàn thành BTL

- ESP32-CAM gửi ảnh ổn định đến laptop.
- Backend chạy được PAD và nhận diện.
- Chỉ ghi điểm danh khi đủ điều kiện.
- Không tạo điểm danh trùng.
- Frontend cập nhật trạng thái và xuất được báo cáo.
- Có kết quả kiểm thử ảnh in/video, bao gồm các trường hợp mô hình thất bại.
- Có sơ đồ kiến trúc, API, mô tả mô hình, giới hạn và hướng phát triển.

---

**Lưu ý:** README này là đặc tả và kế hoạch triển khai của BTL, không phải xác nhận rằng toàn bộ phần mềm đã được viết xong. Hãy cập nhật các mục, lệnh cài đặt và API khi mã nguồn thực tế thay đổi.
