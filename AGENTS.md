# Repository Guidelines

## 项目结构与模块组织
本仓库由三个应用和配套数据、文档组成：

- `backend/`：FastAPI 后端、LangGraph 工作流、MCP 工具、SQLAlchemy 模型、迁移脚本和 pytest 测试。
- `frontend/`：Vue 3 + Vite Web 端。页面位于 `src/views`，通用组件位于 `src/components`，状态管理位于 `src/stores`，接口封装位于 `src/api`。
- `mobile/`：Uni-app 移动端。页面位于 `src/pages`，公共组件位于 `src/components`，静态资源位于 `static/`。
- `dataset/` 与 `data/`：仿真代码、原始数据、Notebook 和 CSV 资源。
- `docs/`：架构、数据库、UI 和开发流程文档。

## 构建、测试与开发命令
- `cd backend && pip install -r requirements.txt`：安装后端依赖。
- `cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 8000`：本地启动 API。
- `cd backend && pytest`：运行后端测试。
- `cd backend && pytest -m "not integration and not e2e"`：运行默认快速测试集。
- `cd frontend && pnpm install && pnpm dev`：启动 Web 开发环境。
- `cd frontend && pnpm build`：执行类型检查并构建 Web 端。
- `cd mobile && pnpm install && pnpm dev:h5`：以 H5 模式启动移动端。
- `docker compose up -d`：仅启动本地 Redis；Postgres 和 RAGFlow 需要单独配置。

## 代码风格与命名约定
Python 使用 4 空格缩进、`snake_case` 模块名，并优先为服务层和辅助函数补充类型标注。Vue 和 TypeScript 使用 2 空格缩进；组件文件使用 PascalCase，例如 `Dashboard.vue`；store 和工具文件使用 camelCase，例如 `authStore.ts`、`homeCharts.ts`。新增 API 路由请放在 `backend/app/api/routes_*.py`，新增测试应尽量靠近对应后端功能。

## 测试规范
自动化测试以 `backend/tests/` 为主，文件命名采用 `test_*.py`，如 `test_api.py`、`test_forecast.py`。真实数据库相关测试使用 `@pytest.mark.integration`，完整 RAG 流程测试使用 `@pytest.mark.e2e`，并要求设置 `RAG_E2E_RUN=1`。涉及前端或移动端改动时，至少确保各自目录下的 `pnpm build` 可以通过。

## 提交与 Pull Request 规范
最近提交记录以简短祈使句为主，常见前缀包括 `feat:` 和 `fix:`。提交应尽量按应用或功能边界拆分，避免混入无关修改。PR 需要说明用户可见行为变化、列出配置或表结构变更、关联任务或问题；若修改了 `frontend/` 或 `mobile/` 界面，请附截图。依赖 `.env`、迁移脚本或外部服务的改动，必须在 PR 描述中明确说明。

## 配置提示
后端配置从 `backend/.env` 加载。运行集成测试或 e2e 测试前，先确认 `DATABASE_URL`、`REDIS_URL`、JWT 配置以及 LLM / RAGFlow 相关密钥已正确设置。
