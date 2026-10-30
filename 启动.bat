@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PATH=%~dp0tools\node\node-v20.18.0-win-x64;%~dp0tools\ffmpeg\bin;%PATH%"
python 快速启动.py
pause
