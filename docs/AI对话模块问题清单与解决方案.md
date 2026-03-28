# AI 对话模块 — 问题清单与解决方案

> 创建时间：2026-03-28  
> 触发场景：用户发送"我现在需要了解教学楼的平均日总用电量以及办公楼的，并且为什么他们有这么大的区别"导致系统卡死

---

## 问题总览

| # | 问题 | 严重度 | 类型 | 预估工作量 |
|---|------|--------|------|-----------|
| 1 | 复合意图无法分拆，单次只路由到一个 Agent | **P0 致命** | 架构 | 中 |
| 2 | LLM 调用无超时，API 挂起则整个请求永久卡死 | **P0 致命** | 稳定性 | 小 |
| 3 | ReAct 循环无单步超时 + 总超时，慢场景可达 60s+ | **P1 严重** | 性能 | 小 |
| 4 | 业务快速路由存在误匹配和实体丢失 | **P1 严重** | 路由 | 中 |
| 5 | Agent 间缺少接力协作机制 | **P1 严重** | 架构 | 中 |
| 6 | data_synthesis 在无有效数据时仍调用 LLM（可能编造） | **P2 一般** | 准确性 | 小 |
| 7 | fallback ainvoke 双重执行 | **P2 一般** | 资源浪费 | 小 |

---

## 问题 1：复合意图无法分拆，单次只路由到一个 Agent

### 问题描述

用户发送：
> "我现在需要了解教学楼的平均日总用电量以及办公楼的，**并且为什么他们有这么大的区别**"

这条消息包含**两个子意图**：
1. **数据查询** — 教学楼和办公楼的平均日总用电量（应路由到 Data Agent）
2. **原因分析** — 为什么有这么大区别（应路由到 Diagnose Agent 或由 Synthesis 深度分析）

当前 Router 只能选择**一个** `next_agent`，导致两种失败路径：

**路径 A：Router 选了 `data_query` → Data Agent**
- Data Agent 的 ReAct Prompt 明确规定**"禁止生成详细分析文本"**
- Agent 查完数据后，尝试"解释为什么"但 Prompt 阻止它
- ReAct 循环陷入矛盾：想回答"为什么"但所有工具都只返回数据，无法归因
- 反复尝试工具调用 → 消耗完 `recursion_limit=12` → 每次 LLM 调用 3-8 秒
- **最终耗时：12 × 5s ≈ 60 秒，用户感知为"卡死"**
- Synthesis 阶段拿到数据后**可能**给出浅层分析，但深度不够

**路径 B：Router 选了 `fault_diagnosis` → Diagnose Agent**
- Diagnose Agent 缺少高效的多楼对比工具（没有 `compare_metric_across_buildings`）
- 需要自行调用 `query_energy_metrics` 分别查两栋楼，再调 RAG 搜索原因
- 工具调用次数多（4-7 次），`recursion_limit=15`
- **最终耗时：可能 45-75 秒**

### 根因

```
当前拓扑（线性，不可分叉）：
  Router ──→ Data Agent ──→ Synthesis ──→ END
         └─→ Diagnose Agent ──→ END

缺少的路径：
  Router ──→ Data Agent ──→ Synthesis ──→ Diagnose Agent ──→ END
                                         （数据+分析接力）
```

`workflow.py` 第 80-84 行硬编码了 `data_synthesis → END` 和 `diagnose_agent → END`，没有条件边允许接力。

### 解决方案

**方案 A（推荐）：Router 意图分拆 + data_synthesis 条件边**

核心改动点：

**1. Router 增加复合意图识别**

在 `RouterDecision` Schema 中增加 `needs_diagnosis` 字段：

```python
class RouterDecision(BaseModel):
    intent: Literal[...] = Field(description="用户主意图类型")
    needs_diagnosis: bool = Field(
        default=False,
        description="是否需要在数据查询完成后进行原因分析/诊断/建议"
    )
    # ... 其他字段不变
```

