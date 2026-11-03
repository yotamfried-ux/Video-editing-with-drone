# Registers a DAILY encrypted Ground Truth backup with Windows Task Scheduler (per-user, no admin rights needed).
#
#   powershell -ExecutionPolicy Bypass -File scripts\install-backup-schedule.ps1 -To "E:\sportreel-gt" -KeyFile "$env:USERPROFILE\.sportreel-backup-key.txt" [-At 21:00]
#
# * -To      : folder on a SEPARATE physical disk (external drive / NAS). The script refuses the system disk.
# * -KeyFile : text file holding the backup passphrase (>= 12 chars). Keep it on your own (BitLocker-encrypted) system
#              disk, NOT on the backup disk and never in Git. Also store the passphrase in your password manager:
#              without it the backup cannot be restored.
# * The task runs `node scripts/gt-offsite-backup.mjs run` and then `verify`; results go to %LOCALAPPDATA%\SportReel\backup.log.
# * The Studio shows a red banner when the last good backup is older than 7 days or the last run failed.
# Remove with:  schtasks /Delete /TN "SportReel GT Backup" /F
param(
  [Parameter(Mandatory = $true)][string]$To,
  [Parameter(Mandatory = $true)][string]$KeyFile,
  [string]$At = "21:00",
  [string]$Scope = "labelled",
  [switch]$AllowSameDisk
)
$ErrorActionPreference = "Stop"
$studio = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path $KeyFile)) { throw "Key file not found: $KeyFile" }
if ((Get-Content $KeyFile -Raw).Trim().Length -lt 12) { throw "Backup passphrase must be at least 12 characters" }
$destDrive = (Resolve-Path (Split-Path -Qualifier $To)).Drive.Name
$sysDrive = $env:SystemDrive.TrimEnd(':')
if ($destDrive -eq $sysDrive) { throw "Destination $To is on the system drive. Use an external/NAS disk." }
$destDisk = (Get-Partition -DriveLetter $destDrive).DiskNumber
$sysDisk = (Get-Partition -DriveLetter $sysDrive).DiskNumber
if (-not $AllowSameDisk -and ($destDisk -eq $sysDisk)) { throw "Destination $To is on the SAME physical disk ($destDisk) as Windows. Use a separate disk, or pass -AllowSameDisk." }
$logDir = Join-Path $env:LOCALAPPDATA "SportReel"; New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "backup.log"
$runner = Join-Path $logDir "run-backup.cmd"
$sameDiskArg = if ($AllowSameDisk) { " --allow-same-disk" } else { "" }
@"
@echo off
cd /d "$studio"
echo [%DATE% %TIME%] backup start>> "$log"
node scripts\gt-offsite-backup.mjs run --to "$To" --scope $Scope --key-file "$KeyFile"$sameDiskArg >> "$log" 2>&1
node scripts\gt-offsite-backup.mjs verify --to "$To" --key-file "$KeyFile" >> "$log" 2>&1
echo [%DATE% %TIME%] backup end (exit %ERRORLEVEL%)>> "$log"
"@ | Set-Content -Encoding ASCII $runner
schtasks /Create /F /SC DAILY /ST $At /TN "SportReel GT Backup" /TR "`"$runner`"" | Out-Null
Write-Host "Scheduled daily encrypted backup at $At -> $To (disk $destDisk). Log: $log"
Write-Host "Run it once now to confirm:  schtasks /Run /TN `"SportReel GT Backup`"  then check the Studio library banner."
