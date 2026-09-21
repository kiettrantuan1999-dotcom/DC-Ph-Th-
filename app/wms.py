"""Lấy dữ liệu từ WMS Supra (api-supra.winmart.vn).

Session WMS không lưu trong app: nó nằm trong file session bundle (xuất bằng extension
"Supra Session Capture") trên Google Drive. Link Drive của file đó được dán vào Google
Sheet "Central OPS" tab Config, ô B2 (ô B1 là của DC Nghệ An). Hết hạn session chỉ cần
xuất bundle mới và dán link mới vào ô đó – app tự đọc lại.

Service account (GOOGLE_SERVICE_ACCOUNT_JSON / GOOGLE_SERVICE_ACCOUNT_FILE) phải được
share quyền Viewer trên Google Sheet VÀ trên file session trong Drive.
"""
import base64
import io
import json
import os
import re
import threading
import time
from urllib.parse import quote

import google.auth.exceptions
import requests
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account

from . import config

SHEET_ID = os.environ.get("WMS_SESSION_SHEET_ID", "1h6veWy2fTGeKnUJIWp_WZzAqDE-RKer4nwk1hB58Sr4")
SHEET_RANGE = os.environ.get("WMS_SESSION_RANGE", "Config!B2")
WH_CODE = os.environ.get("WMS_WH_CODE", "PTD")
API_BASE = os.environ.get("WMS_API_BASE", f"https://api-supra.winmart.vn/sft3-{WH_CODE.lower()}")
SESSION_TTL = 600  # giây – đọc lại session từ Sheet tối đa 10 phút/lần

HEADER_KEYS = ["apisid", "authorization", "scid", "sid", "token", "usid", "x-signature", "x-signature-nonce"]
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
DRIVE_ID_PATTERNS = [re.compile(r"/file/d/([a-zA-Z0-9_-]+)"), re.compile(r"[?&]id=([a-zA-Z0-9_-]+)")]


class WmsError(Exception):
    """Lỗi hiển thị được cho người dùng (tiếng Việt, không chứa token)."""


# ---------------------------------------------------------------- Google (Sheet + Drive)

def _service_account_info(raw: str) -> dict:
    """Đọc JSON service account từ biến môi trường, chịu được các kiểu dán hay gặp:
    bọc trong nháy, bị mã hóa base64, hoặc private_key có '\\n' dạng chữ."""
    raw = raw.strip()
    if len(raw) > 1 and raw[0] == raw[-1] and raw[0] in "'\"":
        raw = raw[1:-1]
    try:
        info = json.loads(raw)
    except ValueError:
        try:
            info = json.loads(base64.b64decode(raw).decode("utf-8"))
        except Exception:
            raise WmsError(
                "Biến GOOGLE_SERVICE_ACCOUNT_JSON không phải JSON hợp lệ – mở file JSON của service account, "
                "copy TOÀN BỘ nội dung (từ { đến }) và dán lại vào biến trên Railway"
            )
    if not isinstance(info, dict) or not info.get("private_key") or not info.get("client_email"):
        raise WmsError("GOOGLE_SERVICE_ACCOUNT_JSON thiếu private_key / client_email – dán lại đủ nội dung file JSON")
    if "\\n" in info["private_key"]:
        info["private_key"] = info["private_key"].replace("\\n", "\n")
    return info


def _google_token() -> str:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    try:
        if raw:
            creds = service_account.Credentials.from_service_account_info(
                _service_account_info(raw), scopes=GOOGLE_SCOPES
            )
        elif path:
            creds = service_account.Credentials.from_service_account_file(path, scopes=GOOGLE_SCOPES)
        else:
            raise WmsError("Chưa cấu hình service account Google (GOOGLE_SERVICE_ACCOUNT_JSON)")
        creds.refresh(GoogleRequest())
    except WmsError:
        raise
    except google.auth.exceptions.GoogleAuthError as exc:
        raise WmsError(f"Service account không đăng nhập được Google: {exc}")
    except ValueError as exc:  # private_key sai định dạng
        raise WmsError(f"Service account không hợp lệ (private_key sai định dạng): {exc}")
    return creds.token


def _drive_file_id(value: str) -> str:
    for pattern in DRIVE_ID_PATTERNS:
        m = pattern.search(value)
        if m:
            return m.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{20,}", value):
        return value
    raise WmsError(f"Ô {SHEET_RANGE} không phải link Google Drive hợp lệ")


def _http_get(url: str, what: str, **kw) -> requests.Response:
    try:
        return requests.get(url, **kw)
    except requests.RequestException as exc:
        raise WmsError(f"Không kết nối được {what}: {type(exc).__name__}")


