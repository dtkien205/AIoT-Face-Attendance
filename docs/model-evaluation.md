# PAD và nhận diện: nguồn, quy ước và hiệu chỉnh

## Model đang dùng

- Repo: https://github.com/yakhyo/face-anti-spoofing
- Weights: https://github.com/yakhyo/face-anti-spoofing/releases/download/weights/MiniFASNetV2.onnx
- File: `models/minifasnet-v2/MiniFASNetV2.onnx`
- SHA-256 của bản tải ngày 2026-10-29: `b32929adc2d9c34b9486f8c4c7bc97c1b69bc0ea9befefc380e4faae4e463907`
- LICENSE trong repo ghi Apache-2.0; adapter là bản tích hợp có điều chỉnh, xem `docs/licenses/face-anti-spoofing-LICENSE.txt`. Repo dẫn nguồn Silent-Face-Anti-Spoofing. Cần kiểm tra thêm điều khoản trọng số/dataset nếu phân phối hoặc dùng thương mại; không suy ra tất cả dữ liệu/weights đều cùng license chỉ từ license code.
- `fas6_iccvw2025` không dùng trong runtime vì bản tải không có checkpoint. Giữ làm tham khảo, không cài dependencies/train tự động.

## Preprocessing và output

Adapter `backend/app/services/antispoof.py` theo `face-anti-spoofing/onnx_inference.py`:

1. Nhận đúng bbox `(x,y,w,h)` từ detector đã qua ROI/chất lượng.
2. Crop mở rộng **2.7 lần**, giới hạn trong khung, giữ quy ước biên inclusive của upstream.
3. OpenCV BGR, resize 80×80, float32 **0..255**, NCHW; không RGB, không chia 255, không normalize ImageNet.
4. ONNX Runtime CPU, softmax 3 logits. **Class index 1 = Real**; hai class còn lại là Fake.
5. Chỉ đạt khi real là class cao nhất, score hữu hạn và `real_score >= PAD_REAL_THRESHOLD`.
6. Khi thiếu model/dependency/lỗi/threshold chưa calibrated: `is_real=false`. Score vẫn có thể được trả để đánh giá offline nếu model nạp được.

Không dùng preprocessing/label của ConvNeXt cũ cho MiniFASNet. Ảnh input tối đa 5 MiB/4 MP; detector Haar không tương đương RetinaFace của demo upstream, vì vậy cần đo lại bbox/crop trên thiết bị thực.

## Quy trình thu thập

- Consent phù hợp, phạm vi và thời hạn lưu rõ ràng; tách thư mục dữ liệu thử khỏi source công khai.
- Tập calibration và tập test độc lập, ưu tiên tách người/buổi/điều kiện ánh sáng. Không chọn threshold trên tập rồi báo chính tập đó là test độc lập.
- Nhóm live, ảnh in (giấy/màn hình khác nhau), replay video điện thoại, ảnh mờ/thiếu sáng/ngược sáng/góc lệch, ngoài ROI, nhiều người.
- Ghi camera, khoảng cách, độ phân giải, JPEG quality, ánh sáng, người/phiên ẩn danh, loại tấn công, bbox, score và latency. Không giữ ảnh lâu hơn consent cho phép.

## Công cụ đánh giá PAD

Tạo CSV riêng (ví dụ minh họa cấu trúc, không phải dữ liệu đo):

```csv
path,label,x,y,w,h
images/live-001.jpg,live,120,80,160,160
images/print-001.jpg,print,118,82,164,164
images/replay-001.jpg,replay,122,84,158,158
```

Bbox lấy từ detector thực. Chạy từ backend với env/model đã cấu hình:

```bash
python evaluate_pad.py --manifest /duong-dan-rieng/calibration.csv --output /duong-dan-rieng/calibration-report.json --threshold 0.9
```

Không ghi đè file báo cáo cũ. Công cụ không ghi attendance, không bật calibrated, không tự chọn threshold và không tải ảnh lên dịch vụ bên ngoài. Trong Docker có thể chạy cùng script qua `docker compose exec` sau khi bạn mount tập kiểm thử riêng; không đưa ảnh test vào image.

- APCER: tấn công bị chấp nhận / tổng mẫu tấn công; báo cả theo loại print/replay.
- BPCER: người thật bị từ chối / tổng mẫu thật.
- Mẫu lỗi được giữ trong tổng số và từ chối an toàn; xem cả `errors`, không che lỗi decode/mô hình. Mean latency gồm đọc/validate/inference từng mẫu, không gồm tải model.
- Chọn threshold dựa trên mục tiêu rủi ro và BPCER chấp nhận được, sau đó đo độc lập. Số liệu ít phải ghi rõ không đủ kết luận.

## Nhận diện danh tính

Dlib/face_recognition tạo embedding 128 chiều. So khớp **Euclidean distance**, không phải cosine; chọn ngưỡng tương ứng, không thay nhầm công thức. Giới hạn ứng viên theo lớp, reject nếu khoảng cách tốt nhất vượt `RECOGNITION_THRESHOLD` hoặc best/second-best quá gần (`RECOGNITION_MARGIN`). Đăng ký và probe cần dùng cùng phiên bản embedding.

Đo genuine/impostor pairs trên dữ liệu consent, ghi FAR/FRR, unknown identity và trường hợp gần giống. Embedding enrollment lưu trong SQLite kèm thời gian consent và người đăng ký; không lưu ảnh thô.

Sau khi có kết quả chấp nhận được, sửa `.env` (Docker) hoặc `backend/.env` (native):

```dotenv
PAD_REAL_THRESHOLD=<nguong_da_do>
RECOGNITION_THRESHOLD=<nguong_da_do>
RECOGNITION_MARGIN=<margin_da_do>
PAD_CALIBRATED=true
RECOGNITION_CALIBRATED=true
```

Docker: `docker compose up -d` để recreate/nạp env mới. Chỉ `restart` không đổi environment. Native: khởi động lại backend. Cờ calibrated là xác nhận của người triển khai, không phải chứng nhận độ chính xác. Chưa có dữ liệu thực thì giữ false và dùng xác minh thủ công.
