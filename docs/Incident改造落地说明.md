# Incident 改造落地说明

本文档说明本次 `incident` 改造为什么要做、已经改了什么、还需要在环境里执行什么，以及上线后应该怎么验收。

---

## 1. 现有问题

在本次改造之前，系统的主链路是：

```text
anomaly_events / predicted_anomaly_events
    -> auto_create_*_orders()
    -> 每条异常点直接创建一张 work_order
    -> AI 审批
    -> 派单 / 处理 / 关闭
```

这个设计在数据量小时还能工作，但一旦异常是连续发生的，就会出现下面几个问题。

### 1.1 连续异常会产生大量重复工单

例如同一栋楼、同一设备、同一规则在 `07:00 / 08:00 / 09:00` 连续异常，旧逻辑会直接生成 3 张工单。  
这会导致：

- `已派单` 数量虚高
- 管理员列表被相似卡片刷屏
- 维修人员收到多张内容几乎一样的任务
- AI 审批次数被放大，浪费算力和时间

### 1.2 前端看到的是“异常碎片”，不是“一个持续中的问题”

用户真正关心的是：

- 哪栋楼出了什么问题
- 问题从什么时候开始
- 最近一次异常是什么时候
- 已经持续了多久
- 当前谁在处理
- 处理到了哪一步

旧模型直接把小时级异常点展示成工单，前端自然只能看到一串零散记录，而不是一个完整事件。

### 1.3 `work_orders` 承担了过多职责

旧模型里 `work_orders` 同时承担了：

- 异常的载体
- AI 审批对象
- 派工对象
- 维修反馈对象
- 列表展示对象

这会让工单语义越来越重，也会让状态机越来越别扭。  
一旦后续出现“持续异常”“误报后复发”“重新派工”“预测预警合并”这种需求，所有逻辑都会被迫继续堆在工单表上。

### 1.4 查询性能和展示口径会越来越差

如果前端想展示：

- 连续次数
- 首次发现时间
- 最近异常时间
- 峰值偏差
- 当前工单状态

旧模型只能靠运行时动态聚合 `work_order_anomaly_links` 或重复扫历史工单来算，查询会越来越重，缓存也更难设计。

---

## 2. 为什么要引入 Incident 层

这次改造的核心思想是把“异常事实”和“可管理的问题对象”拆开。

### 2.1 异常点是事实，incident 才是用户真正关心的问题

- `anomaly_events` / `predicted_anomaly_events` 继续保存原始事实
- `anomaly_incidents` 负责把连续异常聚合成一个持续问题
- `work_orders` 负责处理这个问题的一次执行动作

这样一来：

- 原始数据不丢
- 列表展示变成“问题列表”
- 工单重新回到“执行单”的角色

### 2.2 为什么不是只做“工单并单”

只在 `work_orders` 上做并单，能缓解数量问题，但治标不治本。  
因为工单仍然同时承担“问题实体”和“执行实体”两种职责，后续还会继续膨胀。

引入 incident 层之后，职责分工会清楚很多：

- `anomaly_*` 负责原始异常
- `incident` 负责持续问题聚合
- `work_order` 负责审批、派单、反馈、关闭

这也是这次修改的根本原因。

---

## 3. 本次代码改了什么

### 3.1 新增 incident 数据模型

新增了以下表结构映射：

- `anomaly_incidents`
- `incident_event_links`
- `incident_prediction_links`

对应文件：

- `backend/app/db/models.py`
- `backend/migrations/016_incidents_layer.sql`

这样做的原因是：

- 把连续异常聚合成一个独立主实体
- 保留 incident 与原始证据之间的时间线关系
- 支持告警异常和预测预警都挂在 incident 下

### 3.2 自动建单改为“先找 incident，再决定是否新建工单”

告警链路和预测链路都已经接入 incident 服务：

- `backend/app/services/incident_service.py`
- `backend/app/services/auto_work_order_service.py`

现在处理流程变成：

```text
新异常进入
    -> 计算 merge_key
    -> 查找可合并 incident
    -> 命中则追加证据
    -> 未命中则新建 incident + 当前工单
```

这样改的原因是：

- 避免连续异常不断新建工单
- 将“一个持续问题”的所有证据集中到一个 incident 下
- 前端可以直接读取聚合后的摘要字段

### 3.3 引入连续性窗口

当前连续性窗口规则：

- 一般告警：`6 小时`
- HVAC 且根因明确：`24 小时`
- 预测预警：高风险 `12 小时`，其他 `6 小时`

这样设计的原因是：

- 连续异常应该视为同一个问题
- 但隔了较久再次出现，通常应该视为新的 incident
- 不同异常类型的持续性特征不同，不能全都用一个固定窗口

### 3.4 允许把历史旧工单挂回 incident

在 `incident_service.py` 里，如果某条异常早年已经创建过旧工单，但还没有 incident 归属，系统会优先把旧工单挂到新 incident 上，而不是重复再造一张新工单。

这样做的原因是：

- 兼容历史数据
- 减少迁移时重复工单继续膨胀
- 让旧数据也能逐步纳入新视图

### 3.5 新增 incident API

新增接口：

- `GET /api/incidents`
- `GET /api/incidents/{incident_identifier}`

对应文件：

- `backend/app/api/routes_incidents.py`
- `backend/main.py`

这样做的原因是：

- 前端主列表不应该再直接读 `work_orders`
- incident 列表天然更符合用户认知
- 详情页可以直接展示证据时间线和工单历史

### 3.6 移动端已切到 incident 视图

已切换页面：

- 运维端工单审阅
- 维修端待处理
- 维修端进行中
- 维修端历史记录
- 维修详情页

对应文件：

