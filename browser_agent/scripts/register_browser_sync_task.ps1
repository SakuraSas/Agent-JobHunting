$ErrorActionPreference = "Stop"

$TaskName = "Agent-JobHunting-BrowserSync"
$Runner = Join-Path $PSScriptRoot "run_browser_sync.ps1"
$PowerShell = (Get-Command powershell.exe).Source
$Action = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Runner`""
$StartAt = Get-Date -Hour 2 -Minute 0 -Second 0
if ($StartAt -le (Get-Date)) {
    $StartAt = $StartAt.AddDays(1)
}
$Trigger = New-ScheduledTaskTrigger `
    -Once `
    -At $StartAt `
    -RepetitionInterval (New-TimeSpan -Hours 6) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Offline public job sync for Agent-JobHunting. Runs Browser Agent outside chat requests." `
    -Force | Out-Null

Write-Output "Registered scheduled task: $TaskName"
Write-Output "Schedule: every 6 hours, starting at 02:00"
