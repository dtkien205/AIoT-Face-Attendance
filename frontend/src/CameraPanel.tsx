import { useEffect, useState } from "react";

type Device = { id: string; name: string; status: string };
type Preview = {
  available: boolean; received_at?: string; session_id?: number | null;
  config: { session_id: number | null; active: boolean; roi_left: number; roi_top: number; roi_right: number; roi_bottom: number };
  result?: { accepted?: boolean; created?: boolean; reason?: string; state?: string; student_code?: string; pad_score?: number; box?: number[]; frame_size?: number[] };
};
type Props = { api: (path: string, init?: RequestInit) => Promise<Response>; devices: Device[]; selectedSession: string; token: string; apiUrl: string };
const reasons: Record<string, string> = {
  "waiting for stable face": "Giữ khuôn mặt ổn định trong vùng điểm danh",
  "no face detected": "Chưa phát hiện khuôn mặt",
  "face outside ROI": "Khuôn mặt đang ngoài vùng điểm danh",
  "face too small": "Hãy đứng gần camera hơn",
  "image too blurry": "Ảnh mờ — nhìn thẳng và giữ yên",
  "multiple faces in ROI": "Chỉ một người đứng trong vùng điểm danh",
  "spoof or uncertain PAD score": "PAD từ chối hoặc chưa đủ tin cậy",
  "unknown, uncertain or unavailable identity": "Chưa nhận diện được — kiểm tra đăng ký khuôn mặt và trạng thái mô hình",
};

