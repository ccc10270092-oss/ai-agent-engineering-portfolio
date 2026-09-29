@echo off
rem Local launcher: double-click to start the web UI (Vue frontend + FastAPI, port 8000)
rem Builds frontend/dist automatically on first run (requires Node.js 18+).
cd /d %~dp0

set PY=D:\soft\conda\python.exe
if not exist "%PY%" set PY=python

if not exist frontend\dist\index.html (
  echo [Build] frontend not built yet, building now...
  pushd frontend
  call npm install --no-audit --no-fund
  if errorlevel 1 goto :err
  call npm run build
  if errorlevel 1 goto :err
  popd
)

echo [Start] serving UI + API at http://127.0.0.1:8000
start "" /b cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000"
"%PY%" -m uvicorn api.main:app --host 127.0.0.1 --port 8000
pause
goto :eof

:err
echo.
echo Build failed. Check that Node.js 18+ is installed and on PATH.
pause
