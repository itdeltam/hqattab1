@echo off
REM Launches the trading bot. Intended to be run by NSSM (or Task Scheduler)
REM for auto-start/auto-restart on the trading Windows desktop.
REM
REM NSSM setup (one-time):
REM   nssm install TradingBot "C:\path\to\trading_bot\start_trader.bat"
REM   nssm set TradingBot AppDirectory "C:\path\to\trading_bot"
REM   nssm set TradingBot AppExit Default Restart
REM   nssm start TradingBot

setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo Virtual environment not found. Run: python -m venv .venv
    exit /b 1
)

call .venv\Scripts\activate.bat

if not exist ".env" (
    echo .env not found. Copy .env.example to .env and fill in real values.
    exit /b 1
)

python -m app.main
set EXITCODE=%ERRORLEVEL%

endlocal & exit /b %EXITCODE%
