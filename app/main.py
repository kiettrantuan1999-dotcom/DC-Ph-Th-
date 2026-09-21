"""API + giao diện web cho app định vị pallet nhập trên PDA.

Luật nghiệp vụ:
  - 1 PA chỉ ở đúng 1 vị trí (bảng pallet_locations, khóa chính pa_code).
  - 1 vị trí chứa được nhiều PA.
  - ĐỊNH VỊ chỉ dành cho PA chưa có vị trí; đổi vị trí phải dùng CHUYỂN VT.
"""
import csv
import io
import logging
import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime, time as dtime
from pathlib import Path

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, db, security, wms

STATIC_DIR = Path(__file__).parent / "static"
log = logging.getLogger("dinh-vi-pa")

# Quyền theo loại tài khoản
ROLES = {
    "admin": {"label": "Admin", "perms": {"scan", "move", "log", "wms", "users"}},
    "chuyenvien": {"label": "Chuyên viên", "perms": {"scan", "move", "log", "wms"}},
    "nhanvien": {"label": "Nhân viên", "perms": {"scan", "move"}},
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.validate()
    db.open_pool()
    try:
        yield
    finally:
        db.close_pool()


app = FastAPI(title="Định vị PA", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.exception_handler(psycopg.OperationalError)
async def db_unavailable(_request: Request, _exc: Exception):
    return JSONResponse({"detail": "Không kết nối được cơ sở dữ liệu – thử lại sau"}, status_code=503)


# ---------------------------------------------------------------- helpers

_JUNK = re.compile(r"[\x00-\x20\x7f]")  # khoảng trắng + ký tự điều khiển máy scan hay chèn


def norm_code(value: str) -> str:
    return _JUNK.sub("", value or "").upper()


def fmt_time(ts: datetime) -> str:
    return ts.astimezone(config.TZ).strftime("%d/%m/%Y %H:%M:%S")


def scan_out(row: dict) -> dict:
    return {
        "id": row["id"],
        "time": fmt_time(row["scanned_at"]),
        "action": row["action"],
        "pa": row["pa_code"],
        "loc": row["location_code"],
        "staff": row["staff_name"],
        "user": row["username"],
        "prev_loc": row["prev_location"] or "",
    }


def perms_of(u: dict) -> set[str]:
    return ROLES.get(u["role"], ROLES["nhanvien"])["perms"]


def public_user(u: dict) -> dict:
    return {
        "id": u["id"],
        "username": u["username"],
        "full_name": u["full_name"],
        "role": u["role"],
        "role_label": ROLES.get(u["role"], ROLES["nhanvien"])["label"],
        "perms": sorted(perms_of(u)),
    }


USER_COLS = "id, username, full_name, role, password_hash, is_active"


def current_user(authorization: str | None = Header(default=None)) -> dict:
    expired = HTTPException(401, "Phiên đăng nhập đã hết hạn")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise expired
    data = security.read_token(authorization[7:].strip())
    if not data:
        raise expired
    user = db.fetch_one(f"select {USER_COLS} from app_users where id = %s", (data.get("uid"),))
    if not user or not user["is_active"] or not security.token_matches(data, user):
        raise expired
    return user


def require(perm: str):
    def dep(user: dict = Depends(current_user)) -> dict:
        if perm not in perms_of(user):
            raise HTTPException(403, "Tài khoản của bạn không có quyền dùng chức năng này")
        return user
    return dep


# ---------------------------------------------------------------- pages

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/healthz", include_in_schema=False)
def healthz():
    db.fetch_one("select 1 as ok")
    return {"ok": True}


# ---------------------------------------------------------------- auth

class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)


@app.post("/api/login")
def login(body: LoginIn):
    username = body.username.strip()
    if not username or not body.password:
        raise HTTPException(400, "Nhập đủ tài khoản và mật khẩu")
    key = username.lower()
    security.check_throttle(key)
    user = db.fetch_one(f"select {USER_COLS} from app_users where lower(username) = lower(%s)", (username,))
    if not user or not security.verify_password(body.password, user["password_hash"]):
        security.record_failure(key)
        raise HTTPException(400, "Sai tài khoản hoặc mật khẩu")
    if not user["is_active"]:
        raise HTTPException(403, "Tài khoản đã bị khóa")
    security.clear_failures(key)
    return {"token": security.make_token(user), "user": public_user(user)}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return public_user(user)


# ---------------------------------------------------------------- định vị & chuyển vị trí

class ScanIn(BaseModel):
    pa: str = Field(max_length=128)
    loc: str = Field(max_length=128)
    staff: str = Field(max_length=100)


def clean_scan(body: ScanIn) -> tuple[str, str, str]:
    pa, loc = norm_code(body.pa), norm_code(body.loc)
    staff = " ".join(body.staff.split())
    if not staff:
        raise HTTPException(400, "Chưa có tên nhân viên scan")
    if not pa:
        raise HTTPException(400, "Chưa scan mã PA")
    if not loc:
        raise HTTPException(400, "Chưa scan mã vị trí")
    if pa == loc:
        raise HTTPException(400, "Mã PA và mã vị trí giống nhau – kiểm tra lại")
    if config.PA_RE and not config.PA_RE.fullmatch(pa):
        raise HTTPException(400, f"Mã PA không đúng định dạng: {pa}")
    if config.LOC_RE and not config.LOC_RE.fullmatch(loc):
        raise HTTPException(400, f"Mã vị trí không đúng định dạng: {loc}")
    return pa, loc, staff


INSERT_LOG = """
insert into pallet_scans (action, pa_code, location_code, staff_name, user_id, username, prev_location)
values (%s, %s, %s, %s, %s, %s, %s)
returning id, scanned_at, action, pa_code, location_code, staff_name, username, prev_location
"""


def loc_count(conn, loc: str) -> int:
    return conn.execute("select count(*) as n from pallet_locations where location_code = %s", (loc,)).fetchone()["n"]


@app.post("/api/scans")
def create_scan(body: ScanIn, user: dict = Depends(require("scan"))):
    """ĐỊNH VỊ: gán vị trí cho PA chưa có vị trí."""
    pa, loc, staff = clean_scan(body)
    with db.transaction() as conn:
        created = conn.execute(
            """insert into pallet_locations (pa_code, location_code, staff_name, username)
               values (%s, %s, %s, %s) on conflict (pa_code) do nothing returning pa_code""",
            (pa, loc, staff, user["username"]),
        ).fetchone()
        if not created:
            cur = conn.execute("select location_code from pallet_locations where pa_code = %s", (pa,)).fetchone()
            if cur["location_code"] == loc:
                return {"status": "same", "pa": pa, "loc": loc, "loc_count": loc_count(conn, loc)}
            raise HTTPException(
                409, f"PA {pa} đã được định vị ở {cur['location_code']}. Muốn đổi vị trí → dùng tab CHUYỂN VT"
            )
        row = conn.execute(INSERT_LOG, ("NHAP", pa, loc, staff, user["id"], user["username"], None)).fetchone()
        return {**scan_out(row), "status": "new", "loc_count": loc_count(conn, loc)}


@app.get("/api/pallets/{pa}")
def get_pallet(pa: str, user: dict = Depends(require("scan"))):
    pa = norm_code(pa)
    row = db.fetch_one(
        "select pa_code, location_code, updated_at, staff_name from pallet_locations where pa_code = %s", (pa,)
    )
    if not row:
        raise HTTPException(404, f"PA {pa} chưa được định vị – dùng tab ĐỊNH VỊ trước")
    return {"pa": row["pa_code"], "loc": row["location_code"], "time": fmt_time(row["updated_at"]),
            "staff": row["staff_name"]}


@app.post("/api/moves")
def create_move(body: ScanIn, user: dict = Depends(require("move"))):
    """CHUYỂN VT: đổi vị trí của PA đã được định vị."""
    pa, loc, staff = clean_scan(body)
    with db.transaction() as conn:
        cur = conn.execute(
            "select location_code from pallet_locations where pa_code = %s for update", (pa,)
        ).fetchone()
        if not cur:
            raise HTTPException(404, f"PA {pa} chưa được định vị – dùng tab ĐỊNH VỊ trước")
        old = cur["location_code"]
        if old == loc:
            raise HTTPException(400, f"PA {pa} đang ở {loc} rồi – scan vị trí MỚI")
        conn.execute(
            """update pallet_locations set location_code = %s, updated_at = now(), staff_name = %s, username = %s
               where pa_code = %s""",
            (loc, staff, user["username"], pa),
        )
        row = conn.execute(INSERT_LOG, ("CHUYEN", pa, loc, staff, user["id"], user["username"], old)).fetchone()
        return {**scan_out(row), "status": "moved", "loc_count": loc_count(conn, loc)}


# ---------------------------------------------------------------- log

LOG_COLS = "id, scanned_at, action, pa_code, location_code, staff_name, username, prev_location"
EXPORT_MAX = 100_000


def log_filter(q: str, scope: str, action: str, mine: bool, user: dict) -> tuple[str, list]:
    where, params = [], []
    if scope == "today":
        start = datetime.combine(datetime.now(config.TZ).date(), dtime.min, tzinfo=config.TZ)
        where.append("scanned_at >= %s")
        params.append(start)
    if action:
        where.append("action = %s")
        params.append(action)
    if mine:
        where.append("user_id = %s")
        params.append(user["id"])
    q = q.strip()
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(pa_code ilike %s or location_code ilike %s or staff_name ilike %s)")
        params += [like, like, like]
    return ("where " + " and ".join(where)) if where else "", params


class LogQuery(BaseModel):
    q: str = Field("", max_length=100)
    scope: str = Field("today", pattern="^(today|all)$")
    action: str = Field("", pattern="^(|NHAP|CHUYEN)$")
    mine: bool = False


@app.get("/api/logs")
def list_logs(
    f: LogQuery = Depends(),
    limit: int = Query(200, ge=1, le=500),
    user: dict = Depends(require("log")),
):
    where_sql, params = log_filter(f.q, f.scope, f.action, f.mine, user)
    rows = db.fetch_all(
        f"select {LOG_COLS} from pallet_scans {where_sql} order by scanned_at desc, id desc limit %s",
        params + [limit],
    )
    total = db.fetch_one(f"select count(*) as n from pallet_scans {where_sql}", params)["n"]
    return {"rows": [scan_out(r) for r in rows], "total": total}


@app.get("/api/logs/export")
def export_logs(f: LogQuery = Depends(), user: dict = Depends(require("log"))):
    """Xuất CSV (UTF-8 có BOM để Excel đọc đúng tiếng Việt) theo bộ lọc đang chọn."""
    where_sql, params = log_filter(f.q, f.scope, f.action, f.mine, user)
    rows = db.fetch_all(
        f"select {LOG_COLS} from pallet_scans {where_sql} order by scanned_at desc, id desc limit %s",
        params + [EXPORT_MAX],
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Thời gian", "Thao tác", "Mã PA", "Vị trí cũ", "Vị trí", "Nhân viên scan", "Tài khoản"])
    for r in rows:
        w.writerow([
            fmt_time(r["scanned_at"]),
            "Chuyển vị trí" if r["action"] == "CHUYEN" else "Định vị",
            r["pa_code"], r["prev_location"] or "", r["location_code"], r["staff_name"], r["username"],
        ])
    name = f"log-dinh-vi-pa-{datetime.now(config.TZ):%Y%m%d-%H%M}.csv"
    return Response(
        "\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ---------------------------------------------------------------- WMS: tồn kho theo Bin

# Cột trong file Excel WMS → cột trong bảng wms_bin_stocks
WMS_COLUMNS = [
    ("DC Site", "site"), ("SKU", "sku"), ("Tên sản phẩm", "product_name"), ("Loại sản phẩm", "product_type"),
    ("Mã PO", "po_code"), ("POID", "po_id"), ("Ngày nhận hàng", "received_date"),
    ("Mã VTLT", "vtlt_code"), ("Mã PTLT", "ptlt_code"), ("Loại LT", "lt_type"), ("Tính chất LT", "lt_status"),
    ("Loại hàng Pallet", "pallet_type"), ("Tồn Bin", "qty"), ("Tồn chờ Xuất", "qty_pending"),
    ("Base Units", "uom"), ("NSX", "mfg_date"), ("HSD", "exp_date"), ("ZoneCode", "zone_code"),
]
WMS_NUMERIC = {"qty", "qty_pending"}
WMS_OUT_COLS = ", ".join(col for _, col in WMS_COLUMNS)
_wms_sync_lock = threading.Lock()


def _wms_cell(value, col: str):
    if value is None:
        return None
    if col in WMS_NUMERIC:
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


def wms_status_data() -> dict:
    last_ok = db.fetch_one(
        "select finished_at, row_count, file_name, username from wms_sync_log "
        "where status = 'OK' order by id desc limit 1"
    )
    last = db.fetch_one("select started_at, status, message, username from wms_sync_log order by id desc limit 1")
    statuses = db.fetch_all(
        "select coalesce(lt_status, '(trống)') as name, count(*) as n from wms_bin_stocks group by 1 order by 2 desc"
    )
    return {
        "synced_at": fmt_time(last_ok["finished_at"]) if last_ok else None,
        "row_count": last_ok["row_count"] if last_ok else 0,
        "file_name": last_ok["file_name"] if last_ok else None,
        "synced_by": last_ok["username"] if last_ok else None,
        "last_error": last["message"] if last and last["status"] == "ERROR" else None,
        "running": _wms_sync_lock.locked(),
        "statuses": statuses,
    }


@app.get("/api/wms/status")
def wms_status(_user: dict = Depends(require("wms"))):
    return wms_status_data()


@app.post("/api/wms/sync")
def wms_sync(user: dict = Depends(require("wms"))):
    """Gọi API WMS lấy báo cáo tồn kho theo Bin, thay toàn bộ dữ liệu trong wms_bin_stocks."""
    if not _wms_sync_lock.acquire(blocking=False):
        raise HTTPException(409, "Đang lấy dữ liệu WMS – đợi khoảng 20 giây rồi bấm Tải lại")
    try:
        log_id = db.fetch_one(
            "insert into wms_sync_log (status, username) values ('RUNNING', %s) returning id", (user["username"],)
        )["id"]
        try:
            content, file_name = wms.export_bin_stocks()
            header, data = wms.read_xlsx(content)
            idx = {h: i for i, h in enumerate(header)}
            missing = [h for h, _ in WMS_COLUMNS if h not in idx]
            if missing:
                raise wms.WmsError("File WMS thiếu cột: " + ", ".join(missing))
            rows = [[_wms_cell(r[idx[h]] if idx[h] < len(r) else None, col) for h, col in WMS_COLUMNS] for r in data]
            with db.transaction() as conn:
                conn.execute("delete from wms_bin_stocks")
                with conn.cursor().copy(f"copy wms_bin_stocks ({WMS_OUT_COLS}) from stdin") as cp:
                    for row in rows:
                        cp.write_row(row)
                conn.execute(
                    "update wms_sync_log set finished_at = now(), status = 'OK', row_count = %s, file_name = %s where id = %s",
                    (len(rows), file_name, log_id),
                )
        except Exception as exc:
            if isinstance(exc, wms.WmsError):
                msg = str(exc)
            else:
                log.exception("Đồng bộ WMS lỗi")
                msg = f"Lỗi khi xử lý dữ liệu WMS ({type(exc).__name__}) – xem Deploy Logs trên Railway"
            db.execute(
                "update wms_sync_log set finished_at = now(), status = 'ERROR', message = %s where id = %s", (msg, log_id)
            )
            if isinstance(exc, wms.WmsError):
                raise HTTPException(502, msg)
            raise
    finally:
        _wms_sync_lock.release()
    return wms_status_data()


def wms_filter(q: str, status: str) -> tuple[str, list]:
    where, params = [], []
    if status:
        if status == "(trống)":
            where.append("lt_status is null")
        else:
            where.append("lt_status = %s")
            params.append(status)
    q = q.strip()
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(vtlt_code ilike %s or ptlt_code ilike %s or sku ilike %s or product_name ilike %s or po_code ilike %s)")
        params += [like] * 5
    return ("where " + " and ".join(where)) if where else "", params


class WmsQuery(BaseModel):
    q: str = Field("", max_length=100)
    status: str = Field("", max_length=100)


@app.get("/api/wms/stocks")
def wms_stocks(
    f: WmsQuery = Depends(),
    limit: int = Query(300, ge=1, le=1000),
    _user: dict = Depends(require("wms")),
):
    where_sql, params = wms_filter(f.q, f.status)
    rows = db.fetch_all(
        f"select {WMS_OUT_COLS} from wms_bin_stocks {where_sql} order by vtlt_code, ptlt_code, sku limit %s",
        params + [limit],
    )
    agg = db.fetch_one(
        f"select count(*) as n, coalesce(sum(qty), 0) as qty, count(distinct coalesce(ptlt_code, vtlt_code)) as pallets "
        f"from wms_bin_stocks {where_sql}",
        params,
    )
    for r in rows:
        for k in WMS_NUMERIC:
            if r[k] is not None:
                r[k] = float(r[k])
    return {"rows": rows, "total": agg["n"], "qty": float(agg["qty"]), "pallets": agg["pallets"]}


@app.get("/api/wms/export")
def wms_export(f: WmsQuery = Depends(), _user: dict = Depends(require("wms"))):
    where_sql, params = wms_filter(f.q, f.status)
    rows = db.fetch_all(
        f"select {WMS_OUT_COLS} from wms_bin_stocks {where_sql} order by vtlt_code, ptlt_code, sku", params
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([h for h, _ in WMS_COLUMNS])
    for r in rows:
        w.writerow(["" if r[col] is None else r[col] for _, col in WMS_COLUMNS])
    name = f"ton-bin-wms-{datetime.now(config.TZ):%Y%m%d-%H%M}.csv"
    return Response(
        "\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ---------------------------------------------------------------- quản lý user (admin)

USERNAME_RE = re.compile(r"[A-Za-z0-9._-]{2,32}")


def check_password(pw: str) -> str:
    if len(pw) < 4:
        raise HTTPException(400, "Mật khẩu tối thiểu 4 ký tự")
    if len(pw.encode("utf-8")) > 72:
        raise HTTPException(400, "Mật khẩu quá dài")
    return pw


def check_role(role: str) -> str:
    if role not in ROLES:
        raise HTTPException(400, "Loại tài khoản không hợp lệ")
    return role


def user_row_out(u: dict) -> dict:
    return {**public_user(u), "is_active": u["is_active"], "created_at": fmt_time(u["created_at"])}


@app.get("/api/users")
def list_users(_admin: dict = Depends(require("users"))):
    rows = db.fetch_all(f"select {USER_COLS}, created_at from app_users order by is_active desc, lower(username)")
    return {"rows": [user_row_out(r) for r in rows], "roles": {k: v["label"] for k, v in ROLES.items()}}


class UserCreate(BaseModel):
    username: str = Field(max_length=32)
    full_name: str = Field(max_length=100)
    role: str
    password: str = Field(max_length=128)


@app.post("/api/users")
def create_user(body: UserCreate, _admin: dict = Depends(require("users"))):
    username = body.username.strip()
    full_name = " ".join(body.full_name.split())
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(400, "Username 2–32 ký tự, chỉ gồm chữ không dấu, số và . _ -")
    if not full_name:
        raise HTTPException(400, "Chưa nhập họ tên")
    try:
        row = db.fetch_one(
            f"""insert into app_users (username, password_hash, full_name, role) values (%s, %s, %s, %s)
                returning {USER_COLS}, created_at""",
            (username, security.hash_password(check_password(body.password)), full_name, check_role(body.role)),
        )
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, f"Username '{username}' đã tồn tại")
    return user_row_out(row)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=100)
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, max_length=128)


@app.patch("/api/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, admin: dict = Depends(require("users"))):
    sets, params = [], []
    if body.full_name is not None:
        name = " ".join(body.full_name.split())
        if not name:
            raise HTTPException(400, "Chưa nhập họ tên")
        sets.append("full_name = %s"); params.append(name)
    if body.role is not None:
        if user_id == admin["id"] and body.role != "admin":
            raise HTTPException(400, "Không thể tự hạ quyền admin của chính mình")
        sets.append("role = %s"); params.append(check_role(body.role))
    if body.is_active is not None:
        if user_id == admin["id"] and not body.is_active:
            raise HTTPException(400, "Không thể tự khóa tài khoản của chính mình")
        sets.append("is_active = %s"); params.append(body.is_active)
    if body.password:
        sets.append("password_hash = %s"); params.append(security.hash_password(check_password(body.password)))
    if not sets:
        raise HTTPException(400, "Không có gì thay đổi")
    row = db.fetch_one(
        f"update app_users set {', '.join(sets)} where id = %s returning {USER_COLS}, created_at",
        params + [user_id],
    )
    if not row:
        raise HTTPException(404, "Không tìm thấy tài khoản")
    return user_row_out(row)