- `mobile/src/api/incident.ts`
- `mobile/src/components/IncidentReviewCard.vue`
- `mobile/src/pages/operator/workorders/index.vue`
- `mobile/src/pages/worker/pending/index.vue`
- `mobile/src/pages/worker/active/index.vue`
- `mobile/src/pages/worker/history/index.vue`
- `mobile/src/pages/worker/workorder-detail/index.vue`

这样改的原因是：

- 列表改看“问题”
- 详情改看“问题 + 当前工单 + 证据时间线”
- 减少重复卡片造成的阅读负担

### 3.7 缓存失效已扩展到 incident 维度

相关文件：

- `backend/app/api/routes_workorder.py`

之前只有工单缓存失效，现在 incident 列表和详情缓存也会一起清理。  
这样做的原因是：

- 事件和工单状态现在是联动的
- 只清工单缓存会导致 incident 页读到旧数据

### 3.8 新增 incident 回填入口

管理员接口：

- `POST /api/admin/rebuild-incidents`

这次又补充了两点：

- 支持只回填单栋楼
- 支持同时回填 `alerts` 和 `predictions`
- 支持回填后直接对未审工单触发 AI 审批

这样做的原因是：

- 迁移期间需要渐进式回填
- 有时候只想针对某栋楼做验证
- 预测预警也应该纳入 incident，而不是只回填告警

### 3.9 新增迁移执行脚本

新增脚本：

- `backend/scripts/run_migration_016.py`

这样做的原因是：

- 仓库已有 `014/015` 这种按 SQL 文件执行的脚本风格
- `016` 含有 `DO $$ ... $$` 语句，普通按分号切分容易执行失败
- 新脚本对 PostgreSQL 的 dollar-quoted block 做了兼容处理

---

## 4. 当前已经解决了什么

到目前为止，代码层已经解决了这些问题：

- 新产生的连续告警不会再按每小时无限生成独立工单
- 预测预警也可以聚合到 incident
- 前端主列表已经从工单视角切到 incident 视角
- 详情页可以展示 incident 级摘要和证据时间线
- 历史旧工单可以被纳入 incident 归属
- incident 与 work_order 的状态同步已经打通

---

## 5. 还需要你在环境里执行什么

代码改好并不等于环境已经启用，这里还有两步必须执行。

### 5.1 执行数据库迁移

在 `backend` 目录执行：

```bash
python scripts/run_migration_016.py
```

作用：

- 创建 incident 主表和证据关联表
- 给 `work_orders` 增加 `incident_id`
- 建立 incident 与工单之间的关联约束和索引

### 5.2 回填历史 incident

如果要全量回填：

```http
POST /api/admin/rebuild-incidents
Content-Type: application/json

{
  "include_alerts": true,
  "include_predictions": true,
  "trigger_ai_review": false
}
```

如果只想验证某一栋楼：

```http
POST /api/admin/rebuild-incidents
Content-Type: application/json

{
  "building_id": "Fox_public_Henry",
  "include_alerts": true,
  "include_predictions": true,
  "trigger_ai_review": false
}
```

如果希望回填后直接把新增的 `pending_review` 工单送去 AI 审批：

```http
POST /api/admin/rebuild-incidents
Content-Type: application/json

{
  "include_alerts": true,
  "include_predictions": true,
  "trigger_ai_review": true
}
```

这样做的原因是：

- 迁移只建表，不会自动生成 incident 数据
- 只有回填后，前端 incident 列表才能完整看到历史问题

---

## 6. 建议的上线顺序

建议按下面顺序执行：

1. 在测试环境执行 `python scripts/run_migration_016.py`
2. 对单栋楼调用 `/api/admin/rebuild-incidents` 做小范围验证
3. 检查 incident 列表数量、连续次数、摘要文本、证据时间线是否合理
4. 验证管理员审批、维修反馈、关闭工单后 incident 状态是否同步更新
5. 再对全部楼宇执行全量回填
6. 最后切生产环境

这样安排的原因是：

- incident 回填会影响很多历史数据的展示口径
- 先做单楼验证，最容易定位问题
- 全量回填前先确认前端与后端都符合预期

---

## 7. 上线后重点验收什么

建议重点看下面几项：

### 7.1 数量口径是否变合理

重点检查：

- 运维端 `已派单` 是否明显下降
- 同楼同设备的连续异常是否被折叠为单个 incident
- `anomaly_count` 是否符合时间线数量

### 7.2 详情页是否能看懂“一个问题的全过程”

重点检查：

- `first_seen_at` 和 `last_seen_at` 是否正确
- `summary_text` 是否能准确表达问题
- 证据时间线是否完整
- 当前工单与历史工单记录是否一致

### 7.3 状态同步是否正确

重点检查：

- 工单 AI 审批后，incident 的 `workflow_status` 是否同步
- 维修提交 `fixed / false_alarm / escalated` 后 incident 状态是否同步
- 关闭工单后 incident 是否进入非活跃状态

---

## 8. 当前仍然不是最终形态的地方

这次已经把主链路打通了，但还不是设计文档里的终极版本。

暂未落地的内容包括：

- 独立的 `incident_work_order_links` 关联表
- 专门的 incident 读模型表或物化视图
- 更细粒度的 incident 状态历史表
- 更复杂的事件复发 / reopen 策略

没有优先做这些，是因为当前目标是先把主链路跑起来，先解决“重复工单”和“前端刷屏”这两个最痛的问题。

---

## 9. 总结

本次改造的本质，不是简单地“减少几张工单”，而是把系统从“按异常点驱动工单”升级成“按 incident 驱动问题管理”。

这样改的根本原因是：

- 原始异常点太细，不适合作为用户主视图
- 工单不应该承担问题实体的全部职责
- 用户需要看到的是一个持续中的问题，而不是很多小时级碎片

因此，这次修改既是性能优化，也是建模纠偏和用户体验修复。
