@echo off
REM Double-click this on demo day: server + tunnel + pretest in one window.
REM Add -AutoStart to have it press START for you.
cd /d "%~dp0"
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0Launch-Portal.ps1" %*
