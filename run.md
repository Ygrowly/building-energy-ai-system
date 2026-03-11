前端启动
```
cd frontend
pnpm install
pnpm run dev
```

后端启动
```
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000