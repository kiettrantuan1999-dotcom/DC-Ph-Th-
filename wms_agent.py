"""Máy đồng bộ WMS – chạy trên 1 máy tính Windows ở Việt Nam (WMS chặn server nước ngoài).

Việc làm:
  - Mỗi vài giây: báo "đang online" lên Supabase và nhận yêu cầu "Lấy dữ liệu mới" từ app.
  - Chỉ gọi WMS khi có người bấm "Lấy dữ liệu mới" trên app.
    (Muốn tự lấy định kỳ thì đặt WMS_AUTO_MINUTES=30 – mặc định 0 = tắt.)

Cấu hình trong file .env cạnh file này:
  DATABASE_URL=...                    (giống app)
  GOOGLE_SERVICE_ACCOUNT_FILE=...     (file JSON service account đọc session WMS)
  WMS_AUTO_MINUTES=0                  (0 = chỉ lấy khi bấm nút trên app)

Chạy: python wms_agent.py      (hoặc run_wms_agent.bat để chạy nền, tự khởi động lại khi lỗi)
"""
import logging
import os
import socket
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app import config, db, wms, wms_sync

VERSION = "1.0"
POLL_SECONDS = 5
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


def heartbeat() -> None:
    db.execute(
        """insert into wms_agent (host, last_seen, auto_minutes, version) values (%s, now(), %s, %s)
           on conflict (host) do update set last_seen = now(), auto_minutes = excluded.auto_minutes,
                                            version = excluded.version""",
        (HOST, AUTO_MINUTES, VERSION),
    )


def claim_request() -> dict | None:
    """Nhận 1 yêu cầu PENDING (khóa để 2 máy đồng bộ không làm trùng)."""
    return db.fetch_one(
        """update wms_sync_log set status = 'RUNNING', started_at = now()
           where id = (select id from wms_sync_log where status = 'PENDING' order by id limit 1 for update skip locked)
           returning id, username"""
    )


def auto_due() -> bool:
    if AUTO_MINUTES <= 0:
        return False
    row = db.fetch_one(
        "select extract(epoch from now() - max(started_at))::int as age from wms_sync_log where status <> 'PENDING'"
    )
    return row["age"] is None or row["age"] >= AUTO_MINUTES * 60


def do_sync(log_id: int, who: str) -> None:
    started = time.time()
    try:
        n = wms_sync.run(log_id)
        log.info("Đồng bộ #%s (%s) xong: %s dòng, %.1fs", log_id, who, n, time.time() - started)
    except wms.WmsError as exc:
        log.warning("Đồng bộ #%s (%s) lỗi: %s", log_id, who, exc)
    except Exception:
        log.exception("Đồng bộ #%s (%s) lỗi không xác định", log_id, who)


def main() -> None:
    config.validate()
    db.open_pool()
    if AUTO_MINUTES:
        log.info("Máy đồng bộ WMS '%s' khởi động – tự lấy dữ liệu mỗi %s phút", HOST, AUTO_MINUTES)
    else:
        log.info("Máy đồng bộ WMS '%s' khởi động – chỉ lấy dữ liệu khi bấm nút trên app", HOST)
    while True:
        try:
            heartbeat()
            wms_sync.expire_stale()
            req = claim_request()
            if req:
                do_sync(req["id"], req["username"])
            elif auto_due():
                row = db.fetch_one(
                    "insert into wms_sync_log (status, username) values ('RUNNING', %s) returning id",
                    (f"auto:{HOST}",),
                )
                do_sync(row["id"], "tự động")
        except Exception:
            log.exception("Lỗi vòng lặp – thử lại sau %ss", POLL_SECONDS * 6)
            time.sleep(POLL_SECONDS * 6)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
