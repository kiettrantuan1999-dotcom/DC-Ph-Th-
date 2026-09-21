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

-- Tồn kho theo Bin lấy từ WMS Supra (bản mới nhất, thay toàn bộ mỗi lần đồng bộ)
create table if not exists wms_bin_stocks (
  id            bigint generated always as identity primary key,
  site          text,          -- DC Site
  sku           text,
  product_name  text,          -- Tên sản phẩm
  product_type  text,          -- Loại sản phẩm
  po_code       text,          -- Mã PO
  po_id         text,          -- POID
  received_date text,          -- Ngày nhận hàng
  vtlt_code     text,          -- Mã VTLT (vị trí lưu trữ)
  ptlt_code     text,          -- Mã PTLT (phương tiện lưu trữ = mã PA)
  lt_type       text,          -- Loại LT
  lt_status     text,          -- Tính chất LT
  pallet_type   text,          -- Loại hàng Pallet
  qty           numeric,       -- Tồn Bin
  qty_pending   numeric,       -- Tồn chờ Xuất
  uom           text,          -- Base Units
  mfg_date      text,          -- NSX
  exp_date      text,          -- HSD
  zone_code     text
);
create index if not exists wms_bin_stocks_vtlt_idx on wms_bin_stocks (vtlt_code);
create index if not exists wms_bin_stocks_ptlt_idx on wms_bin_stocks (ptlt_code);
create index if not exists wms_bin_stocks_sku_idx  on wms_bin_stocks (sku);

-- Lịch sử các lần đồng bộ
create table if not exists wms_sync_log (
  id          bigint generated always as identity primary key,
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  status      text not null,   -- OK / ERROR
  row_count   integer,
  file_name   text,
  message     text,
  username    text
);

-- Chặn truy cập qua REST API công khai của Supabase (anon key).
-- App kết nối thẳng Postgres bằng user "postgres" nên không bị ảnh hưởng.
alter table app_users    enable row level security;
alter table pallet_scans enable row level security;
alter table pallet_locations enable row level security;
alter table wms_bin_stocks enable row level security;
alter table wms_sync_log   enable row level security;

-- Máy đồng bộ WMS (WMS chặn server nước ngoài → đồng bộ qua máy ở Việt Nam)
-- Nhịp tim của máy đồng bộ (1 dòng / máy)
create table if not exists wms_agent (
  host         text primary key,
  last_seen    timestamptz not null default now(),
  auto_minutes integer,
  version      text
);
alter table wms_agent enable row level security;

create index if not exists wms_sync_log_status_idx on wms_sync_log (status, id);
