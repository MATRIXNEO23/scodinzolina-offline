@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 gptina_chat_bridge.py --start-memory --open-browser
  goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
  python gptina_chat_bridge.py --start-memory --open-browser
  goto :end
)

echo.
echo ERRORE: Python 3 non trovato.
echo Il memory runtime ha gia' bisogno di Python: verifica il PATH.
echo.
pause

:end
endlocal
