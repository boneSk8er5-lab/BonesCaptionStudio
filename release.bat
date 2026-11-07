@echo off
title Bones Caption Studio - Make Release
cd /d "%~dp0"
python release.py build all
echo.
pause
