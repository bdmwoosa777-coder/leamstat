@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 -X utf8 "%~dp0gamepad_buttons_test.py"
goto done
:use_python
python -X utf8 "%~dp0gamepad_buttons_test.py"
:done
if errorlevel 1 echo Test failed. Copy the error text for diagnosis.
pause
