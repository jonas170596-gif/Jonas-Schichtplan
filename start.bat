@echo off
REM Startet die Weboberflaeche. Doppelklick genuegt.
REM Das Fenster bleibt offen, solange der Server laeuft - mit Strg+C beenden.
cd /d "%~dp0"

where py >nul 2>&1 && (set PY=py) || (set PY=python)

%PY% -c "import yaml" 2>nul
if errorlevel 1 (
  echo PyYAML fehlt, wird nachinstalliert ...
  %PY% -m pip install pyyaml || goto :fehler
)

%PY% -m schichtplan web
if errorlevel 1 goto :fehler
goto :ende

:fehler
echo.
echo Da ist etwas schiefgegangen. Die Meldung oben hilft weiter.
pause

:ende
