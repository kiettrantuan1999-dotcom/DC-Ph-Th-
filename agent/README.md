# Bộ cài máy đồng bộ WMS

Thư mục này giữ các file cài đặt (không chứa khóa). Gói để chép sang máy khác nằm ở
`dist/may-dong-bo-wms.zip` – thư mục `dist/` **không** được đưa lên git vì có `.env`
(mã máy đồng bộ) và `service-account.json`.

Tạo lại gói cài đặt khi đổi máy hoặc sau khi sửa code:

1. Tạo thư mục `dist/may-dong-bo-wms` gồm:
   - `wms_agent.py`, `run_wms_agent.bat`
   - `app/__init__.py`, `app/config.py`, `app/wms.py`
   - 3 file trong thư mục này: `CAI DAT.bat`, `GO CAI DAT.bat`, `HUONG DAN.txt`
   - `requirements.txt` gồm: google-auth, requests, openpyxl, tzdata
   - `service-account.json`: file JSON của service account đọc Google Sheet
   - `.env`:
     ```
     APP_URL=https://dc-ph-th-production.up.railway.app
     WMS_AGENT_TOKEN=<lấy bằng: python -c "from app import wms_sync; print(wms_sync.agent_token())">
     GOOGLE_SERVICE_ACCOUNT_FILE=service-account.json
     WMS_AUTO_MINUTES=0
     ```
2. Nén cả thư mục thành `dist/may-dong-bo-wms.zip`.

Trên máy đồng bộ: giải nén vào `C:\`, chạy `CAI DAT.bat`. File này cài thư viện, kiểm tra
kết nối (App / Google Sheet / WMS), tạo file tự khởi động trong thư mục Startup rồi chạy ngay.

Máy đồng bộ phải vào được WMS: ở trong mạng công ty hoặc đã bật VPN công ty.
