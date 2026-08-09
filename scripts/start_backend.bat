@echo off
rem 启动后端服务（生产模式，含前端静态托管；需在仓库根目录存在 .env）
cd /d %~dp0\..\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
