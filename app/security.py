"""Mã hóa mật khẩu, token đăng nhập và chống dò mật khẩu."""
import hashlib
import threading
import time

import bcrypt
from fastapi import HTTPException
from itsdangerous import BadSignature, URLSafeTimedSerializer

from . import config

MAX_FAILS = 5
LOCK_SECONDS = 300


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode())
    except ValueError:
        return False


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.SECRET_KEY, salt="pa-session")


def _password_version(password_hash: str) -> str:
    # Đổi mật khẩu → token cũ tự hết hiệu lực
    return hashlib.sha256(password_hash.encode()).hexdigest()[:12]


def make_token(user: dict) -> str:
    return _serializer().dumps({"uid": user["id"], "pv": _password_version(user["password_hash"])})


def read_token(token: str) -> dict | None:
    try:
        return _serializer().loads(token, max_age=config.SESSION_HOURS * 3600)
    except BadSignature:  # gồm cả SignatureExpired
        return None


def token_matches(data: dict, user: dict) -> bool:
    return data.get("pv") == _password_version(user["password_hash"])


# --- Khóa tạm tài khoản sau nhiều lần nhập sai (lưu trong RAM) ---
_fails: dict[str, list[float]] = {}
_lock = threading.Lock()


def check_throttle(key: str) -> None:
    now = time.time()
    with _lock:
        recent = [t for t in _fails.get(key, []) if now - t < LOCK_SECONDS]
        _fails[key] = recent
    if len(recent) >= MAX_FAILS:
        wait = int(LOCK_SECONDS - (now - recent[0])) // 60 + 1
        raise HTTPException(429, f"Nhập sai quá {MAX_FAILS} lần. Thử lại sau {wait} phút")


def record_failure(key: str) -> None:
    with _lock:
        _fails.setdefault(key, []).append(time.time())


def clear_failures(key: str) -> None:
    with _lock:
        _fails.pop(key, None)
