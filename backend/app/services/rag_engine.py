"""
RAG 检索引擎服务层。

将 RAGFlow API 调用和本地知识库检索统一封装，
供 MCP 工具层（rag_search.py）和其他模块复用。
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.schemas.mcp_schemas import (
    MCPError,
    RAGHybridSearchOutput,
    RAGSearchResult,
)

# ---------------------------------------------------------------------------
# 内嵌本地知识库（RAGFlow 不可用时的演示降级内容）
# ---------------------------------------------------------------------------
_LOCAL_KB: list[tuple[list[str], str, str, str]] = [
    (
        ["能耗异常", "能耗高", "用电异常", "异常原因", "凌晨", "夜间"],
        "第3章 能耗异常诊断",
        "楼宇能耗运维手册.pdf",
        """能耗异常常见原因与排查步骤：
1. 夜间/无人高能耗（凌晨 22:00-06:00 electricity_kwh 超过日均 40%）
   - 原因：空调/照明未关闭、设备待机功率异常偏高、非法用电接入
   - 排查：查看 operation_status 是否为 NIGHT_MODE；检查 hvac_energy_kwh 是否超过 0.3 × daily_avg
   - 处理：触发运维工单，要求现场巡检；检查楼控系统定时策略

2. 空占比异常（occupancy_density ≈ 0 但 hvac_energy_kwh 仍高）
   - 原因：人员离开后 HVAC 未切到节能模式；楼控传感器故障导致误判有人
   - 排查：对比 occupancy_density_per_100sqm 与 hvac_energy_kwh 的相关性
   - 处理：校准 CO₂/PIR 传感器，更新楼控联动策略

3. 传感器跳变（单点数值 > 均值 3σ）
   - 原因：传感器老化、网络丢包导致异常值写入、电磁干扰
   - 处理：丢弃异常数据点，申请传感器校准工单""",
    ),
    (
        ["COP", "能效比", "制冷效率", "空调", "HVAC", "制冷"],
        "第5章 空调能效管理",
        "楼宇能耗运维手册.pdf",
        """空调系统 COP（能效比）说明与基准：
定义：COP = 制冷量 / 空调系统耗电量
  本系统计算公式：COP_proxy = (供回水温差 × 流量系数) / hvac_energy_kwh
  参考基准（ASHRAE 90.1-2022）：
    - 高效机组 COP ≥ 5.5（满负荷）
    - 正常运行 COP 3.5 ~ 5.5
    - 低效预警 COP < 3.5（需检查）
    - 严重低效 COP < 2.0（立即停机检修）

常见 COP 下降原因：
  1. 冷却塔结垢 → 冷凝温度上升 → COP 下降 0.5~1.0
  2. 冷冻水侧供回水温差缩小（< 4°C）→ 流量不足或旁通阀故障
  3. 制冷剂泄漏 → 系统压力降低 → 制冷能力下降
  4. 室外温度过高（> 38°C）→ 冷凝压力升高 → 效率下降

建议维护周期：
  - 冷却塔清洗：每半年一次
  - 冷凝器管道除垢：每年一次
  - 制冷剂检漏：每季度一次""",
    ),
    (
        ["用电趋势", "能耗趋势", "月度", "周度", "季节", "节能"],
        "第2章 能耗趋势分析",
        "能耗数据字典与分析指南.pdf",
        """楼宇能耗趋势分析方法：
1. 日趋势：查询 daily_energy_summary 视图，关注 total_electricity_kwh 走势
   - 工作日 vs 节假日的基准差（教育建筑差异最大，通常节假日低 60-70%）
   - 供暖季（12-2月）vs 制冷季（6-9月）耗电差异

2. 能耗强度（kWh/㎡）参考值：
   - 办公建筑：40-80 kWh/㎡·月（制冷季偏高）
   - 教育建筑：25-50 kWh/㎡·月（寒暑假低谷明显）
   - 公共建筑：60-120 kWh/㎡·月（全年较高）

3. 节能措施优先级：
   1st: HVAC 时间表优化（节省 10-20%）
   2nd: 照明 LED 替换 + 人感控制（节省 8-15%）
   3rd: 空压机/水泵变频改造（节省 15-25%）
   4th: 楼顶光伏安装（抵消 10-30% 用电）""",
    ),
    (
        ["设备", "维护", "维修", "工单", "巡检", "故障"],
        "第4章 设备运维规范",
        "楼宇能耗运维手册.pdf",
        """设备运维标准操作规程（SOP）：
一、日常巡检（每日）
  - 检查各楼控箱状态指示灯，确认无报警
  - 记录主要设备（空调机组、水泵、变压器）运行参数
  - 对比 meter_device_id 对应传感器最新读数与昨日基准值

