@echo off
REM Holt den neuesten Stand und startet danach die Weboberflaeche.
cd /d "%~dp0"

where git >nul 2>&1
if errorlevel 1 goto :ohnegit
if not exist ".git" goto :ohnegit

echo Hole den neuesten Stand ...
git pull --ff-only
if errorlevel 1 (
  echo.
  echo Das Holen hat nicht geklappt - vermutlich gibt es hier eigene
  echo Aenderungen. Der alte Stand laeuft weiter.
  echo.
  pause
)
goto :starten

:ohnegit
echo Dieser Ordner ist keine Git-Arbeitskopie.
echo Neuen Stand von Hand als ZIP laden und entpacken -
echo die Ordner wochen\ und daten\historie\ dabei behalten!
echo.
pause

:starten
call "%~dp0start.bat"
