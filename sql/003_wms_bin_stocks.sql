-- =====================================================================
--  Migration 003: dữ liệu tồn kho theo Bin lấy từ WMS Supra
--  Mỗi lần đồng bộ thay toàn bộ bảng wms_bin_stocks bằng bản mới nhất.
-- =====================================================================

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

alter table wms_bin_stocks enable row level security;
alter table wms_sync_log   enable row level security;
