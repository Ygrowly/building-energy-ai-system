"""
核心配置：从 .env 文件读取所有环境变量。
使用 pydantic-settings BaseSettings，兼容 Docker 环境变量注入。
"""
from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # -----------------------------------------------------------------------
    # 数据库
    # -----------------------------------------------------------------------
    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/fwwb_db"
    )
    SYNC_DATABASE_URL: str = (
        "postgresql://postgres:postgres@localhost:5432/fwwb_db"
    )
    DATABASE_SSL_MODE: str = "auto"  # disable | auto | require | verify-full
    DATABASE_SSL_CA_FILE: str = ""

    # -----------------------------------------------------------------------
    # 大模型 API（DeepSeek / OpenAI 兼容）
    # -----------------------------------------------------------------------
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.deepseek.com/v1"
    LLM_MODEL: str = "deepseek-chat"

    # 按角色独立配置模型（留空则 fallback 到 LLM_MODEL）
    LLM_MODEL_ROUTER: str = ""
    LLM_MODEL_REACT: str = ""
    LLM_MODEL_SYNTHESIS: str = ""
    LLM_MODEL_DIAGNOSE: str = ""
    LLM_MODEL_REVIEW: str = ""          # AI 审批引擎（留空则 fallback 到 LLM_MODEL_DIAGNOSE → LLM_MODEL）

    # 深度思考模式使用的强模型（留空则 fallback 到 LLM_MODEL）
    LLM_MODEL_DEEP: str = ""

    # -----------------------------------------------------------------------
    # RAGFlow 知识库 API
    # -----------------------------------------------------------------------
    RAGFLOW_API_URL: str = "http://localhost:9380"
    RAGFLOW_API_KEY: str = ""
    RAGFLOW_DATASET_ID: str = ""
    # 重排模型 ID（留空则不在请求中传 rerank_id，RAGFlow 跳过精排）
    RAGFLOW_RERANK_ID: str = ""

    # -----------------------------------------------------------------------
    # Tavily 联网搜索
    # -----------------------------------------------------------------------
    TAVILY_API_KEY: str = ""

    # -----------------------------------------------------------------------
    # 安全 — API Key（旧）
    # -----------------------------------------------------------------------
    API_KEY: str = ""

    # -----------------------------------------------------------------------
    # 安全 — JWT
    # -----------------------------------------------------------------------
    JWT_SECRET_KEY: str = "change-this-to-a-random-secret-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 180   # 3 小时
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7       # 7 天

    # -----------------------------------------------------------------------
    # 数据时间口径（全局统一，所有 Agent prompt 和默认查询范围均引用此配置）
    # -----------------------------------------------------------------------
    DATA_TIME_START: str = "2016-04-01"
    DATA_TIME_END: str = "2016-12-31"
    DATA_TIMEZONE: str = "UTC"

    # -----------------------------------------------------------------------
    # 运行模式
    # -----------------------------------------------------------------------
    DEBUG: bool = True
    APP_ENV: str = "development"  # development | production
    ENABLE_STARTUP_JOBS: bool = False  # 总开关：是否允许 API 进程在启动时注册后台周期任务
    ENABLE_TOKEN_CLEANUP_JOB: bool = False  # 子开关：是否定时清理过期/已吊销的 refresh token
    ENABLE_ANOMALY_JOB: bool = False  # 子开关：是否周期性执行期望值计算 + 异常检测批处理
    ENABLE_FORECAST_JOB: bool = False  # 子开关：是否周期性执行预测预警 + 预测工单流程
    ENABLE_DISPATCH_SLA_JOB: bool = False  # 子开关：是否周期性扫描派工任务临期/超时状态
    ANOMALY_JOB_INTERVAL_SECONDS: int = 3600  # 异常检测任务运行间隔，单位秒；仅在 ENABLE_ANOMALY_JOB=True 时生效
    FORECAST_JOB_INTERVAL_SECONDS: int = 3600  # 预测任务运行间隔，单位秒；仅在 ENABLE_FORECAST_JOB=True 时生效
    DISPATCH_SLA_JOB_INTERVAL_SECONDS: int = 60  # 派工 SLA 扫描间隔，单位秒；仅在 ENABLE_DISPATCH_SLA_JOB=True 时生效
    ENABLE_AUTO_WORK_ORDERS: bool = False  # 业务开关：异常/预测结果产生后，是否自动创建工单
    ENABLE_AUTO_AI_REVIEW: bool = False  # 业务开关：自动创建工单后，是否继续触发 AI 审批
    ENABLE_CHAT_WORK_ORDERS: bool = False  # 对话开关：是否允许聊天链路直接生成工单草稿/工单流程

    # -----------------------------------------------------------------------
    # Redis Cache
    # -----------------------------------------------------------------------
    # 缓存实现采用 Cache-Aside + TTL，并基于 30 秒 time bucket 控制刷新粒度。
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_BUCKET_SECONDS: int = 30

    # 针对首页/驾驶舱高频接口的 TTL（秒）
    CACHE_OVERVIEW_TTL_SECONDS: int = 45
    CACHE_ANOMALIES_RECENT_TTL_SECONDS: int = 45
    CACHE_ANOMALIES_SANKEY_TTL_SECONDS: int = 45
    CACHE_PREDICTIONS_RECENT_TTL_SECONDS: int = 45
    CACHE_BUILDING_ENERGY_TREND_TTL_SECONDS: int = 300
    CACHE_BUILDINGS_TTL_SECONDS: int = 3600
    CACHE_CHAT_SESSIONS_TTL_SECONDS: int = 15
    CACHE_CHAT_MESSAGES_TTL_SECONDS: int = 15
    CACHE_WORKORDERS_TTL_SECONDS: int = 15

    # 请求风暴保护（stampede control）
    CACHE_LOCK_EXPIRE_SECONDS: int = 5
    CACHE_LOCK_WAIT_SECONDS: float = 1.0

    # Redis 不可用时的本地降级缓存容量（避免内存不够/无限增长）
    CACHE_LOCAL_MAXSIZE: int = 1024
    CACHE_LOCAL_DEFAULT_TTL_SECONDS: int = 60

    model_config = {"env_file": ".env", "extra": "ignore"}

    @field_validator("DEBUG", mode="before")
    @classmethod
    def _normalize_debug_flag(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "production", "prod"}:
                return False
            if normalized in {"development", "dev", "debug"}:
                return True
        return value


@lru_cache
def get_settings() -> Settings:
    """单例：整个应用共享同一份配置对象。"""
    return Settings()
