# install.ps1 — Register cert-watchdog as a Scheduled Task (run as Administrator)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptPath = Join-Path $ScriptDir "cert-watchdog.ps1"

$TaskName = "CertWatchdog"

# Remove existing task if present
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`""

$Trigger = New-ScheduledTaskTrigger -AtLogOn

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Monitors Downloads for certificate PDFs and organizes them" `
    -RunLevel Limited

Write-Host "Scheduled task '$TaskName' registered. It will start at next logon."
Write-Host "To start now: Start-ScheduledTask -TaskName '$TaskName'"
