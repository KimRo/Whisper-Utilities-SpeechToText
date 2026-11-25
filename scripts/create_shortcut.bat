@echo off
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File install\create_shortcut.ps1 %*
pause
