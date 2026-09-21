# App Định vị PA – DC Phú Thọ

Web app chạy trên trình duyệt của PDA để định vị pallet nhập hàng.

- **Đăng nhập** bằng tài khoản riêng của từng người.
- **ĐỊNH VỊ**: nhân viên scan → mã PA → mã vị trí, app tự lưu ngay khi scan xong vị trí.
- **CHUYỂN**: chuyển PA từ vị trí lưu trữ này sang vị trí khác.
- **LOG**: xem lịch sử, tìm theo mã PA / vị trí / nhân viên, lọc theo ngày, loại thao tác, hoặc chỉ của mình.
- **WMS**: lấy báo cáo tồn kho theo Bin từ WMS Supra, xem / tìm / lọc (ví dụ các PA *Chờ lưu trữ*) và xuất Excel.
- **USER**: admin tạo / sửa / khóa tài khoản, đặt lại mật khẩu.

### Luật vị trí

- **1 PA chỉ ở đúng 1 vị trí.** Database chặn cứng việc này (bảng `pallet_locations`, khóa chính là mã PA).
- **1 vị trí chứa được nhiều PA.** Sau mỗi lần lưu, app báo vị trí đó hiện có bao nhiêu PA.
- **ĐỊNH VỊ chỉ dùng cho PA chưa có vị trí.** Nếu PA đã ở vị trí khác, app chặn và nhắc sang tab CHUYỂN. Nếu scan lại đúng vị trí cũ, app báo "đã ở vị trí này" và không ghi thêm log.
- **CHUYỂN** chỉ dùng cho PA đã được định vị. Scan PA xong, app hiện vị trí hiện tại, sau đó scan vị trí mới. Log ghi lại cả vị trí cũ và vị trí mới.

### Phân quyền

| Loại tài khoản | ĐỊNH VỊ | CHUYỂN | LOG | WMS | USER |
|---|:-:|:-:|:-:|:-:|:-:|
| Admin | ✔ | ✔ | ✔ | ✔ | ✔ |
| Chuyên viên | ✔ | ✔ | ✔ | ✔ | |
| Nhân viên | ✔ | ✔ | | | |

Để đổi quyền, sửa bảng `ROLES` trong `app/main.py`.

Công nghệ: Python (FastAPI) · Supabase (Postgres) · Railway.

```
app/main.py          API + trả giao diện
app/static/index.html  Giao diện PDA (login / scan / log)
sql/schema.sql       Tạo bảng trên Supabase (project mới)
sql/002_*.sql        Nâng cấp database đã tạo bằng bản đầu
manage_users.py      Tạo / đổi mật khẩu / khóa tài khoản
```

---

## 1. Supabase – tạo database

1. Vào https://supabase.com, chọn **New project**, region **Southeast Asia (Singapore)**. Nhớ lại mật khẩu database.
2. Mở **SQL Editor → New query**, dán toàn bộ nội dung `sql/schema.sql` rồi bấm **Run**. Nếu database đã tạo bằng bản đầu tiên, chạy thêm file `sql/002_one_pa_one_location.sql`.
3. Bấm nút **Connect** ở đầu trang, chọn **Session pooler** và copy URI.
   Trong URI, thay `[YOUR-PASSWORD]` bằng mật khẩu database. Đây là `DATABASE_URL`.

> Chọn **Session pooler** vì Railway không kết nối được "Direct connection" (địa chỉ đó chỉ có IPv6).

## 2. Chạy thử trên máy tính và tạo tài khoản

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Mở file `.env` và điền:

- `DATABASE_URL`: chuỗi kết nối lấy ở bước 1.
- `SECRET_KEY`: tạo bằng lệnh `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

Tạo tài khoản admin đầu tiên. Các tài khoản khác admin tạo ngay trong app, ở tab **USER**:

```bash
python manage_users.py add admin "Quản trị" --role admin
python manage_users.py list
```

Để tạo nhiều tài khoản một lần, chuẩn bị file `users.csv` có các cột `username,full_name,password,role` (role là `admin`, `chuyenvien` hoặc `nhanvien`; bỏ trống thì mặc định là nhân viên). Sau đó chạy `python manage_users.py import users.csv`.

Các lệnh quản lý khác:

| Việc cần làm | Lệnh |
|---|---|
| Đổi / reset mật khẩu | `python manage_users.py passwd nv01` |
| Đổi loại tài khoản | `python manage_users.py role nv01 chuyenvien` |
| Khóa tài khoản (nghỉ việc) | `python manage_users.py disable nv01` |
| Mở khóa | `python manage_users.py enable nv01` |

Khi đổi mật khẩu hoặc khóa tài khoản, PDA đang đăng nhập bằng tài khoản đó sẽ bị đăng xuất.

Chạy thử:

```bash
uvicorn app.main:app --reload --port 8000
```

Sau đó mở http://localhost:8000.

## 3. Deploy lên Railway

1. Đưa code lên một **GitHub repo private**. File `.env` đã nằm trong `.gitignore` nên không bị đẩy lên.
2. Trên https://railway.com, chọn **New Project → Deploy from GitHub repo** và chọn repo vừa tạo.
3. Vào tab **Variables** của service, thêm hai biến:
   - `DATABASE_URL`
   - `SECRET_KEY` (dùng cùng giá trị trong `.env`, hoặc tạo một giá trị mới)
4. Vào **Settings → Networking → Generate Domain** để lấy link dạng `https://xxx.up.railway.app`.
5. Nên chọn region **Southeast Asia (Singapore)** cho gần Supabase (trong **Settings → Deploy → Region**).

