-- =============================================================================
-- 迁移：创建多智能体控制台会话管理表
-- 执行方式：在 PostgreSQL 客户端/psql中粘贴并运行
-- 执行顺序：在现有 buildings / energy_data 表已建好之后执行
-- =============================================================================

-- 1. 创建会话元数据表
CREATE TABLE IF NOT EXISTS chat_sessions (
    id               TEXT        PRIMARY KEY,
    title            TEXT        NOT NULL DEFAULT '新对话',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    message_count    INTEGER     NOT NULL DEFAULT 0,
    last_message     TEXT,
    building_id      TEXT,
    is_archived      BOOLEAN     NOT NULL DEFAULT FALSE,
    messages_json    TEXT,       -- LangChain messages_to_dict() 序列化的 JSON 字符串
    extra_state_json TEXT        -- 其余 AgentState 字段的 JSON 序列化
);

-- 2. 索引：按更新时间倒序列举活跃会话（前端侧边栏列表常用查询）
CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated_at
    ON chat_sessions (updated_at DESC)
    WHERE is_archived = FALSE;

-- 3. 索引：归档查询
CREATE INDEX IF NOT EXISTS idx_chat_sessions_archived
    ON chat_sessions (is_archived, updated_at DESC);

-- 4. 自动更新 updated_at 触发器（可选，若应用层已维护则跳过）
CREATE OR REPLACE FUNCTION update_chat_sessions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_chat_sessions_updated_at ON chat_sessions;
CREATE TRIGGER trg_chat_sessions_updated_at
    BEFORE UPDATE ON chat_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_chat_sessions_updated_at();

-- 5. 授权（将 your_app_user 替换为实际 PostgreSQL 应用账号角色名）
-- 执行前先确认账号名：SELECT current_user;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON chat_sessions TO your_app_user;

-- 6. 验证
SELECT 'chat_sessions 表创建成功' AS status,
       COUNT(*) AS row_count
FROM chat_sessions;