def _read_session_bundle() -> dict:
    token = _google_token()
    auth = {"Authorization": f"Bearer {token}"}
    r = _http_get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{quote(SHEET_RANGE)}",
        "Google Sheets", headers=auth, timeout=30,
    )
    if r.status_code != 200:
        raise WmsError(f"Không đọc được Google Sheet (HTTP {r.status_code}) – kiểm tra đã share Sheet cho service account")
    values = r.json().get("values") or [[""]]
    link = (values[0][0] if values and values[0] else "").strip()
    if not link:
        raise WmsError(f"Ô {SHEET_RANGE} đang trống – dán link Drive của file session vào đó")

    r = _http_get(
        f"https://www.googleapis.com/drive/v3/files/{_drive_file_id(link)}",
        "Google Drive", params={"alt": "media", "supportsAllDrives": "true"}, headers=auth, timeout=60,
    )
    if r.status_code != 200:
        raise WmsError(f"Không tải được file session trên Drive (HTTP {r.status_code}) – kiểm tra đã share file cho service account")
    try:
        return json.loads(r.content.decode("utf-8-sig"))
    except ValueError:
        raise WmsError("File session trên Drive không phải JSON hợp lệ")


def _pick_headers(bundle: dict) -> tuple[dict, str]:
    """Ưu tiên session đúng kho (sessions_by_warehouse.sft.PTD), sau đó tới sessions.sft."""
    candidates = [
        ((bundle.get("sessions_by_warehouse") or {}).get("sft") or {}).get(WH_CODE),
        (bundle.get("sessions") or {}).get("sft"),
        bundle if "headers" in bundle else None,
    ]
    for s in candidates:
        headers = (s or {}).get("headers") or {}
        if all(headers.get(k) for k in HEADER_KEYS):
            return {k: headers[k] for k in HEADER_KEYS}, (s or {}).get("captured_at", "")
    raise WmsError(
        "File session thiếu thông tin đăng nhập WMS (sft). Mở wms-supra.winmart.vn, "
        f"xuất lại session bằng extension Supra Session Capture rồi dán link mới vào {SHEET_RANGE}"
    )


_cache: dict = {"headers": None, "captured_at": "", "loaded": 0.0}
_lock = threading.Lock()


def _session(force: bool = False) -> dict:
    with _lock:
        if force or not _cache["headers"] or time.time() - _cache["loaded"] > SESSION_TTL:
            headers, captured_at = _pick_headers(_read_session_bundle())
            _cache.update(headers=headers, captured_at=captured_at, loaded=time.time())
        return _cache["headers"]


def session_info() -> dict:
    _session()
    return {"captured_at": _cache["captured_at"], "usid": _cache["headers"]["usid"], "source": SHEET_RANGE}


# ---------------------------------------------------------------- WMS API

def wms_get(path: str, params: dict) -> requests.Response:
    """GET tới WMS bằng session hiện tại. Session hết hạn → đọc lại Sheet 1 lần rồi thử lại."""
    for attempt in (0, 1):
        s = _session(force=attempt == 1)
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "origin": "https://wms-supra.winmart.vn",
            "referer": "https://wms-supra.winmart.vn/",
            "appid": "unknown",
            "warehouse": WH_CODE,
            **s,
        }
        r = _http_get(API_BASE + path, "WMS", params=params, headers=headers, timeout=120)
        if r.status_code in (401, 403) and attempt == 0:
            continue
        if r.status_code in (401, 403):
            raise WmsError(
                "Session WMS đã hết hạn. Mở wms-supra.winmart.vn, xuất lại session bằng extension "
                f"Supra Session Capture rồi dán link mới vào Google Sheet ô {SHEET_RANGE}"
            )
        if r.status_code != 200:
            raise WmsError(f"WMS trả lỗi HTTP {r.status_code}")
        return r
    raise AssertionError("unreachable")


def export_bin_stocks() -> tuple[bytes, str]:
    """Báo cáo tồn kho theo Bin của kho (file Excel gốc từ WMS)."""
    r = wms_get("/api/v1/report/stock/exportBinStocks", {
        "FromWH": "true", "Content": "", "ClientCode": "WIN", "WhCode": WH_CODE,
        "WarehouseSiteId": "", "PickupMethod": "", "IsConsign": "false",
    })
    if "spreadsheetml" not in r.headers.get("content-type", ""):
        raise WmsError("WMS không trả về file Excel – có thể session đã hết hạn")
    name = r.headers.get("X-Download-FileName") or ""
    if not name:
        m = re.search(r"filename=([^;]+)", r.headers.get("Content-Disposition", ""))
        name = m.group(1).strip('"') if m else f"REPORT_BIN_INVENTORY_{WH_CODE}.xlsx"
    return r.content, name


def read_xlsx(content: bytes) -> tuple[list[str], list[list]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows, [])]
    data = [list(r) for r in rows if any(v not in (None, "") for v in r)]
    wb.close()
    return header, data
