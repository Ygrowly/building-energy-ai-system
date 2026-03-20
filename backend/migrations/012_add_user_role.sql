-- =============================================================================
-- Migration 012: users 表新增 role 字段
-- role 取值：resident（住户）/ ops（运维人员）/ manager（运维经理）/ admin（系统管理员）
-- 默认值为 resident，兼容已有用户数据。
-- =============================================================================
ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'resident';

COMMENT ON COLUMN users.role IS '用户角色: resident / ops / manager / admin';
