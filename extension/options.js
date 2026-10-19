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

$("moWms").addEventListener("click", () => chrome.tabs.create({ url: "https://wms-supra.winmart.vn/" }));

nap();
setInterval(nap, 4000);
