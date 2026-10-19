const $ = (id) => document.getElementById(id);
const MAC_DINH = self.CAU_HINH_MAC_DINH || { dc: "", appUrl: "", token: "" };

async function nap() {
  const s = await chrome.storage.local.get(null);
  const macDinh = MAC_DINH;
  $("dc").textContent = s.dc || macDinh.dc || "";
  $("appUrl").value = s.appUrl || macDinh.appUrl || "";
  $("token").value = s.token || macDinh.token || "";
  $("tenMay").value = s.tenMay || s.tenTuDong || "";

  const ok = s.ketNoi === "ok";
  $("cham").className = "cham " + (s.ketNoi === "ok" ? "ok" : s.ketNoi === "loi" ? "loi" : "");
  $("ketnoi").textContent = ok ? "Đã kết nối app, đang chờ yêu cầu" : (s.loiKetNoi || "Chưa kết nối app");
  $("lancuoi").textContent = s.lanCuoi
    ? `Lần đồng bộ gần nhất: ${new Date(s.lanCuoi).toLocaleString("vi-VN")} · ${s.dongCuoi || 0} dòng`
    : "Chưa đồng bộ lần nào";

  const ss = s.sessions || {};
  const ds = Object.values(ss);
  $("bangKho").innerHTML = ds.length
    ? ds.map((x) => `<tr><td class="kho">${x.wh}</td><td class="muted">${x.base.split("/").pop()}</td>
        <td class="muted">${x.headers.usid || ""}</td>
        <td class="muted">${new Date(x.at).toLocaleString("vi-VN")}</td></tr>`).join("")
    : `<tr><td class="muted">Chưa có. Mở WMS, chọn kho cần lấy dữ liệu rồi quay lại đây.</td></tr>`;
  const cd = s.chanDoan;
  $("chanDoanTom").textContent = cd
    ? `${cd.so} yêu cầu từ lần khởi động gần nhất · cập nhật ${new Date(cd.luc).toLocaleString("vi-VN")}`
    : "Chưa thấy yêu cầu nào tới api-supra.winmart.vn. Hãy mở WMS và bấm vào một màn hình có dữ liệu.";
  $("bangChanDoan").innerHTML = (cd && cd.gan && cd.gan.length)
    ? `<tr><td class="kho">Kho</td><td class="muted">Đường dẫn</td><td class="muted">Header có</td><td class="muted">Thiếu</td></tr>`
      + cd.gan.map((x) => `<tr><td class="kho">${x.wh || "?"}</td><td class="muted">${x.duongDan}</td>
          <td class="muted">${x.co || "(không có)"}</td><td class="muted">${x.thieu || "–"}</td></tr>`).join("")
    : "";
  $("log").textContent = (s.log || []).join("\n") || "(trống)";
}

$("luu").addEventListener("click", async () => {
  await chrome.storage.local.set({
    appUrl: $("appUrl").value.trim().replace(/\/+$/, ""),
    token: $("token").value.trim(),
    tenMay: $("tenMay").value.trim(),
  });
  $("daLuu").textContent = "Đã lưu";
  chrome.runtime.sendMessage("dongbo-ngay", () => setTimeout(nap, 1500));
});

$("dongbo").addEventListener("click", () => {
  $("ketnoi").textContent = "Đang kiểm tra…";
  chrome.runtime.sendMessage("dongbo-ngay", () => setTimeout(nap, 2000));
});

const WMS_URLS = MAC_DINH.wmsUrls && MAC_DINH.wmsUrls.length
  ? MAC_DINH.wmsUrls : ["https://wms-supra.winmart.vn/sft3/app/dashboard"];
$("moWms").addEventListener("click", () => WMS_URLS.forEach((u) => chrome.tabs.create({ url: u })));

nap();
setInterval(nap, 4000);
