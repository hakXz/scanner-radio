@echo off
echo Installing dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo Failed to install dependencies. Make sure Python and pip are installed.
    echo Download Python from https://www.python.org/downloads/
    pause
    exit /b 1
)
echo.
echo Done. Run run.bat to start the app.
pause
