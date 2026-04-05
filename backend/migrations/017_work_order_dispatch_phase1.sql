-- 017: 派单体系第一阶段改造
-- 目标：
--   1. 工单支持 pending_dispatch 待派工状态
--   2. 补齐派工/接单/到场/开始处理时间字段

ALTER TABLE work_orders
    ADD COLUMN IF NOT EXISTS assigned_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS arrived_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMP WITH TIME ZONE;

-- 将历史 auto_approved 工单迁移为 pending_dispatch，避免继续被误认为“已派工”
UPDATE work_orders
SET status = 'pending_dispatch'
WHERE status = 'auto_approved';

-- 若历史数据已存在 assigned_to 但没有 assigned_at，则回填一个近似派工时间
UPDATE work_orders
SET assigned_at = COALESCE(ai_reviewed_at, updated_at, created_at)
WHERE assigned_to IS NOT NULL
  AND assigned_at IS NULL;
