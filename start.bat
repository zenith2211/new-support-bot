@echo off
REM Start the store bot on this machine. Double-click, or run in a terminal.
REM Configuration is read from .env — copy .env.example if you have not yet.

cd /d "%~dp0"
title Store Bot

if not exist ".env" (
    echo No .env found.
    echo Copy .env.example to .env and fill in BOT_TOKEN and ADMIN_IDS.
    echo.
    pause
    exit /b 1
)

where py >nul 2>nul && (set PY=py) || (set PY=python)

echo Installing dependencies...
%PY% -m pip install --quiet --disable-pip-version-check -r requirements.txt

echo.
echo Starting the bot. Close this window or press Ctrl+C to stop it.
echo.

:run
%PY% bot.py
echo.
echo Bot stopped with exit code %ERRORLEVEL%.
REM A crash restarts after a short pause; a clean exit (Ctrl+C) does not.
if %ERRORLEVEL% NEQ 0 (
    echo Restarting in 5 seconds... press Ctrl+C to stop.
    timeout /t 5 /nobreak >nul
    goto run
)
pause
