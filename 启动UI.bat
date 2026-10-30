@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 抖音直播助手
set "PATH=%~dp0tools\node\node-v20.18.0-win-x64;%~dp0tools\ffmpeg\bin;%PATH%"

set "PYEXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

echo 启动抖音直播助手 UI...
"%PYEXE%" run_ui.py
pause