Router Prompt 增加规则：
```
## 复合意图识别
当用户同时需要"数据查询"和"原因分析/建议"时：
- intent 设为 data_query（先查数据）
- needs_diagnosis 设为 true（查完数据后自动转诊断）
- 示例："教学楼用了多少电？为什么这么高？" → data_query + needs_diagnosis=true
```

**2. AgentState 增加接力标志**

```python
class AgentState(TypedDict):
    # ... 现有字段 ...
    needs_diagnosis: bool
    """Router 标记的复合意图：data_synthesis 完成后是否接力到 diagnose_agent"""
```

**3. workflow.py 增加条件边**

```python
def _route_after_synthesis(state: AgentState) -> str:
    if state.get("needs_diagnosis"):
        return "diagnose_agent"
    return END

# 替换原来的硬边：
# builder.add_edge("data_synthesis", END)
builder.add_conditional_edges(
    "data_synthesis",
    _route_after_synthesis,
    {"diagnose_agent": "diagnose_agent", END: END},
)
```

**4. Diagnose Agent 上下文感知数据阶段的结果**

Diagnose Agent 的上下文注入中已包含 `context_summary`，data_synthesis 完成后会更新摘要。但可进一步优化：将 `react_data_summary` 和 `chart_manifest` 也注入 Diagnose Agent 的 SystemMessage，避免重复查询。

**新拓扑：**

```
START → Router
        ├─ [data_query, needs_diagnosis=false] → data_react → data_synthesis → END
        ├─ [data_query, needs_diagnosis=true]  → data_react → data_synthesis → diagnose_agent → END
        ├─ [fault_diagnosis] → diagnose_agent → END
        └─ [其他] → END
```

**方案 B（轻量替代）：增强 Synthesis Prompt 的分析能力**

不改动图拓扑，仅在 `SYNTHESIS_PROMPT` 中增加"差异分析"指令：

```
## 差异分析
当用户问到"为什么有差异"/"为什么这么高"等原因问题时：
- 基于工具返回的数据，结合建筑类型（Education=教学楼，Office=办公楼）的功能差异进行合理分析
- 可从以下维度给出分析：建筑面积、使用时段、设备类型、季节因素
- 明确标注"基于数据推测"和"建议进一步诊断确认"
```

优点：改动最小。缺点：分析深度不如 Diagnose Agent（无 RAG、无异常检测数据）。

**推荐：先实施方案 B 快速止血，再迭代方案 A。**

---

## 问题 2：LLM 调用无超时，API 挂起时整个请求永久卡死

### 问题描述

所有 `ChatOpenAI` 实例**均未配置 `request_timeout`**：

```python
# router_agent.py L317
_cached_router_llm = ChatOpenAI(
    model=settings.LLM_MODEL_ROUTER,
    api_key=settings.LLM_API_KEY,
    base_url=settings.LLM_BASE_URL,
    temperature=0.0,
    max_tokens=512,
    # ❌ 没有 request_timeout / timeout
)

# data_agent.py L239, L255 — 同样缺失
# data_agent.py L458, L470 — 同样缺失
# diagnose_agent.py L333 — 同样缺失
```

当 DeepSeek API 响应变慢或挂起时：
- 单次 LLM 调用可能等待 30s、60s 甚至无限期
- ReAct 循环中有多次 LLM 调用，**总等待时间无上限**
- 前端 SSE 流保持打开但无任何事件推出，用户看到"卡死"

### 根因

LangChain `ChatOpenAI` 底层使用 `httpx.AsyncClient`，默认无超时（或使用 httpx 默认的 5s connect + 无 read timeout）。当 API 端点延迟高时，read 阶段会无限等待。

### 解决方案

**所有 `ChatOpenAI` 构造处增加 `request_timeout`：**

```python
# 建议值：Router 30s（单次调用，应快速），ReAct/Synthesis/Diagnose 60s
ChatOpenAI(
    model=...,
    api_key=...,
    base_url=...,
    request_timeout=60,  # ← 新增
    ...
)
```

