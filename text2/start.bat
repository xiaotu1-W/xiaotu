@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

echo 正在启动 练习场 OJ，启动后浏览器打开 http://127.0.0.1:8000
echo 关闭这个窗口即可停止服务。
echo.

"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

pause
