@echo off
REM ---------------------------------------------------------------------------
REM One-click launcher for the Document Processor desktop application.
REM
REM What it does the first time it runs:
REM   1. Creates a local virtual environment in the ".venv" folder.
REM   2. Installs the required Python packages from requirements.txt.
REM Every run after that just activates the environment and starts the app.
REM
REM Requirement: Python 3.11+ must be installed and available on PATH.
REM ---------------------------------------------------------------------------

setlocal
cd /d "%~dp0"

REM Pick a Python launcher: prefer the Windows "py" launcher, fall back to python.
where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

REM Create the virtual environment on first run.
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo.
        echo ERROR: Could not create the virtual environment.
        echo Make sure Python 3.11 or newer is installed and on your PATH.
        pause
        exit /b 1
    )

    echo Installing required packages. This can take a few minutes the first time...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo ERROR: Package installation failed.
        pause
        exit /b 1
    )
)

REM Launch the application.
echo Starting Document Processor...
".venv\Scripts\python.exe" app.py

REM Keep the window open if the app exits with an error.
if errorlevel 1 (
    echo.
    echo The application exited with an error.
    pause
)

endlocal
