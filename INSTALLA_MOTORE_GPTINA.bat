@echo off
setlocal
cd /d "%~dp0offline-runtime"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 install_llama_engine.py
  goto :done
)

where python >nul 2>nul
if %errorlevel%==0 (
  python install_llama_engine.py
  goto :done
)

echo ERRORE: Python 3 non trovato.
:done
pause
