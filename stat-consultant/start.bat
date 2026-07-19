@echo off
REM Double-click to (re)launch stat-consultant on Windows: stops any stale
REM backend/frontend from a previous run, (re)installs deps if missing,
REM starts both in their own console windows, and opens the chat in the
REM browser. Close the backend/frontend windows to stop each of them.
setlocal
cd /d "%~dp0"
set ROOT=%cd%

call :kill_stale 8000 "app.main:app"
call :kill_stale 5173 "vite"

echo == backend ==
cd /d "%ROOT%\backend"
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\pip.exe install -e .
)
start "stat-consultant backend" cmd /k .venv\Scripts\uvicorn.exe app.main:app --reload --port 8000

echo == frontend ==
cd /d "%ROOT%\frontend"
if not exist node_modules (
  call npm install
)
start "stat-consultant frontend" cmd /k npm run dev

timeout /t 3 /nobreak >nul
start "" "http://localhost:5173"
goto :eof

:kill_stale
setlocal
set PORT=%~1
set PATTERN=%~2
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
  for /f "delims=" %%c in ('wmic process where "ProcessId=%%p" get CommandLine 2^>nul ^| findstr /i %PATTERN%') do (
    echo 既存の %PATTERN% (PID %%p, port %PORT%) を停止します
    taskkill /PID %%p /F >nul 2>nul
  )
)
endlocal
goto :eof