二、定期维护计划
  - 月度：清洁空调过滤网；检查水管接头是否渗漏
  - 季度：校准温湿度传感器（误差 > ±0.5°C 需更换）；清洗冷却塔填料
  - 半年：电气设备绝缘测试；空调制冷剂压力检查；更换老化密封件
  - 年度：全面管道清洗；系统压力试验；楼控系统软件升级

三、应急响应
  - 设备跳停：立即创建 P1 级工单，30分钟内响应
  - 电力超限（> 额定功率 110%）：联系电力公司，同时检查负载分配
  - 异常告警后 2 小时内现场确认，24 小时内完成整改或提交延期申请""",
    ),
    (
        ["水耗", "水量", "用水", "water", "供水", "耗水"],
        "第6章 水耗管理",
        "能耗数据字典与分析指南.pdf",
        """楼宇水耗管理指南：
主要用水来源：
  1. 生活用水（卫生间、茶水间）：占总水耗 40-60%
  2. 冷却塔补水：制冷季占总水耗 20-35%（蒸发损耗约 1.8% 循环水量/小时）
  3. 空调冷凝水回收：可减少 5-10% 补水需求
  4. 绿化灌溉：占 5-15%

异常判断基准：
  - 月用水量 > 历史均值 150%：检查是否有跑冒滴漏
  - 深夜（0-5点）water_m3 > 0.5 m³/小时：疑似管道泄漏
  - 冷却塔补水 > 2% 循环水量/小时：检查排污阀是否常开

节水措施：
  - 冷却塔安装变频风机（节水 15-20%）
  - 中水回用系统（降低自来水消耗 20-30%）
  - 漏水检测仪安装在主给水管前段""",
    ),
]


def local_search(query: str, top_k: int = 3) -> list[RAGSearchResult]:
    """基于关键词匹配的本地知识库检索（RAGFlow 不可用时的 fallback）。"""
    query_lower = query.lower()
    scored: list[tuple[float, tuple]] = []
    for entry in _LOCAL_KB:
        keywords, section, doc, content = entry
        hits = sum(1 for kw in keywords if kw.lower() in query_lower)
        if hits > 0:
            scored.append((hits / len(keywords), entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, (keywords, section, doc, content) in scored[:top_k]:
        results.append(RAGSearchResult(
            content=content,
            parent_section=section,
            source_doc=doc,
            page=1,
            similarity=round(score, 3),
            rerank_score=None,
        ))

    if not results:
        results.append(RAGSearchResult(
            content=(
                "未在本地知识库中找到直接相关内容。\n"
                "可查询方向：能耗异常、COP能效比、设备维护规程、用电/用水趋势分析。\n"
                "如需更详细的技术支持，请联系楼宇能源管理专家。"
            ),
            parent_section="通用提示",
            source_doc="本地知识库",
            page=1,
            similarity=0.0,
            rerank_score=None,
        ))
    return results


async def search_ragflow(
    query: str,
    metadata_filter: dict | None = None,
    enable_rerank: bool = True,
    top_k: int = 3,
) -> RAGHybridSearchOutput | MCPError:
    """
    调用 RAGFlow API 进行混合检索。

    若 RAGFlow 未配置，自动降级到本地知识库。
    """
    settings = get_settings()

    if not settings.RAGFLOW_API_URL or not settings.RAGFLOW_API_KEY:
        results = local_search(query, top_k=top_k)
        return RAGHybridSearchOutput(
            results=results,
            query=query,
            total_retrieved=len(results),
            reranked=False,
        )

    payload = {
        "question": query,
        "dataset_ids": [settings.RAGFLOW_DATASET_ID],
        "rerank": enable_rerank,
        "top_k": top_k * 6,
        "highlight": False,
    }

    if metadata_filter:
        filters = {k: v for k, v in metadata_filter.items() if v}
        if filters:
            payload["filters"] = filters

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{settings.RAGFLOW_API_URL}/api/v1/retrieval",
                headers={"Authorization": f"Bearer {settings.RAGFLOW_API_KEY}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        return MCPError(
            error=f"RAGFlow 服务不可用：{exc}。知识库检索暂时离线，请直接根据数据给出分析结论。",
            error_code="RAGFLOW_UNAVAILABLE",
            tool_name="rag_hybrid_search",
        )

    chunks = data.get("data", {}).get("chunks", [])[:top_k]
    results = [
        RAGSearchResult(
            content=c.get("content_with_weight", c.get("content", "")),
            parent_section=c.get("document_keyword", "未知章节"),
            source_doc=c.get("doc_name", "unknown.pdf"),
            page=int(c.get("positions", [[1]])[0][0]) if c.get("positions") else 1,
            similarity=float(c.get("similarity", 0.0)),
            rerank_score=float(c.get("score", 0.0)) if enable_rerank else None,
        )
        for c in chunks
    ]

    return RAGHybridSearchOutput(
        results=results,
        query=query,
        total_retrieved=len(data.get("data", {}).get("chunks", [])),
        reranked=enable_rerank,
    )
