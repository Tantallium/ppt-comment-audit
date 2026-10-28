@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -X utf8 "%~dp0ppt_audit.py"
) else (
  python -X utf8 "%~dp0ppt_audit.py"
)
if errorlevel 1 (
  echo 启动失败。请安装 Python 3.10 或更高版本，并执行 python -m pip install -r requirements-ui.txt。
  pause
)
