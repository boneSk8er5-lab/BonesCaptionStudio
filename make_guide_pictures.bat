@echo off
title Bones Caption Studio - Guide pictures
rem Takes the pictures for the guide (guide\images\*.png) from the app's real window, drawn off-screen with a
rem made-up demo video and transcript, so the guide never shows your own videos, words or settings.
rem Run it after changing how the window looks, then run build_guide.bat.
cd /d "%~dp0"
set "PY=%LOCALAPPDATA%\BonesCaptionStudio\envs\cpu\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo Taking the guide's pictures...
"%PY%" tools\guide_pictures\make_guide_pictures.py
if errorlevel 1 goto failed

echo.
echo Done. Run build_guide.bat to make the web page and PDF.
pause
exit /b 0

:failed
echo.
echo Taking the pictures failed. Copy the red errors above and send them to Claude.
pause
exit /b 1
