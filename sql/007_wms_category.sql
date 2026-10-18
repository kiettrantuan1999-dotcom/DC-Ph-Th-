-- =====================================================================
--  Migration 007: cột Ngành hàng trong báo cáo tồn Bin (kho BDD có cột này)
-- =====================================================================
alter table wms_bin_stocks add column if not exists category text;
