-- =====================================================================
--  Migration 002: 1 PA = 1 vị trí + chuyển vị trí + phân quyền user
--  Chạy trên database đã tạo bằng schema.sql bản đầu (chạy lại nhiều lần không sao)
-- =====================================================================

-- Phân quyền: admin (toàn quyền) · chuyenvien (scan + log) · nhanvien (chỉ scan)
alter table app_users add column if not exists role text not null default 'nhanvien';
alter table app_users drop constraint if exists app_users_role_check;
alter table app_users add constraint app_users_role_check check (role in ('admin', 'chuyenvien', 'nhanvien'));
update app_users set role = 'admin' where lower(username) = 'admin' and role = 'nhanvien';

-- Loại thao tác trong log: NHAP = định vị nhập, CHUYEN = chuyển vị trí
alter table pallet_scans add column if not exists action text not null default 'NHAP';

-- Vị trí HIỆN TẠI của từng PA. Khóa chính pa_code ⇒ 1 PA chỉ có đúng 1 vị trí.
create table if not exists pallet_locations (
  pa_code       text primary key,
  location_code text        not null,
  updated_at    timestamptz not null default now(),
  staff_name    text        not null,
  username      text        not null
);
create index if not exists pallet_locations_loc_idx on pallet_locations (location_code);
alter table pallet_locations enable row level security;

-- Lấy dữ liệu đã scan trước đây (lần scan gần nhất của mỗi PA)
insert into pallet_locations (pa_code, location_code, updated_at, staff_name, username)
select distinct on (pa_code) pa_code, location_code, scanned_at, staff_name, username
from pallet_scans
order by pa_code, scanned_at desc, id desc
on conflict (pa_code) do nothing;

-- View cũ thay bằng bảng pallet_locations
drop view if exists pallet_current_location;