**涉及修改位置（6 处）：**

| 文件 | 行号 | 角色 | 建议 timeout |
|------|------|------|-------------|
| `router_agent.py` | L317 | Router | 30s |
| `data_agent.py` | L239 | ReAct (full) | 60s |
| `data_agent.py` | L255 | ReAct (no list) | 60s |
| `data_agent.py` | L458 | Synthesis deep | 90s |
| `data_agent.py` | L470 | Synthesis fast | 60s |
| `diagnose_agent.py` | L333 | Diagnose | 90s |

**同时在 `_stream_graph` 中增加总超时保护：**

```python
# routes_chat.py — _stream_graph 函数入口
import asyncio

async def _stream_graph(...):
    # ...
    try:
        async with asyncio.timeout(180):  # 单轮对话总超时 3 分钟
            async for event in graph.astream_events(graph_input, version="v2"):
                # ...
    except TimeoutError:
        yield _error_event("请求处理超时，请简化问题后重试")
```

---

## 问题 3：ReAct 循环无单步超时 + 总超时

### 问题描述

`recursion_limit` 只限制**循环次数**（Data=12, Diagnose=15），不限制**总耗时**。每次迭代包含：
1. LLM 推理（3-10s，取决于 API 速度和 Prompt 复杂度）
2. 工具调用（0.1-30s，取决于 DB 查询复杂度或外部 API）
3. 结果解析

**最坏情况：12 × (10s LLM + 30s 工具) = 480 秒**，远超用户可接受的等待时间。

### 根因

`create_react_agent` 没有原生的总超时参数。`recursion_limit` 只是"步数上限"，不考虑时间。

### 解决方案

**在 Agent 节点中包装 `asyncio.wait_for`：**

```python
# data_agent.py — data_react_node
_REACT_TIMEOUT = 90  # 秒

try:
    result = await asyncio.wait_for(
        agent.ainvoke(sub_state, config={"recursion_limit": 12}),
        timeout=_REACT_TIMEOUT,
    )
except asyncio.TimeoutError:
    logger.warning("Data Agent ReAct 超时（%ds），强制终止", _REACT_TIMEOUT)
    error_msg = AIMessage(content="数据查询耗时过长，已自动终止。建议拆分为更简单的问题。")
    return {
        "messages": [error_msg],
        "current_agent": "end",
        "hop_count": hop_count,
        "error": "react_timeout",
    }
```

同样应用到 `diagnose_agent_node`（建议 120s）。

---

## 问题 4：业务快速路由存在误匹配和实体丢失

### 问题描述

#### 4a. 长度阈值过于保守

`_FAST_ROUTE_MAX_LEN = 80`，但实际业务问题长度经常超过 80 字符。例如：

> "我现在需要了解教学楼的平均日总用电量以及办公楼的，并且为什么他们有这么大的区别"（47 个汉字 = 47 字符 < 80）

等等，这条消息实际上**不超过 80**，让我重新计算——实际是 41 个汉字 + 标点 ≈ 45 字符，**在快速路由范围内**。

快速路由的匹配顺序问题：
- 该消息同时匹配 `data_query` 正则（含"用电量"+"了解"≈查询）
- 和 `fault_diagnosis` 正则（含"为什么"+"区别"≈诊断原因）
- **先匹配到谁取决于规则列表顺序**

当前顺序：`data_query` 排在 `fault_diagnosis` 前面。所以该消息会被快速路由到 `data_agent`，丢失了"为什么"这个子意图。

#### 4b. 快速路由不提取实体

快速路由命中时，`building_id` / `time_context` 只从 state 中沿用旧值：

```python
# router_agent.py L424-428
return {
    "current_agent": fast_next,
    "intent": fast_intent,
    "building_id": state.get("building_id"),    # ← 旧值
    "device_id": state.get("device_id"),        # ← 旧值
    "time_context": state.get("time_context"),  # ← 旧值
}
```

如果用户在新消息中提到了不同的楼宇（如从"教学楼"切到"办公楼"），实体不会更新。

