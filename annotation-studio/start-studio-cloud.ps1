# Annotation Studio - one-click launcher for Windows (local only; nothing is deployed).
#   1. checks Node >= 22.13, ffmpeg and ffprobe
#   2. loads .studio-cloud.env (never prints secret values)
#   3. starts the Studio and opens it in your browser
# Double-click start-studio-cloud.cmd (or run this file from PowerShell).
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Stop-WithMessage([string]$text) {
  Write-Host ''
  Write-Host ("X  " + $text) -ForegroundColor Red
  Write-Host ''
  Read-Host 'Press Enter to close'
  exit 1
}
function Ok([string]$text) { Write-Host ("OK " + $text) -ForegroundColor Green }

Write-Host 'SportReel Annotation Studio' -ForegroundColor Cyan

# ---- 1. requirements -------------------------------------------------------------------------------------------
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { Stop-WithMessage 'Node.js is not installed. Install Node 22 LTS from https://nodejs.org and run this again.' }
$raw = (& node --version).Trim().TrimStart('v')
$ver = [version]($raw -replace '[^0-9.].*$', '')
if ($ver -lt [version]'22.13.0') { Stop-WithMessage "Node $raw is too old (need 22.13 or newer). Install Node 22 LTS from https://nodejs.org." }
Ok "Node $raw"
if (Test-Path 'C:\ffmpeg\ffmpeg.exe') { $env:PATH = "C:\ffmpeg;$env:PATH" }
foreach ($tool in 'ffmpeg', 'ffprobe') {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
    Stop-WithMessage "$tool was not found on PATH. Install FFmpeg (for example: winget install Gyan.FFmpeg), open a NEW window and run this again."
  }
  Ok $tool
}

# ---- 2. local settings -----------------------------------------------------------------------------------------
$envFile = Join-Path $PSScriptRoot '.studio-cloud.env'
if (-not (Test-Path -LiteralPath $envFile)) {
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'cloud.env.example') -Destination $envFile
  Start-Process notepad.exe -ArgumentList ('"' + $envFile + '"')
  Stop-WithMessage "Created .studio-cloud.env next to this script. Fill in STUDIO_HOME and the four STUDIO_CLOUD_R2_* values (Notepad opened), save, then run this again. The file stays on your computer and is never committed."
}
$settings = @{}
foreach ($line in Get-Content -LiteralPath $envFile) {
  $t = $line.Trim()
  if ($t -eq '' -or $t.StartsWith('#')) { continue }
  $i = $t.IndexOf('=')
  if ($i -gt 0) { $settings[$t.Substring(0, $i).Trim()] = $t.Substring($i + 1).Trim() }
}
$required = 'STUDIO_HOME', 'STUDIO_CLOUD_R2_ACCOUNT_ID', 'STUDIO_CLOUD_R2_BUCKET', 'STUDIO_CLOUD_R2_ACCESS_KEY_ID', 'STUDIO_CLOUD_R2_SECRET_ACCESS_KEY'
$missing = @($required | Where-Object { -not $settings.ContainsKey($_) -or $settings[$_] -eq '' })
if ($missing.Count -gt 0) {
  Start-Process notepad.exe -ArgumentList ('"' + $envFile + '"')
  Stop-WithMessage ("These settings are empty in .studio-cloud.env: " + ($missing -join ', ') + ". Fill them in, save, and run this again.")
}
Ok 'Settings loaded (values not shown)'
if ($settings.ContainsKey('STUDIO_CLOUD_METADATA') -and $settings['STUDIO_CLOUD_METADATA'] -ne '' -and -not (Test-Path -LiteralPath $settings['STUDIO_CLOUD_METADATA'])) {
  Write-Host ("!  STUDIO_CLOUD_METADATA points to a file that does not exist: " + $settings['STUDIO_CLOUD_METADATA'] + " (continuing without it)") -ForegroundColor Yellow
}

# ---- 3. start + open the browser -------------------------------------------------------------------------------
$out = Join-Path $env:TEMP 'studio-cloud.out.log'
$err = Join-Path $env:TEMP 'studio-cloud.err.log'
Remove-Item -LiteralPath $out, $err -ErrorAction SilentlyContinue
$proc = Start-Process -FilePath 'node' -ArgumentList '--env-file=.studio-cloud.env', 'server/main.mjs' `
  -RedirectStandardOutput $out -RedirectStandardError $err -NoNewWindow -PassThru
$url = $null
for ($n = 0; $n -lt 60 -and -not $url; $n++) {
  Start-Sleep -Milliseconds 500
  if ($proc.HasExited) { break }
  if (Test-Path -LiteralPath $out) {
    $m = Select-String -LiteralPath $out -Pattern 'open:\s+(http\S+)' | Select-Object -First 1
    if ($m) { $url = $m.Matches[0].Groups[1].Value }
  }
}
if (-not $url) {
  $detail = if (Test-Path -LiteralPath $err) { (Get-Content -LiteralPath $err -Tail 8) -join [Environment]::NewLine } else { '' }
  if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
  Stop-WithMessage ("The Studio did not start. " + $detail)
}
Ok "Studio is running: $url"
Write-Host 'Opening your browser. Keep this window open while you work; close it (or press Ctrl+C) to stop the Studio.' -ForegroundColor Cyan
Start-Process $url
try { Wait-Process -Id $proc.Id } finally { if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } }
