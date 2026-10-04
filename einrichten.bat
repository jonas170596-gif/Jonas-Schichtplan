@echo off
REM Legt die Verknuepfung "Schichtplan Winterbach" auf den Desktop.
REM Einmal doppelklicken, danach startet alles ueber das Symbol.
cd /d "%~dp0"

cscript //nologo "%~dp0werkzeug\verknuepfung.vbs" "%~dp0."
if errorlevel 1 (
  echo.
  echo Die Verknuepfung konnte nicht angelegt werden.
  echo Das macht nichts: start.bat laesst sich direkt doppelklicken,
  echo und mit Rechtsklick kann man sich davon selbst eine Verknuepfung
  echo auf den Desktop legen.
)
echo.
pause
