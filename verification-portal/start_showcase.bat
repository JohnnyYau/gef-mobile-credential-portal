@echo off
REM start_showcase.bat — double-click this on demo day (U26).
REM It starts the portal, opens a public tunnel, and opens the stage screen.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_showcase.ps1" %*
if errorlevel 1 pause
