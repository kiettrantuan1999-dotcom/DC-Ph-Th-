"""Máy đồng bộ WMS – chạy trên 1 máy tính Windows ở Việt Nam (WMS chặn server nước ngoài).

Chỉ dùng HTTPS (cổng 443) – không kết nối thẳng database, nên chạy được sau firewall công ty:
  1. Mỗi vài giây hỏi app (APP_URL) "có việc không?" – đồng thời báo đang online.
  2. Có việc → đọc session WMS từ Google Sheet, tải báo cáo tồn kho theo Bin từ WMS.
  3. Gửi file Excel lên app; app lưu vào database.

Cấu hình trong file .env cạnh file này:
  APP_URL=https://dc-ph-th-production.up.railway.app
  WMS_AGENT_TOKEN=...                   (mã máy đồng bộ – lấy từ người quản trị app)
  GOOGLE_SERVICE_ACCOUNT_FILE=service-account.json
  WMS_AUTO_MINUTES=0                    (0 = chỉ lấy khi bấm nút trên app)

Chạy: python wms_agent.py        (hoặc run_wms_agent.bat: chạy nền, tự khởi động lại khi lỗi)
      python wms_agent.py --check  (kiểm tra kết nối rồi thoát)
"""
import logging
import os
import socket
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests

from app import wms  # nạp .env qua app.config

VERSION = "2.0"
POLL_SECONDS = 5
APP_URL = os.environ.get("APP_URL", "").rstrip("/")
TOKEN = os.environ.get("WMS_AGENT_TOKEN", "")
AUTO_MINUTES = int(os.environ.get("WMS_AUTO_MINUTES", "0"))
HOST = os.environ.get("WMS_AGENT_NAME") or socket.gethostname()

LOG_FILE = Path(__file__).with_name("wms_agent.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8"),
              logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("wms-agent")
http = requests.Session()
http.headers.update({"X-Agent-Token": TOKEN, "User-Agent": f"dinh-vi-pa-agent/{VERSION}"})


class AppError(Exception):
    pass


def call(method: str, path: str, timeout: int = 30, **kw) -> dict:
    try:
        r = http.request(method, APP_URL + path, timeout=timeout, **kw)
    except requests.RequestException as exc:
        raise AppError(f"Không kết nối được app {APP_URL}: {type(exc).__name__}")
    if r.status_code == 401:
        raise AppError("App từ chối: sai WMS_AGENT_TOKEN trong file .env")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text[:200]
        raise AppError(f"App trả lỗi HTTP {r.status_code}: {detail}")
    return r.json()


def poll() -> dict | None:
    return call("POST", "/api/agent/poll", json={"host": HOST, "version": VERSION, "auto_minutes": AUTO_MINUTES})["job"]


def do_job(job: dict) -> None:
    """Lấy báo cáo tồn Bin của từng ô session (mỗi ô một kho) rồi gửi lên app."""
    started = time.time()
    job_id = job["id"]
    cells = wms.SESSION_RANGES
    total = 0
    for i, cell in enumerate(cells, 1):
        try:
            content, file_name = wms.export_bin_stocks(cell)
        except Exception as exc:
            msg = str(exc) if isinstance(exc, wms.WmsError) else f"Lỗi trên máy đồng bộ ({type(exc).__name__})"
            log.warning("Việc #%s (%s) lỗi khi lấy WMS ở %s: %s", job_id, job["by"], cell, msg)
            if not isinstance(exc, wms.WmsError):
                log.exception("Chi tiết lỗi")
            call("POST", f"/api/agent/jobs/{job_id}/error", json={"message": f"{cell}: {msg}"})
            return
        res = call(
            "POST", f"/api/agent/jobs/{job_id}/result", timeout=180, data=content,
            headers={"Content-Type": "application/octet-stream", "X-File-Name": file_name,
                     "X-Part": str(i), "X-Parts": str(len(cells))},
        )
        total += res.get("rows") or 0
        log.info("Việc #%s · %s (%s) · %s dòng", job_id, cell, file_name, res.get("rows"))
    log.info("Việc #%s (%s) xong: %s dòng từ %s kho, %.1fs", job_id, job["by"], total, len(cells), time.time() - started)


def check() -> bool:
    ok = True
    print(f"  Máy đồng bộ: {HOST}")
    try:
        call("POST", "/api/agent/ping", json={"host": HOST, "version": VERSION, "auto_minutes": AUTO_MINUTES})
        print(f"  App {APP_URL}: OK")
    except AppError as exc:
        print(f"  App: LỖI – {exc}")
        ok = False
    try:
        for src in wms.session_info()["sources"]:
            print(f"  Session WMS ({src['source']}, kho {src['wh']}): OK – tài khoản {src['usid']}, lưu lúc {src['captured_at']}")
    except wms.WmsError as exc:
        print(f"  Session WMS: LỖI – {exc}")
        ok = False
    try:
        r = requests.get("https://api-supra.winmart.vn/", timeout=15)
        print(f"  Kết nối WMS: OK (HTTP {r.status_code})")
    except requests.RequestException as exc:
        print(f"  Kết nối WMS: LỖI – {type(exc).__name__}")
        ok = False
    return ok


def main() -> None:
    if not APP_URL or not TOKEN:
        sys.exit("Thiếu APP_URL hoặc WMS_AGENT_TOKEN trong file .env")
    if "--check" in sys.argv:
        sys.exit(0 if check() else 1)
    log.info("Máy đồng bộ WMS '%s' v%s khởi động – app %s – %s", HOST, VERSION, APP_URL,
             f"tự lấy mỗi {AUTO_MINUTES} phút" if AUTO_MINUTES else "chỉ lấy khi bấm nút trên app")
    errors = 0
    while True:
        try:
            job = poll()
            if errors:
                log.info("Kết nối app trở lại bình thường")
            errors = 0
            if job:
                do_job(job)
                continue
        except AppError as exc:
            errors += 1
            if errors in (1, 10) or errors % 100 == 0:
                log.warning("%s (lần %s)", exc, errors)
            time.sleep(min(60, POLL_SECONDS * errors))
        except Exception:
            log.exception("Lỗi không xác định – thử lại sau 30s")
            time.sleep(30)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