#### 4c. fault_diagnosis 正则过于宽泛

`r'(?:建议|优化|改进|意见|诊断|异常|故障|问题|原因|为什么.*高|为什么.*低|节能|省电|降低能耗|怎么.*减少)'`

- "问题" 一词太常见，"这个数据有什么问题" → 误匹配 fault_diagnosis
- "为什么.*高" 只匹配"为什么...高"，不匹配"为什么...大的区别"

### 解决方案

#### 4a. 复合意图检测拦截

在快速路由匹配逻辑中增加**冲突检测**：如果同时命中 `data_query` 和 `fault_diagnosis`，则放弃快速路由，交给 LLM 处理：

```python
def _try_fast_path(message: str) -> str | dict | None:
    msg = message.strip()
    # ... 问候类不变 ...

    if len(msg) <= _FAST_ROUTE_MAX_LEN:
        matched_intents = set()
        first_match = None
        for pattern, intent in _FAST_ROUTE_RULES:
            if pattern.search(msg):
                matched_intents.add(intent)
                if first_match is None:
                    first_match = intent
        
        # 冲突检测：同时命中数据类和分析类 → 交给 LLM
        data_intents = {"data_query", "cop_analysis", "forecast"}
        analysis_intents = {"fault_diagnosis", "work_order", "knowledge_query"}
        if matched_intents & data_intents and matched_intents & analysis_intents:
            return None  # 复合意图，LLM 来判断
        
        if first_match is not None:
            return {"intent": first_match, "next_agent": _INTENT_ROUTING.get(first_match, "end")}
    
    return None
```

#### 4b. 快速路由增加轻量实体提取

```python
_BUILDING_PATTERNS = [
    (re.compile(r'教学楼|Education', re.IGNORECASE), "Education"),
    (re.compile(r'办公楼|Office', re.IGNORECASE), "Office"),
    (re.compile(r'公共楼|图书馆|Public', re.IGNORECASE), "Public services"),
]

def _extract_building_from_text(msg: str) -> str | None:
    """从消息中提取建筑 ID（正则，零成本）。"""
    for pattern, building_id in _BUILDING_PATTERNS:
        if pattern.search(msg):
            return building_id
    return None
```

在快速路由返回前调用提取：

```python
if isinstance(fast_result, dict):
    extracted_building = _extract_building_from_text(msg)
    return {
        "intent": fast_result["intent"],
        "next_agent": fast_result["next_agent"],
        "building_id": extracted_building or state.get("building_id"),
        # ...
    }
```

#### 4c. 收紧 fault_diagnosis 正则

```python
# 旧规则
r'(?:建议|优化|改进|意见|诊断|异常|故障|问题|原因|为什么.*高|为什么.*低|节能|省电|降低能耗|怎么.*减少)'

# 新规则：移除"问题"（太宽泛），扩展"为什么"匹配
r'(?:建议|优化|改进|意见|诊断|异常|故障|原因分析|为什么.*[高低大多少]|节能|省电|降低能耗|怎么.*减少|什么原因)'
```

---

## 问题 5：Agent 间缺少接力协作机制

### 问题描述

当前图拓扑是**严格线性**的：

```
Router → (Data Agent OR Diagnose Agent) → END
```

两个 Agent 的工具集有部分重叠但不完全相同：

| 工具 | Data Agent | Diagnose Agent |
|------|-----------|----------------|
| query_energy_metrics | ✅ | ✅ |
| query_daily_energy_summary | ✅ | ❌ |
| compare_metric_across_buildings | ✅ | ❌ |
| compare_time_periods | ✅ | ❌ |
| detect_energy_anomalies | ✅ | ✅ |
| get_building_rated_values | ❌ | ✅ |
| rag_hybrid_search | ❌ | ✅ |
| create_work_order_draft | ❌ | ✅ |
| web_search | ❌ | ✅（联网时） |

