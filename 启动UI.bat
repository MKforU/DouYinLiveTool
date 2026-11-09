@echo off
chcp 65001 >nul
cd /d "%~dp0"
title DouYinLiveTool UI

rem 1) 本目录 venv
set "PYEXE=%~dp0.venv\Scripts\python.exe"
if exist "%PYEXE%" goto :run

rem 2) 同级 DouyinBarrage 的 venv（已装依赖）
set "PYEXE=%~dp0..\DouyinBarrage\.venv\Scripts\python.exe"
if exist "%PYEXE%" goto :run

rem 3) 系统 python
set "PYEXE=python"
where python >nul 2>nul && goto :run

echo [错误] 未找到 Python。
echo.
echo 请任选其一：
echo   1^) 在本目录执行:  python -m venv .venv  然后  .venv\Scripts\pip install -r requirements.txt
echo   2^) 使用已装好依赖的 ..\DouyinBarrage\.venv
echo   3^) 安装 Python 3.10+ 并:  pip install -r requirements.txt
echo.
pause
exit /b 1

:run
echo 使用 Python: %PYEXE%
set "PATH=%~dp0tools\node\node-v20.18.0-win-x64;%~dp0..\DouyinBarrage\tools\node\node-v20.18.0-win-x64;%~dp0tools\ffmpeg\bin;%~dp0..\DouyinBarrage\tools\ffmpeg\bin;%PATH%"
"%PYEXE%" run_ui.py
if errorlevel 1 (
  echo.
  echo 启动失败，若缺依赖请执行:
  echo   pip install -r requirements.txt
  pause
)
