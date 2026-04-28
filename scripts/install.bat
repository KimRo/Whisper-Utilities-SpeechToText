rem force a batch file to operate within its own directory rather than C:\Windows\System32
@echo off
cls
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass scripts\install.ps1
pause