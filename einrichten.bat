@echo off
REM Legt eine Verknuepfung "Schichtplan Winterbach" auf den Desktop.
REM Einmal doppelklicken, danach startet das Programm ueber das Symbol.
setlocal
cd /d "%~dp0"

set "ZIEL=%~dp0start.bat"
set "SYMBOL=%~dp0schichtplan\web\bild\symbol.ico"
set "NAME=Schichtplan Winterbach"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = (New-Object -ComObject WScript.Shell);" ^
  "$p = Join-Path ([Environment]::GetFolderPath(Desktop)) %NAME%.lnk;" ^
  "$l = $s.CreateShortcut($p);" ^
  "$l.TargetPath = %ZIEL%;" ^
  "$l.WorkingDirectory = %~dp0;" ^
  "$l.IconLocation = %SYMBOL%;" ^
  "$l.Description = Wocheneinsatzplan Winterbach;" ^
  "$l.Save();" ^
  "Write-Host Verknuepfung angelegt:  $p"

if errorlevel 1 (
  echo.
  echo Die Verknuepfung konnte nicht angelegt werden.
  echo Start.bat laesst sich trotzdem direkt doppelklicken.
)
echo.
pause
