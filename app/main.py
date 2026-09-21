"""API + giao diện web cho app định vị pallet nhập trên PDA.

Luật nghiệp vụ:
  - 1 PA chỉ ở đúng 1 vị trí (bảng pallet_locations, khóa chính pa_code).
  - 1 vị trí chứa được nhiều PA.
  - ĐỊNH VỊ chỉ dành cho PA chưa có vị trí; đổi vị trí phải dùng CHUYỂN VT.
"""
import re
from contextlib import asynccontextmanager
from datetime import datetime, time as dtime
from pathlib import Path

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, db, security

STATIC_DIR = Path(__file__).parent / "static"

# Quyền theo loại tài khoản
ROLES = {
    "admin": {"label": "Admin", "perms": {"scan", "move", "log", "users"}},
    "chuyenvien": {"label": "Chuyên viên", "perms": {"scan", "move", "log"}},
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

@app.get("/api/logs")
def list_logs(
    q: str = Query("", max_length=100),
    scope: str = Query("today", pattern="^(today|all)$"),
    action: str = Query("", pattern="^(|NHAP|CHUYEN)$"),
    mine: bool = False,
    limit: int = Query(200, ge=1, le=500),
    user: dict = Depends(require("log")),
):
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
    where_sql = ("where " + " and ".join(where)) if where else ""

    rows = db.fetch_all(
        f"""select id, scanned_at, action, pa_code, location_code, staff_name, username, prev_location
            from pallet_scans {where_sql}
            order by scanned_at desc, id desc limit %s""",
        params + [limit],
    )
    total = db.fetch_one(f"select count(*) as n from pallet_scans {where_sql}", params)["n"]
    return {"rows": [scan_out(r) for r in rows], "total": total}


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
