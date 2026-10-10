@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

echo ========================================
echo   洛克王国智能助手
echo   前端 http://127.0.0.1:5173
echo   接口 http://127.0.0.1:8000
echo ========================================
echo.

cd /d "%~dp0"

if not exist .venv\Scripts\activate.bat (
    echo 错误：未找到虚拟环境
    echo 请先运行以下命令创建虚拟环境：
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo 正在启动 API 服务...
echo API服务将初始化知识库（包括OCR处理）
start "Policy QA API" cmd /c "set HF_HUB_OFFLINE=1&& set TRANSFORMERS_OFFLINE=1&& set PYTHONIOENCODING=utf-8&& python -u api.py & pause"
timeout /t 5 /nobreak >nul

echo 正在启动对话界面...
echo 正式入口是 React 页面，不再打开 Gradio。
echo 浏览器访问：http://127.0.0.1:5173
echo.

cd web
if not exist node_modules (
    echo 正在安装前端依赖...
    npm install
)
npm run dev

pause