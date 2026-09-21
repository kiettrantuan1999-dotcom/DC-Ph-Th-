"""Đồng bộ báo cáo tồn kho theo Bin từ WMS vào bảng wms_bin_stocks.

  - Chế độ "direct": server tự gọi WMS (khi server ở Việt Nam).
  - Chế độ "agent" (Railway bị WMS chặn): app chỉ tạo yêu cầu; máy đồng bộ wms_agent.py ở Việt Nam
    nhận việc qua /api/agent/poll, lấy file từ WMS rồi gửi lên /api/agent/jobs/{id}/result.
    Máy đồng bộ chỉ cần HTTPS tới app – không cần quyền vào database.
"""
import logging
import os
from datetime import datetime

from . import db, wms

log = logging.getLogger("dinh-vi-pa")

# "agent": app chỉ tạo yêu cầu, máy đồng bộ thực hiện. Trên Railway mặc định là agent.
MODE = os.environ.get("WMS_SYNC_MODE") or (
    "agent" if os.environ.get("RAILWAY_ENVIRONMENT_NAME") or os.environ.get("RAILWAY_ENVIRONMENT") else "direct"
)
STALE_MINUTES = 10       # yêu cầu treo quá lâu → coi như lỗi
AGENT_ONLINE_SECONDS = 90

# Cột trong file Excel WMS → cột trong bảng wms_bin_stocks
COLUMNS = [
    ("DC Site", "site"), ("SKU", "sku"), ("Tên sản phẩm", "product_name"), ("Loại sản phẩm", "product_type"),
    ("Mã PO", "po_code"), ("POID", "po_id"), ("Ngày nhận hàng", "received_date"),
    ("Mã VTLT", "vtlt_code"), ("Mã PTLT", "ptlt_code"), ("Loại LT", "lt_type"), ("Tính chất LT", "lt_status"),
    ("Loại hàng Pallet", "pallet_type"), ("Tồn Bin", "qty"), ("Tồn chờ Xuất", "qty_pending"),
    ("Base Units", "uom"), ("NSX", "mfg_date"), ("HSD", "exp_date"), ("ZoneCode", "zone_code"),
]
NUMERIC = {"qty", "qty_pending"}
OUT_COLS = ", ".join(col for _, col in COLUMNS)


def _cell(value, col: str):
    if value is None:
        return None
    if col in NUMERIC:
        if isinstance(value, (int, float)):
            return value
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            return None
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    text = str(value).strip()
    return text or None


def store(log_id: int, content: bytes, file_name: str) -> int:
    """Đọc file Excel WMS, thay toàn bộ wms_bin_stocks, đánh dấu log OK. Trả về số dòng.
    Lỗi được ghi vào log (status ERROR) rồi ném lại."""
    try:
        try:
            header, data = wms.read_xlsx(content)
        except Exception:
            raise wms.WmsError("File nhận từ WMS không đọc được (không phải Excel?)")
        idx = {h: i for i, h in enumerate(header)}
        missing = [h for h, _ in COLUMNS if h not in idx]
        if missing:
            raise wms.WmsError("File WMS thiếu cột: " + ", ".join(missing))
        rows = [[_cell(r[idx[h]] if idx[h] < len(r) else None, col) for h, col in COLUMNS] for r in data]
        with db.transaction() as conn:
            conn.execute("delete from wms_bin_stocks")
            with conn.cursor().copy(f"copy wms_bin_stocks ({OUT_COLS}) from stdin") as cp:
                for row in rows:
                    cp.write_row(row)
            conn.execute(
                "update wms_sync_log set finished_at = now(), status = 'OK', row_count = %s, file_name = %s, message = null "
                "where id = %s",
                (len(rows), file_name, log_id),
            )
        return len(rows)
    except Exception as exc:
        fail(log_id, exc)
        raise


def fail(log_id: int, exc) -> None:
    if isinstance(exc, str):
        msg = exc
    elif isinstance(exc, wms.WmsError):
        msg = str(exc)
    else:
        log.exception("Đồng bộ WMS lỗi")
        msg = f"Lỗi khi xử lý dữ liệu WMS ({type(exc).__name__})"
    db.execute(
        "update wms_sync_log set finished_at = now(), status = 'ERROR', message = %s where id = %s", (msg[:500], log_id)
    )


def run(log_id: int) -> int:
    """Chế độ direct: server tự gọi WMS rồi lưu."""
    try:
        content, file_name = wms.export_bin_stocks()
    except Exception as exc:
        fail(log_id, exc)
        raise
    return store(log_id, content, file_name)


# ---------------------------------------------------------------- phía server cho máy đồng bộ

def agent_token() -> str:
    """Token máy đồng bộ dùng để gọi app. Mặc định suy ra từ SECRET_KEY (không cần cấu hình thêm)."""
    import hashlib
    import hmac

    from . import config

    return os.environ.get("WMS_AGENT_TOKEN") or hmac.new(
        config.SECRET_KEY.encode(), b"wms-agent", hashlib.sha256
    ).hexdigest()


def heartbeat(host: str, auto_minutes: int, version: str) -> None:
    db.execute(
        """insert into wms_agent (host, last_seen, auto_minutes, version) values (%s, now(), %s, %s)
           on conflict (host) do update set last_seen = now(), auto_minutes = excluded.auto_minutes,
                                            version = excluded.version""",
        (host, auto_minutes, version),
    )


def claim(host: str, auto_minutes: int) -> dict | None:
    """Giao 1 việc cho máy đồng bộ: yêu cầu PENDING cũ nhất, hoặc lượt tự động nếu tới hạn."""
    job = db.fetch_one(
        """update wms_sync_log set status = 'RUNNING', started_at = now()
           where id = (select id from wms_sync_log where status = 'PENDING' order by id limit 1 for update skip locked)
           returning id, username"""
    )
    if job or auto_minutes <= 0:
        return job
    row = db.fetch_one(
        "select extract(epoch from now() - max(started_at))::int as age from wms_sync_log where status <> 'PENDING'"
    )
    if row["age"] is None or row["age"] >= auto_minutes * 60:
        return db.fetch_one(
            "insert into wms_sync_log (status, username) values ('RUNNING', %s) returning id, username",
            (f"auto:{host}",),
        )
    return None


def expire_stale() -> None:
    db.execute(
        "update wms_sync_log set finished_at = now(), status = 'ERROR', "
        "message = case when status = 'PENDING' then 'Máy đồng bộ không nhận yêu cầu (đang tắt?)' "
        "else 'Máy đồng bộ bị gián đoạn khi đang lấy dữ liệu' end "
        f"where status in ('PENDING', 'RUNNING') and started_at < now() - interval '{STALE_MINUTES} minutes'"
    )


def active_request() -> dict | None:
    return db.fetch_one(
        "select id, status, started_at, username from wms_sync_log "
        "where status in ('PENDING', 'RUNNING') order by id desc limit 1"
    )


def agent_info() -> dict | None:
    return db.fetch_one(
        "select host, last_seen, auto_minutes, extract(epoch from now() - last_seen)::int as age "
        "from wms_agent order by last_seen desc limit 1"
    )
