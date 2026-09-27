import sys

from .cli import main

try:
    code = main()
except BrokenPipeError:
    # Ausgabe lief in ein 'head' o. Ae. - kein Fehler, nur frueher Abbruch.
    try:
        sys.stdout.close()
    finally:
        code = 0

raise SystemExit(code)
