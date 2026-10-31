@echo off
rem Double-click to start Annotation Studio (see start-studio-cloud.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-studio-cloud.ps1"
if errorlevel 1 pause
