@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "APP_DIR=%ROOT_DIR%flyers_video_tool"
set "VENV_DIR=%APP_DIR%\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "PIP_EXE=%VENV_DIR%\Scripts\pip.exe"
set "STREAMLIT_EXE=%VENV_DIR%\Scripts\streamlit.exe"

title Flyers Video Tool

if not exist "%APP_DIR%\app.py" (
  echo Cannot find app.py in "%APP_DIR%".
  echo Make sure this launcher stays next to the flyers_video_tool folder.
  pause
  exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found in PATH.
  echo Install Python 3.10+ and tick "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist "%PYTHON_EXE%" (
  echo Creating local virtual environment...
  python -m venv "%VENV_DIR%"
  if errorlevel 1 (
    echo Failed to create virtual environment.
    pause
    exit /b 1
  )
)

echo Installing/updating Python dependencies...
"%PIP_EXE%" install -r "%APP_DIR%\requirements.txt"
if errorlevel 1 (
  echo Failed to install dependencies.
  pause
  exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo.
  echo WARNING: FFmpeg was not found in PATH.
  echo The app can open, but video/audio processing may fail until FFmpeg is installed.
  echo See flyers_video_tool\README.md for FFmpeg installation instructions.
  echo.
)

echo Starting Flyers Video Tool...
cd /d "%APP_DIR%"
"%STREAMLIT_EXE%" run app.py

pause
