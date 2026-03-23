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
        """能耗异常常见原因与排查步骤（基于 energy_data 表与 anomaly_events 表）：

1. 夜间/无人高能耗（本地时间 00:00-06:00，electricity_kwh > 50 kWh）
   - 告警规则：night_high_power（来自 anomaly_events.rule_triggered）
   - 原因：空调/照明未关闭、设备待机功率异常偏高、非法用电接入
   - 排查步骤：
     a. 查 anomaly_events 表，过滤 rule_triggered='night_high_power' 的未解决记录
     b. 通过 meter_device_id 关联 devices 表，定位具体电表设备（device_type='ElectricityMeter'）
     c. 检查对应楼宇 buildings.timezone 换算本地时间，确认是否为真夜间
   - 处理：触发维修工单（create_work_order_draft），指定 device_id 为该楼宇电表设备 ID

2. 冷冻水过耗（chilledwater_kwh 超批次均值 3 倍，HVAC 异常）
   - 告警规则：high_chilled_water
   - 相关设备：device_type='HVAC' 的设备（来自 devices 表）
   - 原因：HVAC 设备故障、旁通阀常开、制冷剂泄漏
   - 排查：通过 sim_supply_temp_c / sim_return_temp_c 计算 COP，低于 3.0 需告警

3. 传感器跳变（electricity_kwh 超批次均值 3 倍）
   - 告警规则：sensor_spike
   - 原因：传感器老化、网络丢包导致异常值写入、电磁干扰
   - 处理：通过 devices.device_id 定位具体设备，申请传感器校准工单

所有异常事件统一存储在 anomaly_events 表，由 GB 物理双阈值规则检测生成。""",
    ),
    (
        ["COP", "能效比", "制冷效率", "空调", "HVAC", "制冷"],
        "第5章 空调能效管理",
        "楼宇能耗运维手册.pdf",
        """空调系统 COP（能效比）说明与基准：

定义：COP = 制冷量 / 空调系统耗电量
  本系统计算公式：COP_proxy = (供回水温差 × 流量系数) / chilledwater_kwh
  数据来源：energy_data 表的 sim_supply_temp_c、sim_return_temp_c、chilledwater_kwh 列
  相关设备：devices 表中 device_type='HVAC' 的设备

  参考基准（GB 50189-2015 国标）：
    - 制冷季系统综合 COP 基准值：3.5（含主机+水泵+冷却塔）
    - 供暖季系统综合 COP 基准值：2.5（热泵/锅炉综合系统）
    - 低效预警：COP 低于国标基准（需检查）
    - 严重低效：COP < 2.0（立即停机检修）

常见 COP 下降原因：
  1. 冷却塔结垢 → 冷凝温度上升 → COP 下降 0.5~1.0
  2. 冷冻水侧供回水温差缩小（< 4°C）→ 流量不足或旁通阀故障
  3. 制冷剂泄漏 → 系统压力降低 → 制冷能力下降
  4. 室外温度过高（> 38°C）→ 冷凝压力升高 → 效率下降

建议维护周期（通过 create_work_order_draft 工具发起工单）：
  - 冷却塔清洗：每半年一次 → device_type='HVAC' 的相关设备
  - 冷凝器管道除垢：每年一次
  - 制冷剂检漏：每季度一次""",
    ),
    (
        ["用电趋势", "能耗趋势", "月度", "周度", "季节", "节能", "强度", "面积"],
        "第2章 能耗趋势分析",
        "能耗数据字典与分析指南.pdf",
        """楼宇能耗趋势分析方法：

1. 日趋势：查询 daily_energy_summary 物化视图（字段：day, building_id, total_electricity_kwh）
   - 工作日 vs 节假日的基准差（教育建筑差异最大，通常节假日低 60-70%）
   - 供暖季（12-2月）vs 制冷季（6-9月）耗电差异

2. 能耗强度（kWh/㎡）计算：total_electricity_kwh / buildings.sqm
   - 办公建筑（primary_space_usage='Office'）：40-80 kWh/㎡·月（制冷季偏高）
   - 教育建筑（primary_space_usage='Education'）：25-50 kWh/㎡·月（寒暑假低谷明显）
   - 公共建筑（primary_space_usage='Public services'）：60-120 kWh/㎡·月（全年较高）

3. 多楼宇横向对比：使用 compare_metric_across_buildings 工具
   - 可按建筑类型分组对比（通过 buildings.primary_space_usage 过滤）
   - 含能耗强度计算（自动除以 buildings.sqm）

4. 节能措施优先级：
   1st: HVAC 时间表优化（节省 10-20%）— devices.device_type='HVAC'
   2nd: 照明 LED 替换 + 人感控制（节省 8-15%）
   3rd: 水泵变频改造（节省 15-25%）— devices.device_type='WaterMeter' 监控用水""",
    ),
    (
        ["设备", "维护", "维修", "工单", "巡检", "故障", "device", "meter"],
        "第4章 设备运维规范",
        "楼宇能耗运维手册.pdf",
        """设备运维标准操作规程（SOP）：

【设备注册体系】
  数据库 devices 表记录所有计量设备：
  - ElectricityMeter（电表）：对应 electricity_kwh 数据
  - WaterMeter（水表）：对应 water_m3 数据
  - HVAC（空调/暖通设备）：对应 chilledwater_kwh、hotwater_kwh、温度数据
  - EnvSensor（环境传感器）：对应 air_temp_c、humidity_rh_pct、dew_temp_c 数据

  每台设备通过 device_id 唯一标识，与 building_id 关联（一楼多设备）。
  维修工单（anomaly_events.meter_device_id）应使用 devices.device_id 的值。

一、日常巡检（每日）
  - 检查各楼控箱状态指示灯，确认无报警
  - 查询 anomaly_events 表中 is_resolved=FALSE 的未处理告警
  - 通过 meter_device_id 关联 devices 表，定位具体需要巡检的设备

二、定期维护计划
  - 月度：清洁空调过滤网；检查水管接头是否渗漏
  - 季度：校准 EnvSensor（误差 > ±0.5°C 需更换）；清洗冷却塔填料
  - 半年：电气设备绝缘测试；空调制冷剂压力检查
  - 年度：全面管道清洗；楼控系统软件升级

三、应急响应
  - 设备跳停：立即用 create_work_order_draft 创建 P1 级工单（30分钟内响应）
  - 电力超限（electricity_kwh > 额定功率 110%）：联系电力公司，检查负载分配
  - anomaly_events 异常告警后 2 小时内现场确认，完成后更新 is_resolved=TRUE""",
    ),
    (
        ["水耗", "水量", "用水", "water", "供水", "耗水", "water_m3"],
        "第6章 水耗管理",
        "能耗数据字典与分析指南.pdf",
        """楼宇水耗管理指南：

数据字段：energy_data.water_m3（单位：立方米/小时）
相关设备：devices 表中 device_type='WaterMeter' 的设备

主要用水来源：
  1. 生活用水（卫生间、茶水间）：占总水耗 40-60%
  2. 冷却塔补水：制冷季占总水耗 20-35%（蒸发损耗约 1.8% 循环水量/小时）
  3. 空调冷凝水回收：可减少 5-10% 补水需求
  4. 绿化灌溉：占 5-15%

异常判断基准：
  - 月用水量 > 历史均值 150%：检查是否有跑冒滴漏
  - 深夜（0-5点本地时间，参考 buildings.timezone）water_m3 > 0.5 m³/小时：疑似管道泄漏
  - 冷却塔补水 > 2% 循环水量/小时：检查排污阀是否常开

诊断工具使用：
  - 用 query_energy_metrics 查询 water_m3 指标时序数据
  - 用 compare_time_periods 做同环比分析（如本月 vs 上月用水对比）
  - 发现泄漏后用 create_work_order_draft 创建工单，device_id 填写 WaterMeter 类型设备 ID

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
    调用 RAGFlow POST /api/v1/retrieval 接口进行混合检索。

    参数对照（RAGFlow API v1）：
      - question          : 用户查询文本
      - dataset_ids       : 知识库 ID 列表（来自 RAGFLOW_DATASET_ID）
      - top_k             : 参与向量余弦计算的候选切片数（默认 1024），
                            这里设置为 top_k * 10 保证召回充足
      - page_size         : 最终返回切片数（对应业务层 top_k）
      - similarity_threshold : 最低相似度阈值，低于此值的切片不返回
      - keyword           : 启用关键词检索，结合向量检索实现混合搜索
      - rerank_id         : 重排模型 ID（仅当配置了 RAGFLOW_RERANK_ID 才传入）

    若 RAGFlow 未配置（API_KEY 为空），自动降级到本地关键词知识库。
    """
    settings = get_settings()

    if not settings.RAGFLOW_API_KEY or not settings.RAGFLOW_DATASET_ID:
        results = local_search(query, top_k=top_k)
        return RAGHybridSearchOutput(
            results=results,
            query=query,
            total_retrieved=len(results),
            reranked=False,
        )

    # 构造请求体，严格对照 /api/v1/retrieval 文档
    payload: dict = {
        "question": query,
        "dataset_ids": [settings.RAGFLOW_DATASET_ID],
        "top_k": top_k * 10,          # 向量召回池大小
        "page": 1,
        "page_size": top_k,            # 最终返回条数
        "similarity_threshold": 0.2,   # 低于此分数的切片过滤掉
        "vector_similarity_weight": 0.3,
        "keyword": True,               # 启用关键词混合检索
        "highlight": False,
    }

    # 有重排模型时才注入 rerank_id
    if enable_rerank and settings.RAGFLOW_RERANK_ID:
        payload["rerank_id"] = settings.RAGFLOW_RERANK_ID

    try:
        async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
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

    response_data: dict = data.get("data", {})
    raw_chunks: list[dict] = response_data.get("chunks", [])
    total_retrieved: int = response_data.get("total", len(raw_chunks))
    actually_reranked = enable_rerank and bool(settings.RAGFLOW_RERANK_ID)

    # 用 doc_aggs 构建 document_id → doc_name 的快速查找表
    # （chunks 本身只有 document_keyword，doc_aggs 提供更完整的文件名）
    doc_id_to_name: dict[str, str] = {
        agg["doc_id"]: agg["doc_name"]
        for agg in response_data.get("doc_aggs", [])
        if "doc_id" in agg and "doc_name" in agg
    }

    results = []
    for c in raw_chunks:
        doc_id = c.get("document_id", "")
        # document_keyword 和 doc_aggs.doc_name 实际上是同一个文件名
        doc_name = doc_id_to_name.get(doc_id) or c.get("document_keyword") or c.get("document_name", "unknown.pdf")

        # similarity：RAGFlow 返回的综合相似度（向量 + 关键词加权，或已经过重排）
        similarity_val = min(float(c.get("similarity", 0.0)), 1.0)
        # vector_similarity：纯向量余弦相似度，用于 rerank_score 以供对比展示
        vector_sim = c.get("vector_similarity")
        rerank_score_val = (
            min(float(vector_sim), 1.0)
            if (actually_reranked and vector_sim is not None)
            else None
        )

        results.append(RAGSearchResult(
            content=c.get("content") or "",
            parent_section=doc_name,   # RAGFlow 不返回章节信息，以文档名代替
            source_doc=doc_name,
            page=1,                    # positions 字段为字符偏移量，非页码，统一置 1
            similarity=similarity_val,
            rerank_score=rerank_score_val,
        ))

    return RAGHybridSearchOutput(
        results=results,
        query=query,
        total_retrieved=total_retrieved,
        reranked=actually_reranked,
    )
