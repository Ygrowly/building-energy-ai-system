"""验证 Qwen Plus API 连通性"""
import pathlib
from dotenv import load_dotenv
load_dotenv(pathlib.Path(__file__).parent / ".env", override=True)

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from app.core.config import get_settings

settings = get_settings()
print(f"Model  : {settings.LLM_MODEL}")
print(f"BaseURL: {settings.LLM_BASE_URL}")
print(f"Key    : {settings.LLM_API_KEY[:12]}...")

llm = ChatOpenAI(
    model=settings.LLM_MODEL,
    api_key=settings.LLM_API_KEY,
    base_url=settings.LLM_BASE_URL,
    temperature=0,
    max_tokens=200,
)

print("\n正在调用 Qwen Plus...")
resp = llm.invoke([
    SystemMessage(content="你是一个楼宇能耗管理助手，回复请简洁。"),
    HumanMessage(content="用一句话介绍你自己，并列出你能帮助处理的3类能耗问题。"),
])
print("✅ 调用成功！")
print("回复：", resp.content)
print(f"\nToken 消耗: {resp.usage_metadata}")
