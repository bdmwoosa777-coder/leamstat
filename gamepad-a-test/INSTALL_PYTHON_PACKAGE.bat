@echo off
setlocal
cd /d "%~dp0"
echo This installs the Python package only, NOT the ViGEmBus driver.
echo Install ViGEmBus separately from the official link in README_RU.txt.
set "VGAMEPAD_SKIP_VIGEMBUS_INSTALL=true"
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 -m pip install -r "%~dp0requirements.txt"
goto done
:use_python
python -m pip install -r "%~dp0requirements.txt"
:done
if errorlevel 1 echo Installation failed. Copy the error text for diagnosis.
pause
