-- 022_dispatch_hall_visibility_scope_length.sql
-- 放宽工单大厅可见范围枚举长度。
-- 020 初版使用 VARCHAR(24)，但组合范围 team_skill_or_recommended 长度为 25。

ALTER TABLE dispatch_hall_entries
    ALTER COLUMN visibility_scope TYPE VARCHAR(32)
    USING visibility_scope::VARCHAR(32);
