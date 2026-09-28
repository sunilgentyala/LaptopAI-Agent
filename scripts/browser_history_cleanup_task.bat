@echo off
REM Registered in Windows Task Scheduler as "LaptopAI Browser History Cleanup",
REM firing every 15 days (see scripts/register_browser_history_cleanup_task.ps1).
REM Backs up then clears history for every closed browser profile found;
REM any browser that's currently running is skipped, never force-closed.
cd /d "C:\Gitrepos\LaptopAI-Agent"
"C:\Users\Sunil\AppData\Local\Python\bin\pythonw.exe" -m src.privacy.history_cleaner >> "C:\Gitrepos\LaptopAI-Agent\logs\browser_history_cleanup.log" 2>&1
