@echo off
REM =================================================================
REM == SRT Translator - One-Click Launcher ==
REM == 双击此脚本以同时启动后端和前端服务 ==
REM =================================================================

REM 设置当前窗口的标题
title SRT Translator Launcher

echo.
echo =============================================
echo   SRT 翻译器 正在启动中...
echo =============================================
echo.
echo 即将打开两个新的命令窗口，请勿关闭它们。
echo.

REM --- 启动 FastAPI 后端服务 ---
REM 使用 start 命令在新窗口中运行 uvicorn
REM cmd /k 会保持新窗口在命令执行后不自动关闭，方便查看日志
echo [1/2] 正在启动 FastAPI 后端服务...
start "SRT_Backend" cmd /k uvicorn main:app --host "0.0.0.0" --port 8000

REM --- 等待几秒钟，确保后端服务有足够的时间初始化 ---
echo.
echo 等待 3 秒钟以确保后端稳定...
timeout /t 3 /nobreak >nul

REM --- 启动 Streamlit 前端服务 ---
REM 同样，在新窗口中启动 Streamlit
echo [2/2] 正在启动 Streamlit 前端界面...
start "SRT_Frontend" cmd /k streamlit run webui.py

echo.
echo =============================================
echo   所有服务已启动！
echo =============================================
echo.
echo - 后端服务运行在 "SRT_Backend" 窗口中。
echo - 前端界面运行在 "SRT_Frontend" 窗口中。
echo - 您的浏览器应该会自动打开应用页面。
echo.
echo 您现在可以关闭这个启动器窗口了。
echo.

REM 暂停一下，让用户可以看到上面的信息
pause