问题场景：
- "对比三栋楼用电 + 给优化建议" → 需要 Data Agent 的 `compare_metric_across_buildings` + Diagnose Agent 的 RAG
- "查异常 + 生成工单" → 两边都可检测异常，但只有 Diagnose Agent 可生成工单
- "预测未来用电 + 预测超标怎么办" → Data Agent 预测 + Diagnose Agent 建议

### 根因

`workflow.py` 中 `data_synthesis → END` 和 `diagnose_agent → END` 是**硬边**，无条件边。

### 解决方案

详见**问题 1 的方案 A**（Router 复合意图 + data_synthesis 条件边）。

补充方案：**Diagnose Agent 增加数据对比工具**

将 `compare_metric_across_buildings` 和 `query_daily_energy_summary` 也注册到 Diagnose Agent 的工具集中：

```python
# diagnose_agent.py
def _build_diagnose_base_tools() -> list[StructuredTool]:
    return [
        # ... 现有工具 ...
        _make_mcp_tool(
            "query_daily_energy_summary",
            "查询按天/周/月汇总的能耗趋势",
            args_schema=QueryDailyEnergySummaryInput,
        ),
        _make_mcp_tool(
            "compare_metric_across_buildings",
            "多栋楼同一指标横向对比",
            args_schema=CompareMetricAcrossBuildingsInput,
        ),
    ]
```

优点：不改图拓扑，Diagnose Agent 可以独立完成"数据对比 + 归因分析"。
缺点：Diagnose Agent 的工具集变大，Prompt 变长，可能影响工具选择精度。

---

## 问题 6：data_synthesis 在无有效数据时仍调用 LLM

### 问题描述

`data_synthesis_node` 不检查 `react_data_summary` 是否有效，即使 ReAct 阶段所有工具调用都失败（返回 MCPError），Synthesis LLM 仍会被调用。Synthesis 拿到"（工具返回结果为空）"的摘要，可能**编造**分析内容。

```python
# data_agent.py L493-494
data_summary = state.get("react_data_summary", "")
# 即使 data_summary == "（工具返回结果为空）"，仍继续调用 LLM
```

### 解决方案

```python
async def data_synthesis_node(state: AgentState) -> dict[str, Any]:
    # ... 错误早退逻辑 ...
    
    data_summary = state.get("react_data_summary", "")
    
    # ★ 无有效数据时直接返回提示，跳过 LLM
    if not data_summary or data_summary.startswith("（"):
        return {
            "messages": [AIMessage(content="抱歉，数据查询未返回有效结果，请检查查询条件后重试。")],
            "current_agent": "end",
        }
    
    # ... 正常 Synthesis 流程 ...
```

---

## 问题 7：fallback ainvoke 双重执行

### 问题描述

`routes_chat.py` 第 748-760 行，当 `astream_events` 的中间事件未正确填充 `final_state_holder` 时（可能由于 LangGraph 事件格式变化），触发 `graph.ainvoke(graph_input)` 作为 fallback。

这会导致**同一条用户消息被 LLM 完整处理两次**：一次在 `astream_events` 中（虽然 state 没收集到），一次在 `ainvoke` 中。

### 解决方案

**改为检查 messages 中是否已有 AI 回复：**

```python
if not final_state_holder:
    # 检查是否已在流式过程中收到了有效回复
    current_msgs = state.get("messages", [])
    has_ai_reply = any(
        isinstance(m, AIMessage) and m.content and not getattr(m, "tool_calls", [])
        for m in current_msgs[-5:]
    )
    if has_ai_reply:
        logger.info("final_state_holder 为空但已有 AI 回复，跳过 fallback")
        _sessions[session_id] = state
        merged = state
        hop = state.get("hop_count", 0)
    else:
        logger.warning("触发 fallback ainvoke")
        # ... 原有 fallback 逻辑 ...
```

---

## 实施优先级建议

### 第一批（立即修复 — 解决"卡死"问题）

