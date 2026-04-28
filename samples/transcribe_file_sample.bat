@echo off
cd /d "%~dp0"

echo ============================================================
echo  SAMPLE: Martin Luther King Jr. - "I Have a Dream" (1963)
echo ============================================================
echo.
echo  This will download and transcribe a recording of the
echo  "I Have a Dream" speech delivered by Dr. Martin Luther
echo  King Jr. on August 28, 1963 at the Lincoln Memorial,
echo  Washington D.C.
echo.
echo  Source : Internet Archive (archive.org)
echo  File   : MLKDream_64kb.mp3  (~3 MB)
echo  Output : MLKDream.txt (saved next to this batch file)
echo.
echo ============================================================
echo.
set /p CONFIRM=Proceed with download and transcription? (Y/N):
if /i not "%CONFIRM%"=="Y" (
    echo Cancelled.
    exit /b 0
)
echo.
echo Downloading MLK "I Have a Dream" speech...
curl -L --progress-bar -o "MLKDream_64kb.mp3" "https://archive.org/download/MLKDream/MLKDream_64kb.mp3"
if %errorlevel% neq 0 (
    echo.
    echo Download failed. Check your internet connection and try again.
    pause
    exit /b 1
)
echo.
echo Saved: %~dp0MLKDream_64kb.mp3, now start transcribing...
python ..\scripts\transcribe_file.py "%~dp0MLKDream_64kb.mp3" -l en -o MLKDream.txt --model small
pause
