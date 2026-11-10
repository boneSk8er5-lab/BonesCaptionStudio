@echo off
title Bones Caption Studio - Make FINAL Release
cd /d "%~dp0"
echo This builds the FINAL public release (no beta number):
echo portable zips + installers for the CPU and GPU editions.
echo Installers need the free Inno Setup 6: https://jrsoftware.org/isdl.php
echo.
pause
python release.py build all final
echo.
pause
