"""
核心配置：从 .env 文件读取所有环境变量。
使用 pydantic-settings BaseSettings，兼容 Docker 环境变量注入。
"""
import inspect
from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
)


CSV_LIST_FIELDS = frozenset(
    {
        "AUTO_DISPATCH_ALLOWED_BUILDINGS",
        "AUTO_DISPATCH_ALLOWED_PRIORITIES",
        "AUTO_DISPATCH_ALLOWED_REQUIRED_SKILLS",
        "AUTO_REASSIGN_ALLOWED_BUILDINGS",
        "AUTO_REASSIGN_ALLOWED_PRIORITIES",
        "AUTO_REASSIGN_ALLOWED_REQUIRED_SKILLS",
    }
)


class _CsvListCompatMixin:
    """Keep CSV env values as raw strings so the field validator can normalize them."""

    def prepare_field_value(
        self, field_name: str, field: Any, value: Any, value_is_complex: bool
    ) -> Any:
        if field_name in CSV_LIST_FIELDS and isinstance(value, str):
            return value
        return super().prepare_field_value(field_name, field, value, value_is_complex)


class CsvEnvSettingsSource(_CsvListCompatMixin, EnvSettingsSource):
    pass


class CsvDotEnvSettingsSource(_CsvListCompatMixin, DotEnvSettingsSource):
    pass


