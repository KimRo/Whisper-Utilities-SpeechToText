@echo off
cls
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass install\uninstall.ps1
pause
