"""
核心配置：从 .env 文件读取所有环境变量。
使用 pydantic-settings BaseSettings，兼容 Docker 环境变量注入。
"""
from functools import lru_cache
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

    # -----------------------------------------------------------------------
    # 大模型 API（DeepSeek / OpenAI 兼容）
    # -----------------------------------------------------------------------
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.deepseek.com/v1"
    LLM_MODEL: str = "deepseek-chat"

    # -----------------------------------------------------------------------
    # RAGFlow 知识库 API
    # -----------------------------------------------------------------------
    RAGFLOW_API_URL: str = "http://localhost:9380"
    RAGFLOW_API_KEY: str = ""
    RAGFLOW_DATASET_ID: str = ""

    # -----------------------------------------------------------------------
    # 运行模式
    # -----------------------------------------------------------------------
    DEBUG: bool = True
    APP_ENV: str = "development"  # development | production

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    """单例：整个应用共享同一份配置对象。"""
    return Settings()
