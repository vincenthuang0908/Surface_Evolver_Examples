
@echo off
setlocal

REM Go two levels up from pcbsim_pipeline\scripts
REM to the evolver_native_min project root.
cd /d "%~dp0..\.."
if errorlevel 1 exit /b 1

echo ============================================
echo   Evolver Native - Environment Setup
echo ============================================
echo.

if not exist "requirements.txt" (
    echo [ERROR] requirements.txt not found at:
    cd
    exit /b 1
)

REM Reuse the existing environment, or create one.
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Creating virtual environment...
    py -3.12 -m venv ".venv"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        exit /b 1
    )
) else (
    echo [INFO] Existing virtual environment found.
)

echo.
echo [INFO] Installing dependencies...
".venv\Scripts\python.exe" -m pip install -r "requirements.txt"
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    exit /b 1
)

echo.
echo [INFO] Checking dependencies...
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 (
    echo [ERROR] Dependency conflicts detected.
    exit /b 1
)

echo.
echo [SUCCESS] Setup completed successfully.
exit /b 0
