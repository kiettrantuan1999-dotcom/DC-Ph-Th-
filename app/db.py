"""Kết nối Postgres (Supabase) qua connection pool."""
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config

_pool: ConnectionPool | None = None


def open_pool() -> None:
    global _pool
    _pool = ConnectionPool(
        config.DATABASE_URL,
        min_size=1,
        max_size=config.DB_POOL_MAX,
        # prepare_threshold=None: tương thích Supabase pooler (không hỗ trợ prepared statement)
        kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
        check=ConnectionPool.check_connection,
        timeout=10,
        open=True,
    )


def close_pool() -> None:
    if _pool is not None:
        _pool.close()


@contextmanager
def transaction():
    """Mở 1 transaction: thoát bình thường → commit, có exception → rollback."""
    with _pool.connection() as conn:
        with conn.transaction():
            yield conn


def fetch_one(sql: str, params=()) -> dict | None:
    with _pool.connection() as conn:
        return conn.execute(sql, params).fetchone()


def fetch_all(sql: str, params=()) -> list[dict]:
    with _pool.connection() as conn:
        return conn.execute(sql, params).fetchall()
