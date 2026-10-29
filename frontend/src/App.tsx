import { FormEvent, useCallback, useEffect, useState } from "react";
import "./styles.css";
import CameraPanel from "./CameraPanel";

type Classroom = { id: number; code: string; name: string };
type Student = { id: number; student_code: string; name: string; class_id: number | null; date_of_birth: string | null; enrolled: boolean };
type Session = { id: number; class_id: number; title: string; status: string };
type Attendance = { id: number; student_id: number; student_code: string; student_name: string; checked_at: string; status: string; verification: string };
type Device = { id: string; name: string; status: string; last_seen: string };
type Event = { id: number; result: string; reason: string; created_at: string };
type Config = { session_id: number | null; roi_left: number; roi_top: number; roi_right: number; roi_bottom: number };
type ModelStatus = { pad: { ready: boolean; loaded: boolean; reason: string; model: string }; recognition: { ready: boolean; reason: string }; stable_frames: number; late_after_minutes: number };
const API = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const initialStudent = { student_code: "", name: "", class_id: "", date_of_birth: "" };
const labels: Record<string, string> = { present: "Đúng giờ", late: "Đi muộn", open: "Đang mở", closed: "Đã đóng", draft: "Chưa mở", online: "Trực tuyến", offline: "Ngoại tuyến", accepted: "Chấp nhận", rejected: "Từ chối", manual: "Thủ công", error: "Lỗi" };
const time = (value: string) => new Date(/Z$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`).toLocaleString("vi-VN");

export default function App() {
  const [token, setToken] = useState("");
  const [tab, setTab] = useState("attendance");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [classes, setClasses] = useState<Classroom[]>([]);
  const [students, setStudents] = useState<Student[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [rows, setRows] = useState<Attendance[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [models, setModels] = useState<ModelStatus | null>(null);
  const [selected, setSelected] = useState("");
  const [socketState, setSocketState] = useState("Chưa kết nối");
  const [studentForm, setStudentForm] = useState(initialStudent);
  const [editing, setEditing] = useState<number | null>(null);
  const [classForm, setClassForm] = useState({ code: "", name: "" });
  const [editingClass, setEditingClass] = useState<number | null>(null);
  const [deviceId, setDeviceId] = useState("");
  const [config, setConfig] = useState<Config | null>(null);
  const [search, setSearch] = useState("");

  const api = useCallback(async (path: string, init: RequestInit = {}) => {
    const headers = new Headers(init.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
    const response = await fetch(`${API}/api${path}`, { ...init, headers });
    if (!response.ok) {
      if (response.status === 401) setToken("");
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === "string" ? data.detail : `Yêu cầu thất bại (${response.status}). Kiểm tra dữ liệu nhập.`);
    }
    return response;
  }, [token]);

  const refresh = useCallback(async () => {
    const filter = selected ? `?session_id=${selected}` : "";
    const data = await Promise.all(["/classes", "/students", "/sessions", "/devices", `/attendance${filter}`, `/liveness-events${filter}`, "/system/status"].map(path => api(path).then(r => r.json())));
    setClasses(data[0]); setStudents(data[1]); setSessions(data[2]); setDevices(data[3]); setRows(data[4]); setEvents(data[5]); setModels(data[6]);
  }, [api, selected]);

  async function action(work: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await work(); await refresh(); setNotice("Đã cập nhật dữ liệu."); }
    catch (e) { setError(e instanceof Error ? e.message : "Không thể kết nối server"); }
    finally { setBusy(false); }
  }

  useEffect(() => {
    if (!token) return;
    let active = true;
    const load = () => refresh().catch(e => { if (active) setError(e.message); });
    void load(); const timer = window.setInterval(load, 10000);
    return () => { active = false; clearInterval(timer); };
  }, [token, refresh]);

  useEffect(() => {
    if (!token || !selected) { setSocketState("Chọn buổi học để theo dõi trực tiếp"); return; }
    let stopped = false; let reconnect: number; let ping: number; let socket: WebSocket;
    const connect = () => {
      setSocketState("Đang kết nối…");
      const socketUrl = new URL(`/ws/sessions/${selected}`, API || window.location.origin);
      socketUrl.protocol = socketUrl.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(socketUrl);
      socket.onopen = () => { socket.send(JSON.stringify({ token })); ping = window.setInterval(() => { if (socket.readyState === WebSocket.OPEN) socket.send("ping"); }, 20000); };
      socket.onmessage = e => { const message = JSON.parse(e.data); setSocketState("● Trực tiếp"); if (message.type !== "ready") void refresh().catch(err => setError(err.message)); };
      socket.onclose = e => { clearInterval(ping); if (stopped) return; if (e.code === 4401) { setToken(""); return; } if (e.code === 4404) { setSocketState("Buổi học không còn tồn tại"); setSelected(""); return; } setSocketState("Mất kết nối · đang thử lại"); reconnect = window.setTimeout(connect, 4000); };
      socket.onerror = () => socket.close();
    };
    connect();
    return () => { stopped = true; clearTimeout(reconnect); clearInterval(ping); socket?.close(); };
  }, [selected, token, refresh]);

  useEffect(() => {
    setConfig(null);
    if (!deviceId || !token) return;
    let active = true;
    api(`/devices/${encodeURIComponent(deviceId)}/config`).then(r => r.json()).then(data => { if (active) setConfig({ session_id: data.session_id, roi_left: data.roi_left, roi_top: data.roi_top, roi_right: data.roi_right, roi_bottom: data.roi_bottom }); }).catch(e => setError(e.message));
    return () => { active = false; };
  }, [deviceId, token, api]);

  const current = sessions.find(s => s.id === Number(selected));
  const roster = current ? students.filter(s => s.class_id === current.class_id) : [];
  const absent = roster.filter(s => !rows.some(r => r.student_id === s.id));
  const className = (id: number | null) => classes.find(c => c.id === id)?.code ?? "Chưa xếp lớp";
  const badge = (value: string) => <span className={`badge ${value}`}>{labels[value] ?? value}</span>;
  const onSubmit = (event: FormEvent<HTMLFormElement>, work: (data: FormData) => Promise<void>) => { event.preventDefault(); const data = new FormData(event.currentTarget); void action(() => work(data)); };

  if (!token) return <main className="login"><section className="login-intro"><p className="eyebrow">AIoT / FACE ATTENDANCE</p><h1>Điểm danh.<br />Có kiểm chứng.</h1><p>Quản lý lớp học, theo dõi thiết bị và xác thực khuôn mặt trong một không gian làm việc.</p><p className="muted">ESP32-CAM → ROI → PAD → Nhận diện → Điểm danh</p></section><form className="panel login-card" onSubmit={e => { e.preventDefault(); const data = new FormData(e.currentTarget); setBusy(true); setError(""); api("/auth/login", { method: "POST", body: JSON.stringify(Object.fromEntries(data)) }).then(r => r.json()).then(data => { setToken(data.access_token); }).catch(e => setError(e.message)).finally(() => setBusy(false)); }}><p className="eyebrow">KHÔNG GIAN GIẢNG VIÊN</p><h2>Đăng nhập</h2><label>Tên đăng nhập<input name="username" defaultValue="admin" autoComplete="username" required /></label><label>Mật khẩu<input name="password" type="password" autoComplete="current-password" required /></label>{error && <p role="alert" className="error">{error}</p>}<button disabled={busy}>{busy ? "Đang kết nối…" : "Vào dashboard →"}</button><small>Mật khẩu được cấu hình trong backend/.env. Token chỉ giữ trong bộ nhớ của trang.</small></form></main>;

  return <div className="shell"><aside><a className="brand" href="#" onClick={e => e.preventDefault()}><span className="brand-mark">A</span><span>Attendance<small>AIoT WORKSPACE</small></span></a><nav>{[["attendance", "01", "Điểm danh"], ["students", "02", "Sinh viên"], ["classes", "03", "Lớp & buổi học"], ["devices", "04", "Thiết bị & ROI"], ["events", "05", "Nhật ký xác thực"]].map(([key, number, title]) => <button key={key} className={tab === key ? "nav active" : "nav"} onClick={() => setTab(key)}><small>{number}</small>{title}</button>)}</nav><div className="aside-bottom"><p>Không báo thành công khi chưa đủ điều kiện xác thực.</p><button className="secondary" onClick={() => { setToken(""); setRows([]); setEvents([]); }}>Đăng xuất</button></div></aside><main className="workspace"><header><div><p className="eyebrow">HỆ THỐNG ĐIỂM DANH KHUÔN MẶT</p><h1>{({ attendance: "Theo dõi điểm danh", students: "Hồ sơ sinh viên", classes: "Lớp & buổi học", devices: "Thiết bị & vùng điểm danh", events: "Nhật ký xác thực" })[tab]}</h1></div><button className="secondary" disabled={busy} onClick={() => void action(async () => {})}>↻ Làm mới</button></header>{error && <div className="message error" role="alert">{error}<button className="link" onClick={() => setError("")}>Đóng</button></div>}{notice && <div className="message" role="status">{notice}</div>}
    {models && (!models.pad.ready || !models.recognition.ready) && <div className="warning"><strong>⚠ Điểm danh tự động chưa sẵn sàng</strong><span>PAD: {models.pad.reason}. Nhận diện: {models.recognition.reason}.</span><small>Có thể quản lý lớp và xác minh thủ công. Không bỏ qua PAD để chạy demo.</small></div>}
    {tab === "attendance" && <><CameraPanel api={api} devices={devices} selectedSession={selected} token={token} apiUrl={API} /><div className="toolbar"><label>Buổi học<select value={selected} onChange={e => setSelected(e.target.value)}><option value="">Tất cả bản ghi</option>{sessions.map(s => <option key={s.id} value={s.id}>{s.title} · {className(s.class_id)} · {labels[s.status]}</option>)}</select></label><span className="muted">{socketState}</span><button disabled={busy || !rows.length} onClick={() => void action(async () => { const response = await api(`/attendance/export${selected ? `?session_id=${selected}` : ""}`); const url = URL.createObjectURL(await response.blob()); const a = document.createElement("a"); a.href = url; a.download = `attendance-${selected || "all"}.csv`; a.click(); URL.revokeObjectURL(url); })}>↓ Xuất CSV</button></div><div className="stats"><section className="panel"><small>ĐÃ GHI NHẬN</small><strong>{rows.length}</strong><span>{selected ? "trong buổi học đã chọn" : "trong toàn hệ thống"}</span></section><section className="panel"><small>ĐI MUỘN</small><strong>{rows.filter(r => r.status === "late").length}</strong><span>Sau {models?.late_after_minutes ?? "—"} phút từ lúc mở</span></section><section className="panel"><small>CHƯA GHI NHẬN</small><strong>{current ? absent.length : "—"}</strong><span>{current ? `${roster.length} sinh viên hiện thuộc lớp` : "Chọn một buổi học để xem"}</span></section></div><section className="panel"><div className="panel-head"><h2>Danh sách điểm danh</h2>{current && badge(current.status)}</div><div className="table-wrap"><table><thead><tr><th>Sinh viên</th><th>Thời gian</th><th>Trạng thái</th><th>Xác thực</th></tr></thead><tbody>{rows.map(r => <tr key={r.id}><td><strong>{r.student_name}</strong><small>{r.student_code}</small></td><td>{time(r.checked_at)}</td><td>{badge(r.status)}</td><td><code>{r.verification}</code></td></tr>)}{!rows.length && <tr><td colSpan={4} className="empty">Chưa có bản ghi điểm danh.</td></tr>}</tbody></table></div></section>{current && <section className="panel spaced"><h2>Xác minh thay thế</h2><p className="muted">Chỉ dùng khi giảng viên đã kiểm tra trực tiếp danh tính. Bản ghi được gắn nhãn thủ công và lưu lý do.</p><form className="inline-form" onSubmit={e => onSubmit(e, async data => { await api(`/sessions/${selected}/manual-attendance`, { method: "POST", body: JSON.stringify({ student_id: Number(data.get("student_id")), reason: data.get("reason") }) }); })}><label>Sinh viên<select name="student_id" required><option value="">Chọn sinh viên chưa ghi nhận</option>{absent.map(s => <option key={s.id} value={s.id}>{s.student_code} · {s.name}</option>)}</select></label><label>Lý do<input name="reason" required minLength={5} maxLength={500} placeholder="Đã kiểm tra thẻ sinh viên…" /></label><button disabled={busy || current.status !== "open" || !absent.length}>Xác nhận thủ công</button></form></section>}</>}
    {tab === "students" && <><section className="panel"><h2>{editing ? "Cập nhật sinh viên" : "Thêm sinh viên"}</h2><form className="inline-form" onSubmit={e => onSubmit(e, async () => { await api(`/students${editing ? `/${editing}` : ""}`, { method: editing ? "PUT" : "POST", body: JSON.stringify({ ...studentForm, class_id: studentForm.class_id ? Number(studentForm.class_id) : null, date_of_birth: studentForm.date_of_birth || null }) }); setEditing(null); setStudentForm(initialStudent); })}><label>Mã sinh viên<input required pattern="[A-Za-z0-9_-]+" maxLength={32} value={studentForm.student_code} onChange={e => setStudentForm({ ...studentForm, student_code: e.target.value })} /></label><label>Họ và tên<input required maxLength={255} value={studentForm.name} onChange={e => setStudentForm({ ...studentForm, name: e.target.value })} /></label><label>Ngày sinh<input placeholder="dd/mm/yyyy" value={studentForm.date_of_birth} onChange={e => setStudentForm({ ...studentForm, date_of_birth: e.target.value })} /></label><label>Lớp<select value={studentForm.class_id} onChange={e => setStudentForm({ ...studentForm, class_id: e.target.value })}><option value="">Chưa xếp lớp</option>{classes.map(c => <option key={c.id} value={c.id}>{c.code}</option>)}</select></label><button disabled={busy}>{editing ? "Lưu" : "Thêm sinh viên"}</button>{editing && <button type="button" className="secondary" onClick={() => { setEditing(null); setStudentForm(initialStudent); }}>Hủy</button>}</form></section><section className="panel spaced"><div className="panel-head"><h2>Danh sách · {students.length}</h2><input aria-label="Tìm sinh viên" placeholder="Tìm tên hoặc mã sinh viên" value={search} onChange={e => setSearch(e.target.value)} /></div><div className="table-wrap"><table><thead><tr><th>Sinh viên</th><th>Lớp</th><th>Khuôn mặt</th><th>Thao tác</th></tr></thead><tbody>{students.filter(s => `${s.name} ${s.student_code}`.toLowerCase().includes(search.toLowerCase())).map(s => <tr key={s.id}><td><strong>{s.name}</strong><small>{s.student_code}</small></td><td>{className(s.class_id)}</td><td>{s.enrolled ? "✓ Đã đăng ký" : "Chưa đăng ký"}<details><summary>Đăng ký / thu hồi</summary><form className="enroll" onSubmit={e => onSubmit(e, async data => { await api(`/students/${s.id}/face`, { method: "POST", body: data }); })}><input aria-label="Ảnh đăng ký" name="image" type="file" accept="image/jpeg,image/png" required /><label className="check"><input type="checkbox" name="consent" value="true" required />Đã có sự đồng ý cho mục đích điểm danh; giảng viên đã kiểm tra đúng người.</label><small>Thay thế embedding cũ. Không lưu ảnh thô.</small><button disabled={busy}>Lưu embedding</button></form>{s.enrolled && <button className="danger" disabled={busy} onClick={() => { if (confirm(`Xóa embedding của ${s.name}?`)) void action(async () => { await api(`/students/${s.id}/face`, { method: "DELETE" }); }); }}>Thu hồi dữ liệu khuôn mặt</button>}</details></td><td><div className="actions"><button className="secondary" onClick={() => { setEditing(s.id); setStudentForm({ student_code: s.student_code, name: s.name, class_id: s.class_id?.toString() ?? "", date_of_birth: s.date_of_birth ?? "" }); window.scrollTo({ top: 0, behavior: "smooth" }); }}>Sửa</button><button className="danger" disabled={busy} onClick={() => { if (confirm(`Xóa hồ sơ ${s.student_code}? Hồ sơ có lịch sử điểm danh sẽ không bị xóa.`)) void action(async () => { await api(`/students/${s.id}`, { method: "DELETE" }); }); }}>Xóa</button></div></td></tr>)}{!students.length && <tr><td colSpan={4} className="empty">Thêm sinh viên hoặc chạy seed để nạp danh sách lớp.</td></tr>}</tbody></table></div></section></>}
    {tab === "classes" && <><div className="two-col"><section className="panel"><h2>{editingClass ? "Sửa lớp" : "Tạo lớp học"}</h2><form onSubmit={e => onSubmit(e, async () => { await api(`/classes${editingClass ? `/${editingClass}` : ""}`, { method: editingClass ? "PUT" : "POST", body: JSON.stringify(classForm) }); setClassForm({ code: "", name: "" }); setEditingClass(null); })}><label>Mã lớp<input required value={classForm.code} onChange={e => setClassForm({ ...classForm, code: e.target.value })} /></label><label>Tên lớp<input required value={classForm.name} onChange={e => setClassForm({ ...classForm, name: e.target.value })} /></label><button disabled={busy}>Lưu lớp</button>{editingClass && <button type="button" className="secondary" onClick={() => { setEditingClass(null); setClassForm({ code: "", name: "" }); }}>Hủy</button>}</form></section><section className="panel"><h2>Tạo buổi điểm danh</h2><form onSubmit={e => onSubmit(e, async data => { await api("/sessions", { method: "POST", body: JSON.stringify({ class_id: Number(data.get("class_id")), title: data.get("title") }) }); })}><label>Lớp<select name="class_id" required><option value="">Chọn lớp</option>{classes.map(c => <option key={c.id} value={c.id}>{c.code}</option>)}</select></label><label>Tên buổi học<input name="title" required maxLength={255} placeholder="IoT · Buổi 01" /></label><button disabled={busy || !classes.length}>Tạo buổi học</button></form></section></div><section className="panel spaced"><h2>Lớp học</h2><div className="list">{classes.map(c => <div className="list-row" key={c.id}><div><strong>{c.code}</strong><small>{c.name} · {students.filter(s => s.class_id === c.id).length} sinh viên</small></div><div className="actions"><button className="secondary" onClick={() => { setEditingClass(c.id); setClassForm({ code: c.code, name: c.name }); }}>Sửa</button><button className="danger" disabled={busy} onClick={() => { if (confirm(`Xóa lớp ${c.code}?`)) void action(async () => { await api(`/classes/${c.id}`, { method: "DELETE" }); }); }}>Xóa</button></div></div>)}{!classes.length && <p className="empty">Chưa có lớp học.</p>}</div></section><section className="panel spaced"><h2>Các buổi học</h2><div className="list">{sessions.map(s => <div className="list-row" key={s.id}><div><strong>{s.title}</strong><small>{className(s.class_id)} · #{s.id}</small></div><div className="actions">{badge(s.status)}<button className="secondary" onClick={() => { setSelected(String(s.id)); setTab("attendance"); }}>Xem</button>{s.status !== "closed" && <button disabled={busy} className={s.status === "open" ? "danger" : ""} onClick={() => { if (s.status === "open" && !confirm("Đóng buổi học? Không thể mở lại buổi đã đóng.")) return; void action(async () => { await api(`/sessions/${s.id}/${s.status === "open" ? "close" : "start"}`, { method: "POST" }); }); }}>{s.status === "open" ? "Đóng phiên" : "Mở điểm danh"}</button>}</div></div>)}{!sessions.length && <p className="empty">Chưa có buổi học.</p>}</div></section></>}
    {tab === "devices" && <><section className="panel"><h2>Camera đã kết nối</h2><p className="muted">Thiết bị xuất hiện sau heartbeat đầu tiên. Chọn thiết bị để gán buổi học và hiệu chỉnh ROI.</p><div className="list">{devices.map(d => <button className={`device-row ${deviceId === d.id ? "selected" : ""}`} key={d.id} onClick={() => setDeviceId(d.id)}><span><strong>{d.name}</strong><small>{d.id} · Lần cuối {time(d.last_seen)}</small></span>{badge(d.status)}</button>)}{!devices.length && <p className="empty">Chưa nhận heartbeat từ ESP32-CAM.</p>}</div></section>{config && <section className="panel spaced"><h2>Cấu hình · {deviceId}</h2><form onSubmit={e => onSubmit(e, async () => { await api(`/devices/${encodeURIComponent(deviceId)}/config`, { method: "PUT", body: JSON.stringify(config) }); })}><label>Buổi học được gán<select value={config.session_id ?? ""} onChange={e => setConfig({ ...config, session_id: e.target.value ? Number(e.target.value) : null })}><option value="">Không gán / dừng gửi ảnh</option>{sessions.filter(s => s.status !== "closed").map(s => <option key={s.id} value={s.id}>{s.title} · {labels[s.status]}</option>)}</select></label><p className="muted">ROI dùng tọa độ chuẩn hóa 0–1, không phải pixel. Cần hiệu chỉnh theo góc lắp camera.</p><div className="roi-preview" aria-label="Minh họa ROI, không phải ảnh camera"><span style={{ left: `${config.roi_left * 100}%`, top: `${config.roi_top * 100}%`, width: `${(config.roi_right - config.roi_left) * 100}%`, height: `${(config.roi_bottom - config.roi_top) * 100}%` }}>VÙNG ĐIỂM DANH</span></div><div className="inline-form">{(["roi_left", "roi_top", "roi_right", "roi_bottom"] as const).map((key, index) => <label key={key}>{["Trái", "Trên", "Phải", "Dưới"][index]}<input type="number" min="0" max="1" step="0.01" required value={config[key]} onChange={e => setConfig({ ...config, [key]: Number(e.target.value) })} /></label>)}</div><button disabled={busy || config.roi_left >= config.roi_right || config.roi_top >= config.roi_bottom}>Lưu cấu hình</button></form></section>}<section className="panel spaced"><h2>Trạng thái xử lý</h2><p>PAD: {models?.pad.model} · {models?.pad.loaded ? "Đã nạp ONNX" : "Chưa nạp model"}</p><p>Yêu cầu {models?.stable_frames ?? "—"} khung hình ổn định trước khi xác thực.</p><p className="muted">Ổn định hình học không chứng minh danh tính hoặc hướng di chuyển. PAD không bảo đảm chống giả mạo tuyệt đối.</p></section></>}
    {tab === "events" && <section className="panel"><div className="panel-head"><h2>Sự kiện gần nhất · tối đa 200</h2><select aria-label="Lọc nhật ký" value={selected} onChange={e => setSelected(e.target.value)}><option value="">Tất cả buổi học</option>{sessions.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}</select></div><div className="table-wrap"><table><thead><tr><th>Thời gian</th><th>Kết quả</th><th>Chi tiết</th></tr></thead><tbody>{events.map(e => <tr key={e.id}><td>{time(e.created_at)}</td><td>{badge(e.result)}</td><td>{e.reason}</td></tr>)}{!events.length && <tr><td colSpan={3} className="empty">Chưa có sự kiện xác thực.</td></tr>}</tbody></table></div></section>}
    <footer>AIoT Face Attendance · Dữ liệu thực từ backend · Tự làm mới mỗi 10 giây</footer></main></div>;
}
