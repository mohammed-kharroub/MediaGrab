@echo off
title MediaGrab - Installer
cd /d "%~dp0"
echo.
echo  ===============================================
echo     MediaGrab installer
echo     This builds the app and puts an icon on
echo     your Desktop. It takes 2-5 minutes.
echo  ===============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo  [!] Python is not installed.
    echo      1. Go to https://www.python.org/downloads/
    echo      2. Install it and TICK "Add python.exe to PATH"
    echo      3. Run this INSTALL.bat again
    echo.
    start https://www.python.org/downloads/
    pause
    exit /b
)

echo  [1/3] Installing components...
python -m pip install --upgrade --quiet pip
python -m pip install --upgrade --quiet yt-dlp imageio-ffmpeg customtkinter pillow pyinstaller
if errorlevel 1 (
    echo  [!] Could not install components. Check your internet and try again.
    pause
    exit /b
)

echo  [2/3] Building MediaGrab.exe ...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name MediaGrab --icon icon.ico --add-data "icon.ico;." ^
  --collect-all customtkinter --collect-all imageio_ffmpeg --collect-all yt_dlp ^
  MediaGrab.py >build.log 2>&1
if not exist "dist\MediaGrab.exe" (
    echo  [!] Build failed. See build.log for details.
    pause
    exit /b
)

echo  [3/3] Installing app and creating Desktop shortcut...
set "APPDIR=%LOCALAPPDATA%\MediaGrab"
if not exist "%APPDIR%" mkdir "%APPDIR%"
copy /y "dist\MediaGrab.exe" "%APPDIR%\MediaGrab.exe" >nul
copy /y "icon.ico" "%APPDIR%\icon.ico" >nul

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s=(New-Object -ComObject WScript.Shell);" ^
  "$d=[Environment]::GetFolderPath('Desktop');" ^
  "$l=$s.CreateShortcut((Join-Path $d 'MediaGrab.lnk'));" ^
  "$l.TargetPath='%APPDIR%\MediaGrab.exe';$l.IconLocation='%APPDIR%\icon.ico';$l.WorkingDirectory='%APPDIR%';$l.Save();" ^
  "$p=Join-Path ([Environment]::GetFolderPath('Programs')) 'MediaGrab.lnk';" ^
  "$m=$s.CreateShortcut($p);$m.TargetPath='%APPDIR%\MediaGrab.exe';$m.IconLocation='%APPDIR%\icon.ico';$m.Save()"

rmdir /s /q build >nul 2>nul
del /q MediaGrab.spec >nul 2>nul

echo.
echo  Done! MediaGrab is on your Desktop and in the Start menu.
echo  (To update when a site stops working, just run INSTALL.bat again.)
echo.
start "" "%APPDIR%\MediaGrab.exe"
pause