export default function CameraPanel({ api, devices, selectedSession, token, apiUrl }: Props) {
  const [camera, setCamera] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [source, setSource] = useState("");
  const [error, setError] = useState("");
  const [paused, setPaused] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const effectiveCamera = devices.some(d => d.id === camera) ? camera : devices[0]?.id ?? "";

  useEffect(() => {
    setPreview(null); setSource(""); setError("");
    if (!effectiveCamera || paused) return;
    let stopped = false; let timer: number; let reconnect: number; let objectUrl = "";
    let socket: WebSocket; let lastImage = Date.now();
    const controller = new AbortController();
    const release = () => { if (objectUrl) URL.revokeObjectURL(objectUrl); objectUrl = ""; };
    const connect = () => {
      const url = new URL(`/ws/devices/${encodeURIComponent(effectiveCamera)}/camera`, apiUrl || window.location.origin);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(url); socket.binaryType = "blob";
      socket.onopen = () => socket.send(JSON.stringify({ token }));
      socket.onmessage = async event => {
        if (typeof event.data === "string") {
          if (!stopped) { release(); setSource(""); }
          return;
        }
        const currentSocket = socket;
        const nextUrl = URL.createObjectURL(event.data);
        const image = new Image(); image.src = nextUrl;
        try {
          await image.decode();
          if (stopped || currentSocket !== socket) { URL.revokeObjectURL(nextUrl); return; }
          const oldUrl = objectUrl; objectUrl = nextUrl; setSource(nextUrl); setError(""); lastImage = Date.now();
          requestAnimationFrame(() => {
            if (oldUrl) URL.revokeObjectURL(oldUrl);
            if (!stopped && currentSocket.readyState === WebSocket.OPEN) currentSocket.send("next");
          });
        } catch {
          URL.revokeObjectURL(nextUrl);
          if (!stopped && currentSocket.readyState === WebSocket.OPEN) currentSocket.send("next");
        }
      };
      socket.onclose = event => {
        if (stopped) return;
        release(); setSource("");
        setError(event.code === 4401 ? "Phiên xem camera hết hạn — đăng nhập lại" : "Mất kết nối camera — đang kết nối lại…");
        if (event.code !== 4401) reconnect = window.setTimeout(connect, 1500);
      };
      socket.onerror = () => socket.close();
    };
    const update = async () => {
      try {
        const path = `/devices/${encodeURIComponent(effectiveCamera)}/preview`;
        const metadata: Preview = await (await api(path, { signal: controller.signal, cache: "no-store" })).json();
        if (!stopped) {
          setPreview(metadata);
          if (!metadata.available || Date.now() - lastImage > 5000) { release(); setSource(""); }
        }
      } catch (e) {
        if (!stopped) { release(); setSource(""); setPreview(null); setError(e instanceof Error ? e.message : "Mất kết nối ảnh camera"); }
      } finally { if (!stopped) timer = window.setTimeout(update, 800); }
    };
    connect(); void update();
    return () => { stopped = true; controller.abort(); clearTimeout(timer); clearTimeout(reconnect); socket?.close(); release(); };
  }, [effectiveCamera, api, paused, token, apiUrl]);

  const result = preview?.result;
  const wrongSession = Boolean(preview && (selectedSession ? Number(selectedSession) !== preview.config.session_id : false));
  const verified = source && !wrongSession && preview?.config.active && preview.session_id === preview.config.session_id && result?.accepted === true && !paused;
  const title = paused ? "Đã tạm dừng xem trước" : !source ? "Chưa có ảnh camera mới" : wrongSession ? "Camera đang xử lý buổi học khác" : verified ? result?.created === false ? "Đã điểm danh trước đó" : "Điểm danh thành công" : result?.state === "processing" ? "Đang xử lý khuôn mặt…" : result?.state === "preview" ? "Xem trước · Chưa chạy điểm danh" : "Đang xác thực";
  const reason = result?.reason ? reasons[result.reason] ?? result.reason : "Đứng trong khung ROI và nhìn thẳng camera.";
  const roi = preview?.config;
  // AI analyzes sampled frames, not necessarily the current live frame.

  return <section className={`panel camera-panel${expanded ? " camera-expanded" : ""}`}>
    <div className="panel-head"><div><h2>Camera điểm danh</h2><small>Ảnh từ ESP32 · không mở thêm stream trên thiết bị</small></div><div className="actions"><button className="secondary" onClick={() => setPaused(!paused)}>{paused ? "Tiếp tục" : "Tạm dừng"}</button><button className="secondary" onClick={() => setExpanded(!expanded)}>{expanded ? "Thu gọn" : "Phóng to"}</button></div></div>
    <label>Camera<select value={effectiveCamera} onChange={e => setCamera(e.target.value)} disabled={!devices.length}><option value="" disabled>Chưa có thiết bị</option>{devices.map(d => <option key={d.id} value={d.id}>{d.name} · {d.id}</option>)}</select></label>
    <div className="camera-layout"><div className="camera-view">{source && !paused ? <div className="camera-image-wrap"><img src={source} alt="Ảnh hiện tại từ camera điểm danh" onError={() => { setSource(""); setError("Không đọc được ảnh camera"); }} />{roi && <div className="camera-roi" style={{ left: `${roi.roi_left * 100}%`, top: `${roi.roi_top * 100}%`, width: `${(roi.roi_right - roi.roi_left) * 100}%`, height: `${(roi.roi_bottom - roi.roi_top) * 100}%` }}><span>VÙNG ĐIỂM DANH</span></div>}</div> : <div className="camera-placeholder"><strong>◎</strong><p>{paused ? "Xem trước đang tạm dừng" : "Đang chờ ảnh từ ESP32-CAM"}</p><small>Kết nối Wi-Fi ESP32 và chạy camera_bridge.py.<br />Đóng các trang /stream và ứng dụng đọc camera khác.</small></div>}</div>
    <div className={`camera-result${verified ? " confirmed" : ""}`} aria-live="polite"><p className="eyebrow">{verified ? "✓ BACKEND ĐÃ XÁC NHẬN" : "TRẠNG THÁI CAMERA"}</p><h3>{title}</h3>{verified ? <p className="camera-student">{result?.student_code}</p> : <p>{error || reason}</p>}{preview?.received_at && source && <small>Ảnh nhận lúc {new Date(preview.received_at).toLocaleTimeString("vi-VN")}</small>}{result?.pad_score !== undefined && <small>PAD real score: {result.pad_score.toFixed(3)}</small>}<hr /><small>{preview?.config.active ? `Camera được gán buổi #${preview.config.session_id}` : "Gán camera vào buổi đang mở ở Thiết bị & ROI để điểm danh."}</small><small>Video truyền độc lập với AI. Kết quả xác thực thuộc khung hình lấy mẫu gần nhất; ảnh chỉ giữ tạm trong RAM.</small>{paused && <small>Tạm dừng chỉ tắt màn hình xem trước; cầu nối và điểm danh vẫn hoạt động.</small>}</div></div>
  </section>;
}
