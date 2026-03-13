-- 004_create_datasets.sql
-- 数据中心模块：用户上传的结构化数据集文件记录表
-- 执行前提：003_create_users.sql 已执行（users 表存在）

CREATE TABLE IF NOT EXISTS dataset_files (
    id            TEXT        PRIMARY KEY,
    original_name TEXT        NOT NULL,
    file_path     TEXT        NOT NULL,
    file_type     TEXT        NOT NULL,          -- csv | xlsx | xls
    row_count     INTEGER,
    column_count  INTEGER,
    columns_json  TEXT,                          -- JSON 数组：[{name, dtype, null_count}]
    stats_json    TEXT,                          -- JSON 对象：{col: {min,max,mean,std}}
    uploaded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    uploader_id   TEXT        REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_dataset_files_uploader
    ON dataset_files (uploader_id);

CREATE INDEX IF NOT EXISTS idx_dataset_files_uploaded_at
    ON dataset_files (uploaded_at DESC);
