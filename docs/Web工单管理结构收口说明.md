# Web 工单管理结构收口说明

## 目标

本次结构收口只调整代码边界，不改变用户看到的页面。

保持不变：

- 左侧导航仍然只有 `工单管理` 入口。
- 顶部胶囊切换仍然是 `总览 / 工单审阅 / 派工中心 / 执行跟踪`。
- 原有 tab、按钮、卡片、派工面板、批量派工面板位置不变。
- 不新增前端页面视觉，不调整布局。

## 当前组件边界

- `WorkOrders.vue`：页面编排层，负责数据、动作、路由模式和子组件组合。
- `WorkOrdersShell.vue`：公共页面壳，负责标题、胶囊切换、toolbar、汇总条、loading/error/empty。
- `WorkOrdersWorkspacePane.vue`：按当前胶囊模式分发到具体语义 pane。
- `WorkOrdersOverviewPane.vue`：总览模式，目前允许展示工单大厅或工单列表。
- `WorkOrdersDispatchPane.vue`：派工中心模式，目前允许展示工单大厅或工单列表。
- `WorkOrdersReviewPane.vue`：工单审阅模式，只承接工单列表。
- `WorkOrdersTrackingPane.vue`：执行跟踪模式，只承接工单列表。
- `WorkOrdersMainPane.vue`：大厅/工单列表通用主内容，适合总览和派工中心。
- `WorkOrdersOrderOnlyPane.vue`：只展示工单列表，适合工单审阅和执行跟踪。
- `WorkOrdersOverlayPane.vue`：派工面板和批量派工面板。

## 设计约束

后续继续拆分时仍应遵守：

- 不为了拆组件改变页面交互。
- 不把左侧导航拆成多个入口，除非产品上明确要求。
- 审阅、派工、跟踪可以逐步拥有自己的 pane，但共享 composable 仍应复用。
- 批量派工、工单大厅申请、派工/改派面板继续复用现有组件，避免复制业务逻辑。

## 后续可选收口

如果后面继续做 Web 结构化，可以考虑：

- 让 `WorkOrdersReviewPane` 承接更明确的 AI 审阅动作区。
- 让 `WorkOrdersDispatchPane` 承接派工中心特有的批量推荐入口和大厅事项。
- 让 `WorkOrdersTrackingPane` 承接执行中、待关闭、已关闭的跟踪摘要。

这些都应先保持视觉不变，只做内部结构拆分。