| 序号 | 修改项 | 文件 | 说明 |
|------|--------|------|------|
| 1 | ChatOpenAI 增加 `request_timeout` | `router_agent.py` / `data_agent.py` / `diagnose_agent.py` | 6 处，每处加 1 行 |
| 2 | ReAct 节点增加 `asyncio.wait_for` 总超时 | `data_agent.py` / `diagnose_agent.py` | 2 处，包裹 ainvoke |
| 3 | `_stream_graph` 增加总超时 | `routes_chat.py` | 1 处，asyncio.timeout |

预估改动：~20 行代码，解决 100% 的"永久卡死"问题。

### 第二批（快速止血 — 解决复合意图体验）

| 序号 | 修改项 | 文件 | 说明 |
|------|--------|------|------|
| 4 | 快速路由增加冲突检测 | `router_agent.py` | 复合意图交给 LLM |
| 5 | 快速路由增加实体提取 | `router_agent.py` | building_id 正则提取 |
| 6 | 增强 SYNTHESIS_PROMPT 差异分析能力 | `data_agent.py` | 在 Prompt 中增加分析指引 |
| 7 | data_synthesis 无数据早退 | `data_agent.py` | 防止 LLM 编造 |

预估改动：~50 行代码，解决"对比+分析"类复合问题。

### 第三批（架构演进 — Agent 接力协作）

| 序号 | 修改项 | 文件 | 说明 |
|------|--------|------|------|
| 8 | RouterDecision 增加 `needs_diagnosis` | `router_agent.py` / `state.py` | Schema + State 扩展 |
| 9 | Router Prompt 增加复合意图识别规则 | `router_agent.py` | Prompt 改动 |
| 10 | workflow.py 增加 data_synthesis → diagnose 条件边 | `workflow.py` | 图拓扑改动 |
| 11 | Diagnose Agent 上下文感知数据阶段结果 | `diagnose_agent.py` | 注入 data_summary |
| 12 | fallback ainvoke 修复 | `routes_chat.py` | 防止双重执行 |

预估改动：~100 行代码，实现 Data → Diagnose 接力协作。

---

## 附录：卡死场景的完整调用链分析

```
用户: "我现在需要了解教学楼的平均日总用电量以及办公楼的，并且为什么他们有这么大的区别"
  │
  ├─ routes_chat._stream_graph()
  │   ├─ _router_fast_path("...") → len=45 < 80，检查快速路由
  │   │   ├─ data_query 正则: "用电量" 命中 ✅ → data_query
  │   │   └─ fault_diagnosis 正则: 未检测到冲突，返回 data_query
  │   │   ★ 丢失了"为什么...区别"这个分析子意图
  │   │
  │   ├─ 跳过 LLM Router，直接路由到 data_react
  │   │
  │   ├─ data_react_node()
  │   │   ├─ LLM 推理 #1: 选择工具 compare_metric_across_buildings (3-8s)
  │   │   ├─ 工具调用 #1: 查 electricity_kwh 全楼对比 (0.5-2s)
  │   │   ├─ LLM 推理 #2: 数据拿到了，但用户问"为什么" (3-8s)
  │   │   ├─ LLM 推理 #3: 尝试调 detect_energy_anomalies (3-8s)
  │   │   ├─ 工具调用 #2: 异常检测 Education (0.5-2s)
  │   │   ├─ LLM 推理 #4: 还是不够解释"为什么" (3-8s)
  │   │   ├─ 工具调用 #3: 异常检测 Office (0.5-2s)
  │   │   ├─ LLM 推理 #5-12: 反复尝试但无法满足... (24-64s)
  │   │   └─ 最终: GraphRecursionError 或勉强结束
  │   │   ★ 累计耗时：30-90 秒
  │   │
  │   ├─ data_synthesis_node()
  │   │   ├─ LLM Synthesis: 基于不完整数据生成分析 (3-10s)
  │   │   └─ 可能给出浅层"面积不同/用途不同"的分析
  │   │
  │   └─ 推送 SSE done 事件
  │
  └─ 用户体验: 等待 30-90 秒，收到浅层回答（如果没超时的话）
```

