-- =====================================================================
--  Migration 004: máy đồng bộ WMS (chạy trên máy tính ở Việt Nam)
--  WMS chặn server nước ngoài (Railway) → app chỉ tạo yêu cầu PENDING trong
--  wms_sync_log, máy đồng bộ (wms_agent.py) nhận yêu cầu, gọi WMS và ghi dữ liệu.
-- =====================================================================

-- Nhịp tim của máy đồng bộ (1 dòng / máy)
create table if not exists wms_agent (
  host         text primary key,
  last_seen    timestamptz not null default now(),
  auto_minutes integer,
  version      text
);
alter table wms_agent enable row level security;

create index if not exists wms_sync_log_status_idx on wms_sync_log (status, id);
