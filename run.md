# 项目运行说明

## 目标

这份说明解决的是后端 **Python 启动环境和依赖安装**，不是 `.env` 配置。

可以提交到 Git 的内容是：

- `backend/requirements.txt`
- `backend/requirements-forecast.txt`
- `backend/scripts/setup_backend_venv.ps1`
- `backend/scripts/run_backend.ps1`
- 本文档 `run.md`

不要把真实虚拟环境目录提交到 Git：

- `backend/.venv/`
- `backend/.venv-forecast/`

## 推荐做法：用脚本创建后端虚拟环境

### 1. 创建主后端环境

在仓库根目录执行：

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\setup_backend_venv.ps1
```

脚本会自动完成：

- 优先使用 `py -3.11`，没有就退回到 `python`
- 创建 `backend/.venv`
- 升级 `pip / setuptools / wheel`
- 安装 `requirements.txt` 中的后端依赖

### 2. 如需预测功能，再创建预测专用环境

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\setup_backend_venv.ps1 -IncludeForecast
```

这会额外创建：

- `backend/.venv-forecast`

并安装：

- `backend/requirements-forecast.txt`

说明：

- 主后端接口环境使用 `backend/.venv`
- 预测 worker 会优先使用 `backend/.venv-forecast`
- 如果你们当前只开发普通接口，不涉及预测模型，可以先只创建 `backend/.venv`

### 3. 启动后端

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\run_backend.ps1
```

默认启动参数：

- Host: `0.0.0.0`
- Port: `8000`
- 开启 `--reload`

自定义端口示例：

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\run_backend.ps1 -Port 18000
```

关闭热重载示例：

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\run_backend.ps1 -NoReload
```

## 手工做法：不用脚本也能创建

如果本机限制 PowerShell 脚本执行，可以直接手工执行。

### 主后端环境

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果机器上没有 `py -3.11`，可改成：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 预测专用环境

```powershell
cd backend
py -3.11 -m venv .venv-forecast
.\.venv-forecast\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv-forecast\Scripts\python.exe -m pip install -r requirements-forecast.txt
```

### 手工启动后端

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## 同事拿到代码后的最短路径

```powershell
git clone <仓库地址>
cd construction-management\backend
powershell -ExecutionPolicy Bypass -File .\scripts\setup_backend_venv.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\run_backend.ps1
```

如果需要预测能力：

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\setup_backend_venv.ps1 -IncludeForecast
```

## 启动前建议检查

确认 Python 版本：

```powershell
python --version
py -0p
```

建议优先使用 Python `3.11` 或 `3.12`。

安装完成后可检查：

```powershell
cd backend
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip list
```

## 常用验证命令

### 后端健康检查

启动后访问：

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/health/db
```

### 跑默认测试

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -m "not integration and not e2e"
```

### 启动前端

```powershell
cd frontend
pnpm install
pnpm dev
```

### 启动移动端 H5

```powershell
cd mobile
pnpm install
pnpm dev:h5
```

## 说明

- 虚拟环境目录体积大、路径强依赖本机，不能作为可复用产物上传 Git。
- 真正应该提交的是依赖清单和初始化脚本，这样同事拉代码后才能在自己的机器上重新生成可用环境。
- 如果后端依赖安装完成但接口仍然起不来，再单独检查 `backend/.env`、数据库、Redis、RAGFlow 等外部服务。
