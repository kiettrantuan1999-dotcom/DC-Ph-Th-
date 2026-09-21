"""Cấu hình đọc từ biến môi trường (Railway Variables) hoặc file .env khi chạy local."""
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo


def _load_dotenv() -> None:
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "")
SESSION_HOURS = int(os.environ.get("SESSION_HOURS", "12"))
DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "5"))
TZ = ZoneInfo(os.environ.get("APP_TZ", "Asia/Ho_Chi_Minh"))

# Regex kiểm tra định dạng mã (để trống = không kiểm tra). VD: PA_PATTERN=PA\d{8}
PA_RE = re.compile(os.environ["PA_PATTERN"]) if os.environ.get("PA_PATTERN") else None
LOC_RE = re.compile(os.environ["LOC_PATTERN"]) if os.environ.get("LOC_PATTERN") else None


def validate() -> None:
    if not DATABASE_URL:
        raise RuntimeError("Thiếu biến môi trường DATABASE_URL (chuỗi kết nối Supabase)")
    if len(SECRET_KEY) < 32:
        raise RuntimeError("SECRET_KEY phải dài ít nhất 32 ký tự")
