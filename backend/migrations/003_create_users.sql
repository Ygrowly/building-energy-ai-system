-- =============================================================================
-- Migration 003: 用户认证表
-- 创建 users 表和 refresh_tokens 表，支持 JWT 登录注册与 token rotation。
-- =============================================================================

-- ---------------------------------------------------------------------------
-- users 表
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              VARCHAR         PRIMARY KEY,
    username        VARCHAR(50)     NOT NULL,
    hashed_password VARCHAR         NOT NULL,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_users_username UNIQUE (username)
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users (username);

COMMENT ON TABLE  users                   IS '系统用户表，密码以 bcrypt 哈希存储';
COMMENT ON COLUMN users.id                IS 'UUID 主键';
COMMENT ON COLUMN users.username          IS '登录用户名，3~50 字符，全小写，唯一';
COMMENT ON COLUMN users.hashed_password   IS 'passlib bcrypt 哈希值';
COMMENT ON COLUMN users.is_active         IS '账户是否启用，false 时拒绝登录';
COMMENT ON COLUMN users.created_at        IS '注册时间';

-- ---------------------------------------------------------------------------
-- refresh_tokens 表
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id          VARCHAR     PRIMARY KEY,
    jti         VARCHAR     NOT NULL,           -- JWT ID（唯一标识一个 refresh token）
    user_id     VARCHAR     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked     BOOLEAN     NOT NULL DEFAULT FALSE,

    CONSTRAINT uq_refresh_tokens_jti UNIQUE (jti)
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_jti     ON refresh_tokens (jti);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens (user_id);

COMMENT ON TABLE  refresh_tokens            IS 'Refresh Token 持久化，用于 token rotation 与主动吊销';
COMMENT ON COLUMN refresh_tokens.jti        IS 'JWT jti claim，与 JWT payload 对应，用于查找与吊销';
COMMENT ON COLUMN refresh_tokens.user_id    IS '关联用户，级联删除';
COMMENT ON COLUMN refresh_tokens.expires_at IS 'Token 过期时间（7 天）';
COMMENT ON COLUMN refresh_tokens.revoked    IS '是否已吊销（logout 或 rotation 后置 true）';

-- ---------------------------------------------------------------------------
-- 可选：定期清理已过期/已吊销的 token（可由定时任务或 pg_cron 调用）
-- ---------------------------------------------------------------------------
-- DELETE FROM refresh_tokens
-- WHERE revoked = TRUE OR expires_at < NOW();
