@echo off
setlocal
cd /d "%~dp0offline-runtime"

where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw -3 gptina_offline_app.pyw
  exit /b 0
)

where py >nul 2>nul
if %errorlevel%==0 (
  start "" py -3 gptina_offline_app.pyw
  exit /b 0
)

where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw gptina_offline_app.pyw
  exit /b 0
)

echo ERRORE: Python 3 non trovato.
pause
