# Registers (or re-registers) the "LaptopAI Browser History Cleanup" Windows
# Scheduled Task from browser_history_cleanup_task.xml: runs
# scripts\browser_history_cleanup_task.bat every 15 days at 03:00.
#
# The XML (not a plain /Create flag invocation) is what sets the two
# non-default safety settings this task relies on:
#   - ExecutionTimeLimit = 30 min: if the run ever hangs (e.g. a browser
#     relaunches mid-backup and something downstream gets stuck), Task
#     Scheduler kills it instead of leaving a zombie process forever.
#   - StartWhenAvailable = true, battery restrictions off: a laptop is
#     often asleep or on battery at 03:00, so a missed run fires as soon as
#     the machine is next available rather than silently skipping to the
#     next 15-day window.
#
# Must be saved as UTF-16LE with a BOM (schtasks' XML import is picky about
# this — UTF-8, even with a matching <?xml encoding="UTF-8"?> declaration,
# fails with "unable to switch the encoding"). Re-run this script any time
# to update the schedule.
#
# To remove: schtasks /Delete /TN "LaptopAI Browser History Cleanup" /F

$taskName = "LaptopAI Browser History Cleanup"
$xmlPath = "C:\Gitrepos\LaptopAI-Agent\scripts\browser_history_cleanup_task.xml"

schtasks /Create /TN $taskName /XML $xmlPath /F

Write-Host "Registered '$taskName' to run every 15 days at 03:00 (30 min execution cap)."
Write-Host "Verify with:  schtasks /Query /TN `"$taskName`" /V /FO LIST"
