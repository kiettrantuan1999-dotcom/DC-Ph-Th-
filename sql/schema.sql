-- =====================================================================
--  App Định vị PA – DC Phú Thọ
--  Chạy 1 lần trong Supabase → SQL Editor → New query → Run
--  (Chạy lại nhiều lần cũng không sao – mọi lệnh đều "if not exists")
-- =====================================================================

create extension if not exists pg_trgm;   -- tìm kiếm nhanh theo 1 phần mã

-- Tài khoản đăng nhập PDA
create table if not exists app_users (
  id            bigint generated always as identity primary key,
  username      text        not null,
  password_hash text        not null,          -- bcrypt, tạo bằng manage_users.py
  full_name     text        not null,
  role          text        not null default 'nhanvien'
                check (role in ('admin', 'chuyenvien', 'nhanvien')),
  is_active     boolean     not null default true,
  created_at    timestamptz not null default now()
);
create unique index if not exists app_users_username_key on app_users (lower(username));

-- Log thao tác: mỗi lần định vị / chuyển = 1 dòng (không sửa/xóa)
create table if not exists pallet_scans (
  id             bigint generated always as identity primary key,
  scanned_at     timestamptz not null default now(),
  action         text        not null default 'NHAP',   -- NHAP = định vị nhập, CHUYEN = chuyển vị trí
  pa_code        text        not null,         -- mã PA (pallet)
  location_code  text        not null,         -- mã vị trí lưu trữ
  staff_name     text        not null,         -- nhân viên thực hiện scan
  user_id        bigint      references app_users (id),
  username       text        not null,         -- tài khoản đăng nhập trên PDA
  prev_location  text                          -- vị trí cũ (với thao tác CHUYEN)
);
create index if not exists pallet_scans_time_idx      on pallet_scans (scanned_at desc);
create index if not exists pallet_scans_pa_idx        on pallet_scans (pa_code, scanned_at desc);
create index if not exists pallet_scans_user_time_idx on pallet_scans (user_id, scanned_at desc);
create index if not exists pallet_scans_pa_trgm       on pallet_scans using gin (pa_code gin_trgm_ops);
create index if not exists pallet_scans_loc_trgm      on pallet_scans using gin (location_code gin_trgm_ops);
create index if not exists pallet_scans_staff_trgm    on pallet_scans using gin (staff_name gin_trgm_ops);

-- Vị trí HIỆN TẠI của từng PA. Khóa chính pa_code ⇒ 1 PA chỉ có đúng 1 vị trí,
-- 1 vị trí chứa được nhiều PA.
create table if not exists pallet_locations (
  pa_code       text primary key,
  location_code text        not null,
  updated_at    timestamptz not null default now(),
  staff_name    text        not null,
  username      text        not null
);
create index if not exists pallet_locations_loc_idx on pallet_locations (location_code);

-- Chặn truy cập qua REST API công khai của Supabase (anon key).
-- App kết nối thẳng Postgres bằng user "postgres" nên không bị ảnh hưởng.
alter table app_users    enable row level security;
alter table pallet_scans enable row level security;
alter table pallet_locations enable row level security;
