@echo off
rem Start the PitchLens studio locally and open it in the browser.
cd /d "%~dp0web"
where npm >nul 2>nul || (echo Node.js is required: https://nodejs.org & pause & exit /b 1)
if not exist node_modules (
  echo Installing dependencies...
  call npm install || (pause & exit /b 1)
)
rem The AI analyst API is optional: without Python the panel says it is offline.
where py >nul 2>nul && start "PitchLens API" /min py "%~dp0api\local_server.py"
echo Starting PitchLens Studio - close this window to stop it.
call npm run dev -- --open
pause
