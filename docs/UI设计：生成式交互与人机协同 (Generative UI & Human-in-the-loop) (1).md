# 【文档 4】UI设计：生成式交互与人机协同 (Generative UI & Human-in-the-loop)
**核心理念升级：**  
界面不是静态的 HTML，而是随着对话动态“生长”出来的。AI 不仅能输出文字，还能在对话流中直接**渲染图表、高亮异常设备、弹出审批卡片**。更重要的是，我们要通过 **“信任可视化”** 让用户敢用 AI。

## 1. 整体布局架构：三栏式“沉浸指挥舱”设计
不要做成传统的后台管理系统，要做成类似 **Cursor IDE** 或 **Claude Artifacts** 的沉浸式分析工作台。

+ **左侧：导航与资源栏 (The Context) —— [宽 15%]** (全局菜单、当前选中的设备树)
+ **中间：动态主工作区 (The Canvas) —— [宽 55%]**
    - **逻辑**：这里是“真相展示区”。当右侧 AI 说话时，这里会**自动跳转**到相关页面，并**高亮** AI 提到的数据（如：自动缩放折线图到凌晨 3 点）。
+ **右侧：多智能体协作控制台 (The Agent Console) —— [宽 30%]**
    - **核心组件（新增）**：
        1. **思维链展示区 (Thinking Stream)**：显示 `Router -> Data -> Diagnose` 的流转状态。
        2. **生成式组件区 (Artifacts)**：AI 生成的图表、工单卡片作为独立卡片浮动在消息流中。

---

## 2. 核心页面交互设计 (融入“进阶特性”)
### 页面 1：【驾驶舱 / 首页】(Dashboard) —— “叙事性报表”
+ **功能**：全局 KPI 卡片与 3D 建筑模型。
+ **进阶交互 (Proactive UI)**：
    - **场景**：用户早上首次登录。
    - **AI 主动行为**：右侧 Console 自动弹出一条 Toast：“早上好！昨晚办公楼能耗异常，系统记录为 Anomaly。”
    - **联动**：用户点击 Toast，中间的 3D 模型自动旋转并**红色高亮**办公楼，弹出异常详情悬浮窗。

### 页面 2：【能源透视 / 查询统计】(Analysis) —— “生成式图表”
+ **功能**：给分析师用的，替代传统的 Excel 拖拽分析。
+ **进阶交互 (Generative Charting)**：
    - **场景**：用户在右侧输入：“对比一下教学楼和办公楼最近一周的每日总电耗。”
    - **AI 响应 (Generative UI)**：
        1. **Thinking**：`Data Agent 识别到“每日总电耗”意图 -> 直接命中连续聚合视图 daily_energy_summary -> 生成极速 SQL -> 获取数据`。
        2. **Rendering**：AI 控制中间 Canvas 瞬间渲染出 ECharts 柱状对比图。
        3. **Traceability (杀手锏)**：图表下方有一个小按钮 **[ ****🔍**** 数据来源与性能分析 ]**。点击后弹出审计浮层：
            + <font style="color:rgb(43, 45, 49);">数据路由: Data Agent -> 精准命中预计算层</font>
            + <font style="color:rgb(43, 45, 49);">数据来源: daily_energy_summary (PostgreSQL 物化视图)</font>
            + <font style="color:rgb(43, 45, 49);">查询耗时: 15ms (以此向评委展示：即使在原生 PG 环境下，也实现了极致的预聚合性能)。</font>

### 页面 3：【智慧运维 / 故障诊断】(Operations) —— “可解释性诊断”
+ **进阶交互 (Trust Visualization)**：
    - **场景**：AI 给出结论“定时策略失效”。
    - **交互**：用户点击结论旁边的 **[ ****🛡️**** 审计盾牌 ]** 图标。
    - **效果**：侧边栏滑出 **“思维透视面板”**，展示：
        1. **原始数据**：展示 `energy_data` 提取的 `occupancy_density_per_100sqm=0` 数据快照。
        2. **参考依据**：高亮显示《运维手册》原文截图。
        3. **置信度**：显示 AI 逻辑判断置信度 92%。
    - **人机协同 (Human-in-the-loop)**：AI 在对话流中渲染一个 **【维修工单卡片】**，状态为 `待审批` (黄色)。用户点击 **[ ****✅**** 批准 ]** 后，卡片变绿。

### 页面 4：【数据中心 / 配置】(Data Management) —— “数据血缘视图”
+ **可视化**：展示数据流向：`原始传感器 CSV` -> `energy_data 时序表` -> `daily_energy_summary 聚合视图` -> `AI 分析结论`。

---

## 3. 三个“加分”的 UI 微交互设计 (Micro-Interactions)
1. **流式渲染与防抖 (Streaming & Stability)**：
    - **骨架屏预判 (Optimistic UI)**：当后端返回 `type: chart` 但数据还在传输时，前端立即渲染灰色的图表骨架（Skeleton），防止页面高度跳动。
    - **Shadow JSON Parsing**：使用流式解析器处理未闭合的 JSON，确保图表是“平滑生长”出来的。
2. **多智能体状态可视化 (Agent Presence)**：
    - 显示当前工作的 Agent 头像和状态。如：`🕵️‍♂️ Data Agent 正在查询连续聚合视图...` -> `👨‍⚕️ Diagnose Agent 正在过滤设备手册...`。
3. **引用锚点 (Citation Anchors)**：
    - AI 回复涉及具体数据，必须标 `[1]`。鼠标悬停显示：`Source: Meter #M-OFF-001 @ 2023-10-25 03:00 UTC`。

---

## <font style="color:rgb(43, 45, 49);">4. 总结：你的设计口号 (Design Philosophy)</font>
<font style="color:rgb(43, 45, 49);">在答辩 PPT 的最后一页，请用这句话总结你的 UI 设计：</font>

**<font style="color:rgb(43, 45, 49);">“我们不仅仅是把 Chatbot 塞进网页，而是重构了人机协作的范式。</font>**

**<font style="color:rgb(43, 45, 49);">通过 Generative UI 技术，我们让 GUI 具备了 LUI 的灵活性；通过可视化的思维链与审计面板，我们构建了从底层预计算视图到上层决策逻辑的全链路可信溯源，彻底解决了大模型落地的‘黑盒’难题。”</font>**

