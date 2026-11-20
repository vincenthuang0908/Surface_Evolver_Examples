
@echo off
setlocal

REM Move to the pipeline directory.
cd /d "%~dp0.."
if errorlevel 1 exit /b 1

REM Python environment is one level above pcbsim_pipeline.
if not exist "..\.venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found.
    exit /b 1
)

"..\.venv\Scripts\python.exe" "run_pipeline.py" --config "pipeline.json" %*
exit /b %ERRORLEVEL%
