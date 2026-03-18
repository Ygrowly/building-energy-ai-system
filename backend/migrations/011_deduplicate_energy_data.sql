-- =============================================================================
-- 迁移 011：去除 energy_data 重复行 + 补充唯一约束
-- =============================================================================
-- 背景：energy_data 表无主键约束，原始 CSV（fwwb01_realistic.csv）与异常注入
--       CSV（fwwb01_realistic_with_anomalies.csv）被先后各加载一次，导致同一
--       (building_id, timestamp) 存在两条记录。
--
-- 去重策略：对每个 (building_id, timestamp) 分组，保留
--           electricity_kwh + COALESCE(water_m3,0) + COALESCE(hac_energy,0)
--           之和最大的那条记录（即异常注入行，能耗值更高）。
--           对于非异常时刻，两行数值完全相同，任意保留一条即可。
--
-- 幂等性：脚本通过 ctid 定位物理行，可安全重复执行（已无重复行时不删除任何记录）。
-- =============================================================================

-- 1. 确认重复行数量（仅统计，不修改）
DO $$
DECLARE
    dup_count INTEGER;
BEGIN
    SELECT COUNT(*) - COUNT(DISTINCT (building_id, timestamp))
    INTO   dup_count
    FROM   energy_data;

    RAISE NOTICE '当前重复行数量（需删除的多余行数）：%', dup_count;
END
$$;

-- 2. 删除多余重复行，保留每组能耗之和最大的一行
--    若多行能耗之和相同，保留 ctid 最大的（最后写入的）
DELETE FROM energy_data
WHERE ctid NOT IN (
    SELECT DISTINCT ON (building_id, "timestamp")
           ctid
    FROM   energy_data
    ORDER BY
           building_id,
           "timestamp",
           -- 优先保留能耗和最大的行（注入异常行），相同时取最后写入的物理行
           (COALESCE(electricity_kwh, 0)
            + COALESCE(water_m3, 0)
            + COALESCE(hac_energy, 0)) DESC,
           ctid DESC
);

-- 3. 统计去重后的行数，验证结果
DO $$
DECLARE
    total   INTEGER;
    remain  INTEGER;
BEGIN
    SELECT COUNT(*) INTO total FROM energy_data;
    SELECT COUNT(DISTINCT (building_id, timestamp)) INTO remain FROM energy_data;
    RAISE NOTICE '去重完成。总行数：%，唯一 (building_id, timestamp) 组合数：%', total, remain;
    IF total <> remain THEN
        RAISE EXCEPTION '去重后仍存在重复行，请手动排查！';
    END IF;
END
$$;

-- 4. 补充唯一约束，防止今后重复写入
--    注意：energy_data 无主键，此约束以唯一索引形式添加
CREATE UNIQUE INDEX IF NOT EXISTS uq_energy_data_building_timestamp
    ON energy_data (building_id, "timestamp");

COMMENT ON INDEX uq_energy_data_building_timestamp IS
    '防止同一建筑在同一时刻重复写入能耗记录（迁移 011 补充）';
