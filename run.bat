@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    if exist "%LOCALAPPDATA%\uv\uv.exe" (
        uv update
        uv venv --python 3.10 .venv --verbose
        echo Installing dependencies...
        uv pip install --python .venv\Scripts\python.exe --link-mode=copy -r requirements.txt --verbose
    ) else (
        echo Installing dependencies...
        python -m venv .venv --verbose
        .venv\Scripts\python.exe -m pip install -r requirements.txt --verbose
    )
)
echo Running...
".venv\Scripts\python.exe" main.py --verbose
if errorlevel 1 pause