---

## 第四批修复：Router 路由死循环（2026-03-28）

### 问题 4.1：`clarify → router` 路由表导致无限循环

**现象**：用户发送复合意图（如"查教学楼用电量并给优化建议"）后，前端显示"正在识别意图..."长时间无响应。后端日志显示 `快速路由: 检测到复合意图` 反复出现。

**根因链**：
1. 快速路由检测到同时命中 `data_query` + `fault_diagnosis` → 判定为复合意图 → 返回 None → 交给 LLM
2. LLM 面对复合意图不确定时返回 `intent: "clarify"`
3. `_INTENT_ROUTING["clarify"] = "router"` → Graph 条件边把控制权交回 router 节点
4. 用户没有新消息 → router 拿到完全一样的输入 → 重复 1-3 → **死循环**
5. 虽有 `MAX_HOPS = 5` 熔断，但每轮 LLM 调用 30 秒超时，最坏等 150 秒

**修复**（`router_agent.py` + `workflow.py`）：
- **A.** `_INTENT_ROUTING["clarify"]` 从 `"router"` 改为 `"end"` — Router 输出澄清问题后结束本轮，等用户下一条消息
- **B.** `_parse_router_output` JSON 解析失败时 fallback 的 `next_agent` 也从 `"router"` 改为 `"end"`
- **C.** 新增重入降级逻辑：`hop_count > 1` 且 intent 仍是 `clarify` 时，自动降级为 `data_query + needs_diagnosis=true`，走数据→诊断链路
- **D.** `router_node` 返回前新增 INFO 日志打印 intent/next_agent/confidence/hop_count

### 问题 4.2：`logging.basicConfig` 在 `uvicorn --reload` 下失效

**现象**：后端终端只有 SQLAlchemy 和 uvicorn access 日志，`app.*` 模块日志完全不输出，无法排查 agent 执行问题。

**根因**：`uvicorn --reload` 在导入 `main.py` 前已配置 root logger handler。Python `logging.basicConfig()` 默认在 root logger 已有 handler 时为 no-op，导致 `app.*` 的 INFO 日志被静默吞掉。

**修复**（`main.py`）：
- `logging.basicConfig(..., force=True)` 强制覆盖 uvicorn 预配置
- 将 `app.graph.nodes.*` 和 `app.graph.workflow` 等关键模块加入显式 `setLevel(INFO)` 列表

### 问题 4.3：Router LLM 调用无外层超时保护

**现象**：Router LLM 调用（结构化输出或 free-form）可能因 DashScope API 响应缓慢而无限挂起。

**修复**（`router_agent.py`）：
- 结构化输出和 free-form 两个 LLM 调用路径均加 `asyncio.wait_for(timeout=30)`
- 结构化输出超时自动降级到 free-form
- free-form 也超时则返回友好提示并终止

### 问题 4.4：`threading.Lock` 嵌套调用导致 Router 死锁（核心根因）

**现象**：复合意图进入 LLM 路径后，`_get_structured_router()` 调用处事件循环永久阻塞。后端日志在 `快速路由: 检测到复合意图` 之后无任何 LLM 结果日志，前端最终显示超时/终止。

**根因**：
- `_get_structured_router()` 持有 `threading.Lock` 的同时调用 `_get_router_llm()`
- `_get_router_llm()` 也试图获取**同一把 `threading.Lock`**
- `threading.Lock` 是非重入锁 → 同一线程第二次 `acquire()` 永久阻塞 → **死锁**
- asyncio 事件循环运行在单线程上，一旦死锁，整个服务器冻结

**修复**（`router_agent.py`）：
- `threading.Lock()` → `threading.RLock()`（重入锁，允许同线程多次获取）
- 抽取 `_ensure_base_llm()` 内部函数，`_get_structured_router()` 直接调用它而非嵌套调用 `_get_router_llm()`
- 在 LLM 调用前后增加详细 INFO 日志，确保执行链路完全可追踪
