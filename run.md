前端启动
```
cd frontend
pnpm install
pnpm run dev
```

后端启动
```
cd backend
pip install -r requirements.txt
# 若曾误装过 jwt 包，请先卸载：pip uninstall jwt，再安装 PyJWT
# 注册 500 / failed to fetch：密码哈希已改为原生 bcrypt，无需再折腾 passlib 版本
# 若日志里 buildings.meter_device_id does not exist：在库里执行 migrations/005_buildings_meter_device_id.sql
uvicorn main:app --reload --host 0.0.0.0 --port 8000

docker compose up -d --build

```

RAG 端到端测试（上传 PDF → 向量化 → 对话引用知识库）
```
# 1. 确保后端已启动；RAGFlow 已启动且 .env 中 RAGFLOW_API_URL、RAGFLOW_API_KEY、RAGFLOW_DATASET_ID 已配置
cd backend
python scripts/test_rag_e2e.py
```
- 若出现 **502 "RAGFlow 返回错误"**：先在本机跑诊断 `cd backend && python scripts/check_ragflow_connection.py`。  
  - 若在 **RAGFlow 所在电脑** 上 `curl http://127.0.0.1:9380/` 得到 404（或 200）说明本机服务正常，502 多半是「从外网/Tailscale 访问 100.114.223.54:9380」时出的问题。请在该电脑上：  
    1. **看谁在监听 9380**：`netstat -ano | findstr :9380`（Windows）或 `ss -tlnp | grep 9380`（Linux）。若只有 127.0.0.1:9380，则从 Tailscale IP 来的请求会连不上或由别的程序处理；RAGFlow 需监听 `0.0.0.0:9380` 才能被 Tailscale 访问。  
    2. **防火墙**：放行 9380（如 Windows 防火墙 → 入站规则）。  
    3. **从本机用 Tailscale IP 自测**：在 RAGFlow 机器上执行 `curl -v http://100.114.223.54:9380/`，若也 502 则说明本机通过 Tailscale 访问自己时就有问题（绑定/防火墙/代理）。
- 运行 E2E 的 pytest（需先设环境变量）：  
  - CMD: `set RAG_E2E_RUN=1 && python -m pytest tests/test_rag_e2e_real.py -v -s`  
  - PowerShell: `$env:RAG_E2E_RUN="1"; python -m pytest tests/test_rag_e2e_real.py -v -s`  
  - 注意：不要在同一行用 `#` 写注释，否则 pytest 会误把 `#` 后当路径。