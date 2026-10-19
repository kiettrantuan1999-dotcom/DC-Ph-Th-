/* Extension "Định vị PA – Đồng bộ WMS"
 *
 *  1. Nhân viên đăng nhập WMS như bình thường → extension bắt lấy session của từng kho
 *     (các header mà WMS gửi kèm mỗi request) và lưu trong máy.
 *  2. Mỗi 30 giây hỏi app xem có ai bấm "Lấy dữ liệu mới" không.
 *  3. Có việc → tải báo cáo tồn kho theo Bin của từng kho rồi đẩy file lên app.
 *
 *  Session không rời khỏi máy nhân viên: chỉ file báo cáo được gửi lên app.
 */
importScripts("config.js");

const HEADER_KEYS = ["apisid", "authorization", "scid", "sid", "token", "usid", "warehouse", "appid"];
const SIGN_KEYS = ["x-signature", "x-signature-nonce"];
const WMS_HOST = "https://api-supra.winmart.vn";
const VERSION = "1.0.0";

// Mỗi hệ thống WMS một đường dẫn báo cáo tồn Bin
const REPORTS = {
  sft3: {
    path: "/api/v1/report/stock/exportBinStocks",
    params: (wh) => ({ FromWH: "true", Content: "", ClientCode: "WIN", WhCode: wh,
                       WarehouseSiteId: "", PickupMethod: "", IsConsign: "false" }),
  },
  legacy: {
    path: "/api/v1/report/exportBinInventory",
    params: (wh) => ({ Content: "", ClientCode: "", WhCode: wh, WarehouseSiteId: "", WhSite: "" }),
  },
};

const get = (keys) => chrome.storage.local.get(keys);
const set = (obj) => chrome.storage.local.set(obj);

async function cauHinh() {
  const s = await get(["appUrl", "token", "dc", "tenMay"]);
  return {
    appUrl: (s.appUrl || self.CAU_HINH_MAC_DINH.appUrl || "").replace(/\/+$/, ""),
    token: s.token || self.CAU_HINH_MAC_DINH.token || "",
    dc: s.dc || self.CAU_HINH_MAC_DINH.dc || "",
    tenMay: s.tenMay || "",
  };
}

async function ghiNhatKy(dong) {
  const { log = [] } = await get("log");
  log.unshift(`${new Date().toLocaleString("vi-VN")} · ${dong}`);
  await set({ log: log.slice(0, 60) });
}

// ---------------------------------------------------------------- 1. Bắt session từ WMS
chrome.webRequest.onBeforeSendHeaders.addListener(
  (chiTiet) => {
    const h = {};
    for (const { name, value } of chiTiet.requestHeaders || []) {
      const k = name.toLowerCase();
      if (HEADER_KEYS.includes(k) || SIGN_KEYS.includes(k)) h[k] = value;
    }
    const wh = (h.warehouse || "").trim();
    if (!wh || !h.token || !h.authorization || !h.sid) return;   // chưa đăng nhập xong
    const url = new URL(chiTiet.url);
    const base = `${url.origin}/${url.pathname.split("/").filter(Boolean)[0] || ""}`;
    luuSession(wh, { wh, base, headers: h, at: new Date().toISOString() });
  },
  { urls: [`${WMS_HOST}/*`] },
  ["requestHeaders"]
);

let dangLuu = Promise.resolve();
function luuSession(wh, phien) {
  dangLuu = dangLuu.then(async () => {
    const { sessions = {} } = await get("sessions");
    const cu = sessions[wh];
    // chỉ ghi khi có thay đổi thật sự, tránh ghi liên tục
    const giongNhau = cu && cu.base === phien.base &&
      HEADER_KEYS.concat(SIGN_KEYS).every((k) => (cu.headers[k] || "") === (phien.headers[k] || ""));
    if (giongNhau) return;
    sessions[wh] = phien;
    await set({ sessions });
    await ghiNhatKy(`Cập nhật session kho ${wh} (${phien.base.split("/").pop()})`);
  });
  return dangLuu;
}

// ---------------------------------------------------------------- 2. Hỏi app xem có việc không
async function goiApp(duongDan, tuyChon = {}) {
  const { appUrl, token } = await cauHinh();
  if (!appUrl || !token) throw new Error("Chưa cấu hình link app hoặc mã máy đồng bộ");
  const r = await fetch(appUrl + duongDan, {
    ...tuyChon,
    headers: { "X-Agent-Token": token, ...(tuyChon.headers || {}) },
  });
  if (r.status === 401) throw new Error("App từ chối: sai mã máy đồng bộ");
  if (!r.ok) throw new Error(`App trả lỗi HTTP ${r.status}`);
  return r;
}

