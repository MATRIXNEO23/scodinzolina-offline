@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 gptina_memory_server.py --host 127.0.0.1 --port 8765
  goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
  python gptina_memory_server.py --host 127.0.0.1 --port 8765
  goto :end
)

echo.
echo ERRORE: Python 3 non trovato.
echo Installa Python 3 oppure aggiungilo al PATH, poi rilancia questo file.
echo.
pause

:end
endlocal
