-- =============================================================================
-- Migration 006: users 表新增 email / phone 联系字段
-- =============================================================================
ALTER TABLE users ADD COLUMN IF NOT EXISTS email  VARCHAR(254);
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone  VARCHAR(20);

CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email ON users (email) WHERE email IS NOT NULL;

COMMENT ON COLUMN users.email IS '用户邮箱（可选，唯一）';
COMMENT ON COLUMN users.phone IS '用户手机号（可选）';
