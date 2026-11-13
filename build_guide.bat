@echo off
title Bones Caption Studio - Build the guide
rem Makes the shareable copy of the guide in the "docs" folder next to this file:
rem   docs\guide.html                       the guide as a web page (with docs\images)
rem   docs\Bones Caption Studio guide.pdf   the same guide as a PDF (made with Microsoft Edge, which comes with Windows)
rem The guide inside the app (Help > User Guide) reads the "guide" folder directly; release.bat puts the PDF in the zips.
cd /d "%~dp0"
set "DOCS=%~dp0docs"
set "PDF=%DOCS%\Bones Caption Studio guide.pdf"
set "PY=%LOCALAPPDATA%\BonesCaptionStudio\envs\cpu\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo Saving the guide as a web page...
if exist "%DOCS%\guide.html" del "%DOCS%\guide.html"
"%PY%" bones_caption_studio.py --export-guide "%DOCS%"
if not exist "%DOCS%\guide.html" (
    echo The web page wasn't made. Check debug_log.txt: Help, Open Logs and Settings Folder.
    goto failed
)

echo Making the PDF...
set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" set "EDGE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" (
    echo Microsoft Edge wasn't found, so there's no PDF. Open docs\guide.html in a browser and print it to PDF instead.
    goto done
)
if exist "%PDF%" del "%PDF%"
"%EDGE%" --headless --disable-gpu --no-pdf-header-footer --user-data-dir="%TEMP%\BCS guide pdf" --print-to-pdf="%PDF%" "%DOCS%\guide.html"
if not exist "%PDF%" (
    echo The PDF wasn't made. Open docs\guide.html in a browser and print it to PDF instead.
    goto done
)

:done
echo.
echo Done: %DOCS%
pause
exit /b 0

:failed
echo.
pause
exit /b 1
