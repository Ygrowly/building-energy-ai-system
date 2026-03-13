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
```