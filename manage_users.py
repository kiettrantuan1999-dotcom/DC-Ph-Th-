"""Quản lý tài khoản đăng nhập PDA (chạy trên máy tính, dùng DATABASE_URL trong .env).
Admin cũng có thể tạo / sửa tài khoản ngay trong app (tab USER).

  python manage_users.py list
  python manage_users.py add <username> "<Họ tên>" [--role admin|chuyenvien|nhanvien] [--password <mk>]
  python manage_users.py role <username> admin|chuyenvien|nhanvien
  python manage_users.py passwd <username> [--password <mk>]
  python manage_users.py disable <username>
  python manage_users.py enable <username>
  python manage_users.py import users.csv      # cột: username,full_name,password[,role]
"""
import argparse
import csv
import getpass
import sys

import psycopg
from psycopg.rows import dict_row

from app import config
from app.security import hash_password

ROLES = ("admin", "chuyenvien", "nhanvien")


def ask_password(given: str | None) -> str:
    if given:
        pw = given
    else:
        pw = getpass.getpass("Mật khẩu: ")
        if pw != getpass.getpass("Nhập lại: "):
            sys.exit("Mật khẩu nhập lại không khớp")
    if len(pw) < 4:
        sys.exit("Mật khẩu tối thiểu 4 ký tự")
    if len(pw.encode("utf-8")) > 72:
        sys.exit("Mật khẩu tối đa 72 ký tự")
    return pw


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Quản lý user app Định vị PA")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    a = sub.add_parser("add"); a.add_argument("username"); a.add_argument("full_name"); a.add_argument("--password")
    a.add_argument("--role", choices=ROLES, default="nhanvien")
    r = sub.add_parser("role"); r.add_argument("username"); r.add_argument("role", choices=ROLES)
    pw = sub.add_parser("passwd"); pw.add_argument("username"); pw.add_argument("--password")
    sub.add_parser("disable").add_argument("username")
    sub.add_parser("enable").add_argument("username")
    sub.add_parser("import").add_argument("csv_file")
    args = p.parse_args()

    if not config.DATABASE_URL:
        sys.exit("Thiếu DATABASE_URL trong file .env")

    with psycopg.connect(config.DATABASE_URL, autocommit=True, prepare_threshold=None, row_factory=dict_row) as conn:
        if args.cmd == "list":
            rows = conn.execute("select username, full_name, role, is_active from app_users order by username").fetchall()
            for r in rows:
                status = "" if r["is_active"] else "  [KHÓA]"
                print(f"{r['username']:<20} {r['role']:<11} {r['full_name']}{status}")
            print(f"-- {len(rows)} tài khoản")

        elif args.cmd == "add":
            username = args.username.strip()
            try:
                conn.execute(
                    "insert into app_users (username, password_hash, full_name, role) values (%s, %s, %s, %s)",
                    (username, hash_password(ask_password(args.password)), args.full_name.strip(), args.role),
                )
            except psycopg.errors.UniqueViolation:
                sys.exit(f"Username '{username}' đã tồn tại")
            print(f"Đã tạo tài khoản {username}")

        elif args.cmd == "passwd":
            cur = conn.execute(
                "update app_users set password_hash = %s where lower(username) = lower(%s)",
                (hash_password(ask_password(args.password)), args.username),
            )
            print("Đã đổi mật khẩu" if cur.rowcount else f"Không tìm thấy '{args.username}'")

        elif args.cmd == "role":
            cur = conn.execute(
                "update app_users set role = %s where lower(username) = lower(%s)", (args.role, args.username)
            )
            print(f"Đã đổi loại tài khoản thành {args.role}" if cur.rowcount else f"Không tìm thấy '{args.username}'")

        elif args.cmd in ("disable", "enable"):
            cur = conn.execute(
                "update app_users set is_active = %s where lower(username) = lower(%s)",
                (args.cmd == "enable", args.username),
            )
            label = "Đã mở khóa" if args.cmd == "enable" else "Đã khóa"
            print(label if cur.rowcount else f"Không tìm thấy '{args.username}'")

        elif args.cmd == "import":
            created = skipped = 0
            with open(args.csv_file, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    username, name, pw_, role = (
                        (r.get(k) or "").strip() for k in ("username", "full_name", "password", "role")
                    )
                    role = role.lower() or "nhanvien"
                    if not username or not name or len(pw_) < 4 or role not in ROLES:
                        print(f"Bỏ qua dòng thiếu dữ liệu: {r}")
                        skipped += 1
                        continue
                    cur = conn.execute(
                        """insert into app_users (username, password_hash, full_name, role) values (%s, %s, %s, %s)
                           on conflict (lower(username)) do nothing""",
                        (username, hash_password(pw_), name, role),
                    )
                    if cur.rowcount:
                        created += 1
                    else:
                        print(f"Đã tồn tại, bỏ qua: {username}")
                        skipped += 1
            print(f"Tạo mới {created}, bỏ qua {skipped}")


if __name__ == "__main__":
    main()
