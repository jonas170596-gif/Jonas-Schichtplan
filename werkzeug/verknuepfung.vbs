' Legt die Desktop-Verknuepfung an.
' VBScript statt PowerShell: cscript ist auf jedem Windows da und faellt
' nicht unter die Ausfuehrungsrichtlinien, an denen PowerShell scheitern kann.
'   cscript //nologo werkzeug\verknuepfung.vbs "C:\Pfad\zum\Projekt"
Option Explicit

Dim shell, fso, ordner, desktop, ziel, verknuepfung, symbol
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

If WScript.Arguments.Count > 0 Then
  ordner = WScript.Arguments(0)
Else
  ordner = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
End If
If Right(ordner, 1) = "\" Then ordner = Left(ordner, Len(ordner) - 1)

ziel = ordner & "\start.bat"
If Not fso.FileExists(ziel) Then
  WScript.Echo "start.bat nicht gefunden in: " & ordner
  WScript.Quit 1
End If

desktop = shell.SpecialFolders("Desktop")
If desktop = "" Then
  WScript.Echo "Der Desktop-Ordner liess sich nicht ermitteln."
  WScript.Quit 1
End If

symbol = ordner & "\schichtplan\web\bild\symbol.ico"
Set verknuepfung = shell.CreateShortcut(desktop & "\Schichtplan Winterbach.lnk")
verknuepfung.TargetPath = ziel
verknuepfung.WorkingDirectory = ordner
verknuepfung.Description = "Wocheneinsatzplan Winterbach"
If fso.FileExists(symbol) Then verknuepfung.IconLocation = symbol & ",0"
verknuepfung.Save

WScript.Echo "Verknuepfung angelegt:"
WScript.Echo "  " & desktop & "\Schichtplan Winterbach.lnk"
