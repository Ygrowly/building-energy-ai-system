-- =============================================================================
-- 迁移：为 chat_sessions 增加 user_id，支持会话归属与生产环境鉴权
-- 执行顺序：在 003_create_users 之后
-- =============================================================================

-- 1. 增加 user_id 列（可空，兼容历史数据）
ALTER TABLE chat_sessions
    ADD COLUMN IF NOT EXISTS user_id TEXT REFERENCES users(id) ON DELETE SET NULL;

-- 2. 索引：按用户列举会话（列表接口过滤）
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id
    ON chat_sessions (user_id)
    WHERE user_id IS NOT NULL;

-- 3. 验证
SELECT 'chat_sessions.user_id 已添加' AS status;
