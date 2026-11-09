@echo off
chcp 65001 >nul
cd /d "%~dp0"
title DouYinLiveTool CLI

set "PYEXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYEXE%" set "PYEXE=%~dp0..\DouyinBarrage\.venv\Scripts\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

set "PATH=%~dp0tools\node\node-v20.18.0-win-x64;%~dp0..\DouyinBarrage\tools\node\node-v20.18.0-win-x64;%~dp0tools\ffmpeg\bin;%~dp0..\DouyinBarrage\tools\ffmpeg\bin;%PATH%"

"%PYEXE%" 快速启动.py
pause