def _build_settings_source(
    source_cls: type[PydanticBaseSettingsSource],
    settings_cls: type[BaseSettings],
    **kwargs: Any,
) -> PydanticBaseSettingsSource:
    supported_params = inspect.signature(source_cls.__init__).parameters
    compatible_kwargs = {
        key: value for key, value in kwargs.items() if key in supported_params
    }
    return source_cls(settings_cls, **compatible_kwargs)


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
    # 双端 AI Provider（维小修 / 运小维）
    # -----------------------------------------------------------------------
    AI_PROVIDER: str = "qwen_dashscope"
    AI_API_KEY: str = ""  # 可统一填 Qwen / OpenAI 兼容 Key；留空时回退 DASHSCOPE_API_KEY
    DASHSCOPE_API_KEY: str = ""
    AI_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    AI_TEXT_MODEL: str = "qwen-plus"
    AI_STRUCTURED_OUTPUT_STRICT: bool = True

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
    ENABLE_AUTO_DISPATCH_EXECUTION: bool = False  # 业务开关：是否允许系统按 dry-run 结果自动创建派工任务
    AUTO_DISPATCH_MIN_SCORE: int = 110  # 自动派工第一候选人最低推荐分
    AUTO_DISPATCH_MIN_GAP: int = 10  # 自动派工第一候选人与第二候选人的最低分差
    AUTO_DISPATCH_REQUIRE_ON_DUTY: bool = True  # 自动派工是否要求第一候选人为值班中
    ENABLE_AUTO_DISPATCH_FALLBACK_EXECUTION: bool = False  # 是否允许低置信兜底派工
    AUTO_DISPATCH_FALLBACK_MIN_SCORE: int = 95  # 低置信兜底派工最低推荐分
    AUTO_DISPATCH_FALLBACK_ALLOW_STANDBY: bool = False  # 低置信兜底是否允许待命人员
    ENABLE_AUTO_DISPATCH_HALL_FALLBACK: bool = False  # 无法指定个人时是否自动创建工单大厅接管入口
    AUTO_DISPATCH_CREATE_HALL_ON_ROLLOUT_SKIP: bool = False  # 灰度外审批通过工单是否自动进大厅
    AUTO_DISPATCH_ALLOWED_BUILDINGS: list[str] = []  # 灰度：允许自动派工的楼宇白名单；空表示不限
    AUTO_DISPATCH_ALLOWED_PRIORITIES: list[str] = []  # 灰度：允许自动派工的优先级白名单；空表示不限
    AUTO_DISPATCH_ALLOWED_REQUIRED_SKILLS: list[str] = []  # 灰度：允许自动派工的技能白名单；空表示不限
    AUTO_DISPATCH_ALLOW_LOW_CONFIDENCE_IN_GREY: bool = False  # 灰度：是否允许低置信兜底派工
    AUTO_DISPATCH_ALLOW_HALL_FALLBACK_IN_GREY: bool = False  # 灰度：是否允许工单大厅兜底
    ENABLE_AUTO_REASSIGN_EXECUTION: bool = False  # 业务开关：是否允许系统按自动重派评估结果执行改派
    AUTO_REASSIGN_MIN_SCORE: int = 115  # 自动重派新候选人最低推荐分
    AUTO_REASSIGN_MIN_GAP: int = 10  # 自动重派第一候选人与第二候选人的最低分差
    AUTO_REASSIGN_REQUIRE_ON_DUTY: bool = True  # 自动重派是否要求新候选人为值班中
    AUTO_REASSIGN_REQUIRE_OVERDUE: bool = True  # 自动重派是否要求当前派工已超时
    AUTO_REASSIGN_MAX_ATTEMPT_NO: int = 3  # 自动重派允许的最大派工尝试次数
    ENABLE_AUTO_REASSIGN_PHASE1_TRIGGER: bool = False  # 一期触发器：是否允许 SLA/责任人状态自动触发自动重派
    ENABLE_AUTO_REASSIGN_SHADOW_MODE: bool = False  # 影子观察：只评估自动重派，不真正执行改派
    AUTO_REASSIGN_ALLOWED_BUILDINGS: list[str] = []  # 灰度：允许自动重派自动执行的楼宇白名单；空表示不限
    AUTO_REASSIGN_ALLOWED_PRIORITIES: list[str] = []  # 灰度：允许自动重派自动执行的优先级白名单；空表示不限
    AUTO_REASSIGN_ALLOWED_REQUIRED_SKILLS: list[str] = []  # 灰度：允许自动重派自动执行的技能白名单；空表示不限
    AUTO_REASSIGN_TRIGGER_ASSIGNED_OVERDUE: bool = True  # 一期触发器：未接单超时是否进入自动重派
    AUTO_REASSIGN_TRIGGER_ACCEPTED_OVERDUE: bool = True  # 一期触发器：已接单未到场超时是否进入自动重派
    AUTO_REASSIGN_ACCEPTED_MIN_PREVIOUS_REMINDERS: int = 1  # accepted->overdue 前至少已有几次提醒，才允许自动重派
    AUTO_REASSIGN_TRIGGER_ASSIGNEE_UNAVAILABLE: bool = False  # 一期触发器：当前责任人客观不可用时是否进入自动重派
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

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            _build_settings_source(
                CsvEnvSettingsSource,
                settings_cls,
                case_sensitive=getattr(env_settings, "case_sensitive", None),
                env_prefix=getattr(env_settings, "env_prefix", None),
                env_nested_delimiter=getattr(
                    env_settings, "env_nested_delimiter", None
                ),
                env_ignore_empty=getattr(env_settings, "env_ignore_empty", None),
                env_parse_none_str=getattr(env_settings, "env_parse_none_str", None),
                env_parse_enums=getattr(env_settings, "env_parse_enums", None),
            ),
            _build_settings_source(
                CsvDotEnvSettingsSource,
                settings_cls,
                env_file=getattr(dotenv_settings, "env_file", None),
                env_file_encoding=getattr(dotenv_settings, "env_file_encoding", None),
                case_sensitive=getattr(dotenv_settings, "case_sensitive", None),
                env_prefix=getattr(dotenv_settings, "env_prefix", None),
                env_nested_delimiter=getattr(
                    dotenv_settings, "env_nested_delimiter", None
                ),
                env_ignore_empty=getattr(dotenv_settings, "env_ignore_empty", None),
                env_parse_none_str=getattr(
                    dotenv_settings, "env_parse_none_str", None
                ),
                env_parse_enums=getattr(dotenv_settings, "env_parse_enums", None),
            ),
            file_secret_settings,
        )

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

    @field_validator(
        "AUTO_DISPATCH_ALLOWED_BUILDINGS",
        "AUTO_DISPATCH_ALLOWED_PRIORITIES",
        "AUTO_DISPATCH_ALLOWED_REQUIRED_SKILLS",
        "AUTO_REASSIGN_ALLOWED_BUILDINGS",
        "AUTO_REASSIGN_ALLOWED_PRIORITIES",
        "AUTO_REASSIGN_ALLOWED_REQUIRED_SKILLS",
        mode="before",
    )
    @classmethod
    def _normalize_csv_list(cls, value: Any) -> Any:
        if value in (None, "", []):
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """单例：整个应用共享同一份配置对象。"""
    return Settings()
