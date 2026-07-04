@echo off
REM Keeps the bot running — automatically restarts it if it crashes or
REM gets interrupted for any reason. Run THIS file instead of main.py directly.
REM
REM Make sure your environment variables (MT5_LOGIN, TELEGRAM_BOT_TOKEN, etc.)
REM are set BEFORE running this — either via `set` commands above, or by
REM setting them permanently in System Properties > Environment Variables.

:loop
echo [%date% %time%] Starting bot...
python main.py
echo [%date% %time%] Bot stopped (crash, interrupt, or exit). Restarting in 10 seconds...
timeout /t 10
goto loop
