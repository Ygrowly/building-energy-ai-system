# 登录与首页首屏性能优化方案

## Summary
- 当前“登录很慢”主要不是 `/api/auth/login` 本身。登录接口只有用户查询 + `bcrypt` 校验，感知上的慢主要来自登录后立即进入首页并触发重型 `/api/home/bundle`。
- 当前首页 bundle 一次请求会把 3 个楼宇类型的总览、异常、额定对比、负荷画像、状态等全部算完，并反复执行 `building_type -> building_id`、`MAX(timestamp)`、小时/星期聚合，单请求查询数过多。
- 这次按你确认的方向做：首屏分阶段加载，并允许数据库索引迁移。

## Key Changes
- 认证启动链路
  - 在 `frontend/src/stores/authStore.ts` 持久化 `accessToken`、`accessTokenExpiresAt`、`user`；优先复用未过期 access token，避免每次硬刷新都先走 refresh。
  - 在 auth store 内给 `refresh()` 加单飞锁；路由守卫、401 自动续期、首屏初始化共用同一个 refresh promise，避免 token rotation 下的重复 refresh 和误跳回登录页。
  - 在 `frontend/src/main.ts` 等待 `router.isReady()` 后再挂载应用；受保护页面的初始化请求统一要求“已登录且非登录页”后才允许发送。
  - 未授权跳转统一改为 `router.replace({ name: 'Login', query: { redirect } })`，避免重复 push 和历史栈污染。

- 首页接口拆分
  - 保留现有 `/api/home/bundle` 兼容旧调用，但首页不再把它作为首屏接口。
  - 新增 `GET /api/home/overview-bundle`
    - 返回 `overview`、`anomalies`、`sankey`、`overview_series`
    - 不返回 Education / Office / Public services 的 section 级 load profile / status / peak valley
    - 服务端 TTL 60s；前端 session cache TTL 60s
  - 新增 `GET /api/home/section-bundle?building_type=...`
    - 只返回当前楼宇分区所需 payload
    - Education: load profiles + rated_vs_actual_electricity + anomalies + status
    - Office: load_profile_electricity + peak_valley + energy + anomalies
    - Public services: energy + load profiles + anomalies + rated_vs_actual_electricity + status
    - 服务端 TTL 300s；前端 session cache TTL 300s

- 首页前端加载策略
  - `frontend/src/views/Home.vue` 首屏只请求 `overview-bundle` + `predictions`。
  - 默认 `activeBuilding === 'all'` 时不请求任何 section-bundle。
  - 用户切换到某个 building tab 时按需请求该 `section-bundle`。
  - 首屏完成后用 `requestIdleCallback` 预取另外两个 section-bundle；失败不阻塞 UI。
  - skeleton 改为分块结束：总览区和分区区分别独立 loading，不再等全量 bundle 一起结束。

- 后端查询收敛
  - 在 `backend/app/api/routes_data.py` 增加 bundle 内部 building context 解析器，单次 bundle 计算只做一次 `building_type -> building_id/sqm/display_name` 映射，并把 `building_id` 直接传给下游 helper。
  - 新增多指标 load profile helper：同一 building + same days 只做 1 次 `MAX(timestamp)`、1 次 `GROUP BY hour`、1 次 `GROUP BY isodow`，一条 SQL 同时聚合多个 metric，替代现在“每个 metric 两条聚合 SQL”。
  - `get_recent_anomalies`、`get_building_status`、`get_peak_valley_stats`、`get_rated_vs_actual` 增加可选 `building_id` 参数；已拿到 building_id 时禁止再次查 `buildings` 表。
  - `overview-bundle` 只组装首屏需要的数据，不再夹带 section 级重查询。

- 数据库变更
  - 新增兼容 migration，使用 `IF NOT EXISTS` 创建：
    - `idx_energy_data_building_timestamp_desc ON energy_data (building_id, "timestamp" DESC)`
    - `idx_devices_building_type ON devices (building_id, device_type)`
  - 交付前对最新值查询、load-profile 聚合、peak-valley 聚合跑 `EXPLAIN ANALYZE`，确认走索引且没有回退到全表排序。

## Test Plan
- 登录后进入 `/home`，只发生 1 次 `/api/auth/login`，不因首页初始化再触发额外 refresh。
- 已登录状态硬刷新受保护路由：
  - access token 未过期时不调用 `/api/auth/refresh`
  - access token 过期但 refresh token 有效时只调用 1 次 `/api/auth/refresh`
  - 页面不应偶发跳回登录页
- 首页默认 `all` tab 只请求 `overview-bundle` + `predictions`；不请求 section-bundle。
- 切到 Education / Office / Public services 时只请求对应一个 `section-bundle`，二次进入命中 session cache。
- 后端日志里 `SELECT buildings.building_id FROM buildings WHERE primary_space_usage = ...` 的重复次数明显下降。
- `/api/home/overview-bundle` 冷启动耗时显著低于当前 `/api/home/bundle`，首屏从当前几十秒级压到可接受秒级。

## Assumptions
- 不改页面展示内容，只改加载顺序、缓存策略和接口拆分。
- 现有 `/api/home/bundle` 先保留，避免其它调用方被破坏；首页只切新接口。
- 这次优先解决“登录后慢”和“首页首屏慢”，预测页等其它重接口只做必要兼容，不做额外重构。
