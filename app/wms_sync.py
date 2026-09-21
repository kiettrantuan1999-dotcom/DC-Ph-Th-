"""Đồng bộ báo cáo tồn kho theo Bin từ WMS vào bảng wms_bin_stocks.

Dùng chung cho:
  - app (chế độ "direct", khi server gọi được WMS – ví dụ chạy trên máy ở Việt Nam)
  - máy đồng bộ wms_agent.py (chế độ "agent", khi app chạy trên Railway bị WMS chặn)
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


def run(log_id: int) -> int:
    """Gọi WMS, thay toàn bộ wms_bin_stocks, cập nhật dòng log. Trả về số dòng.
    Lỗi được ghi vào log (status ERROR) rồi ném lại."""
    try:
        content, file_name = wms.export_bin_stocks()
        header, data = wms.read_xlsx(content)
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
        if isinstance(exc, wms.WmsError):
            msg = str(exc)
        else:
            log.exception("Đồng bộ WMS lỗi")
            msg = f"Lỗi khi xử lý dữ liệu WMS ({type(exc).__name__})"
        db.execute(
            "update wms_sync_log set finished_at = now(), status = 'ERROR', message = %s where id = %s", (msg, log_id)
        )
        raise


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