async function tenMay() {
  const { tenMay } = await cauHinh();
  if (tenMay) return tenMay;
  const { tenTuDong } = await get("tenTuDong");
  if (tenTuDong) return tenTuDong;
  const { sessions = {} } = await get("sessions");
  const usid = Object.values(sessions)[0]?.headers?.usid;
  const ten = "ext:" + (usid || Math.random().toString(36).slice(2, 7));
  await set({ tenTuDong: ten });
  return ten;
}

async function hoiViec() {
  const body = JSON.stringify({ host: await tenMay(), version: VERSION, auto_minutes: 0 });
  const r = await goiApp("/api/agent/poll", {
    method: "POST", body, headers: { "Content-Type": "application/json" },
  });
  return (await r.json()).job;
}

// ---------------------------------------------------------------- 3. Lấy báo cáo rồi đẩy lên app
async function taiBaoCao(phien) {
  const kieu = phien.base.includes("/sft3-") ? "sft3" : "legacy";
  const bc = REPORTS[kieu];
  const url = new URL(phien.base + bc.path);
  Object.entries(bc.params(phien.wh)).forEach(([k, v]) => url.searchParams.set(k, v));
  const headers = {
    accept: "application/json, text/plain, */*",
    "content-type": "application/json",
    ...phien.headers,
  };
  delete headers.warehouse;
  headers.warehouse = phien.wh;
  const r = await fetch(url.toString(), { headers, credentials: "omit" });
  if (r.status === 401 || r.status === 403) throw new Error(`kho ${phien.wh}: session hết hạn, mở lại WMS`);
  if (!r.ok) throw new Error(`kho ${phien.wh}: WMS trả lỗi HTTP ${r.status}`);
  const ct = r.headers.get("content-type") || "";
  if (!ct.includes("spreadsheetml")) throw new Error(`kho ${phien.wh}: WMS không trả file Excel`);
  const ten = r.headers.get("X-Download-FileName") || `REPORT_BIN_INVENTORY_${phien.wh}.xlsx`;
  return { blob: await r.blob(), ten };
}

async function lamViec(job) {
  const { sessions = {} } = await get("sessions");
  const khoCanLay = (job.warehouses && job.warehouses.length ? job.warehouses : Object.keys(sessions));
  const thieu = khoCanLay.filter((wh) => !sessions[wh]);
  if (thieu.length) {
    const msg = `Chưa có session kho ${thieu.join(", ")} – mở WMS và chọn kho đó một lần`;
    await goiApp(`/api/agent/jobs/${job.id}/error`, {
      method: "POST", body: JSON.stringify({ message: msg }), headers: { "Content-Type": "application/json" },
    });
    await ghiNhatKy(`Việc #${job.id}: ${msg}`);
    return;
  }
  let tong = 0;
  for (let i = 0; i < khoCanLay.length; i++) {
    const wh = khoCanLay[i];
    try {
      const { blob, ten } = await taiBaoCao(sessions[wh]);
      const r = await goiApp(`/api/agent/jobs/${job.id}/result`, {
        method: "POST", body: blob,
        headers: { "Content-Type": "application/octet-stream", "X-File-Name": ten,
                   "X-Part": String(i + 1), "X-Parts": String(khoCanLay.length) },
      });
      const kq = await r.json();
      tong += kq.rows || 0;
      await ghiNhatKy(`Việc #${job.id} · kho ${wh}: ${kq.rows} dòng`);
    } catch (e) {
      await goiApp(`/api/agent/jobs/${job.id}/error`, {
        method: "POST", body: JSON.stringify({ message: String(e.message || e) }),
        headers: { "Content-Type": "application/json" },
      });
      await ghiNhatKy(`Việc #${job.id} · kho ${wh} LỖI: ${e.message || e}`);
      return;
    }
  }
  await set({ lanCuoi: new Date().toISOString(), dongCuoi: tong });
  await ghiNhatKy(`Việc #${job.id} xong: ${tong} dòng`);
}

let dangChay = false;
async function vongLap() {
  if (dangChay) return;
  dangChay = true;
  try {
    const job = await hoiViec();
    await set({ ketNoi: "ok", loiKetNoi: "" });
    if (job) await lamViec(job);
  } catch (e) {
    await set({ ketNoi: "loi", loiKetNoi: String(e.message || e) });
  } finally {
    dangChay = false;
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("dongbo", { periodInMinutes: 0.5 });
  vongLap();
});
chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create("dongbo", { periodInMinutes: 0.5 });
});
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === "dongbo") vongLap();
});
chrome.runtime.onMessage.addListener((msg, _s, traLoi) => {
  if (msg === "dongbo-ngay") vongLap().then(() => traLoi({ ok: true }));
  return true;
});
