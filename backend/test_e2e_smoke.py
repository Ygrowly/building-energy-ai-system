"""
端到端冒烟测试：真实 LLM + 真实数据库，走完完整对话链路
测试问题：不涉及时间的简单查询，验证路由→DataAgent→工具→回答全流程
"""
import asyncio, pathlib
from dotenv import load_dotenv
load_dotenv(pathlib.Path(__file__).parent / ".env", override=True)

from langchain_core.messages import HumanMessage

from app.db.session import AsyncSessionLocal  # 使用全局 Session（含 SSL 配置）
from app.graph.state import initial_state
from app.graph.workflow import get_graph
from app.mcp.tools.data_query import list_available_buildings


async def run_query(question: str):
    print(f"\n{'='*60}")
    print(f"  用户提问：{question}")
    print('='*60)

    # 从 DB 获取楼宇列表
    async with AsyncSessionLocal() as db:
        bldg_result = await list_available_buildings(db)
        available_buildings = [b.building_type for b in bldg_result.buildings]
    print(f"  注入楼宇列表: {available_buildings}")

    state = initial_state(available_buildings=available_buildings)
    state["messages"] = [HumanMessage(content=question)]

    graph = get_graph()
    final_state = await graph.ainvoke(state)

    # 取最后一条 AI 消息作为回答
    from langchain_core.messages import AIMessage
    ai_msgs = [m for m in final_state["messages"] if isinstance(m, AIMessage)]
    if ai_msgs:
        print(f"\n  AI 回答:\n  {ai_msgs[-1].content[:1200]}")
    print(f"\n  意图: {final_state.get('intent')}  "
          f"置信度: {final_state.get('confidence')}  "
          f"跳转次数: {final_state.get('hop_count')}")


async def main():
    await run_query("当前系统里有哪些楼宇？")
    await run_query("所有楼宇哪栋平均用电最多？")
    await run_query("Public 楼 2016年4月前两周 vs 后两周的用电量变化了多少？")
    await run_query("Office 楼 2016年4月按周统计用电趋势")
    print("\n冒烟测试完成 ✅")

asyncio.run(main())
