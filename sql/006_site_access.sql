-- =====================================================================
--  Migration 006: phân quyền theo site (1 DC có nhiều site, VD BD: 1379 và 1312)
--  app_users.site_code: NULL = xem tất cả site (admin / chuyên viên quản lý nhiều site)
-- =====================================================================

alter table app_users        add column if not exists site_code text;
alter table pallet_scans     add column if not exists site_code text;
alter table pallet_locations add column if not exists site_code text;
alter table wms_bin_stocks   add column if not exists site_code text;

-- Mã site lấy từ cột "DC Site" của WMS: "1379 - WMP_AMBIENT_BD1_KM" → "1379"
update wms_bin_stocks set site_code = split_part(site, ' - ', 1) where site_code is null and site is not null;

create index if not exists pallet_scans_site_idx     on pallet_scans (site_code, scanned_at desc);
create index if not exists pallet_locations_site_idx on pallet_locations (site_code);
create index if not exists wms_bin_stocks_site_idx   on wms_bin_stocks (site_code);
