@echo off
title Bones Caption Studio - Set Up Build Tools (one time)
cd /d "%~dp0"
echo This creates two private Python environments for building Bones Caption Studio:
echo   CPU edition  (~1 GB)   and   GPU / NVIDIA edition  (~5 GB)
echo They live in %LOCALAPPDATA%\BonesCaptionStudio\envs - your normal Python is NOT changed.
echo.
python release.py setup all
echo.
pause