Railway tự nhận Python qua `requirements.txt`. Lệnh chạy và healthcheck `/healthz` đã khai báo sẵn trong `railway.json`. Mỗi lần push code lên GitHub, Railway tự deploy lại.

## 4. Cài trên PDA

1. Mở **Chrome** trên PDA, vào link Railway.
2. Mở menu ⋮ và chọn **Add to Home screen**. App sẽ mở toàn màn hình như app thường.
3. **Cấu hình đầu scan** (quan trọng). Đầu scan phải xuất dữ liệu kiểu bàn phím và thêm phím **Enter** ở cuối:
   - **Zebra (DataWedge)**: trong Profile, bật *Keystroke output* và tắt *Intent output*. Vào *Keystroke output → Basic data formatting*, tích **Send ENTER key**.
   - **Honeywell**: vào *Settings → Honeywell Settings → Scanning → Internal Scanner → Default profile → Data Processing Settings*. Chọn *Wedge Method = Standard/Keyboard* và *Suffix = `\n`* (Enter).
   - **Urovo / Chainway / iData**: vào *Scanner settings*. Chọn *Output mode = Keyboard / Input method (Keyboard emulation)* và bật *Add suffix: Enter*.

## Cách dùng màn ĐỊNH VỊ

1. **Nhân viên scan**: mặc định là tên người đăng nhập. Có thể sửa hoặc scan thẻ nhân viên. Máy sẽ nhớ tên này cho các lần sau.
2. Scan **mã PA**. Con trỏ tự nhảy xuống ô vị trí.
3. Scan **mã vị trí**. App tự lưu, kêu *bíp* và rung, rồi quay về ô mã PA để scan pallet tiếp theo.

Kết quả hiện theo màu:

- **Xanh**: đã lưu. Dòng dưới cho biết vị trí đó hiện có bao nhiêu PA.
- **Vàng**: PA đã ở đúng vị trí này từ trước. App không ghi thêm log.
- **Đỏ + bíp 2 tiếng**: chưa lưu. Dòng chữ bên dưới cho biết lý do, ví dụ PA đã có vị trí khác, mất mạng, hoặc scan nhầm mã.

Màn **CHUYỂN** dùng tương tự: scan PA, app hiện vị trí hiện tại, rồi scan **vị trí mới**.

Khi scan, bàn phím ảo được ẩn để không che màn hình. Nếu cần gõ tay, bấm **⌨ Gõ tay**.

## Tùy chỉnh (biến môi trường)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `SESSION_HOURS` | 12 | Số giờ giữ đăng nhập (1 ca) |
| `PA_PATTERN` | *(trống)* | Regex định dạng mã PA, ví dụ `PA\d{8}`. Có giá trị thì app chặn khi scan nhầm mã |
| `LOC_PATTERN` | *(trống)* | Regex định dạng mã vị trí, ví dụ `[A-Z]\d{2}-\d{2}-\d{2}` |
| `APP_TZ` | Asia/Ho_Chi_Minh | Múi giờ hiển thị |

## Tra cứu / xuất báo cáo

Trên Supabase, mở **Table Editor** để xem hai nguồn dữ liệu:

- `pallet_scans`: toàn bộ log. Cột `action` là `NHAP` (định vị) hoặc `CHUYEN` (chuyển vị trí).
- `pallet_locations`: vị trí hiện tại của từng PA.

Có thể lọc dữ liệu rồi **Export → CSV** để mở bằng Excel.

## Module WMS – tồn kho theo Bin

Tab **WMS** gọi API `exportBinStocks` của WMS Supra, kho PTD. Mỗi lần bấm **⟳ Lấy dữ liệu mới**, app lấy bản mới nhất (khoảng 20 giây) và thay toàn bộ bảng `wms_bin_stocks` trên Supabase.

**Session WMS** không lưu trong app mà nằm ở:

- Google Sheet *Central OPS*, tab **Config**, ô **B2** (ô B1 là của DC Nghệ An). Ô này chứa link Google Drive tới file session xuất bằng extension **Supra Session Capture**.
- Khi app báo *"Session WMS đã hết hạn"*: vào wms-supra.winmart.vn, xuất lại session bằng extension, rồi dán link Drive mới vào ô B2. App tự đọc lại, không cần deploy.

**Service account** `getdata@central-ops-507204.iam.gserviceaccount.com` cần quyền **Viewer** trên cả Google Sheet và file session trên Drive.

- Trên Railway: tạo biến `GOOGLE_SERVICE_ACCOUNT_JSON`, dán toàn bộ nội dung file JSON của service account.
- Khi chạy trên máy: dùng `GOOGLE_SERVICE_ACCOUNT_FILE` trỏ tới file JSON.
