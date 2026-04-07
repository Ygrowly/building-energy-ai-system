-- 018: 派单体系第二阶段改造
-- 目标：
--   1. 新增班组、人员画像、技能标签数据结构
--   2. 为现有 ops 账号补齐最小画像，支持候选人推荐

CREATE TABLE IF NOT EXISTS worker_teams (
    id TEXT PRIMARY KEY,
    team_code VARCHAR(32) NOT NULL UNIQUE,
    name VARCHAR(64) NOT NULL,
    description TEXT,
    service_buildings_json TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_worker_teams_active ON worker_teams (is_active);
CREATE INDEX IF NOT EXISTS idx_worker_teams_code ON worker_teams (team_code);

CREATE TABLE IF NOT EXISTS worker_skills (
    id TEXT PRIMARY KEY,
    code VARCHAR(32) NOT NULL UNIQUE,
    name VARCHAR(64) NOT NULL,
    category VARCHAR(32),
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_worker_skills_active ON worker_skills (is_active);
CREATE INDEX IF NOT EXISTS idx_worker_skills_code ON worker_skills (code);

CREATE TABLE IF NOT EXISTS worker_profiles (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    team_id TEXT REFERENCES worker_teams(id) ON DELETE SET NULL,
    job_title VARCHAR(64),
    shift_status VARCHAR(20) NOT NULL DEFAULT 'on_duty',
    dispatch_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    max_active_orders INTEGER NOT NULL DEFAULT 4,
    accepts_emergency BOOLEAN NOT NULL DEFAULT TRUE,
    service_buildings_json TEXT,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_worker_profiles_team ON worker_profiles (team_id);
CREATE INDEX IF NOT EXISTS idx_worker_profiles_shift ON worker_profiles (shift_status);
CREATE INDEX IF NOT EXISTS idx_worker_profiles_dispatch_enabled ON worker_profiles (dispatch_enabled);

CREATE TABLE IF NOT EXISTS worker_profile_skills (
    profile_user_id TEXT NOT NULL REFERENCES worker_profiles(user_id) ON DELETE CASCADE,
    skill_id TEXT NOT NULL REFERENCES worker_skills(id) ON DELETE CASCADE,
    proficiency INTEGER NOT NULL DEFAULT 3,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (profile_user_id, skill_id)
);

CREATE INDEX IF NOT EXISTS idx_worker_profile_skills_skill ON worker_profile_skills (skill_id);
CREATE INDEX IF NOT EXISTS idx_worker_profile_skills_primary ON worker_profile_skills (profile_user_id, is_primary);

INSERT INTO worker_teams (id, team_code, name, description, service_buildings_json)
VALUES (
    'team_ops_general',
    'general_ops',
    '综合运维班',
    '默认综合运维班组，用于承接尚未细分班组的维修人员。',
    '[]'
)
ON CONFLICT (team_code) DO NOTHING;

INSERT INTO worker_skills (id, code, name, category, description)
VALUES
    ('skill_hvac', 'hvac', '暖通空调', 'facility', '适用于空调、供回水、制冷制热等异常'),
    ('skill_electrical', 'electrical', '电气配电', 'facility', '适用于配电、照明、电力波动等异常'),
    ('skill_plumbing', 'plumbing', '给排水', 'facility', '适用于漏水、阀门、给排水系统等异常'),
    ('skill_controls', 'controls', '楼宇自控', 'facility', '适用于传感器、BMS、联动控制异常'),
    ('skill_inspection', 'inspection', '现场巡检', 'generic', '通用巡检与基础排查能力')
ON CONFLICT (code) DO NOTHING;

INSERT INTO worker_profiles (
    user_id,
    team_id,
    job_title,
    shift_status,
    dispatch_enabled,
    max_active_orders,
    accepts_emergency,
    service_buildings_json,
    notes
)
SELECT
    u.id,
    'team_ops_general',
    '维修工程师',
    'on_duty',
    TRUE,
    4,
    TRUE,
    '[]',
    '由 018 迁移为现有运维账号自动补齐默认画像'
FROM users u
WHERE u.role = 'ops'
  AND NOT EXISTS (
      SELECT 1
      FROM worker_profiles wp
      WHERE wp.user_id = u.id
  );

INSERT INTO worker_profile_skills (profile_user_id, skill_id, proficiency, is_primary)
SELECT
    wp.user_id,
    ws.id,
    3,
    CASE WHEN ws.code = 'inspection' THEN TRUE ELSE FALSE END
FROM worker_profiles wp
CROSS JOIN worker_skills ws
WHERE ws.code = 'inspection'
  AND NOT EXISTS (
      SELECT 1
      FROM worker_profile_skills wps
      WHERE wps.profile_user_id = wp.user_id
        AND wps.skill_id = ws.id
  );
