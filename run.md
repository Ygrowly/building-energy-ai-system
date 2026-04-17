# 项目运行说明

## 推荐方案

同事电脑如果访问 PyPI 经常握手失败，后端推荐使用 `conda-pack` 分发。

这套方案的核心思路是：

1. 在一台能正常联网安装依赖的机器上创建后端 `conda` 环境。
2. 用 `conda-pack` 打成一个压缩包。
3. 同事拿到压缩包后本地解压，不再访问 PyPI。
4. 直接用解压后的 Python 启动后端。

这样比直接拷整个 `.venv` 更稳，因为 `conda-pack` 会在解压后修正环境路径。

## 可以提交到 Git 的文件

- `backend/requirements.txt`
- `backend/requirements-forecast.txt`
- `backend/scripts/setup_backend_conda.ps1`
- `backend/scripts/pack_backend_conda.ps1`
- `backend/scripts/unpack_backend_conda.ps1`
- `backend/scripts/run_backend.ps1`
- 本文档 `run.md`

## 不要提交到 Git 的目录

- `backend/.conda-env/`
- `backend/.conda-packed-env/`
- `backend/.venv/`
- `backend/.venv-forecast/`
- `backend/dist/conda-pack/`

## 打包机器操作

打包机器指的是那台可以正常安装依赖的机器。

### 1. 创建后端 conda 环境

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\setup_backend_conda.ps1
```

如果还要包含预测模型依赖：

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\setup_backend_conda.ps1 -IncludeForecast
```

默认会创建：

- `backend/.conda-env`

默认 Python 版本：

- `3.11`

说明：

- 脚本内部已经处理了当前机器上常见的 conda CUDA 探测报错。
- 如果你手工执行 conda 命令，也建议先设置 `CONDA_OVERRIDE_CUDA=0`。
- 脚本默认不会升级 `pip / setuptools / wheel`，这是为了保证后续 `conda-pack` 能正常打包。

如果打包机器自己访问 `repo.anaconda.com` 也有 SSL 握手问题，可以直接克隆一套本机已有的 conda 环境，再补装项目依赖：

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\setup_backend_conda.ps1 -CloneFrom <已有conda环境名或路径> -IncludeForecast
```

要求：

- 被克隆环境最好是 Python `3.11`
- 被克隆环境越干净越好，避免把无关包一起打进压缩包

如需重建环境：

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\setup_backend_conda.ps1 -Recreate
```

### 2. 打包 conda 环境

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\pack_backend_conda.ps1
```

默认输出目录：

- `backend/dist/conda-pack/`

打包完成后会生成类似文件：

- `construction-management-backend-conda-win-py311-20260417-183000.zip`

这个压缩包通过网盘、NAS、IM 文件传输发给同事，不要放 Git。

## 同事电脑操作

### 1. 拉代码

```powershell
git clone <仓库地址>
cd construction-management\backend
```

### 2. 把压缩包放到 backend 目录

推荐放到：

- `backend/dist/conda-pack/`

### 3. 解压已打包环境

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\unpack_backend_conda.ps1
```

默认会解压到：

- `backend/.conda-packed-env`

如果要覆盖已存在目录：

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\unpack_backend_conda.ps1 -Force
```

也可以显式指定压缩包路径：

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\unpack_backend_conda.ps1 -Archive "D:\share\cm-backend.zip"
```

### 4. 启动后端

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\run_backend.ps1
```

`run_backend.ps1` 会按顺序自动查找：

1. `backend/.conda-packed-env`
2. `backend/.conda-env`
3. `backend/.venv`

所以同事电脑上只要 `.conda-packed-env` 解压成功，就可以直接启动。

## 启动参数

默认启动：

- Host: `0.0.0.0`
- Port: `8000`
- 启用 `--reload`

自定义端口：

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\run_backend.ps1 -Port 18000
```

关闭热重载：

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\run_backend.ps1 -NoReload
```

如果你要手工指定环境目录：

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\run_backend.ps1 -EnvDir .conda-packed-env
```

## 手工启动

如果不想走脚本，也可以直接用解压环境里的 Python：

```powershell
cd backend
.\.conda-packed-env\python.exe -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

如果是本机直接创建的 conda 环境：

```powershell
cd backend
.\.conda-env\python.exe -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## 验证命令

### 检查 Python

```powershell
cd backend
.\.conda-packed-env\python.exe --version
```

### 健康检查

启动后访问：

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/health/db
```

### 跑默认测试

```powershell
cd backend
.\.conda-packed-env\python.exe -m pytest -m "not integration and not e2e"
```

## 兼容性说明

- `conda-pack` 压缩包不适合提交到 Git，体积太大。
- 打包环境需要与同事电脑保持同平台。
- Windows 打的包给 Windows 用；不要直接给 Linux 或 macOS。
- 如果 Python 主版本或系统架构差异太大，也不要混用。
- 解压后要先运行 `unpack_backend_conda.ps1`，不要直接跳过 `conda-unpack`。

## 备选方案

如果只是你自己本机开发，仍然可以继续使用原来的 `venv` 脚本：

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\setup_backend_venv.ps1
```

但对“同事机器无法稳定访问 PyPI”这个问题，优先还是 `conda-pack`。
