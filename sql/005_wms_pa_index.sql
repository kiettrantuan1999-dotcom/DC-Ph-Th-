-- =====================================================================
--  Migration 005: tra nhanh trạng thái WMS theo mã PA (cột STATUS WMS trong LOG)
--  Mã PA nằm ở Mã PTLT (PA đã cất lên vị trí) hoặc Mã VTLT (PA đang chờ lưu trữ).
-- =====================================================================
create index if not exists wms_bin_stocks_pa_idx on wms_bin_stocks ((coalesce(ptlt_code, vtlt_code)));
